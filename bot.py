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
import os
import random

from protocol import C, S, SERVER_NAMES, pack, pack_str, unpack, try_unpack_str
from ws_transport import GameWebSocket, http_login
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

    def find_nearest_cow(self, cow_type: int) -> tuple | None:
        best, best_d = None, 10_000
        for eid, (tid, nx, ny, hp, _mhp) in self.npcs.items():
            if tid == cow_type and hp > 0 and eid not in self.dead_npcs:
                d = abs(nx - self.x) + abs(ny - self.y)
                if d < best_d:
                    best_d = d
                    best = (eid, nx, ny)
        return best


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

        self._trunc_at: tuple[int, int] | None = None
        self._trunc_count: int = 0
        self.ev_path_truncated = asyncio.Event()

    # ── Network ──────────────────────────────────────────────────────────────

    def _http_login_sync(self) -> tuple[str, str, str]:
        """Returns (auth_token, device_id, device_cookie)."""
        token, device_id, cookie = http_login(self.username, self.password)
        log.info("HTTP login OK — device_id=%s", device_id[:8] + "…")
        return token, device_id, cookie

    async def _send(self, data: bytes):
        await self.ws.send(data)

    # ── Message dispatch ─────────────────────────────────────────────────────

    def _dispatch(self, raw: bytes):
        op, vals = unpack(raw)

        if op == S.LOGIN_OK:
            if vals:
                self.state.own_entity_id = vals[0]
                if len(vals) >= 3:
                    self.state.x, self.state.y = vals[1], vals[2]
            log.info(f"LOGIN_OK entity_id={self.state.own_entity_id} pos=({self.state.x},{self.state.y})")
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

        elif op == S.SERVER_PONG:
            log.debug(f"SERVER_PONG seq={vals[0] if vals else '?'}")

        elif op == S.NPC_APPEARANCE:
            log.debug(f"NPC_APPEARANCE entity={vals[0] if vals else '?'}")

        elif op == S.PATH_TRUNCATED:
            if len(vals) >= 2:
                self.state.x, self.state.y = vals[0], vals[1]
                log.info(f"PATH_TRUNCATED at ({vals[0]},{vals[1]})")
                pos = (vals[0], vals[1])
                if self._trunc_at == pos:
                    self._trunc_count += 1
                else:
                    self._trunc_at = pos
                    self._trunc_count = 1
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

    async def _move(self, x: int, y: int, timeout: float | None = None):
        """
        Move to (x, y) in x10 coordinates.

        The server never sends position updates during normal movement — the JS client
        uses client-side prediction (moveSpeed=1.67 tiles/sec).  We mirror that here:
        estimate travel time from path length, sleep, then assume arrival.

        If the server sends PATH_TRUNCATED the position IS updated and we re-path.
        If the server sends PLAYER_SELF_SYNC (rare correction) the position is updated too.
        """
        if abs(self.state.x - x) <= ARRIVE_WINDOW and abs(self.state.y - y) <= ARRIVE_WINDOW:
            return

        log.info(f"Moving to ({x},{y}), currently at ({self.state.x},{self.state.y})")
        self.ev_path_truncated.clear()
        self._trunc_at    = None
        self._trunc_count = 0

        async def _send_path_from(sx: int, sz: int) -> int:
            """Send a move packet from (sx,sz) to (x,y). Returns waypoint count."""
            path = pathfinder.find_path(sx, sz, x, y)
            if path:
                chunk = path[:50]
                args  = [len(chunk)]
                for wx, wz in chunk:
                    args.extend([wx, wz])
                await self._send(pack(C.PLAYER_MOVE, *args))
                return len(chunk)
            else:
                await self._send(pack(C.PLAYER_MOVE, 1, x, y))
                return max(1, (abs(sx - x) + abs(sz - y)) // 10)

        n_steps    = await _send_path_from(self.state.x, self.state.y)
        travel_sec = n_steps / WALK_TILES_PER_SEC

        if timeout is None:
            timeout = max(15.0, travel_sec * 2.5)

        loop    = asyncio.get_event_loop()
        deadline = loop.time() + timeout
        elapsed  = 0.0

        # Sleep through estimated travel time, waking early on PATH_TRUNCATED
        while elapsed < travel_sec and loop.time() < deadline:
            remaining = travel_sec - elapsed
            try:
                await asyncio.wait_for(self.ev_path_truncated.wait(), timeout=min(1.0, remaining))
                self.ev_path_truncated.clear()
            except asyncio.TimeoutError:
                elapsed += 1.0
                continue

            # PATH_TRUNCATED: server gave us our actual position — re-path from there
            cx, cy = self.state.x, self.state.y

            if abs(cx - x) <= ARRIVE_WINDOW and abs(cy - y) <= ARRIVE_WINDOW:
                log.info(f"Arrived at ({cx},{cy}) (PATH_TRUNCATED near destination)")
                return

            if self._trunc_count >= 2:
                fresh = pathfinder.find_path(cx, cy, x, y)
                if fresh:
                    bx10, bz10 = fresh[0]
                    btx, btz   = bx10 // 10, bz10 // 10
                    log.info(f"Dynamic block ({btx},{btz}) — repeated PATH_TRUNCATED at ({cx},{cy})")
                    pathfinder.add_dynamic_block(btx, btz)
                self._trunc_count = 0
                self._trunc_at    = None

            log.info(f"PATH_TRUNCATED, re-pathing from ({cx},{cy})")
            n_steps    = await _send_path_from(cx, cy)
            travel_sec = n_steps / WALK_TILES_PER_SEC
            elapsed    = 0.0

        # Check if a PLAYER_SELF_SYNC already moved us there
        cx, cy = self.state.x, self.state.y
        if abs(cx - x) <= ARRIVE_WINDOW and abs(cy - y) <= ARRIVE_WINDOW:
            log.info(f"Arrived at ({cx},{cy}) (server confirmed)")
        else:
            # Client-side prediction: assume we reached the destination
            log.info(f"Movement done ({n_steps} steps ≈ {travel_sec:.1f}s), assuming at ({x},{y})")
            self.state.x, self.state.y = x, y

    # ── Woodcutting ───────────────────────────────────────────────────────────

    async def _chop_tree(self) -> bool:
        # Decide where to move first
        trees = self.state.nearby_trees()
        if trees:
            _, _, tx, ty = trees[0]
        else:
            tx, ty = self.tree_x, self.tree_y
            log.info(f"No trees visible yet — moving to tree area ({tx},{ty})")

        self.state.ev_skilling_start.clear()
        self.state.ev_skilling_stop.clear()

        await self._move(tx, ty)
        await asyncio.sleep(0.5)   # let WORLD_OBJECT_SYNC packets arrive for the new area

        # Re-scan after arriving — trees in the area should now be in state.objects
        trees = self.state.nearby_trees()
        if trees:
            eid, _, tx, ty = trees[0]
            log.info(f"Chopping tree entity={eid} at ({tx},{ty})")
        else:
            eid, tx, ty = self.tree_entity, self.tree_x, self.tree_y
            log.warning(f"No trees in sync after move, using default entity={eid} at ({tx},{ty})")

        # PLAYER_INTERACT_OBJECT format: (entity_id, action_index)
        # action_index 0 = first interaction option (e.g. "Chop" for trees)
        await self._send(pack(C.PLAYER_INTERACT_OBJECT, eid, 0))

        try:
            await asyncio.wait_for(self.state.ev_skilling_start.wait(), timeout=6.0)
        except asyncio.TimeoutError:
            log.warning("No SKILLING_START")
            return False

        try:
            await asyncio.wait_for(self.state.ev_skilling_stop.wait(), timeout=120.0)
        except asyncio.TimeoutError:
            log.warning("No SKILLING_STOP in 2 minutes")
            return False

        # Logs go directly to inventory in EvilQuest (no ground pickup needed).
        # logs_in_inventory is incremented in the SKILLING_STOP handler.
        await asyncio.sleep(0.2)
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
        await asyncio.sleep(0.4)

        self.state.ev_dialogue.clear()
        self.state.ev_shop_open.clear()
        await self._send(pack(C.PLAYER_TALK_NPC, eid))

        try:
            await asyncio.wait_for(self.state.ev_dialogue.wait(), timeout=6.0)
        except asyncio.TimeoutError:
            log.warning("No DIALOGUE_OPEN after talking to Robert")
            return

        await asyncio.sleep(0.3)
        sid = self.state.dialogue_session_id
        log.info(f"DIALOGUE_CHOOSE npc={eid} session={sid} option={self.shop_option}")
        await self._send(pack(C.DIALOGUE_CHOOSE, eid, sid, self.shop_option))

        try:
            await asyncio.wait_for(self.state.ev_shop_open.wait(), timeout=5.0)
            log.info("SHOP_OPEN received — selling now")
        except asyncio.TimeoutError:
            log.warning("No SHOP_OPEN after DIALOGUE_CHOOSE — selling anyway")

        await asyncio.sleep(0.3)
        n = self.state.logs_in_inventory
        log.info(f"Selling {n} logs from slot 0")
        await self._send(pack(C.PLAYER_SELL_ITEM, 0, n, LOG_ITEM_ID))
        self.state.logs_chopped = 0
        self.state.logs_in_inventory = 0

    async def _inventory_watchdog(self):
        while True:
            await asyncio.sleep(30)
            n = self.state.logs_in_inventory
            log.info(f"Watchdog: {n}/{SELL_AT_LOGS} logs")
            if n >= SELL_AT_LOGS:
                await self._sell_logs()

    async def _woodcutting_loop(self):
        while True:
            ok = await self._chop_tree()
            if ok:
                log.info(f"Logs in inventory: {self.state.logs_in_inventory}/{SELL_AT_LOGS}")
            if self.state.logs_in_inventory >= SELL_AT_LOGS:
                await self._sell_logs()
            await asyncio.sleep(0.3)

    # ── Combat ────────────────────────────────────────────────────────────────

    async def _walk_to_cow_area(self):
        jx = self.cow_x + random.randint(-60, 60)
        jy = self.cow_y + random.randint(-60, 60)
        log.info(f"Walking to cow area ({jx},{jy})")
        await self._move(jx, jy)

    async def _combat_loop(self):
        await self._walk_to_cow_area()
        await asyncio.sleep(1.0)

        no_cow_since = asyncio.get_event_loop().time()

        while True:
            cow = self.state.find_nearest_cow(self.cow_type)
            if not cow:
                waited = asyncio.get_event_loop().time() - no_cow_since
                if waited > 30:
                    log.info("No cows for 30s — walking closer")
                    await self._walk_to_cow_area()
                    no_cow_since = asyncio.get_event_loop().time()
                else:
                    log.info(f"No cows visible — waiting ({int(waited)}s)")
                    await asyncio.sleep(3.0)
                continue

            eid, cx, cy = cow
            no_cow_since = asyncio.get_event_loop().time()
            dist = abs(cx - self.state.x) + abs(cy - self.state.y)
            if dist > 200:
                log.info(f"Cow entity={eid} is {dist} units away — walking closer")
                await self._move(cx, cy)
                await asyncio.sleep(0.5)
                continue

            log.info(f"Attacking cow entity={eid} at ({cx},{cy})")
            await self._move(cx, cy)
            await asyncio.sleep(0.5)

            self.state.dead_npcs.discard(eid)
            self.state.ev_player_died.clear()
            self.state.ev_player_respawned.clear()
            await self._send(pack(C.PLAYER_ATTACK_NPC, eid))

            deadline    = asyncio.get_event_loop().time() + 60.0
            target_dead = False
            player_dead = False

            while asyncio.get_event_loop().time() < deadline:
                if self.state.ev_player_died.is_set():
                    player_dead = True
                    break
                if eid in self.state.dead_npcs or eid not in self.state.npcs:
                    target_dead = True
                    break
                await asyncio.sleep(0.5)

            if not target_dead and not player_dead:
                log.warning(f"Combat stalled on cow {eid} — finding new target")
                continue

            if player_dead:
                log.info("Died — waiting for respawn...")
                try:
                    await asyncio.wait_for(self.state.ev_player_respawned.wait(), timeout=30.0)
                except asyncio.TimeoutError:
                    log.warning("Respawn timed out — continuing anyway")
                await asyncio.sleep(1.0)
                wx = self.cow_x + random.randint(-80, 80)
                wy = self.cow_y + random.randint(-80, 80)
                log.info(f"Walking back to cow area ({wx},{wy})")
                await self._move(wx, wy)
            else:
                log.info(f"Cow {eid} defeated")
                self.state.dead_npcs.discard(eid)
                await asyncio.sleep(0.5)

    # ── Heartbeat ─────────────────────────────────────────────────────────────

    async def _heartbeat_loop(self):
        """
        Heartbeat mirrors the browser: 5000–6200 ms jittered interval (matches
        _a=5000, Ra=1200 in GameManager.js).  Also sends CLIENT_ACTIVITY to
        simulate the user being at the keyboard.
        """
        seq              = 0
        last_activity    = 0.0
        loop             = asyncio.get_running_loop()
        while True:
            delay = 5.0 + random.uniform(0.0, 1.2)
            await asyncio.sleep(delay)
            now = loop.time()
            seq = (seq + 1) & 32767
            try:
                await self.ws.send(pack(C.CLIENT_PING, seq))
                # Send CLIENT_ACTIVITY no more than once every 5 s
                if now - last_activity >= 5.0:
                    await self.ws.send(pack(C.CLIENT_ACTIVITY))
                    last_activity = now
            except Exception:
                break

    # ── Entry points ─────────────────────────────────────────────────────────

    async def run(self, mode: str = "woodcutting"):
        pathfinder.load_walls()
        pathfinder.load_tiles()
        log.info(f"Pathfinder ready — {len(pathfinder._walls)} walls, "
                 f"{len(pathfinder._blocked_tiles)} blocked tiles loaded")

        loop = asyncio.get_running_loop()
        self._token, self._device_id, self._device_cookie = await loop.run_in_executor(None, self._http_login_sync)

        ws = GameWebSocket(self._token, self._device_id, self._device_cookie)
        await ws.connect()   # performs CRYPTO_CHALLENGE/RESPONSE + OPCODE_MAPPING
        self.ws = ws
        log.info("WebSocket connected + crypto handshake complete")

        recv      = asyncio.create_task(self._recv_loop())
        heartbeat = asyncio.create_task(self._heartbeat_loop())

        try:
            await asyncio.wait_for(self.state.ev_login_ok.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            raise RuntimeError("No LOGIN_OK within 10 s")

        await asyncio.sleep(random.uniform(3.0, 5.0))
        log.info(
            f"Ready — mode={mode} pos=({self.state.x},{self.state.y}) "
            f"trees={len(self.state.nearby_trees())} npcs={len(self.state.npcs)}"
        )

        if mode == "woodcutting":
            watchdog = asyncio.create_task(self._inventory_watchdog())
            try:
                await self._woodcutting_loop()
            finally:
                recv.cancel()
                watchdog.cancel()
                heartbeat.cancel()
        else:
            try:
                await self._combat_loop()
            finally:
                recv.cancel()
                heartbeat.cancel()

        await ws.close()

    async def sniff(self):
        loop = asyncio.get_running_loop()
        self._token, self._device_id, self._device_cookie = await loop.run_in_executor(None, self._http_login_sync)

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
    parser.add_argument("--username",    required=True)
    parser.add_argument("--password",    required=True)
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
