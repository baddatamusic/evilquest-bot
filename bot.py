"""
EvilQuest bot — woodcutting and combat modes.

Protocol facts confirmed from live sniff:
  - Own position: opcode 122 (PLAYER_SELF_SYNC) → [x, y, hp, max_hp, tick, 0]
  - NPC_SYNC (11): one NPC per packet → [entity_id, type_id, x, y, hp, max_hp] (stride 6)
  - Object sync: WORLD_OBJECT_SYNC (55) → [entity_id, type_id, x, y, 0, 0, rotation, 0]
  - Ground items: GROUND_ITEM_SYNC (12) → [entity_id, item_id, quantity, x, y]
  - PLAYER_SYNC (10): OTHER players, format [entity_id, x, y, hp, max_hp, ...]
  - NPC name: NPC_NAME (84, string) → str=name, vals=[entity_id]
  - LOGIN_OK (1): vals=[own_entity_id, x, y, ...]
  - COMBAT_HIT (30): vals=[attacker_entity_id, target_entity_id, damage]
  - ENTITY_DEATH (31): vals=[entity_id]

PLAYER_MOVE packet format:
  [opcode=10][count: int16][x1*10: int16][z1*10: int16]...[xN*10][zN*10]
  Up to 50 waypoints. Each waypoint is tile-centre x10.

Usage:
  python bot.py              # interactive mode select
  python bot.py --mode woodcutting
  python bot.py --mode combat
  python bot.py --sniff      # log all messages; play manually to verify flows
"""

import asyncio
import argparse
import logging
import math
import os
import random
import time
from pathlib import Path


# ── Human-like timing helpers ─────────────────────────────────────────────────
#
# Three problems addressed here:
#
#  1. Tick-aligned timing.  Python's asyncio loop fires with <1 ms variance.
#     Every fixed asyncio.sleep(0.3) lands at the same offset inside each
#     server tick cycle.  Statistical analysis of inter-packet arrival times
#     across even a single session distinguishes this from a browser in seconds.
#     _tick_slip() samples a multi-modal lognormal + GC-outlier distribution
#     before every send, matching real Chrome DevTools trace data.  The old
#     uniform U[10,120ms] had a flat histogram that is itself a fingerprint.
#
#  2. Reaction-time distribution.  Human reaction times after a server event
#     follow a right-skewed lognormal distribution with a hard floor around
#     150 ms.  Fixed sleeps produce near-zero-variance Gaussian distributions
#     that are trivially modelled and flagged.  _human_reaction() samples from
#     a lognormal that matches empirical human response-time data.
#
#  3. General delay jitter.  Every asyncio.sleep(N) call goes through _jitter()
#     which multiplies by a lognormal factor, keeping the median at N while
#     adding realistic spread that matches browser JS event-loop timing.

def _jitter(base: float, scale: float = 0.20) -> float:
    """
    Lognormal-jittered delay centred on `base`.
    scale ≈ coefficient of variation (std / mean).
    Result is clamped to [base*0.35, base*3.0] to prevent absurd extremes.
    """
    # lognormal: ln(X) ~ N(mu, sigma²).  Choose mu so E[X]=1 (i.e. mu=-σ²/2).
    sigma  = scale
    mu     = -(sigma ** 2) / 2.0
    factor = math.exp(random.gauss(mu, sigma))
    factor = max(0.35, min(3.0, factor))
    return base * factor


def _human_reaction(floor: float = 0.15) -> float:
    """
    Human post-event reaction time: lognormal with median ≈ 280 ms,
    hard floor at `floor` seconds (150 ms by default).

    Samples from the same distribution measured in cognitive-psychology
    simple-reaction-time studies (μ_ln ≈ –1.27, σ_ln ≈ 0.40).
    """
    raw = math.exp(random.gauss(-1.27, 0.40))   # median ≈ 0.28 s
    return max(floor, min(2.5, raw))


def _tick_slip() -> float:
    """
    Multi-modal micro-jitter before every game packet send.

    The old implementation used uniform U[10, 120ms].  A flat histogram is
    itself a statistical fingerprint — the server's tickAlignedTiming detector
    runs a modular-residue or KS test on inter-arrival times and flags uniform
    distributions as readily as it flags zero-variance ones.

    Real Chrome browser send timing (from DevTools Network traces):
      - Baseline: rAF-driven lognormal, median ~25 ms, right-skewed.
      - Minor GC / layout: 50–350 ms, ~15 % of sends.
      - Major GC compaction: 350–1200 ms, ~3 % of sends.

    Distribution stats:
      P50 ≈  25 ms   P75 ≈  80 ms
      P90 ≈ 210 ms   P99 ≈ 720 ms   mean ≈ 90 ms
    """
    r = random.random()
    if r < 0.82:
        # Baseline: lognormal, median e^-3.69 ≈ 25 ms, σ=0.80 (right-skewed).
        # Capped at 200 ms — values beyond that fall into GC territory.
        v = math.exp(random.gauss(-3.69, 0.80))
        return max(0.002, min(v, 0.200))
    elif r < 0.97:
        # Minor GC / event-loop saturation: 50–350 ms uniform.
        return random.uniform(0.050, 0.350)
    else:
        # Major GC compaction: 350–1200 ms (rare — ~3 % of sends).
        return random.uniform(0.350, 1.200)


def _load_dotenv() -> None:
    """Load key=value pairs from .env (same dir as bot.py) into os.environ.
    Only sets variables that are not already set — CLI / shell env always wins.
    """
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if key and key not in os.environ:
                os.environ[key] = value


_load_dotenv()

from protocol import C, S, SERVER_NAMES, pack, pack_str, unpack, try_unpack_str
from ws_transport import GameWebSocket, async_http_login
import pathfinder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("bot")

BASE_URL = "https://evilquest.net"

# ── Item / NPC constants ──────────────────────────────────────────────────────
LOG_ITEM_ID      = 23
SHOPKEEPER_TYPE  = 8
TREE_TYPE_ID     = 1

DEFAULT_TREE_ENTITY  = 10208
DEFAULT_TREE_X       = 1470
DEFAULT_TREE_Y       = 1476

ROBERT_ENTITY_ID = 2
ROBERT_X         = 1475
ROBERT_Y         = 1515

SELL_AT_LOGS = 28

DEFAULT_COW_TYPE_ID = 10
DEFAULT_COW_X = 1200
DEFAULT_COW_Y = 1720

EQUIP_SLOTS = ["weapon", "shield", "head", "body", "legs", "feet", "cape", "ring", "ammo"]

# All opcodes now live in protocol.py as S.* / C.* logical constants.
# The transport layer translates to/from wire opcodes transparently.

ARRIVE_WINDOW = 25          # x10 units — consider arrived when within this distance
WALK_TILES_PER_SEC = 1.67  # from GameManager.js moveSpeed constant


# ── Game state ────────────────────────────────────────────────────────────────

class State:
    def __init__(self):
        self.own_entity_id: int = -1
        self.x: int = 0
        self.y: int = 0
        self.hp: int = 0

        self.npcs: dict[int, tuple] = {}
        self.objects: dict[int, tuple] = {}
        self.ground_items: dict[int, tuple] = {}

        self.logs_chopped = 0
        self.logs_in_inventory = 0
        self.dialogue_session_id: int = 0

        self.equipped: dict[str, int] = {}

        self._has_hp_baseline: bool = False
        self._is_dead: bool = False
        self.dead_npcs: set[int] = set()

        self._pending_map_ready = False
        self.trunc_x: int = 0   # last PATH_TRUNCATED tile (x10)
        self.trunc_y: int = 0

        self.height_y: float = 0.0   # ground Y height (world units), used for CLIENT_POSITION_Y

        self.ev_login_ok         = asyncio.Event()
        self.ev_skilling_start   = asyncio.Event()
        self.ev_skilling_stop    = asyncio.Event()
        self.ev_shop_open        = asyncio.Event()
        self.ev_dialogue         = asyncio.Event()
        self.ev_player_died      = asyncio.Event()
        self.ev_player_respawned = asyncio.Event()

    def nearby_trees(self, max_dist: int = 500) -> list[tuple]:
        results = []
        for eid, (tid, ox, oy) in self.objects.items():
            if tid == TREE_TYPE_ID:
                d = abs(ox - self.x) + abs(oy - self.y)
                if d <= max_dist:
                    results.append((eid, tid, ox, oy, d))
        results.sort(key=lambda r: r[4])
        return [(e, t, x, y) for e, t, x, y, _ in results]

    def find_shopkeeper(self) -> tuple | None:
        for eid, (tid, nx, ny, _, __) in self.npcs.items():
            if tid == SHOPKEEPER_TYPE:
                return eid, nx, ny
        return None

    def ground_logs(self) -> list[tuple]:
        return [
            (eid, qty, gx, gy)
            for eid, (iid, qty, gx, gy) in self.ground_items.items()
            if iid == LOG_ITEM_ID
        ]

    def find_nearby_cows(self, cow_type: int, max_dist: int = 10_000) -> list[tuple]:
        """
        Return all live cows of `cow_type` within `max_dist` (Manhattan, x10 units),
        sorted nearest-first.  Excludes entities in dead_npcs.

        Returns list of (eid, nx, ny).  Empty list if none visible.
        """
        results = []
        for eid, (tid, nx, ny, hp, _mhp) in self.npcs.items():
            if tid == cow_type and hp > 0 and eid not in self.dead_npcs:
                d = abs(nx - self.x) + abs(ny - self.y)
                if d <= max_dist:
                    results.append((eid, nx, ny, d))
        results.sort(key=lambda r: r[3])
        return [(e, x, y) for e, x, y, _ in results]

    def find_nearest_cow(self, cow_type: int) -> tuple | None:
        cows = self.find_nearby_cows(cow_type)
        return cows[0] if cows else None


# ── Bot ───────────────────────────────────────────────────────────────────────

class Bot:
    def __init__(self, username: str, password: str,
                 tree_entity: int, tree_x: int, tree_y: int,
                 shop_option: int,
                 cow_type: int, cow_x: int, cow_y: int):
        self.username    = username
        self.password    = password
        self.tree_entity = tree_entity
        self.tree_x      = tree_x
        self.tree_y      = tree_y
        self.shop_option = shop_option
        self.cow_type    = cow_type
        self.cow_x       = cow_x
        self.cow_y       = cow_y
        self.state       = State()
        self.ws: GameWebSocket | None = None
        self._token:          str = ""
        self._device_id:      str = ""
        self._device_cookie:  str = ""
        self._sell_lock  = asyncio.Lock()
        self._session_start: float = 0.0   # set in run(); used by _fatigue_scale()

        self.ev_path_truncated = asyncio.Event()
        # Set by _recv_loop() when the socket closes unexpectedly.
        # _send() checks this before touching the socket; all wait loops
        # check it so they abort immediately instead of timing out.
        self._ws_closed  = asyncio.Event()

    # ── Network ──────────────────────────────────────────────────────────────

    async def _http_login(self) -> tuple[str, str, str]:
        """Browser-based login via pydoll (handles reCAPTCHA v3).
        Returns (auth_token, device_id, device_cookie)."""
        token, device_id, cookie = await async_http_login(self.username, self.password)
        log.info("Browser login OK — device_id=%s", (device_id[:8] + "…") if device_id else "N/A")
        return token, device_id, cookie

    async def _send(self, data: bytes, apply_tick_slip: bool = True):
        """
        Send a game packet.

        apply_tick_slip=True (default) inserts a 10–120 ms micro-jitter before
        the send.  This breaks tick-phase alignment: even if the surrounding
        sleep is perfectly regular, the actual packet arrival at the server is
        uniformly spread across the tick window, matching browser-level timing
        variance.  Pass apply_tick_slip=False only for latency-critical paths
        (e.g. heartbeat) that already carry their own jitter.
        """
        if self._ws_closed.is_set():
            raise ConnectionError("WebSocket is closed — cannot send")
        if apply_tick_slip:
            await asyncio.sleep(_tick_slip())
        await self.ws.send(data)

    # ── Message dispatch ─────────────────────────────────────────────────────

    def _dispatch(self, raw: bytes):
        op, vals = unpack(raw)

        if op == S.LOGIN_OK:
            if vals:
                self.state.own_entity_id = vals[0]
                if len(vals) >= 3:
                    self.state.x, self.state.y = vals[1], vals[2]
                if len(vals) >= 4:
                    self.state.height_y = vals[3] / 10.0   # initial ground Y height
            log.info(
                f"LOGIN_OK entity_id={self.state.own_entity_id} "
                f"pos=({self.state.x},{self.state.y}) height_y={self.state.height_y:.2f}"
            )
            self.state.ev_login_ok.set()

        elif op == S.PLAYER_SELF_SYNC:
            prev_hp = self.state.hp
            if len(vals) >= 2:
                self.state.x, self.state.y = vals[0], vals[1]
            if len(vals) >= 3:
                self.state.hp = vals[2]

            if not self.state._has_hp_baseline:
                if self.state.hp > 0:
                    self.state._has_hp_baseline = True
            else:
                if self.state.hp == 0 and prev_hp > 0:
                    self.state._is_dead = True
                    self.state.ev_player_died.set()
                    log.info("Player died!")
                elif self.state.hp > 0 and self.state._is_dead:
                    self.state._is_dead = False
                    self.state.ev_player_respawned.set()
                    log.info(f"Respawned at ({self.state.x},{self.state.y}) hp={self.state.hp}")

            log.debug(f"OWN_STATE pos=({self.state.x},{self.state.y}) hp={self.state.hp}")

        elif op == S.PLAYER_SYNC:
            # Server may include own player in sync — use it for position tracking during movement
            stride = 5  # entity_id, x, y, hp, max_hp
            i = 0
            while i + stride <= len(vals):
                eid = vals[i]
                if eid == self.state.own_entity_id and self.state.own_entity_id != -1:
                    self.state.x, self.state.y = vals[i + 1], vals[i + 2]
                    if vals[i + 3] > 0:
                        self.state.hp = vals[i + 3]
                    log.debug(f"PLAYER_SYNC own pos=({self.state.x},{self.state.y})")
                i += stride

        elif op == S.NPC_SYNC:
            if len(vals) >= 6:
                eid, tid, nx, ny, hp, mhp = vals[:6]
                self.state.npcs[eid] = (tid, nx, ny, hp, mhp)
            elif len(vals) >= 4:
                eid, tid, nx, ny = vals[:4]
                self.state.npcs[eid] = (tid, nx, ny, 0, 0)

        elif op == S.WORLD_OBJECT_SYNC:
            if len(vals) >= 4:
                eid, tid, ox, oy = vals[:4]
                self.state.objects[eid] = (tid, ox, oy)

        elif op == S.WORLD_OBJECT_DEPLETED:
            if vals:
                dep_eid = vals[0]
                self.state.objects.pop(dep_eid, None)
                log.debug(f"WORLD_OBJECT_DEPLETED entity={dep_eid}")

        elif op == S.GROUND_ITEM_SYNC:
            if len(vals) >= 5:
                eid, iid, qty, gx, gy = vals[:5]
                if qty > 0:
                    self.state.ground_items[eid] = (iid, qty, gx, gy)
                else:
                    self.state.ground_items.pop(eid, None)

        elif op == S.ENTITY_DEATH:
            if vals:
                dead_eid = vals[0]
                self.state.ground_items.pop(dead_eid, None)
                self.state.npcs.pop(dead_eid, None)
                if dead_eid == self.state.own_entity_id:
                    if not self.state._is_dead:
                        self.state._is_dead = True
                        self.state.ev_player_died.set()
                        log.info("Player died! (ENTITY_DEATH)")
                else:
                    self.state.dead_npcs.add(dead_eid)

        elif op == S.COMBAT_HIT:
            if len(vals) >= 3:
                log.debug(f"COMBAT_HIT attacker={vals[0]} target={vals[1]} dmg={vals[2]}")

        elif op == S.SKILLING_START:
            log.info(f"SKILLING_START {vals}")
            self.state.ev_skilling_start.set()

        elif op == S.SKILLING_STOP:
            log.info(f"SKILLING_STOP {vals}")
            self.state.logs_chopped    += 1
            self.state.logs_in_inventory += 1   # logs go directly to inventory
            self.state.ev_skilling_stop.set()

        elif op == S.DIALOGUE_OPEN:
            parsed = try_unpack_str(raw)
            if parsed and parsed[1]:
                self.state.dialogue_session_id = parsed[1][-1]
                log.info(f"DIALOGUE_OPEN session_id={self.state.dialogue_session_id}")
            else:
                log.info(f"DIALOGUE_OPEN vals={vals[:4]}")
            self.state.ev_dialogue.set()

        elif op == S.SHOP_OPEN:
            log.info(f"SHOP_OPEN {vals}")
            self.state.ev_shop_open.set()

        elif op == S.MAP_CHANGE:
            parsed = try_unpack_str(raw)
            map_name = parsed[0] if parsed else "?"
            if parsed and len(parsed[1]) >= 2:
                self.state.x, self.state.y = parsed[1][0], parsed[1][1]
            log.info(f"MAP_CHANGE map={map_name!r} pos=({self.state.x},{self.state.y})")
            self.state._pending_map_ready = True

        elif op == S.TRADE_REQUEST_RECEIVED:
            # Another player sent us a trade request.  A real player always
            # responds — either accepting (rarely) or declining.  An account
            # that receives hundreds of trade requests and never sends
            # TRADE_DECLINE is a strong bot signal visible in the social graph.
            #
            # We decline after a human-like reading delay (150–600 ms).
            # We do NOT accept trades — the bot has no trade logic and accepting
            # an unsolicited trade could expose our inventory to inspection.
            if vals:
                requester_eid = vals[0]
                log.info(f"TRADE_REQUEST_RECEIVED from entity={requester_eid} — declining")
                async def _decline_trade(req_eid: int) -> None:
                    await asyncio.sleep(_human_reaction())
                    try:
                        await self._send(pack(C.TRADE_DECLINE, req_eid))
                    except Exception:
                        pass
                asyncio.create_task(_decline_trade(requester_eid))
            else:
                log.debug("TRADE_REQUEST_RECEIVED (no entity id in vals)")

        elif op == S.ADMIN_FLAGS:
            # New server opcode added with the admin-UI anti-cheat system.
            # The real client receives this and may update local UI state.
            # Falling through to the generic unhandled logger would generate
            # a noisy INFO line for a packet the server sends deliberately —
            # handle it explicitly so it stays at DEBUG level and doesn't
            # confuse post-session log analysis.
            if vals:
                flag_names = {
                    0: "tickAlignedTiming",
                    1: "suspiciousPackets",
                    2: "packetFuzzing",
                    3: "pathOptimality",
                    4: "zeroCancellations",
                    5: "selectivePickup",
                    6: "noChat",
                }
                active = [flag_names.get(v, f"flag_{v}") for v in vals]
                log.warning(f"ADMIN_FLAGS: {active} — adjust behaviour accordingly")
            else:
                log.debug("ADMIN_FLAGS received (empty payload)")

        elif op == S.SERVER_PONG:
            log.debug(f"SERVER_PONG seq={vals[0] if vals else '?'}")

        elif op == S.NPC_APPEARANCE:
            log.debug(f"NPC_APPEARANCE entity={vals[0] if vals else '?'}")

        elif op == S.PATH_TRUNCATED:
            if len(vals) >= 2:
                # vals[0,1] = the tile where the server truncated the path (x10 coords).
                # This is where the player will STOP, not where they currently ARE.
                # Do NOT update state.x/y here — the player is still walking there.
                self.state.trunc_x = vals[0]
                self.state.trunc_y = vals[1]
                log.info(f"PATH_TRUNCATED at ({vals[0]},{vals[1]})")
                self.ev_path_truncated.set()

        elif op == S.XP_GAIN:
            log.info(f"XP_GAIN skill={vals[0] if vals else '?'} xp={vals[1] if len(vals)>1 else '?'}")

        elif op == S.LEVEL_UP:
            log.info(f"LEVEL_UP {vals}")

        elif op == S.PLAYER_EQUIPMENT:
            self.state.equipped.clear()
            for i, slot in enumerate(EQUIP_SLOTS):
                item_id = vals[i] if i < len(vals) else 0
                if item_id:
                    self.state.equipped[slot] = item_id
            log.info(f"PLAYER_EQUIPMENT equipped={self.state.equipped}")

        elif op == S.PLAYER_STATS:
            log.debug(f"PLAYER_STATS vals={vals}")

        else:
            parsed = try_unpack_str(raw)
            label  = SERVER_NAMES.get(op, f"op_{op}")
            if parsed:
                log.debug(f"{label}: str={parsed[0]!r} vals={parsed[1]}")
            else:
                if len(vals) >= 6:
                    log.info(f"UNHANDLED op={op} ({len(vals)} vals) vals={vals[:12]}")
                else:
                    log.debug(f"{label}: vals={vals}")

    async def _recv_loop(self):
        while True:
            try:
                data = await self.ws.recv()
            except ConnectionError as exc:
                log.error(f"WebSocket closed: {exc}")
                break
            except Exception as exc:
                log.error(f"recv error: {exc}")
                break
            if data is None:
                continue
            self._dispatch(data)
            if self.state._pending_map_ready:
                self.state._pending_map_ready = False
                await self.ws.send(pack(C.MAP_READY))
                log.info("MAP_READY sent")
        # Signal all blocked waits so they raise ConnectionError immediately
        # instead of hanging until their own timeouts expire.
        self._ws_closed.set()

    # ── Movement ─────────────────────────────────────────────────────────────

    def _build_move_packet(self, dest_x: int, dest_z: int) -> bytes:
        path = pathfinder.find_path(self.state.x, self.state.y, dest_x, dest_z)
        if not path:
            return pack(C.PLAYER_MOVE, 1, dest_x, dest_z)
        chunk = path[:50]
        args = [len(chunk)]
        for wx, wz in chunk:
            args.extend([wx, wz])
        return pack(C.PLAYER_MOVE, *args)

    async def _move(self, x: int, y: int, timeout: float | None = None,
                    arrive_window: int = ARRIVE_WINDOW):
        """
        Move to (x, y) in x10 coordinates.

        The server never sends position updates during normal walking — the JS client
        uses client-side prediction (moveSpeed=1.67 tiles/sec).  We mirror that here:

        • Send PLAYER_MOVE with up to 50 A*-planned waypoints.
        • Sleep for estimated travel time (path_steps / 1.67 s).
        • If PATH_TRUNCATED fires: the server will walk the player to the truncated
          tile and stop.  Wait for the player to REACH that tile (based on distance
          from current position / walk speed), then re-path to the destination.
        • On repeated truncation at the same tile, identify the *next tile in the
          original sent path after the truncation point* and add it as a dynamic
          block so A* routes around it on the next attempt.  The dynamic block set
          is persisted to disk so it survives restarts.
        • On timeout, update state.x/y to cur_x/cur_y (last confirmed position
          from PATH_TRUNCATED feedback) rather than assuming the destination.
        """
        if abs(self.state.x - x) <= arrive_window and abs(self.state.y - y) <= arrive_window:
            return

        log.info(f"Moving to ({x},{y}), currently at ({self.state.x},{self.state.y})")
        self.ev_path_truncated.clear()

        loop = asyncio.get_event_loop()
        _last_path_sent: list[tuple[int, int]] = []   # waypoints sent in last PLAYER_MOVE

        async def _send_path_from(sx: int, sz: int) -> tuple[int, float]:
            """Send a PLAYER_MOVE from (sx,sz) → (x,y). Returns (steps, travel_sec)."""
            nonlocal _last_path_sent
            path = pathfinder.find_path(sx, sz, x, y)
            if path:
                # ── Path suboptimality (~7 % of moves with ≥5 waypoints) ──────
                # Real players click imprecisely and don't always produce
                # mathematically optimal routes.  We inject a single off-axis
                # detour waypoint near the start of the path.  If the detour tile
                # turns out to be blocked, the server fires PATH_TRUNCATED and the
                # re-path logic handles it transparently — safe either way.
                # Only applied on the INITIAL send (sx == state.x), not on
                # re-paths triggered by truncation events.
                if (len(path) >= 5
                        and sx == self.state.x and sz == self.state.y
                        and random.random() < 0.07):
                    di  = random.randint(1, min(3, max(1, len(path) // 4)))
                    px, pz = path[di - 1]
                    # Deviate one tile perpendicular to the primary travel axis
                    dx = random.choice([-10, 10])
                    dz = random.choice([-10, 10])
                    detour = (px + dx, pz + dz)
                    path = path[:di] + [detour] + path[di:]
                    log.debug(
                        f"Path detour at step {di}: ({detour[0]},{detour[1]}) "
                        f"(total {len(path)} waypoints)"
                    )

                chunk = path[:50]
                _last_path_sent = list(chunk)
                args  = [len(chunk)]
                for wx, wz in chunk:
                    args.extend([wx, wz])
                await self._send(pack(C.PLAYER_MOVE, *args))
                steps = len(chunk)
            else:
                _last_path_sent = []
                await self._send(pack(C.PLAYER_MOVE, 1, x, y))
                steps = max(1, (abs(sx - x) + abs(sz - y)) // 10)
            return steps, steps / WALK_TILES_PER_SEC

        # Track where the player actually is (server-confirmed or assumed)
        cur_x, cur_y = self.state.x, self.state.y

        n_steps, travel_sec = await _send_path_from(cur_x, cur_y)
        t_send    = loop.time()
        t_arrive  = t_send + travel_sec

        if timeout is None:
            timeout = max(20.0, travel_sec * 3.0)
        deadline = t_send + timeout

        dynamic_blocks = 0  # consecutive truncations at same tile

        while loop.time() < deadline:
            if self._ws_closed.is_set():
                raise ConnectionError("WebSocket closed during movement")
            remaining = t_arrive - loop.time()
            if remaining <= 0:
                break   # estimated travel time elapsed → assume arrived

            try:
                await asyncio.wait_for(self.ev_path_truncated.wait(),
                                       timeout=min(1.0, remaining))
                self.ev_path_truncated.clear()
            except asyncio.TimeoutError:
                continue

            # PATH_TRUNCATED: server reports the tile where the player will stop.
            # Two cases:
            #   ON-PATH  — the tile is in our last sent path; the player is walking
            #              there and we must wait for them to arrive.
            #   OFF-PATH — the server is correcting our position (player was never at
            #              cur_x/cur_y, or ended up elsewhere due to a prior move).
            #              Update state immediately; no wait needed.
            tx, ty = self.state.trunc_x, self.state.trunc_y

            # Immediately sync state.x/y to server-confirmed position.
            self.state.x, self.state.y = tx, ty

            if abs(tx - x) <= ARRIVE_WINDOW and abs(ty - y) <= ARRIVE_WINDOW:
                cur_x, cur_y = tx, ty
                log.info(f"PATH_TRUNCATED near destination ({tx},{ty})")
                break

            # Is the truncation tile on the path we sent?
            trunc_tile_x = tx // 10
            trunc_tile_z = ty // 10
            in_path = any(p[0] // 10 == trunc_tile_x and p[1] // 10 == trunc_tile_z
                          for p in _last_path_sent)

            # Find the tile immediately after T in the sent path — that is the
            # step the server refused.  Used for both on-path and off-path cases.
            _next_blocked: tuple[int, int] | None = None
            for i, (px, pz) in enumerate(_last_path_sent):
                if px // 10 == trunc_tile_x and pz // 10 == trunc_tile_z:
                    if i + 1 < len(_last_path_sent):
                        _next_blocked = (_last_path_sent[i + 1][0] // 10,
                                         _last_path_sent[i + 1][1] // 10)
                    break

            if in_path:
                # ON-PATH: the server is telling us the player will stop at T and
                # the next step is impassable.  We know this for certain — block it
                # immediately so the very next re-path already routes around it.
                if _next_blocked:
                    log.info(f"PATH_TRUNCATED at ({tx},{ty}) → blocking {_next_blocked}")
                    pathfinder.add_dynamic_block(*_next_blocked)

                # Wait for the player to walk to T (use Euclidean distance for
                # accuracy — diagonal steps are faster than Manhattan tiles).
                trunc_dist_tiles = math.sqrt((cur_x - tx) ** 2 + (cur_y - ty) ** 2) / 10.0
                t_reach_trunc    = t_send + trunc_dist_tiles / WALK_TILES_PER_SEC
                wait_for = t_reach_trunc - loop.time()
                if wait_for > 0:
                    log.info(f"PATH_TRUNCATED at ({tx},{ty}), walking "
                             f"{trunc_dist_tiles:.1f} tiles ({wait_for:.1f}s)")
                    await asyncio.sleep(wait_for)
                dynamic_blocks = 0   # on-path blocking handled above
            else:
                # OFF-PATH: server is correcting our position; T is where the
                # player actually is.  Block only on repeated truncation at the
                # same spot (one re-path that lands at T again confirms the block).
                log.info(f"PATH_TRUNCATED at ({tx},{ty}) (position correction, no wait)")
                if self.state.trunc_x == tx and self.state.trunc_y == ty:
                    dynamic_blocks += 1
                    if dynamic_blocks >= 2:
                        blocked_tile: tuple[int, int] | None = _next_blocked
                        if blocked_tile is None:
                            fresh = pathfinder.find_path(cur_x, cur_y, x, y)
                            if fresh:
                                blocked_tile = (fresh[0][0] // 10, fresh[0][1] // 10)
                        if blocked_tile:
                            log.info(f"Dynamic block {blocked_tile} — repeated truncation at ({tx},{ty})")
                            pathfinder.add_dynamic_block(*blocked_tile)
                        dynamic_blocks = 0
                else:
                    dynamic_blocks = 0

            cur_x, cur_y = tx, ty

            if abs(cur_x - x) <= ARRIVE_WINDOW and abs(cur_y - y) <= ARRIVE_WINDOW:
                break

            log.info(f"Re-pathing from ({cur_x},{cur_y}) to ({x},{y})")
            n_steps, travel_sec = await _send_path_from(cur_x, cur_y)
            t_send   = loop.time()
            t_arrive = t_send + travel_sec

        # Update state to reflect where the player ended up.
        # Prefer server-confirmed position (PLAYER_SELF_SYNC may have updated state.x/y).
        cx, cy = self.state.x, self.state.y
        if abs(cx - x) <= ARRIVE_WINDOW and abs(cy - y) <= ARRIVE_WINDOW:
            log.info(f"Arrived at ({cx},{cy}) (server confirmed)")
        elif abs(cur_x - x) <= ARRIVE_WINDOW and abs(cur_y - y) <= ARRIVE_WINDOW:
            log.info(f"Arrived at ({cur_x},{cur_y}) (truncation path complete)")
            self.state.x, self.state.y = cur_x, cur_y
        else:
            # Use cur_x/cur_y — the last position confirmed via PATH_TRUNCATED.
            # Do NOT assume destination arrival; the player may not have moved far.
            steps_walked = max(1, (abs(self.state.x - cur_x) + abs(self.state.y - cur_y)) // 10)
            log.info(f"Movement done ({steps_walked} steps ≈ {steps_walked / WALK_TILES_PER_SEC:.1f}s), assuming at ({cur_x},{cur_y})")
            self.state.x, self.state.y = cur_x, cur_y

    # ── Helpers ───────────────────────────────────────────────────────────────

    async def _wait_for_event(self, event: asyncio.Event, timeout: float) -> bool:
        """
        Wait up to `timeout` seconds for `event` to be set.
        Returns True if the event fired, False on timeout.
        Raises ConnectionError immediately if the WebSocket closes while waiting.
        """
        event_task  = asyncio.create_task(event.wait())
        closed_task = asyncio.create_task(self._ws_closed.wait())
        done, pending = await asyncio.wait(
            {event_task, closed_task},
            timeout=timeout,
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
        if self._ws_closed.is_set():
            raise ConnectionError("WebSocket closed while waiting for event")
        return event_task in done

    # ── Woodcutting ───────────────────────────────────────────────────────────

    @staticmethod
    def _stand_beside(player_x: int, player_y: int,
                      obj_x: int, obj_y: int) -> tuple[int, int]:
        """
        Return the orthogonal tile (x10 coords) adjacent to (obj_x, obj_y)
        that is nearest to (player_x, player_y).

        Trees occupy their own tile — sending PLAYER_MOVE to the tree's exact
        tile causes a PATH_TRUNCATED roundtrip every time.  Walking to an
        adjacent tile instead avoids that wasted exchange entirely.
        """
        candidates = [
            (obj_x + 10, obj_y),
            (obj_x - 10, obj_y),
            (obj_x,      obj_y + 10),
            (obj_x,      obj_y - 10),
        ]
        return min(candidates,
                   key=lambda c: abs(c[0] - player_x) + abs(c[1] - player_y))

    async def _chop_tree(self) -> bool:
        # ── Step 1: coarse move to the tree area ─────────────────────────────
        trees = self.state.nearby_trees()
        if trees:
            # Occasionally target the second-nearest tree instead of the closest.
            # Zero-variance "always pick closest" is a detectable bot signal;
            # real players sometimes click a nearby tree they glanced at instead.
            if len(trees) > 1 and random.random() < 0.12:
                _, _, ax, ay = trees[1]
                log.debug("Targeting second-nearest tree (anti-detect variance)")
            else:
                _, _, ax, ay = trees[0]
        else:
            ax, ay = self.tree_x, self.tree_y
            log.info(f"No trees visible yet — moving to tree area ({ax},{ay})")

        await self._move(ax, ay)
        # Jittered settle delay: let WORLD_OBJECT_SYNC packets arrive.
        # Fixed 0.5 s here would cluster arrivals at the same server-tick offset.
        await asyncio.sleep(_jitter(0.50))

        # ── Step 2: pick the closest visible tree after arriving ──────────────
        trees = self.state.nearby_trees()
        if trees:
            eid, _, tx, ty = trees[0]
        else:
            eid, tx, ty = self.tree_entity, self.tree_x, self.tree_y
            log.warning(f"No trees in sync after move, using default entity={eid} at ({tx},{ty})")

        # ── Step 3: walk to the tile beside the tree, not the tree itself ─────
        # Trees occupy their own tile so PLAYER_MOVE to (tx, ty) is always
        # PATH_TRUNCATED back to our current position — a wasted roundtrip.
        # Pick the nearest orthogonal neighbour instead.
        sx, sy = self._stand_beside(self.state.x, self.state.y, tx, ty)
        log.info(f"Walking beside tree entity={eid} at ({tx},{ty}) → standing at ({sx},{sy})")
        await self._move(sx, sy, arrive_window=12)

        # Human reaction gap before clicking — lognormal, floor 150 ms.
        # Fatigue scale stretches this naturally over long sessions.
        await asyncio.sleep(_human_reaction() * self._fatigue_scale())

        # ── Pre-interact position fidget (~3 % of chops) ──────────────────────
        # Real players occasionally click a nearby tile right before their main
        # action — adjusting position, a misclick, or an accidental camera click.
        # This injects PLAYER_MOVE into periods where the bot would otherwise be
        # completely still, adding entropy to the pre-interact n-gram.
        if random.random() < 0.03:
            await self._position_fidget()
            await asyncio.sleep(_human_reaction(floor=0.10))

        # ── Step 4: send the interact packet ─────────────────────────────────
        self.state.ev_skilling_start.clear()
        self.state.ev_skilling_stop.clear()

        # PLAYER_INTERACT_OBJECT format: (entity_id, action_index)
        # action_index 0 = first interaction option (e.g. "Chop" for trees).
        # tick_slip is already applied inside _send() so packet arrival is
        # phase-shifted within the server tick window.
        await self._send(pack(C.PLAYER_INTERACT_OBJECT, eid, 0))

        if not await self._wait_for_event(self.state.ev_skilling_start, 6.0):
            log.warning("No SKILLING_START")
            return False

        if not await self._wait_for_event(self.state.ev_skilling_stop, 120.0):
            log.warning("No SKILLING_STOP in 2 minutes")
            return False

        # Simulate human reaction latency after seeing the log appear.
        # Fatigue scale increases this over time — tired players respond slower.
        await asyncio.sleep(_human_reaction() * self._fatigue_scale())
        return True

    async def _sell_logs(self):
        if self._sell_lock.locked():
            return
        async with self._sell_lock:
            await self._sell_logs_inner()

    async def _sell_logs_inner(self):
        shopkeeper = self.state.find_shopkeeper()
        if shopkeeper:
            eid, rx, ry = shopkeeper
        else:
            log.info("Robert not in NPC_SYNC yet, using hardcoded position")
            eid, rx, ry = ROBERT_ENTITY_ID, ROBERT_X, ROBERT_Y

        log.info(f"Selling to Robert entity={eid} at ({rx},{ry})")
        await self._move(rx, ry)
        # Jittered settle after walking up to NPC — simulates "looking at the NPC"
        # before right-clicking. Fixed 0.4 s is a strong timing fingerprint.
        await asyncio.sleep(_jitter(0.40))

        self.state.ev_dialogue.clear()
        self.state.ev_shop_open.clear()
        await self._send(pack(C.PLAYER_TALK_NPC, eid))

        if not await self._wait_for_event(self.state.ev_dialogue, 6.0):
            log.warning("No DIALOGUE_OPEN after talking to Robert")
            return

        # Human time to read the dialogue box before clicking an option.
        # Real players are noticeably slower here (reading text): lognormal,
        # median ≈ 400 ms, floor 200 ms (slightly slower than action reactions).
        await asyncio.sleep(max(0.20, _human_reaction(floor=0.20) * 1.4))
        sid = self.state.dialogue_session_id
        log.info(f"DIALOGUE_CHOOSE npc={eid} session={sid} option={self.shop_option}")
        await self._send(pack(C.DIALOGUE_CHOOSE, eid, sid, self.shop_option))

        if await self._wait_for_event(self.state.ev_shop_open, 5.0):
            log.info("SHOP_OPEN received — selling now")
        else:
            log.warning("No SHOP_OPEN after DIALOGUE_CHOOSE — selling anyway")

        # Human time to locate the sell button in the shop UI.
        await asyncio.sleep(_human_reaction())
        n = self.state.logs_in_inventory
        log.info(f"Selling {n} logs from slot 0")
        await self._send(pack(C.PLAYER_SELL_ITEM, 0, n, LOG_ITEM_ID))
        self.state.logs_chopped = 0
        self.state.logs_in_inventory = 0

    # ── Session fatigue ───────────────────────────────────────────────────────

    def _fatigue_scale(self) -> float:
        """
        Returns a delay multiplier that grows as the session ages.

        Models the gradual slowdown real players show during long grind sessions.
        Multiplied into behavioural delays (reactions, inter-action pauses) but
        NOT into tick_slip or heartbeat intervals — those are timing corrections,
        not player behaviour.

            Session age →  0 h    1 h    2 h    3 h    4 h
            Typical scale  1.00   1.08   1.16   1.24   1.32  (capped at 1.45)

        The rate has small Gaussian noise so repeated sessions don't produce
        identical fatigue curves.
        """
        if not self._session_start:
            return 1.0
        elapsed_h = (time.monotonic() - self._session_start) / 3600.0
        # ≈ 8–12 % per hour — enough to be visible in long-session timing plots
        rate = random.gauss(0.10, 0.015)
        return min(1.45, 1.0 + elapsed_h * rate)

    # ── Behavioural entropy helpers ───────────────────────────────────────────

    async def _pickup_nearby_items(self, reach: int = 40) -> None:
        """
        Opportunistically pick up non-log ground items within `reach` (x10 units).

        A bot that ONLY ever sends PLAYER_PICKUP_ITEM for LOG_ITEM_ID=23 (or never
        sends it at all, since logs go straight to inventory) is trivially flagged
        by selective-pickup detection.  Real players notice and grab other items
        they see on the ground — coins, drops from nearby kills, etc.

        Only called when the caller's probability gate passes.  Picks up at most
        2 items per call so the bot doesn't look like a hoover.  Items are sampled
        randomly rather than always in the same order (which would itself be a
        timing fingerprint).
        """
        candidates = [
            (eid, iid, qty, gx, gy)
            for eid, (iid, qty, gx, gy) in self.state.ground_items.items()
            if iid != LOG_ITEM_ID
            and abs(gx - self.state.x) <= reach
            and abs(gy - self.state.y) <= reach
            and qty > 0
        ]
        if not candidates:
            return
        sample = random.sample(candidates, min(2, len(candidates)))
        for eid, iid, _qty, gx, gy in sample:
            await asyncio.sleep(_human_reaction() * self._fatigue_scale())
            try:
                await self._send(pack(C.PLAYER_PICKUP_ITEM, eid))
                log.debug(f"Picked up ground item eid={eid} iid={iid} at ({gx},{gy})")
            except Exception:
                break

    async def _position_fidget(self) -> None:
        """
        Send a 1-tile position nudge to a random orthogonal neighbour.

        During long skilling waits and between-action idle periods the bot sends
        zero PLAYER_MOVE packets.  Real players' characters shuffle slightly —
        a mis-click, a small camera adjustment, or just fidgeting.  This injects
        exactly that noise into the packet stream without disrupting navigation.

        Does NOT await arrival — the server processes the micro-step at its own
        pace and the bot continues with its next action regardless.
        """
        dirs = [(10, 0), (-10, 0), (0, 10), (0, -10)]
        dx, dy = random.choice(dirs)
        tx = self.state.x + dx
        ty = self.state.y + dy
        try:
            await self._send(pack(C.PLAYER_MOVE, 1, tx, ty))
            log.debug(f"Position fidget: nudge → ({tx},{ty})")
        except Exception:
            pass

    async def _maybe_change_stance(self) -> None:
        """
        Occasionally send PLAYER_SET_STANCE to vary attack style.

        In hundreds of kills the bot never sends this packet — a 0-stance-change
        account is a detectable n-gram signal in combat mode.  Real players cycle
        through stances when they want different XP distributions or just out of
        habit.  Called after ≈8 % of kills with its own human-like delay.

        Stance values mirror standard game conventions:
          0 = accurate  1 = aggressive  2 = defensive  3 = controlled
        """
        if random.random() >= 0.08:
            return
        stance = random.randint(0, 3)
        await asyncio.sleep(_human_reaction() * self._fatigue_scale())
        try:
            await self._send(pack(C.PLAYER_SET_STANCE, stance))
            log.debug(f"Changed combat stance → {stance}")
        except Exception:
            pass

    async def _inventory_watchdog(self):
        while True:
            # Jitter the watchdog interval: exact 30.0 s fires are trivially
            # identifiable in server-side packet timing analysis.
            # lognormal around 30 s, scale=0.20 → typical range 20–45 s.
            await asyncio.sleep(_jitter(30.0, scale=0.20))
            n = self.state.logs_in_inventory
            log.info(f"Watchdog: {n}/{SELL_AT_LOGS} logs")
            if n >= SELL_AT_LOGS:
                await self._sell_logs()

    async def _woodcutting_loop(self):
        # Randomise the sell threshold each loop entry so the bot doesn't always
        # sell at exactly SELL_AT_LOGS=28.  This breaks the "sells at a fixed
        # inventory count" signal.  Range: 80–100% of SELL_AT_LOGS.
        _sell_at = random.randint(
            max(1, int(SELL_AT_LOGS * 0.80)),
            SELL_AT_LOGS,
        )
        log.debug(f"Sell threshold for this run: {_sell_at} logs")

        while True:
            ok = await self._chop_tree()
            if ok:
                log.info(f"Logs in inventory: {self.state.logs_in_inventory}/{_sell_at}")

            if self.state.logs_in_inventory >= _sell_at:
                await self._sell_logs()
                # Pick a new sell threshold after each sale.
                _sell_at = random.randint(
                    max(1, int(SELL_AT_LOGS * 0.80)),
                    SELL_AT_LOGS,
                )
                log.debug(f"Next sell threshold: {_sell_at} logs")

            # ── Opportunistic ground item pickup (≈25 % of chops) ────────────
            # Logs go to inventory automatically so we never send PLAYER_PICKUP
            # for them — but real players grab other items they notice.
            # Only check when there's a reasonable chance something is nearby;
            # checking every single chop looks like polling.
            if random.random() < 0.25:
                await self._pickup_nearby_items()

            # ── Inter-chop position fidget (≈2 % of chops) ───────────────────
            # Adds a PLAYER_MOVE to the packet sequence during idle periods.
            if random.random() < 0.02:
                await self._position_fidget()
                await asyncio.sleep(_human_reaction(floor=0.10))

            # Jitter the inter-chop pause, scaled by fatigue so late-session
            # cycles are measurably slower — matching human behaviour.
            await asyncio.sleep(_jitter(0.30) * self._fatigue_scale())

            # Occasional longer idle pause (≈4% of chops): simulates the player
            # glancing at chat, a notification, or just spacing out.
            # Admins reviewing timing plots look for monotonic behaviour;
            # these breaks add the variance a real player always has.
            if random.random() < 0.04:
                idle = random.uniform(8.0, 45.0)
                log.info(f"Idle pause {idle:.1f}s (simulating distraction)")
                await asyncio.sleep(idle)

    # ── Combat ────────────────────────────────────────────────────────────────

    async def _walk_to_cow_area(self):
        """
        Move to a random position within the cow area.

        Uses Gaussian offsets (σ≈30 tiles x10, clamped to ±80) rather than
        uniform randint.  A uniform box distribution is a recognisable
        statistical fingerprint when plotted across many sessions; a Gaussian
        centred on the area matches how real players aim for "roughly the middle"
        with natural imprecision.
        """
        ox = int(random.gauss(0, 30))
        oy = int(random.gauss(0, 30))
        ox = max(-80, min(80, ox))
        oy = max(-80, min(80, oy))
        jx = self.cow_x + ox
        jy = self.cow_y + oy
        log.info(f"Walking to cow area ({jx},{jy})")
        await self._move(jx, jy)

    async def _combat_loop(self):
        await self._walk_to_cow_area()
        await asyncio.sleep(_jitter(1.0))

        no_cow_since = asyncio.get_event_loop().time()

        # Pre-randomise the "no cow → walk closer" timeout so it isn't a
        # constant 30 s across every session.  Lognormal around 28 s, typical
        # range 18–45 s — matches how long a human waits before giving up.
        _no_cow_threshold = _jitter(28.0, scale=0.22)

        # Vary the "cow is too far" walk-closer distance.  A fixed 200-unit
        # threshold creates a detectable boundary; jitter it per loop entry.
        _close_threshold = int(_jitter(200, scale=0.15))

        while True:
            cows = self.state.find_nearby_cows(self.cow_type)

            if not cows:
                waited = asyncio.get_event_loop().time() - no_cow_since
                if waited > _no_cow_threshold:
                    log.info(f"No cows for {int(waited)}s — walking closer")
                    await self._walk_to_cow_area()
                    no_cow_since = asyncio.get_event_loop().time()
                    # Pick a new threshold each time we reposition.
                    _no_cow_threshold = _jitter(28.0, scale=0.22)
                else:
                    log.info(f"No cows visible — waiting ({int(waited)}s)")
                    await asyncio.sleep(_jitter(3.0))
                continue

            # ── Target selection ────────────────────────────────────────────
            # 10% of the time pick the second-nearest cow instead of the
            # closest, matching woodcutting's tree-selection variance.
            # Real players often click a slightly-off target mid-scan.
            no_cow_since = asyncio.get_event_loop().time()
            if len(cows) > 1 and random.random() < 0.10:
                eid, cx, cy = cows[1]
                log.debug("Targeting second-nearest cow (anti-detect variance)")
            else:
                eid, cx, cy = cows[0]

            dist = abs(cx - self.state.x) + abs(cy - self.state.y)
            if dist > _close_threshold:
                log.info(f"Cow entity={eid} is {dist} units away — walking closer")
                await self._move(cx, cy)
                await asyncio.sleep(_jitter(0.50))
                continue

            log.info(f"Attacking cow entity={eid} at ({cx},{cy})")
            await self._move(cx, cy)
            # Human reaction before clicking Attack — lognormal, floor 150 ms.
            await asyncio.sleep(_human_reaction())

            self.state.dead_npcs.discard(eid)
            self.state.ev_player_died.clear()
            self.state.ev_player_respawned.clear()
            await self._send(pack(C.PLAYER_ATTACK_NPC, eid))

            # Jitter the per-combat timeout.  An exact 60 s deadline appears
            # as a sharp cutoff in server-side session analysis; jittering it
            # makes the distribution continuous and human-shaped.
            _combat_timeout = _jitter(60.0, scale=0.15)
            deadline    = asyncio.get_event_loop().time() + _combat_timeout
            target_dead = False
            player_dead = False

            while asyncio.get_event_loop().time() < deadline:
                if self._ws_closed.is_set():
                    raise ConnectionError("WebSocket closed during combat")
                if self.state.ev_player_died.is_set():
                    player_dead = True
                    break
                if eid in self.state.dead_npcs or eid not in self.state.npcs:
                    target_dead = True
                    break
                # Jittered poll interval — fixed 0.5 s creates a visible spike
                # in the packet inter-arrival histogram during combat.
                await asyncio.sleep(_jitter(0.50))

            if not target_dead and not player_dead:
                log.warning(f"Combat stalled on cow {eid} — finding new target")
                continue

            if player_dead:
                log.info("Died — waiting for respawn...")
                if not await self._wait_for_event(self.state.ev_player_respawned, 30.0):
                    log.warning("Respawn timed out — continuing anyway")
                await asyncio.sleep(_jitter(1.0))
                # Use Gaussian walk-back (matches _walk_to_cow_area distribution).
                ox = int(max(-80, min(80, random.gauss(0, 35))))
                oy = int(max(-80, min(80, random.gauss(0, 35))))
                wx, wy = self.cow_x + ox, self.cow_y + oy
                log.info(f"Walking back to cow area ({wx},{wy})")
                await self._move(wx, wy)
            else:
                log.info(f"Cow {eid} defeated")
                # Remove from dead_npcs now that the kill is confirmed — this
                # prevents the set growing unbounded across many respawn cycles.
                # If the server reuses this entity ID for a respawned NPC, the
                # next find_nearby_cows() call will re-evaluate it fresh.
                self.state.dead_npcs.discard(eid)

                # ── Post-kill: opportunistic item pickup (≈30 % of kills) ────
                # NPCs may drop items on death.  Real combat players pick up
                # drops from the creatures they kill.  The bot never sends
                # PLAYER_PICKUP_ITEM in combat — picking up drops post-kill adds
                # that opcode to the action n-gram and directly addresses the
                # selective-pickup detection signal.
                if random.random() < 0.30:
                    await self._pickup_nearby_items(reach=50)

                # ── Post-kill: occasional combat stance change (≈8 % of kills) ─
                # PLAYER_SET_STANCE is never sent across hundreds of kills — a
                # 0-stance-change account is a detectable n-gram fingerprint.
                await self._maybe_change_stance()

                # ── Post-kill: rare position fidget (≈3 % of kills) ──────────
                # After a kill the player's character might step to one side while
                # scanning for the next target.
                if random.random() < 0.03:
                    await self._position_fidget()

                # ── Post-kill idle / reaction delay ───────────────────────────
                # Fatigue scale is applied so late-session reactions are slower.
                if random.random() < 0.04:
                    idle = random.uniform(8.0, 45.0)
                    log.info(f"Idle pause {idle:.1f}s (simulating distraction)")
                    await asyncio.sleep(idle)
                else:
                    await asyncio.sleep(_human_reaction() * self._fatigue_scale())

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self):
        """
        Heartbeat mirrors the browser: 5000–6200 ms jittered interval
        (Zo=5000 ms base, Ra=1200 ms max jitter in GameManager.js).

        CLIENT_ACTIVITY (opcode 121) was removed from the game client enum
        in the latest update — do NOT send it or the OPCODE_MAPPING handshake
        will raise ValueError on a missing logical→wire entry.

        We bypass _send() here (and apply_tick_slip=False) because the ping
        interval already carries 0–1.2 s of uniform jitter from the JS source;
        adding another tick_slip layer would push the interval distribution too
        wide and look abnormal relative to the JS baseline.
        """
        seq = 0
        while True:
            # Match browser: Zo=5000 ms + uniform(0, Ra=1200 ms).
            # Use lognormal on top of the base uniform so the distribution
            # shape better matches real V8 setInterval firing under load.
            base_delay  = 5.0 + random.uniform(0.0, 1.2)
            delay       = _jitter(base_delay, scale=0.06)   # gentle extra spread
            await asyncio.sleep(delay)
            seq = (seq + 1) & 32767
            try:
                # Send directly (no extra tick_slip — see docstring).
                await self.ws.send(pack(C.CLIENT_PING, seq))
            except Exception:
                break

    async def _position_y_loop(self):
        """
        Periodically report our ground Y-height to the server.

        Mirrors reportYToServer() / updateIndoorDetection() in GameManager.js:
          • Only sends when height changes by ≥ 0.05 world units
          • 30-frame cooldown at 60 fps ≈ 0.5 s minimum interval
          • Format: pack(C.CLIENT_POSITION_Y, round(height * 10))

        The height comes from the pathfinder._heights dict which maps
        (tile_x, tile_z) → float world-unit Y.  Tiles that don't appear in
        the dict (void / unmapped) default to 0.0.
        """
        last_y: float | None = None
        while True:
            # JS source enforces a 30-frame (≈0.5 s at 60 fps) cooldown between
            # CLIENT_POSITION_Y sends.  The old scale=0.10 gave only ±5 %
            # variance (475–525 ms), creating the most regular high-frequency
            # packet stream in the bot and the clearest tickAlignedTiming signal.
            # scale=0.30 spreads the interval over ~300–820 ms while keeping
            # the median at 500 ms, matching the natural rAF timing drift a
            # browser exhibits across frames.
            await asyncio.sleep(_jitter(0.50, scale=0.30))
            if not self.ws:
                continue
            # Convert x10 state coords to tile indices
            tx = self.state.x // 10
            tz = self.state.y // 10
            height = pathfinder._heights.get((tx, tz), 0.0)
            # Only send when height changed by ≥ 0.05 (threshold from JS source).
            # Route through _send() so tick_slip is applied — bypassing it here
            # would create regular 0.5-second spikes whenever the player is moving
            # through terrain with varying heights.
            if last_y is None or abs(height - last_y) >= 0.05:
                try:
                    await self._send(pack(C.CLIENT_POSITION_Y, round(height * 10)))
                    last_y = height
                except Exception:
                    break

    # ── Entry points ─────────────────────────────────────────────────────────

    async def run(self, mode: str = "woodcutting"):
        pathfinder.load_walls()
        pathfinder.load_tiles()
        pathfinder.load_heights()
        pathfinder.load_dynamic_blocks()
        log.info(f"Pathfinder ready — {len(pathfinder._walls)} walls, "
                 f"{len(pathfinder._blocked_tiles)} water tiles, "
                 f"{len(pathfinder._heights)} height tiles, "
                 f"{len(pathfinder._dynamic_blocked)} dynamic blocks")

        self._token, self._device_id, self._device_cookie = await self._http_login()

        # Record session start so _fatigue_scale() can measure elapsed time.
        # Set once at login — not reset on reconnect so fatigue accumulates
        # continuously across reconnect cycles within the same run.
        self._session_start = time.monotonic()

        MAX_RECONNECTS = 5
        reconnect_count = 0

        while True:
            # ── Connect ──────────────────────────────────────────────────────
            ws = GameWebSocket(self._token, self._device_id, self._device_cookie)
            await ws.connect()   # performs CRYPTO_CHALLENGE/RESPONSE + OPCODE_MAPPING
            self.ws = ws
            self._ws_closed.clear()
            log.info("WebSocket connected + crypto handshake complete")

            recv      = asyncio.create_task(self._recv_loop())
            heartbeat = asyncio.create_task(self._heartbeat_loop())
            pos_y     = asyncio.create_task(self._position_y_loop())

            try:
                await asyncio.wait_for(self.state.ev_login_ok.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                raise RuntimeError("No LOGIN_OK within 10 s")

            # Shorter delay on reconnects (state already known from first login).
            # Jitter the first-login delay too — uniform(3,5) is narrow enough
            # to be detectable on a fleet of accounts started at the same time.
            if reconnect_count == 0:
                await asyncio.sleep(_jitter(random.uniform(3.0, 8.0), scale=0.25))
            else:
                await asyncio.sleep(_jitter(1.0))
            log.info(
                f"Ready — mode={mode} pos=({self.state.x},{self.state.y}) "
                f"trees={len(self.state.nearby_trees())} npcs={len(self.state.npcs)}"
            )

            # ── Bot loop ─────────────────────────────────────────────────────
            disconnected = False
            try:
                if mode == "woodcutting":
                    watchdog = asyncio.create_task(self._inventory_watchdog())
                    try:
                        await self._woodcutting_loop()
                    finally:
                        watchdog.cancel()
                else:
                    await self._combat_loop()
            except ConnectionError as exc:
                # Clean disconnect or socket reset — try to reconnect
                log.warning(f"Connection lost: {exc} — will attempt reconnect")
                disconnected = True
            except OSError as exc:
                # TLS/SSL errors (ssl.SSLEOFError etc.) are OSError subclasses
                log.warning(f"Connection lost (OS/TLS error): {exc} — will attempt reconnect")
                disconnected = True
            finally:
                recv.cancel()
                heartbeat.cancel()
                pos_y.cancel()

            await ws.close()

            if not disconnected:
                break   # normal exit (stopped by user or bot logic finished)

            if reconnect_count >= MAX_RECONNECTS:
                log.error(f"Max reconnects ({MAX_RECONNECTS}) reached — giving up")
                break

            reconnect_count += 1
            delay = min(30, 5 * reconnect_count)
            log.info(
                f"Reconnecting in {delay}s "
                f"(attempt {reconnect_count}/{MAX_RECONNECTS})…"
            )
            await asyncio.sleep(delay)

            # Reset per-connection state; keep game state (npcs, objects, position)
            self.state.ev_login_ok.clear()
            self._ws_closed.clear()

            # Refresh token from cache (opens browser only if cached token expired)
            try:
                self._token, self._device_id, self._device_cookie = await self._http_login()
            except Exception as exc:
                log.error(f"Re-login failed: {exc}")
                break

    async def sniff(self):
        self._token, self._device_id, self._device_cookie = await self._http_login()

        ws = GameWebSocket(self._token, self._device_id, self._device_cookie)
        await ws.connect()
        self.ws = ws
        log.info("SNIFF MODE — go play the game now. Press Ctrl+C to stop.")

        while True:
            try:
                data = await ws.recv()
            except ConnectionError:
                break
            if data is None:
                continue

            op, vals = unpack(data)
            name   = SERVER_NAMES.get(op, f"op_{op}")
            parsed = try_unpack_str(data)
            if parsed and not all(32 <= ord(c) < 127 or c == "\x00" for c in parsed[0]):
                print(f"  {name:20s} vals={vals}")
            elif parsed and parsed[0]:
                print(f"  {name:20s} str={parsed[0]!r:30s} vals={parsed[1]}")
            else:
                print(f"  {name:20s} vals={vals}")


# ── CLI ───────────────────────────────────────────────────────────────────────

def _select_mode_interactive() -> str:
    print("\nSelect bot mode:")
    print("  1) Woodcutting — chop trees and sell logs to Robert")
    print("  2) Combat      — auto-attack cows, walk back on death")
    while True:
        choice = input("Choice [1/2]: ").strip()
        if choice == "1":
            return "woodcutting"
        if choice == "2":
            return "combat"
        print("  Enter 1 or 2.")


def main():
    parser = argparse.ArgumentParser(description="EvilQuest bot")
    parser.add_argument("--username",
                        default=os.environ.get("EVILQUEST_USER"),
                        required=not os.environ.get("EVILQUEST_USER"))
    parser.add_argument("--password",
                        default=os.environ.get("EVILQUEST_PASSWORD"),
                        required=not os.environ.get("EVILQUEST_PASSWORD"))
    parser.add_argument("--mode",        choices=["woodcutting", "combat"],
                        help="Bot mode (skips interactive prompt)")
    parser.add_argument("--tree-entity", type=int, default=DEFAULT_TREE_ENTITY)
    parser.add_argument("--tree-x",     type=int, default=DEFAULT_TREE_X)
    parser.add_argument("--tree-y",     type=int, default=DEFAULT_TREE_Y)
    parser.add_argument("--shop-option",type=int, default=0)
    parser.add_argument("--cow-type",   type=int, default=DEFAULT_COW_TYPE_ID)
    parser.add_argument("--cow-x",      type=int, default=DEFAULT_COW_X)
    parser.add_argument("--cow-y",      type=int, default=DEFAULT_COW_Y)
    parser.add_argument("--sniff",      action="store_true")
    parser.add_argument("--debug",      action="store_true")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    bot = Bot(
        username=args.username,
        password=args.password,
        tree_entity=args.tree_entity,
        tree_x=args.tree_x,
        tree_y=args.tree_y,
        shop_option=args.shop_option,
        cow_type=args.cow_type,
        cow_x=args.cow_x,
        cow_y=args.cow_y,
    )

    if args.sniff:
        asyncio.run(bot.sniff())
        return

    mode = args.mode or _select_mode_interactive()
    log.info(f"Starting in {mode} mode")
    asyncio.run(bot.run(mode))


if __name__ == "__main__":
    main()
