# EvilQuest Bot · v3.1

Automation bot for [EvilQuest](https://evilquest.net) supporting woodcutting and combat modes.  
Fully implements the **evilquest-game-v2** WebSocket protocol including ECDH key exchange, per-session opcode remapping, and AES-256-GCM encrypted frames.

---

## Features

- **Woodcutting mode** — chops trees near the default area, auto-sells logs to Robert when inventory is full (28 logs)
- **Combat mode** — finds and attacks cows, walks back to the combat area on death
- **Sniff mode** — passive packet logger; play the game manually while the bot prints every decoded message (useful for reverse engineering)
- Automatic reconnect-safe login: fetches a server-issued device ID, registers a persistent ECDSA signing key, and negotiates a fresh session on every run
- A\* pathfinder with wall, water-tile, and **height-based cliff blocking** (pre-computed from terrain height chunks); dynamic tile learning via `PATH_TRUNCATED` catches any missed edges
- Jittered heartbeat (5.0–6.2 s) with `CLIENT_ACTIVITY` to pass behavioural checks

---

## Requirements

```
Python 3.11+
cryptography
requests
```

Install dependencies:

```bash
pip install cryptography requests
```

Map assets (walls, tile chunks, height chunks) must be present under `gameassets/maps/kcmap/`.  
Run `scrape_assets.py` once to download them if missing.

---

## Usage

```bash
# Woodcutting (chops trees, sells logs)
python bot.py --username YOUR_USER --password YOUR_PASS --mode woodcutting

# Combat (attacks cows)
python bot.py --username YOUR_USER --password YOUR_PASS --mode combat

# Sniff mode — decode all packets while you play manually
python bot.py --username YOUR_USER --password YOUR_PASS --sniff

# Extra flags
--debug            # verbose packet logging
--tree-entity INT  # override default tree entity ID
--tree-x INT       # override default tree X coordinate (x10)
--tree-y INT       # override default tree Y coordinate (x10)
--shop-option INT  # dialogue option index for the shop NPC
--cow-type INT     # NPC type ID to attack
--cow-x / --cow-y  # cow area centre (x10 coords)
```

Persistent state is stored in `~/.evilquest/` (device ID, ECDSA signing key).  
On first run the bot generates the signing key and registers it with the server automatically.

---

## Version history

| Version | Date | Summary |
|---|---|---|
| **3.1** | May 2026 | Height-based cliff pre-computation (≥78 % of cliff tiles blocked at startup); on-path immediate blocking; Euclidean wait-time; `.env` credential loading |
| **3.0** | May 2026 | Dynamic obstacle persistence; robust `_move()` position tracking; on-path/off-path PATH_TRUNCATED detection; A* tuning |
| **2.0** | May 2026 | Full evilquest-game-v2 protocol rewrite (ECDH, AES-256-GCM, opcode remapping, signing key) |
| **1.0** | — | Initial release (v1 protocol, static key, basic woodcutting) |

---

## Changelog

---

### v3.1 — Height-based cliff detection + credential management (May 2026)

#### Background

After v3.0's dynamic block learning, the bot was still spending the first 2–5 minutes of each run re-learning the cliff from scratch (PATH_TRUNCATED events required 2 occurrences before blocking a tile, and 233 blocks × ~1.5 s each = significant delay).  
Two improvements were made: (1) pre-compute cliff tiles from the terrain height data already present on disk, and (2) block on the first on-path truncation instead of waiting for a second.

---

#### 3.1.1 Height-based cliff pre-computation (`pathfinder.py`)

| What changed | Why |
|---|---|
| Added `_HEIGHTS_DIR` pointing to `gameassets/maps/kcmap/heights/` | Location of per-chunk terrain height files |
| Added `HEIGHT_CLIFF_THRESHOLD = 0.7` constant | Height difference (game units) above which an edge between two tiles is treated as impassable |
| Added `_heights` dict and `load_heights()` | Reads all 16 `chunk_CX_CZ.json` height files at startup; keys are `(global_x, global_z)` tile coords, values are floats |
| `_is_wall_blocked()` checks height diff before wall bitmask | If `abs(h_from − h_to) > 0.7`, the edge is blocked — no server round-trip needed |
| `find_path()` auto-calls `load_heights()` on first invocation | Heights always loaded before the first A\* search |

**Calibration:** empirical testing against 233 known cliff blocks showed threshold `0.75` matches 78 % of them; `1.0` matches 55 %.  
`HEIGHT_CLIFF_THRESHOLD = 0.7` recovers a few additional edges.  The remaining misses are still caught by PATH_TRUNCATED dynamic learning.

Height data format (sparse JSON):
```json
{ "row,col": float_height, ... }
```
`row` = local z, `col` = local x within the 64×64 chunk.  Tiles absent from the file default to height `0.0`.

---

#### 3.1.2 On-path immediate blocking (`bot.py`)

**Problem:** the old code required 2 PATH_TRUNCATED events at the same `(trunc_x, trunc_y)` position before blocking the implied tile.  
For an on-path truncation this is one round-trip too many: if the player is walking *toward* tile T and the server sends `PATH_TRUNCATED` with endpoint T, then the tile *after* T in the sent path is definitively blocked.

**Fix:** on on-path truncation, look up the truncation tile in `_last_path_sent` and immediately call `pathfinder.add_dynamic_block()` for the next tile in the list.  The 2-occurrence gate is retained only for off-path (position-correction) truncations.

---

#### 3.1.3 Euclidean wait-time (`bot.py`)

Diagonal moves are `√2 ≈ 1.414` tiles long but the old wait-time calculation used Manhattan distance (overestimates by up to 41 % on diagonals).  
Fixed: `trunc_dist_tiles = math.sqrt((cur_x − tx)² + (cur_y − tz)²) / 10.0`.

---

#### 3.1.4 `.env` credential loading (`bot.py`)

Added `_load_dotenv()`: reads `key=value` pairs from `.env` (same directory as `bot.py`) into `os.environ` at import time.  
`--username` and `--password` CLI flags now default to `EVILQUEST_USER` / `EVILQUEST_PASSWORD` from the environment; they become optional when `.env` is present.  
The `.env` file is listed in `.gitignore` and never tracked.

---

### v3.0 — Navigation reliability (May 2026)

#### Background

After deploying combat mode, the bot could not reach the cow area reliably.  
A large diagonal cliff running from tile (85,106) to (127,161) is enforced server-side but **absent from the local `walls.json` / tile chunk data**.  
The server responds to illegal cross-cliff moves with `PATH_TRUNCATED`, which was being handled incorrectly in several ways — wrong position tracking, wrong tile blocked, redundant waiting — causing the bot to spin in place or diverge from its actual game position.

---

#### 3.1 Dynamic block persistence (`pathfinder.py`)

| What changed | Why |
|---|---|
| Added `load_dynamic_blocks()` — reads `~/.evilquest/dynamic_blocks.json` on startup | Previously, every run re-learned the entire cliff from scratch via repeated `PATH_TRUNCATED` signals |
| Added `_save_dynamic_blocks()` — atomically persists the current block set after each new discovery | Ensures blocks accumulate across runs |
| Modified `add_dynamic_block()` — skips save if tile already known | Avoids redundant writes |

Format: `[[tx, tz], ...]` sorted by coordinate pair.

---

#### 3.2 A\* `max_steps` increase (`pathfinder.py`)

Default `max_steps` raised **500 → 5000** (node expansion budget 2000 → 20000).

With 185+ dynamic blocks representing the diagonal cliff staircase, paths from spawn positions near the cliff require A\* to explore a large detour around the obstacle.  
The old limit caused `find_path()` to return `[]` (no path found) for legitimate routes, forcing the bot to send a single-waypoint fallback move that the server immediately truncated.

Worst-case timing: ~100 ms for a full 5000-step search. Acceptable at 1.67 tiles/sec walk speed.

---

#### 3.3 `_move()` position-tracking overhaul (`bot.py`)

Three independent position-tracking bugs fixed in the movement loop:

**Bug 1 — State not updated on `PATH_TRUNCATED`**

The server-confirmed position in `state.trunc_x / trunc_y` was not being written back to `state.x / state.y`.  
Subsequent A\* calls planned from a stale position, generating paths that crossed already-known obstacles.

Fix: `self.state.x, self.state.y = tx, ty` immediately upon receiving `PATH_TRUNCATED`.

**Bug 2 — Timeout assumed arrival**

On movement timeout, the old code set `state.x, state.y = destination`, assuming the player arrived.  
When the player was actually stuck mid-path (e.g., blocked by the cliff), this caused all later moves to start A\* from the wrong position.

Fix: on timeout, use `cur_x, cur_y` (the last `PATH_TRUNCATED`-confirmed position) rather than the intended destination.

**Bug 3 — Wrong tile blocked on repeated truncation**

When A\* re-pathed from the truncation point, the old code blocked `fresh[0]` — the first step of the *new* path from the truncation point.  
This is not necessarily the impassable tile.  

Fix: look up the truncation tile in `_last_path_sent` (the actual path sent to the server).  
The *next* tile in that list after the truncation point is the tile the server refused to enter, and that is the correct tile to block.

---

#### 3.4 On-path vs off-path `PATH_TRUNCATED` detection (`bot.py`)

**Problem:** The server sometimes sends `PATH_TRUNCATED` at a tile that is *not on the planned path*.  
This is a position-correction signal: the player's actual position differs from the client's assumption.  
The old code always waited `distance / 1.67` seconds before re-pathing, causing a stall when the truncation tile was off-path.

**Fix:** Check whether the truncation tile appears in `_last_path_sent`:

- **In path** → the player is walking there; wait `(distance_to_trunc) / 1.67` seconds before re-pathing.
- **Not in path** → position correction; re-path immediately, no wait.

---

#### 3.5 `_last_path_sent` tracking (`bot.py`)

Added `_last_path_sent: list[tuple[int, int]]` populated by `_send_path_from()`.  
Stores the exact waypoint list sent in the last `PLAYER_MOVE` packet (up to 50 waypoints).  
Used by both the on-path detection (3.4) and the correct-tile-to-block logic (3.3 Bug 3).

---

### v2.0 — Protocol v2 rewrite (May 2026)

#### Background

EvilQuest's anti-cheat was upgraded to the **evilquest-game-v2** subprotocol.  
The original bot was failing with `403 Client Error: Forbidden for url: https://evilquest.net/api/login`.  
Every layer of the connection — HTTP login, WebSocket upgrade, encryption, opcode layout, and game logic — had changed.  
This session reverse-engineered the new protocol from the minified JS bundle and rewrote the transport, protocol definitions, and game logic to match.

---

#### 2.1 HTTP login hardening (`ws_transport.py`)

| What changed | Why |
|---|---|
| Added Chrome-like browser headers (`User-Agent`, `Sec-Fetch-*`, `Origin`, `Referer`, …) to every API call | Server fingerprints headers and returns 403 to non-browser clients |
| `GET /api/device-id` before login | Server requires a server-issued UUID; self-generated UUIDs return 400 "Missing or invalid device identifier" |
| Store/restore `eq_device_id` cookie across runs (`~/.evilquest/device.json`) | Server ties the device ID to a cookie; sending a mismatched pair fails |
| Collect *all* session cookies after login (`eq_device_id` + `eq_ws_session`) and forward them verbatim in the WebSocket `Cookie:` header | `eq_ws_session` is set during login and checked during WS upgrade; omitting it gives 401 |

---

#### 2.2 Full protocol v2 rewrite (`ws_transport.py`)

The v1 protocol used a static SHA-256 key derived from the auth token + a server nonce, a uint32 counter, no AAD, and fixed opcodes.  
v2 replaces all of this.

#### 2.2a ECDH P-256 key exchange

Every session generates a fresh ephemeral P-256 keypair.  
The server sends its ephemeral public key in the `CRYPTO_CHALLENGE` frame.  
An ECDH shared secret is computed and fed into HKDF to produce the session keys.

#### 2.2b Persistent device signing key (ECDSA P-256)

A persistent P-256 signing key is stored in `~/.evilquest/signing_key.json`.  
On every login the public key is registered with `POST /api/device-key` (JWK format, `key_ops: ["verify"]`).  
During the handshake the bot signs the session transcript with this key.  
Signatures are in **P1363 format** (raw r ‖ s, 64 bytes) — not DER, which is what Python's `cryptography` library produces by default.

#### 2.2c HKDF-SHA-256 session key derivation

```
ecdh_secret    = ECDH(clientEphemeral.private, serverPublic)
auth_hash      = SHA-256(authToken)
transcript_hash = SHA-256(canonical_json(transcript))
hkdf_ikm       = ecdh_secret ‖ auth_hash ‖ transcript_hash

salt = SHA-256("evilquest-game-v2:salt" ‖ serverNonce ‖ clientNonce ‖ auth_hash)

c2s_key        = HKDF(hkdf_ikm, salt, "evilquest-game-v2:client-to-server:<connId>")  [32 B]
s2c_key        = HKDF(hkdf_ikm, salt, "evilquest-game-v2:server-to-client:<connId>")  [32 B]
c2s_iv_prefix  = SHA-256("evilquest-game-v2:iv:client-to-server" ‖ transcript_hash)[:4]
s2c_iv_prefix  = SHA-256("evilquest-game-v2:iv:server-to-client" ‖ transcript_hash)[:4]
```

#### 2.2d AES-256-GCM v2 frame format

```
[0xFE][0x02][counter uint64 BE 8 bytes][ciphertext + 16-byte GCM tag]
```

IV = `iv_prefix[4] ‖ counter[uint64 BE 8]` (12 bytes total).

AAD = canonical JSON (keys sorted alphabetically) of:
```json
{"accountId": N, "connectionId": "...", "counter": N, "direction": "c2s"|"s2c", "frame": "evilquest-game-v2", "version": 2}
```

v1 used no AAD and a uint32 counter; v2 uses a uint64 counter with strict anti-replay checks.

#### 2.2e Per-session opcode remapping

After the crypto handshake the server sends an `OPCODE_MAPPING` frame containing a random shuffle of all opcodes:

```json
{"version": 1, "client": {"10": 179, "20": 232, ...}, "server": {"1": 84, "10": 31, ...}}
```

All game frames use the shuffled *wire* opcodes.  
The transport layer translates transparently — the rest of the bot always works with the stable *logical* opcodes from `protocol.py`.

#### 2.2f Canonical JSON (`canonical_json()`)

A deterministic JSON serialiser that sorts object keys alphabetically at every nesting level, matching the JS `D()` function used server-side.  
Used for HKDF info strings, transcript hashing, and AAD construction.

---

#### 2.3 Protocol definitions rewrite (`protocol.py`)

All opcodes updated to match the v2 JS enum constants (`q.*` / `$.*`).

**Renamed opcodes:**

| Old name | New name |
|---|---|
| `OP_OWN_STATE` | `S.PLAYER_SELF_SYNC = 122` |
| `OP_OBJECT_SYNC` | `S.WORLD_OBJECT_SYNC = 55` |
| `OP_GROUND_ITEM` | `S.GROUND_ITEM_SYNC = 12` |
| `OP_NPC_NAME` | `S.NPC_NAME = 84` |
| `PLAYER_PICKUP` | `C.PLAYER_PICKUP_ITEM = 30` |
| `PLAYER_EQUIP` | `C.PLAYER_EQUIP_ITEM = 32` |
| `PLAYER_DROP` | `C.PLAYER_DROP_ITEM = 31` |
| `PLAYER_EAT` | `C.PLAYER_EAT_ITEM = 34` |

**New server opcodes added:** `CRYPTO_CHALLENGE (2)`, `OPCODE_MAPPING (3)`, `WORLD_OBJECT_DEPLETED (56)`, `SKILLING_START (57)`, `SKILLING_STOP (58)`, `SMITHING_OPEN (59)`, `FLOOR_CHANGE (61)`, `SHOW_CHARACTER_CREATOR (70)`, `PLAYER_TELEPORT (71)`, `PLAYER_REMOTE_EQUIPMENT (72)`, `NPC_APPEARANCE (73)`, `NPC_EQUIPMENT (74)`, `PLAYER_REMOTE_STANCE (75)`, `DIALOGUE_OPEN (76)`, `DIALOGUE_CLOSE (77)`, `NPC_INTERACTIONS (78)`, `PLAYER_ANIMATION (79)`, `BANK_OPEN/UPDATE_SLOT/CLOSE (80-82)`, `NPC_FACING (85)`, `NPC_CUSTOM_COLORS (86)`, `NPC_ATTACK_ANIM (87)`, `RENOWN_SYNC (88)`, trade/duel opcodes, quest opcodes.

**New client opcodes added:** `CRYPTO_RESPONSE (2)`, `CLIENT_ACTIVITY (121)`.

---

#### 2.4 Bot logic fixes (`bot.py`)

#### 2.4a Movement: client-side position prediction

**Problem:** `_move()` was polling `state.x / state.y` and waiting for them to change.  
The server **never sends position updates during normal walking** — just like the real JS client, position is tracked client-side.

**Fix:** After sending `PLAYER_MOVE`, sleep for `n_waypoints / 1.67` seconds (walk speed from `GameManager.js`: `moveSpeed = 1.67` tiles/sec), then optimistically update `state.x, state.y` to the destination.  
`PATH_TRUNCATED` still wakes the loop early and provides the server-confirmed position for re-pathing.

#### 2.4b `PLAYER_INTERACT_OBJECT` missing action index

**Problem:** The bot sent `pack(C.PLAYER_INTERACT_OBJECT, entity_id)` — one value.  
The JS client sends `(entity_id, action_index)` — two values.  
The server silently ignored single-argument interact packets.

**Fix:** `pack(C.PLAYER_INTERACT_OBJECT, eid, 0)` — action index 0 is the primary interaction (e.g. "Chop" for trees).

#### 2.4c Log inventory tracking

**Problem:** Logs go directly to the player's inventory in EvilQuest (no ground drop).  
The bot was looking for `GROUND_ITEM_SYNC` log entries that never appear, so `logs_in_inventory` stayed at 0 and selling never triggered.

**Fix:** Increment `logs_in_inventory += 1` in the `SKILLING_STOP` handler.  
The ground-pickup loop in `_chop_tree()` was removed.

#### 2.4d Tree re-scan after movement

`_chop_tree()` now re-calls `state.nearby_trees()` *after* arriving at the tree area, so it uses a live entity ID from `WORLD_OBJECT_SYNC` packets received during the walk rather than the hardcoded fallback.

#### 2.4e `WORLD_OBJECT_DEPLETED` handler

When a tree is fully chopped the server sends opcode 56.  
The dispatcher now removes the entity from `state.objects` so the next `nearby_trees()` call skips it and picks a freshly synced tree.

#### 2.4f Heartbeat and activity signals

- Heartbeat interval changed from fixed 5.0 s to jittered **5.0–6.2 s**, matching `_a=5000, Ra=1200` in `GameManager.js`
- `CLIENT_ACTIVITY` (opcode 121) sent alongside each ping to signal keyboard activity

#### 2.4g Minor fixes

- `S.PLAYER_EQUIP` → `S.PLAYER_EQUIPMENT` (broken reference to renamed opcode)
- Bot fields `_device_id` and `_device_cookie` added for v2 login flow
- `_http_login_sync()` now calls `ws_transport.http_login()` which handles the full device + signing-key flow

---

## File structure

```
bot.py              — main bot: game state, dispatch, woodcutting/combat loops
ws_transport.py     — WebSocket transport: HTTP login, ECDH handshake, encryption
protocol.py         — opcode enums (C.* / S.*) and packet pack/unpack helpers
pathfinder.py       — A* pathfinder using local map wall + tile data
gameassets/
  maps/kcmap/
    walls.json      — wall bitmask data (N/E/S/W per tile)
    tiles/          — chunk_CX_CZ.json files (water tile blocking)
    heights/        — chunk_CX_CZ.json files (terrain height per tile; cliff detection)
~/.evilquest/
  device.json           — cached server device ID + eq_device_id cookie
  signing_key.json      — persistent ECDSA P-256 private key (JWK)
  dynamic_blocks.json   — tile coords learned as impassable via PATH_TRUNCATED (survives restarts)
```

---

## Protocol version reference

| Field | Value |
|---|---|
| WebSocket subprotocol | `evilquest-game-v2` |
| Protocol version (`protocolVersion` in transcript) | `11` |
| Crypto version (`version` in CRYPTO_CHALLENGE) | `2` |
| Opcode mapping version | `1` |
| Encrypted frame marker | `0xFE 0x02` |
| Counter width | `uint64 BE` (8 bytes) |
| AES key size | 256-bit |
| HKDF hash | SHA-256 |
| EC curve | P-256 (secp256r1) |
| Signature format | P1363 (r ‖ s, 64 bytes) |
| Walk speed | 1.67 tiles/sec |
