# EvilQuest Bot · v6.0

Automation bot for [EvilQuest](https://evilquest.net) supporting woodcutting and combat modes.  
Fully implements the **evilquest-game-v2** WebSocket protocol including ECDH key exchange, per-session opcode remapping, and AES-256-GCM encrypted frames.

---

## Features

- **Woodcutting mode** — chops trees near the default area, auto-sells logs to Robert when inventory is full (28 logs); walks to the tile *beside* each tree for guaranteed adjacency before every chop
- **Combat mode** — finds and attacks cows, walks back to the combat area on death; first kill confirmed in **53 s** from spawn; multi-cow targeting via `find_nearby_cows()`
- **Sniff mode** — passive packet logger; play the game manually while the bot prints every decoded message (useful for reverse engineering)
- **reCAPTCHA v3 bypass** — launches a visible Chrome window via pydoll CDP automation; the page's own JS handles reCAPTCHA scoring transparently; auth token cached for 23 h so Chrome only opens once per day
- **Cached-auth reconnect** — if Chrome is not running, the bot uses cached cookies + a Python-signed ECDSA key registered via HTTP; WS session connects and signs the crypto handshake without opening a browser
- **Zero key-registration race** — IDB injection pre-seeds the signing key before the game page loads; browser-fetch registration fires only after `window.gm.network.deviceSigningKeyPair` is confirmed ready (game's `Aa()` complete)
- **Human-like timing** — lognormal-jittered delays (`_jitter`, `_human_reaction`, `_tick_slip`) applied to moves, interactions, and every packet send; defeats statistical timing analysis
- **Anti-cheat handlers** — `ADMIN_FLAGS` detector logs server-signalled suspicious behaviours; path-suboptimality injection (~7 % of multi-waypoint moves add a single off-axis detour); trade-request auto-decline
- Automatic reconnect-safe login: fetches a server-issued device ID, registers a persistent ECDSA signing key, and negotiates a fresh session on every run
- A\* pathfinder with wall, water-tile, and **height-based cliff blocking** (pre-computed from terrain height chunks); dynamic tile learning via `PATH_TRUNCATED` catches any missed edges
- Jittered heartbeat (5.0–6.2 s) with `CLIENT_PING`; `CLIENT_POSITION_Y` loop reports ground Y-height every 0.5 s (mirrors `reportYToServer()` in `GameManager.js`)

---

## Requirements

```
Python 3.11+
cryptography
requests
pydoll-python>=2.0
```

Install dependencies:

```bash
pip install cryptography requests pydoll-python
```

Google Chrome must be installed at the default path (`C:\Program Files\Google\Chrome\Application\chrome.exe` on Windows).  
Chrome is only launched on the first run of each day; subsequent runs within 23 h use the cached auth token and skip the browser entirely.

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

Credentials can also be provided via `.env` (same directory as `bot.py`):

```
EVILQUEST_USER=yourname
EVILQUEST_PASSWORD=yourpass
```

Persistent state is stored in `~/.evilquest/` (device ID, ECDSA signing key, auth token cache).

---

## Version history

| Version | Date | Summary |
|---|---|---|
| **6.1** | May 2026 | `_uptime_loop()` — total runtime logged every 60 s (`UPTIME Xh YYm ZZs`); survives reconnects |
| **6.0** | May 2026 | `PROTOCOL_VERSION` 12→13 fix (second asset build May 2026); cached-auth 401 detection + auto-clear; `CURSOR_POSITION` opcode 122 + `_cursor_loop()` / `_click_cursor()` (anti-cheat cursor events); `_tick_slip()` P50 raised 25ms→120ms (reaction time floor); version banner; `fetch_latest_js.py` utility — **all known ADMIN_FLAGS addressed** |
| **5.0** | May 2026 | `PROTOCOL_VERSION` 11→12 fix (server asset update); zero key-registration race (IDB injection + browser-fetch after `Aa()`); cached-auth Python signing for reconnect without Chrome; human-like timing (`_jitter` / `_human_reaction` / `_tick_slip`); ADMIN_FLAGS handler; path suboptimality injection; trade auto-decline; `find_nearby_cows()` — **bot confirmed working end-to-end after server update** |
| **4.0** | May 2026 | reCAPTCHA v3 bypass via pydoll Chrome CDP; 23 h auth token cache; protocol v3.2 (DUEL removed, CLIENT_POSITION_Y added); Chrome startup reliability fix; woodcutting stand-beside adjacency — **PATH_TRUNCATED eliminated, 2× log rate** |
| **3.1** | May 2026 | Height-based cliff pre-computation (≥78 % of cliff tiles blocked at startup); on-path immediate blocking; Euclidean wait-time; `.env` credential loading — **first kill in 53 s, zero PATH_TRUNCATED events** |
| **3.0** | May 2026 | Dynamic obstacle persistence; robust `_move()` position tracking; on-path/off-path PATH_TRUNCATED detection; A* tuning |
| **2.0** | May 2026 | Full evilquest-game-v2 protocol rewrite (ECDH, AES-256-GCM, opcode remapping, signing key) |
| **1.0** | — | Initial release (v1 protocol, static key, basic woodcutting) |

---

## Changelog

---

### v6.1 — Uptime timer (May 2026)

#### 6.1.1 `_uptime_loop()` — total runtime logged every 60 s (`bot.py`)

Adds a background task that logs total bot runtime to the console once per minute:

```
10:01:00  INFO      UPTIME   1m 00s
10:02:00  INFO      UPTIME   2m 00s
11:05:00  INFO      UPTIME   1h 05m 00s
```

**Format:** `Xm YYs` under one hour; `Xh YYm ZZs` once past an hour.

**Implementation notes:**

- Sleeps exactly 60 s per tick (no jitter — it is a clock, not a game action)
- Uses `_session_start` (set once at first login, never reset on reconnect) so the timer continues uninterrupted across reconnect cycles
- Separate from the jittered `STATUS` line; `UPTIME` is a clean standalone line without HP/XP/kill stats
- Task started alongside `_status_loop()`, cancelled in the connection `finally` block

---

### v6.0 — Protocol version 13 + cursor anti-cheat + timing hardening (May 2026)

#### Summary

A second server-side JS asset push in May 2026 bumped `PROTOCOL_VERSION` from 12 → 13 (`bi` constant in `GameManager-_UxitI8j.js`).  
The session also addressed the two highest-signal ADMIN_FLAGS metrics remaining after v5.0: `sessionCursorEvents = 0` (bot never sent a cursor-position packet) and `sessionInputlessCommands ≈ 100 %` (every game action fired without any preceding cursor movement).  
Additionally, `_tick_slip()` P50 was too low — the server's `reactionMedianMs` was landing at ~25 ms vs the human floor of ~150 ms.

All four issues are fixed in v6.0.

#### Verified results (combat mode)

```
EvilBot V6     by Blackberry
[login] cached auth loaded — skipping browser
[ws] WebSocket connected + crypto handshake complete
[game] LOGIN_OK entity_id=105 pos=(1115,1825)
[bot] cursor loop started
[bot] Walking to cow area
[bot] Attacking cow entity=7 at (1205,1695)
[bot] XP_GAIN skill=0 xp=1
[bot] Cow 7 defeated
[bot] Attacking cow entity=9 at (1205,1675)
```

---

#### 6.1 PROTOCOL_VERSION 12 → 13 (`ws_transport.py`)

**Root cause:** The game server pushed new JS assets (second push, May 2026):

| Old file | New file |
|---|---|
| `index-CJfY6JbI.js` | `index-DSIgc8je.js` |
| `GameManager-DCJfmSEz.js` | `GameManager-_UxitI8j.js` |
| `babylon-core-CFbJrqqe.js` | `babylon-core-BshMRevz.js` |

The new `GameManager-_UxitI8j.js` contains `bi=13` (was `12`).  
This constant appears as `protocolVersion` in the canonical JSON transcript; a mismatch causes the server to close the WS with code **1008 "bad encrypted packet"**.

**Fix:**

```python
PROTOCOL_VERSION = 13  # bi = 13 in GameManager-_UxitI8j.js (updated May 2026)
```

**How to detect future bumps:** Run `python fetch_latest_js.py` — it downloads new assets and prints any changed constants.  
The variable name changes with every build; look for the integer constant immediately before `po="/ws/game"` in the constant block.

---

#### 6.2 Cached-auth 401 detection (`ws_transport.py`)

**Problem:** When the server expired a cached auth token between runs, the device-key `POST /api/device-key` returned HTTP 401.  
The `except` block was calling `return cached` regardless of the error type — the stale token was passed to the WS upgrade, which also failed with 401.

**Fix:** In the cached-auth fast path, detect a 401 response from the device-key POST:

```python
_is_401 = (
    hasattr(_qe, "response")
    and _qe.response is not None
    and getattr(_qe.response, "status_code", 0) == 401
)
if _is_401:
    _log.info("cached-auth: token rejected (401) — discarding cache, triggering browser login")
    _state_path("auth.json").unlink(missing_ok=True)
    # Fall through to browser login
else:
    _log.warning("cached-auth: device-key registration failed: %s", _qe)
    return cached
```

After deleting `auth.json`, the code falls through to the pydoll browser-login path and obtains a fresh token.

---

#### 6.3 `CURSOR_POSITION` opcode + cursor simulation (`protocol.py`, `ws_transport.py`, `bot.py`)

**Problem:** ADMIN_FLAGS metrics `sessionCursorEvents = 0` and `sessionInputlessCommands ≈ 100 %` were flagging the bot.  
Human players continuously move the mouse; every action is preceded by cursor movement.  
The bot never sent opcode 122 (`CURSOR_POSITION`), and the server was receiving attack/interact packets with zero associated cursor activity.

**Fix — three-part change:**

**`protocol.py`:**
```python
CURSOR_POSITION = 122   # mouse cursor x,y scaled to [0,1000]
```

**`ws_transport.py`** — added `122` to `_CLIENT_LOGICAL`:
```python
_CLIENT_LOGICAL = sorted({
    ..., 120, 122,
    # 122 = CURSOR_POSITION (mouse x/y scaled to [0,1000]); added May 2026
})
```

**`bot.py`** — two new methods:

`_cursor_loop()` — background task that sends idle cursor drift every 1–8 s (lognormal median 3 s), random-walking within the [120, 880] viewport box:

```python
async def _cursor_loop(self):
    cx, cy = 480, 510
    _ok = True
    while _ok:
        wait = math.exp(random.gauss(math.log(3.0), 0.60))
        await asyncio.sleep(max(1.0, min(8.0, wait)))
        if not self.ws or self._ws_closed.is_set():
            continue
        cx = max(120, min(880, cx + random.randint(-70, 70)))
        cy = max(120, min(880, cy + random.randint(-55, 55)))
        try:
            await self.ws.send(pack(C.CURSOR_POSITION, cx, cy))
        except ValueError:
            log.debug("CURSOR_POSITION not in opcode map — cursor loop stopped")
            _ok = False
        except Exception:
            break
```

`_click_cursor()` — sends a cursor position immediately before any game action (1–16 ms gap):

```python
async def _click_cursor(self, hint_x=None, hint_y=None):
    x = hint_x if hint_x is not None else random.randint(320, 680)
    y = hint_y if hint_y is not None else random.randint(280, 620)
    x = max(50, min(950, x + random.randint(-25, 25)))
    y = max(50, min(950, y + random.randint(-20, 20)))
    try:
        await self.ws.send(pack(C.CURSOR_POSITION, x, y))
        await asyncio.sleep(random.uniform(0.001, 0.016))
    except (ValueError, Exception):
        pass
```

`_click_cursor()` is called immediately before every `PLAYER_ATTACK_NPC` and `PLAYER_INTERACT_OBJECT` packet.  
`_cursor_loop()` is started as a background task alongside `_status_loop()` and cancelled in the `finally` block.

---

#### 6.4 `_tick_slip()` P50 raise — reaction time floor (`bot.py`)

**Problem:** ADMIN_FLAGS metric `reactionMedianMs` was reporting ~25 ms.  
Human reaction times are never below ~150 ms; the server uses this as a bot signal.  
The old distribution had P50 at ~25 ms (uniform [10, 120] ms).

**Fix:** Rewritten as a three-tier lognormal distribution with P50 ≈ 120 ms:

```python
def _tick_slip() -> float:
    r = random.random()
    if r < 0.55:                          # 55 % — lognormal, median ~120 ms
        v = math.exp(random.gauss(math.log(0.120), 0.80))
        return max(0.025, min(v, 0.600))
    elif r < 0.88:                        # 33 % — uniform 60–700 ms
        return random.uniform(0.060, 0.700)
    else:                                 # 12 % — long tail 700 ms–2 s
        return random.uniform(0.700, 2.000)
```

| Percentile | Old | New |
|---|---|---|
| P10 | ~10 ms | ~35 ms |
| P50 | ~25 ms | ~120 ms |
| P90 | ~110 ms | ~600 ms |
| P99 | ~120 ms | ~1800 ms |

---

#### 6.5 Version banner (`bot.py`)

Startup banner printed before the argparse/login step:

```
╔══════════════════════════════════════╗
║  EvilBot V6      by Blackberry       ║
╚══════════════════════════════════════╝
```

Implemented as a module-level `BANNER` f-string using `BOT_VERSION` and `BOT_AUTHOR` constants; `main()` prints it before any other output.

---

#### 6.6 `fetch_latest_js.py` utility (new file)

New utility script that automates detection of future protocol version bumps:

1. Fetches `/play` and finds all `<script src="/assets/*.js">` tags + module preloads
2. Downloads any files not already present in `gameassets/assets/`
3. Searches each bundle for protocol constants:
   - `PROTOCOL_VERSION`: integer immediately before `"/ws/game"` in the constant block
   - `CRYPTO_VERSION`: `Qe=\d+` pattern
   - HKDF strings (`evilquest-game-v2:...`)
   - Frame header bytes (`0xFE`, `0x02`)
4. Compares found values against current `ws_transport.py` constants
5. Prints a diff of anything that changed

Run after any 1008 error to identify changed constants without manual JS inspection.

---

### v5.0 — Protocol version 12 + key-registration race fix + anti-detection (May 2026)

#### Summary

A server-side JS asset push (May 2026) bumped `PROTOCOL_VERSION` from 11 → 12 (`ms` constant in `GameManager-DDbuhVzL.js`).  
Because `protocolVersion` is part of the ECDSA-signed CRYPTO_CHALLENGE transcript, the server recomputed a different canonical JSON than the bot signed → every WS handshake closed with code **1008 "bad encrypted packet"** regardless of authentication status.

This version fixes the version bump, eliminates the key-registration race introduced in v4.0, adds a full cached-auth reconnect path (no Chrome required), and hardens the bot against statistical timing analysis and server-side anti-cheat flags.

#### Verified results (combat mode)

```
18:12:04  WebSocket connected + crypto handshake complete
18:12:04  LOGIN_OK entity_id=105 pos=(1115,1825)
18:12:06  Walking to cow area (1211,1664)
18:12:28  Arrived at (1215,1665) (server confirmed)
18:12:29  Attacking cow entity=7 at (1205,1695)
18:12:34  XP_GAIN skill=0 xp=1 …
18:12:48  Cow 7 defeated
18:12:48  Attacking cow entity=9 at (1205,1675)
```

---

#### 5.1 PROTOCOL_VERSION 11 → 12 (`ws_transport.py`)

**Root cause:** The game server pushed new JS assets:

| Old file | New file |
|---|---|
| `index-DGTyz-tl.js` | `index-DTlu9WCm.js` |
| `GameManager-B7gNzArI.js` | `GameManager-DDbuhVzL.js` |

The new `GameManager-DDbuhVzL.js` changed `hs = 11` → `ms = 12`.  
This constant is included as `protocolVersion` in the canonical JSON transcript that both sides sign/verify.

**Fix:**

```python
PROTOCOL_VERSION = 12  # ms = 12 in GameManager-DDbuhVzL.js (updated May 2026)
```

**How to detect future version bumps:** Scrape `/play` → find the `GameManager-*.js` href → `grep ms=\d+`.  
When persistent 1008 errors appear despite a passing HTTP 200 on device-key registration, this is the first thing to check.

**What did NOT change in the new assets:** AES-256-GCM encryption, ECDSA P-256 signing, HKDF-SHA-256 key derivation, encrypted frame format (`0xFE 0x02`), opcode remapping protocol, and canonical JSON algorithm — all identical.

---

#### 5.2 Zero key-registration race (`ws_transport.py`)

**Problem (v4.0):** The bot registered its own public key via HTTP before navigating to `/play`.  
The game page's own async `Aa(token)` function then registered a *new* key (the game-generated one) — overwriting our registration.  
The bot's signing key was therefore unknown to the server when the CRYPTO_CHALLENGE arrived.

**Fix — two-stage IDB injection + browser-fetch registration:**

**Stage 1 — IDB pre-seed (before page load):**  
The bot navigates to a neutral same-origin page (`evilquest.net/`), opens IndexedDB `evilquest_device_crypto_v1 / keys / ecdsa-p256`, and writes our Python signing key (imported as a `CryptoKey` via `crypto.subtle.importKey`).  
When the game page loads at `/play`, `Ia()` reads *our* key from IDB — the game never generates its own.

**Stage 2 — browser-fetch registration (after `Aa()` completes):**  
The bot polls `window.gm?.network?.deviceSigningKeyPair?.privateKey` (up to 15 s / 150 polls × 100 ms).  
Once the game confirms its `Aa()` function has completed and set `deviceSigningKeyPair`, the bot fires a `fetch('/api/device-key', …)` from inside the browser tab using the game's own auth token and `credentials:'same-origin'` cookies.  
This registration is guaranteed to be *last* — the server now holds our Python public key.

**Result:** Signing with our Python private key produces a signature the server can verify with the registered public key.  Previously this race caused all CRYPTO_RESPONSE frames to be rejected.

---

#### 5.3 `_browser_sign()` game-tab targeting (`ws_transport.py`)

When Chrome is running, `_browser_sign()` signs the WS transcript by executing `crypto.subtle.sign()` inside the game tab (using the game's own `deviceSigningKeyPair.privateKey` held in JS memory).

**Previously:** `browser.connect(browser_ws)` always returned `tabs[0]`, which could be a background tab (e.g. a new-tab page) if the user had multiple tabs open.

**Fix:** After connecting, enumerate `browser.get_opened_tabs()`, check `current_url` for `"evilquest.net"`, and use that tab.  Falls back to `tabs[0]` if URL inspection fails.

---

#### 5.4 Cached-auth Python signing path (`ws_transport.py`)

When Chrome is not running (e.g. reconnect after a crash, or a second bot instance), the browser-based signing path is unavailable.

**Fix:** `async_http_login()` detects that Chrome is unreachable and falls back to:

1. Load cached `~/.evilquest/auth.json` (token, device ID, cookies).
2. Load `~/.evilquest/signing_key.json` (our persistent ECDSA private key).
3. Register the public key via direct HTTP POST to `/api/device-key` using the cached cookies and auth token.
4. Return the cached credentials — WS connect proceeds normally.

During `CRYPTO_CHALLENGE`, the transport signs with the Python key (`_signing_key`) instead of delegating to `_browser_sign()`.  
With PROTOCOL_VERSION=12 correct, the server accepts this signature.

---

#### 5.5 Human-like timing system (`bot.py`)

Three timing helpers replace all fixed `asyncio.sleep()` calls in game-action paths:

| Helper | Distribution | Purpose |
|---|---|---|
| `_jitter(base, scale=0.20)` | Lognormal, σ=0.20, clamped [0.35×, 3.0×] | General-purpose delay with proportional variance |
| `_human_reaction(floor=0.15)` | Lognormal median ≈ 280 ms, clamped [0.15, 2.5] | Post-event reaction time before responding to a server message |
| `_tick_slip()` | Uniform [10, 120] ms | Per-packet micro-jitter applied in `_send()` before every outgoing frame |

**`_send()` integration:** Every packet send now calls `await asyncio.sleep(_tick_slip())` before writing to the WebSocket unless `apply_tick_slip=False` is passed explicitly.  This desynchronises packet timing from the Python event loop's natural tick alignment, which is a known statistical fingerprint of bots.

---

#### 5.6 ADMIN_FLAGS anti-cheat handler (`bot.py`)

The server added a new server opcode `ADMIN_FLAGS` that signals which bot-like behaviour patterns have been detected for the current session.

**Handler:**

```python
elif op == S.ADMIN_FLAGS:
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
```

Receiving `ADMIN_FLAGS` does not immediately disconnect the session, but the active flags inform which timing/behaviour adjustments are most urgent.

---

#### 5.7 Path suboptimality injection (`bot.py`)

The server's `pathOptimality` flag (ADMIN_FLAGS bit 3) detects bots that always take mathematically shortest A\* paths.  Human players routinely take slightly suboptimal routes.

**Fix:** In `_send_path_from()`, when a path has ≥ 5 waypoints, inject a single off-axis detour waypoint with 7 % probability.  The detour is one tile perpendicular to the dominant movement direction, inserted at a random position in the middle third of the path.  This shifts the path length by exactly 2 extra tiles — undetectable as intentional by statistical tests tuned for constant-optimal routing.

---

#### 5.8 Trade request auto-decline (`bot.py`)

Other players can send trade requests to the bot's character.  Leaving them unanswered is a mild anti-cheat signal (flag 4: `zeroCancellations`); accepting them would interrupt combat or skilling loops.

**Handler:**

```python
elif op == S.TRADE_REQUEST_RECEIVED:
    if vals:
        requester_eid = vals[0]
        async def _decline_trade(req_eid: int) -> None:
            await asyncio.sleep(_human_reaction())   # 150–500 ms "thinking" delay
            await self._send(pack(C.TRADE_DECLINE, req_eid))
        asyncio.create_task(_decline_trade(requester_eid))
```

The `_human_reaction()` delay before declining mimics a player noticing and dismissing the dialog.

---

#### 5.9 `find_nearby_cows()` — multi-target combat (`bot.py`)

Replaced the single-target `find_nearest_cow()` lookup with `State.find_nearby_cows(cow_type, max_dist)`:

- Returns **all** living cows of the given type within `max_dist` (Manhattan distance, default 10 000 x10 units), sorted nearest-first.
- Filters `dead_npcs` so a just-killed entity is never re-targeted.
- The combat loop calls `find_nearby_cows()` after each kill and picks the first result — instant retarget without waiting for the next `NPC_SYNC` cycle.

---

#### 5.10 Game asset update

| Asset | Old | New | Size |
|---|---|---|---|
| Index JS | `index-DGTyz-tl.js` | `index-DTlu9WCm.js` | 45 244 B |
| GameManager JS | `GameManager-B7gNzArI.js` | `GameManager-DDbuhVzL.js` | 519 801 B |

New assets downloaded to `gameassets/assets/` and verified: all crypto primitives unchanged, only `protocolVersion` (`ms`) bumped 11 → 12.

---

### v4.0 — reCAPTCHA bypass + protocol v3.2 + woodcutting reliability (May 2026)

#### Summary

EvilQuest added reCAPTCHA v3 to `/api/login`, breaking the direct HTTP login flow.  
A game update removed the duel system and `CLIENT_ACTIVITY` opcode, adding `CLIENT_POSITION_Y` in their place.  
Woodcutting was wasting one full `PLAYER_MOVE` → `PATH_TRUNCATED` roundtrip per chop because the bot was targeting the tree's own (impassable) tile.

All three issues are fixed in v4.0.

#### Verified results (woodcutting, 2-minute test)

```
19:10:50  Walking beside tree entity=10358 at (1170,1690) → standing at (1180,1690)
19:10:51  SKILLING_START [10358, 31]
19:10:54  XP_GAIN skill=7 xp=25
...
19:12:40  XP_GAIN skill=7 xp=25   ← 7+ logs chopped (mid-chop at cutoff)
```

- Zero `PATH_TRUNCATED` events during woodcutting (was 1 per chop)
- ~8 logs / 2 min (was 4 before adjacency fix)

---

#### 4.1 reCAPTCHA v3 bypass (`ws_transport.py`)

**Problem:** `/api/login` added reCAPTCHA v3 token validation. The bot's direct `requests` POST returned `400 Captcha score too low`.

**Fix:** `async_http_login()` launches a visible Chrome window via pydoll-python (Chrome DevTools Protocol).  
The page's own JS generates the reCAPTCHA token while the bot fills in credentials with human-like typing and mouse movement — no token extraction or third-party solver needed.

| Step | What happens |
|---|---|
| Navigate `evilquest.net` (root) | Warms up reCAPTCHA session; 4–6 s dwell |
| Navigate `evilquest.net/play` | Login form loads |
| Human-like mouse movement | 5-point cursor path with jitter before touching the form |
| `type_text(humanize=True)` | Randomised inter-keystroke delays |
| "Remember username" checkbox | Ticked if present |
| Wait for `localStorage["projectrs_token"]` | Up to 20 s polling |
| Manual fallback | If automated login scores too low, Chrome stays open 120 s for manual login; token read from `localStorage` once the user logs in |

After a successful login, the auth token, device ID, and session cookies are saved to `~/.evilquest/auth.json` with a 23 h TTL.  Subsequent runs hit the fast path and skip Chrome entirely.

---

#### 4.2 Auth token caching (`ws_transport.py`)

| Function | Purpose |
|---|---|
| `save_auth_state(token, device_id, cookie)` | Writes `~/.evilquest/auth.json` with a `ts` timestamp |
| `load_auth_state()` | Returns cached values if age < 23 h; returns `None` otherwise |

`async_http_login()` checks the cache first and returns immediately if a fresh token is present.  
The 23 h window (vs the server's 24 h token expiry) provides a 1 h safety margin.

---

#### 4.3 Chrome startup reliability (`ws_transport.py`)

Two startup failures were discovered and fixed during development:

**Bug 1 — Partial `--user-data-dir` profile blocked Chrome's CDP port**

The bot was copying `User Data/Local State` + `Default/Network/Cookies` into a temp directory and passing it as `--user-data-dir`.  
Chrome requires a `Default/Preferences` file to initialise the profile; without it, Chrome hangs during startup and never exposes the CDP debugging port (observed: 30 s timeout with no connection).

Fix: removed the profile copy entirely. pydoll creates a clean, isolated temp directory per launch.

**Bug 2 — Unsupported Chrome flags showed warning banners**

`--disable-blink-features=AutomationControlled`, `--disable-infobars`, and `--no-sandbox` all produce a "You are using an unsupported command-line flag" banner in modern Chrome (120+).  
These banners modify the browser's visual state and degrade reCAPTCHA v3 trust scoring.

Fix: all three flags removed. Added `--disable-sync` (prevents Google sign-in prompt on fresh profile) and `--disable-extensions` (faster startup). `start_timeout` raised from 10 s to 30 s.

---

#### 4.4 Protocol v3.2 — duel system removed, `CLIENT_POSITION_Y` added

A game update removed the duel system and `CLIENT_ACTIVITY` opcode from the server's accepted opcode set.

**Opcodes removed from `_CLIENT_LOGICAL`:**

| Opcode | Name |
|---|---|
| 100–105 | `DUEL_REQUEST` / `DUEL_ACCEPT_REQUEST` / `DUEL_DECLINE` / `DUEL_STAKE_ITEM` / `DUEL_REMOVE_STAKE` / `DUEL_ACCEPT` |
| 121 | `CLIENT_ACTIVITY` — entirely removed from game client; sending it raises `ValueError: Missing client opcode mapping for logical 121` |

**Opcodes removed from `_SERVER_LOGICAL`:**

| Opcodes | Names |
|---|---|
| 96–99, 101–103 | All duel server opcodes (`DUEL_REQUEST_RECEIVED`, `DUEL_OPEN`, `DUEL_STAKE_UPDATE`, `DUEL_ACCEPT_STATE`, `DUEL_CLOSE`, `DUEL_START`, `DUEL_FINISH`) |

**New: `CLIENT_POSITION_Y` (opcode 71)**

`_position_y_loop()` in `bot.py` runs every 0.5 s and mirrors `reportYToServer()` / `updateIndoorDetection()` from `GameManager.js`:

- Only sends when `abs(height − lastSentY) ≥ 0.05` world units
- Packet format: `pack(C.CLIENT_POSITION_Y, round(height * 10))`
- Height source: `pathfinder._heights[(tile_x, tile_z)]` (float, world-unit Y)
- Initial height from `LOGIN_OK vals[3] / 10.0`

---

#### 4.5 Woodcutting adjacency — `_stand_beside()` + `arrive_window` (`bot.py`)

**Problem 1 — Interact packets silently ignored (~50 % of attempts)**

`PLAYER_INTERACT_OBJECT` was being sent while the player was up to 2.5 tiles from the tree (`ARRIVE_WINDOW = 25` x10 units).  The server requires the player to be within ~1–2 tiles to accept the interaction.

Fix: added `arrive_window: int = ARRIVE_WINDOW` parameter to `_move()`.  `_chop_tree()` now passes `arrive_window=12` (≈1.2 tiles) for the tree-approach step, guaranteeing adjacency before every interact packet.

**Problem 2 — `PATH_TRUNCATED` roundtrip on every chop**

Trees occupy their own tile.  Sending `PLAYER_MOVE` to the tree's exact coordinates `(tx, ty)` always triggers a `PATH_TRUNCATED` back to the player's current position — a wasted network roundtrip on every single chop.

Fix: `_stand_beside(player_x, player_y, obj_x, obj_y)` computes the four orthogonal neighbours of the tree tile and returns whichever is closest to the player.  `_chop_tree()` walks to this adjacent tile instead of the tree tile itself.

```
Before:  PLAYER_MOVE(1170,1690) → PATH_TRUNCATED(1185,1695) → re-send interact
After:   PLAYER_MOVE(1180,1690) → arrives clean → interact immediately
```

**`_chop_tree()` new flow:**

1. Coarse move to tree area (loose `ARRIVE_WINDOW`)
2. Re-scan `state.objects` for nearest live tree entity
3. Compute `_stand_beside()` neighbour tile
4. Fine move to neighbour tile (`arrive_window=12`)
5. Send `PLAYER_INTERACT_OBJECT(eid, 0)`

---

### v3.1 — Height-based cliff detection + credential management (May 2026)

#### Verified results

Live test, 54-second run from login to first confirmed kill:

```
08:31:52  Pathfinder ready — 2222 walls, 3710 water tiles, 19595 height tiles, 235 dynamic blocks
08:31:54  LOGIN_OK entity_id=170 pos=(1115,1825)
08:31:58  Walking to cow area (1211,1664)
08:32:24  Arrived at (1215,1665) (server confirmed)   ← zero PATH_TRUNCATED events
08:32:25  Attacking cow entity=14 at (1205,1695)
08:32:30  XP_GAIN skill=0 xp=1  …
08:32:45  Cow 14 defeated                             ← first kill at 53 s
08:32:45  Attacking cow entity=15 at (1205,1675)      ← immediate retarget
```

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
fetch_latest_js.py  — utility: check for JS asset updates, extract protocol constants
gameassets/
  assets/
    index-DSIgc8je.js          — current game index bundle (updated May 2026 v2)
    GameManager-_UxitI8j.js    — current GameManager bundle (PROTOCOL_VERSION=13)
    babylon-core-BshMRevz.js   — current Babylon.js core
  maps/kcmap/
    walls.json      — wall bitmask data (N/E/S/W per tile)
    tiles/          — chunk_CX_CZ.json files (water tile blocking)
    heights/        — chunk_CX_CZ.json files (terrain height per tile; cliff detection)
~/.evilquest/
  device.json           — cached server device ID + eq_device_id cookie
  signing_key.json      — persistent ECDSA P-256 private key (JWK)
  dynamic_blocks.json   — tile coords learned as impassable via PATH_TRUNCATED (survives restarts)
  auth.json             — cached auth token + device ID + cookies (23 h TTL; skips Chrome on re-runs)
```

---

## Protocol version reference

| Field | Value |
|---|---|
| WebSocket subprotocol | `evilquest-game-v2` |
| Protocol version (`protocolVersion` in transcript) | `13` (bumped from 12, May 2026 v2) |
| Crypto version (`version` in CRYPTO_CHALLENGE) | `2` |
| Opcode mapping version | `1` |
| Encrypted frame marker | `0xFE 0x02` |
| Counter width | `uint64 BE` (8 bytes) |
| AES key size | 256-bit |
| HKDF hash | SHA-256 |
| EC curve | P-256 (secp256r1) |
| Signature format | P1363 (r ‖ s, 64 bytes) |
| Walk speed | 1.67 tiles/sec |
