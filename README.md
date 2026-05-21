# EvilQuest Bot

Automation bot for [EvilQuest](https://evilquest.net) supporting woodcutting and combat modes.  
Fully implements the **evilquest-game-v2** WebSocket protocol including ECDH key exchange, per-session opcode remapping, and AES-256-GCM encrypted frames.

---

## Features

- **Woodcutting mode** — chops trees near the default area, auto-sells logs to Robert when inventory is full (28 logs)
- **Combat mode** — finds and attacks cows, walks back to the combat area on death
- **Sniff mode** — passive packet logger; play the game manually while the bot prints every decoded message (useful for reverse engineering)
- Automatic reconnect-safe login: fetches a server-issued device ID, registers a persistent ECDSA signing key, and negotiates a fresh session on every run
- A\* pathfinder with wall and water-tile blocking; dynamic tile blocking on repeated `PATH_TRUNCATED` signals
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

Map assets (walls, tile chunks) must be present under `gameassets/maps/kcmap/`.  
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

## Session changelog — May 2026

### Background

EvilQuest's anti-cheat was upgraded to the **evilquest-game-v2** subprotocol.  
The original bot was failing with `403 Client Error: Forbidden for url: https://evilquest.net/api/login`.  
Every layer of the connection — HTTP login, WebSocket upgrade, encryption, opcode layout, and game logic — had changed.  
This session reverse-engineered the new protocol from the minified JS bundle and rewrote the transport, protocol definitions, and game logic to match.

---

### 1. HTTP login hardening (`ws_transport.py`)

| What changed | Why |
|---|---|
| Added Chrome-like browser headers (`User-Agent`, `Sec-Fetch-*`, `Origin`, `Referer`, …) to every API call | Server fingerprints headers and returns 403 to non-browser clients |
| `GET /api/device-id` before login | Server requires a server-issued UUID; self-generated UUIDs return 400 "Missing or invalid device identifier" |
| Store/restore `eq_device_id` cookie across runs (`~/.evilquest/device.json`) | Server ties the device ID to a cookie; sending a mismatched pair fails |
| Collect *all* session cookies after login (`eq_device_id` + `eq_ws_session`) and forward them verbatim in the WebSocket `Cookie:` header | `eq_ws_session` is set during login and checked during WS upgrade; omitting it gives 401 |

---

### 2. Full protocol v2 rewrite (`ws_transport.py`)

The v1 protocol used a static SHA-256 key derived from the auth token + a server nonce, a uint32 counter, no AAD, and fixed opcodes.  
v2 replaces all of this.

#### 2a. ECDH P-256 key exchange

Every session generates a fresh ephemeral P-256 keypair.  
The server sends its ephemeral public key in the `CRYPTO_CHALLENGE` frame.  
An ECDH shared secret is computed and fed into HKDF to produce the session keys.

#### 2b. Persistent device signing key (ECDSA P-256)

A persistent P-256 signing key is stored in `~/.evilquest/signing_key.json`.  
On every login the public key is registered with `POST /api/device-key` (JWK format, `key_ops: ["verify"]`).  
During the handshake the bot signs the session transcript with this key.  
Signatures are in **P1363 format** (raw r ‖ s, 64 bytes) — not DER, which is what Python's `cryptography` library produces by default.

#### 2c. HKDF-SHA-256 session key derivation

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

#### 2d. AES-256-GCM v2 frame format

```
[0xFE][0x02][counter uint64 BE 8 bytes][ciphertext + 16-byte GCM tag]
```

IV = `iv_prefix[4] ‖ counter[uint64 BE 8]` (12 bytes total).

AAD = canonical JSON (keys sorted alphabetically) of:
```json
{"accountId": N, "connectionId": "...", "counter": N, "direction": "c2s"|"s2c", "frame": "evilquest-game-v2", "version": 2}
```

v1 used no AAD and a uint32 counter; v2 uses a uint64 counter with strict anti-replay checks.

#### 2e. Per-session opcode remapping

After the crypto handshake the server sends an `OPCODE_MAPPING` frame containing a random shuffle of all opcodes:

```json
{"version": 1, "client": {"10": 179, "20": 232, ...}, "server": {"1": 84, "10": 31, ...}}
```

All game frames use the shuffled *wire* opcodes.  
The transport layer translates transparently — the rest of the bot always works with the stable *logical* opcodes from `protocol.py`.

#### 2f. Canonical JSON (`canonical_json()`)

A deterministic JSON serialiser that sorts object keys alphabetically at every nesting level, matching the JS `D()` function used server-side.  
Used for HKDF info strings, transcript hashing, and AAD construction.

---

### 3. Protocol definitions rewrite (`protocol.py`)

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

### 4. Bot logic fixes (`bot.py`)

#### 4a. Movement: client-side position prediction

**Problem:** `_move()` was polling `state.x / state.y` and waiting for them to change.  
The server **never sends position updates during normal walking** — just like the real JS client, position is tracked client-side.

**Fix:** After sending `PLAYER_MOVE`, sleep for `n_waypoints / 1.67` seconds (walk speed from `GameManager.js`: `moveSpeed = 1.67` tiles/sec), then optimistically update `state.x, state.y` to the destination.  
`PATH_TRUNCATED` still wakes the loop early and provides the server-confirmed position for re-pathing.

#### 4b. `PLAYER_INTERACT_OBJECT` missing action index

**Problem:** The bot sent `pack(C.PLAYER_INTERACT_OBJECT, entity_id)` — one value.  
The JS client sends `(entity_id, action_index)` — two values.  
The server silently ignored single-argument interact packets.

**Fix:** `pack(C.PLAYER_INTERACT_OBJECT, eid, 0)` — action index 0 is the primary interaction (e.g. "Chop" for trees).

#### 4c. Log inventory tracking

**Problem:** Logs go directly to the player's inventory in EvilQuest (no ground drop).  
The bot was looking for `GROUND_ITEM_SYNC` log entries that never appear, so `logs_in_inventory` stayed at 0 and selling never triggered.

**Fix:** Increment `logs_in_inventory += 1` in the `SKILLING_STOP` handler.  
The ground-pickup loop in `_chop_tree()` was removed.

#### 4d. Tree re-scan after movement

`_chop_tree()` now re-calls `state.nearby_trees()` *after* arriving at the tree area, so it uses a live entity ID from `WORLD_OBJECT_SYNC` packets received during the walk rather than the hardcoded fallback.

#### 4e. `WORLD_OBJECT_DEPLETED` handler

When a tree is fully chopped the server sends opcode 56.  
The dispatcher now removes the entity from `state.objects` so the next `nearby_trees()` call skips it and picks a freshly synced tree.

#### 4f. Heartbeat and activity signals

- Heartbeat interval changed from fixed 5.0 s to jittered **5.0–6.2 s**, matching `_a=5000, Ra=1200` in `GameManager.js`
- `CLIENT_ACTIVITY` (opcode 121) sent alongside each ping to signal keyboard activity

#### 4g. Minor fixes

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
~/.evilquest/
  device.json       — cached server device ID + eq_device_id cookie
  signing_key.json  — persistent ECDSA P-256 private key (JWK)
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
