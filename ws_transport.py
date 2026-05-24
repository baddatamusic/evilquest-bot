"""
EvilQuest GameWebSocket — v2 transport (evilquest-game-v2 protocol).

Connection flow
───────────────
1.  GET /api/device-id      → server issues device UUID + sets eq_device_id cookie
2.  POST /api/login         → returns auth token (browser-like headers required)
3.  POST /api/device-key    → registers persistent ECDSA-P256 signing key with server
4.  WSS /ws/game [auth.<token>]
      ← CRYPTO_CHALLENGE   (plain string frame, server logical opcode 2)
      → CRYPTO_RESPONSE    (plain string frame, client logical opcode 2)
      ← OPCODE_MAPPING     (first encrypted frame, logical opcode 3)
      ↔  game frames        (encrypted + opcode-remapped)

Frame format (encrypted):
    [0xFE][0x02][counter uint64 BE 8 bytes][AES-256-GCM ciphertext + 16-byte tag]
    AAD = canonical_json({accountId, connectionId, counter, direction, frame, version})
    IV  = ivPrefix[4 bytes] || counter[uint64 BE 8 bytes]  → 12 bytes

Key derivation (RFC 5869 HKDF-SHA-256):
    ecdh_secret   = ECDH(clientEphemeral.private, serverPublic)   [32 bytes]
    auth_hash     = SHA-256(authToken utf-8)
    transcript_hash = SHA-256(transcript)
    hkdf_ikm      = ecdh_secret || auth_hash || transcript_hash
    salt          = SHA-256("evilquest-game-v2:salt" || serverNonce || clientNonce || auth_hash)
    c2s_key       = HKDF(hkdf_ikm, salt, "evilquest-game-v2:client-to-server:<connId>") [32 B]
    s2c_key       = HKDF(hkdf_ikm, salt, "evilquest-game-v2:server-to-client:<connId>") [32 B]
    c2s_iv_prefix = SHA-256("evilquest-game-v2:iv:client-to-server" || transcript_hash)[:4]
    s2c_iv_prefix = SHA-256("evilquest-game-v2:iv:server-to-client" || transcript_hash)[:4]

Persistent state (stored in ~/.evilquest/):
    device.json     — {device_id, eq_device_id cookie value}
    signing_key.json — ECDSA P-256 private key as JWK {kty,crv,x,y,d}
"""

import asyncio
import base64
import hashlib
import http.client
import json
import logging
import math
import os
import random
import secrets
import shutil
import socket
import ssl
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.ec import (
    ECDH, SECP256R1, EllipticCurvePublicNumbers, EllipticCurvePrivateNumbers,
    generate_private_key,
)
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

import requests

# ── Constants ─────────────────────────────────────────────────────────────────

ENC_BYTE_0 = 0xFE   # J = 254  — encrypted frame marker first byte
ENC_BYTE_1 = 0x02   # H = 2    — protocol version byte
PROTOCOL_VERSION = 13            # bi = 13 in GameManager-_UxitI8j.js (updated May 2026)
CRYPTO_VERSION   = 2             # qe = 2
OPCODE_MAPPING_VERSION = 1       # bt = 1

STATE_DIR = Path.home() / ".evilquest"

# CDP port used for browser-side transcript signing.
# Initialised from EQ_CDP_PORT at import time so the bot can use browser
# signing even when running with a cached auth token (no browser login).
# async_http_login() also writes here when it opens its own Chrome session.
_last_cdp_port: int = int(os.environ.get("EQ_CDP_PORT", 0) or 0)

# Client-side logical opcodes that ARE in the opcode mapping
# (all client opcodes except LOGIN=1 and CRYPTO_RESPONSE=2)
#
# Removed in latest game update:
#   100-105  — DUEL_REQUEST / DUEL_ACCEPT_REQUEST / DUEL_DECLINE /
#              DUEL_STAKE_ITEM / DUEL_REMOVE_STAKE / DUEL_ACCEPT  (duel system removed)
#   121      — CLIENT_ACTIVITY  (removed from client enum entirely)
_CLIENT_LOGICAL = sorted({
    10, 20, 21, 22, 23, 30, 31, 32, 33, 34, 35, 36, 37, 38, 40, 41, 42, 43, 44, 45,
    50, 60, 70, 71, 80, 81, 82, 83, 90, 91, 92, 93, 94, 95, 120, 122,
    #                                                               ^^^
    # 122 = CURSOR_POSITION (mouse x/y scaled to [0,1000]); added May 2026
})

# Server-side logical opcodes that ARE in the opcode mapping
# (all server opcodes except CRYPTO_CHALLENGE=2 and OPCODE_MAPPING=3)
#
# Removed in latest game update:
#   96-99, 101-103  — DUEL server opcodes (DUEL_REQUEST_RECEIVED, DUEL_OPEN,
#                     DUEL_STAKE_UPDATE, DUEL_ACCEPT_STATE, DUEL_CLOSE,
#                     DUEL_START, DUEL_FINISH)  — duel system removed entirely
_SERVER_LOGICAL = sorted({
    1, 10, 11, 12, 21, 22, 23, 24, 25, 26,
    30, 31, 32, 33, 34, 35, 42, 50, 55, 56, 57, 58, 59,
    60, 61, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
    80, 81, 82, 84, 85, 86, 87, 88,
    90, 91, 92, 93, 94, 95,
    100, 110, 111, 120, 121, 122,
})

# ── Base64url helpers ─────────────────────────────────────────────────────────

def _b64u_enc(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64u_dec(s: str) -> bytes:
    s = s.replace("-", "+").replace("_", "/")
    return base64.b64decode(s + "=" * ((-len(s)) % 4))


# ── SHA-256 helper ────────────────────────────────────────────────────────────

def _sha256(*parts: bytes) -> bytes:
    h = hashlib.sha256()
    for p in parts:
        h.update(p)
    return h.digest()


# ── Canonical JSON (mirrors the JS D() function) ─────────────────────────────

def canonical_json(obj) -> str:
    if obj is None:
        return "null"
    if isinstance(obj, bool):
        return "true" if obj else "false"
    if isinstance(obj, int):
        return str(obj)
    if isinstance(obj, float):
        # JS Number serialisation (no trailing zeros, etc.)
        return json.dumps(obj, separators=(",", ":"))
    if isinstance(obj, str):
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    if isinstance(obj, list):
        return "[" + ",".join(canonical_json(x) for x in obj) + "]"
    if isinstance(obj, dict):
        return (
            "{"
            + ",".join(
                json.dumps(k, ensure_ascii=False) + ":" + canonical_json(obj[k])
                for k in sorted(obj.keys())
            )
            + "}"
        )
    raise TypeError(f"Cannot canonical-JSON serialize {type(obj)}")


# ── EC key helpers ────────────────────────────────────────────────────────────

def _ec_pub_to_jwk(pub_key, key_ops: list) -> dict:
    """Export an EC P-256 public key as a browser-compatible JWK dict."""
    nums = pub_key.public_numbers()
    return {
        "crv": "P-256",
        "ext": True,
        "key_ops": key_ops,
        "kty": "EC",
        "x": _b64u_enc(nums.x.to_bytes(32, "big")),
        "y": _b64u_enc(nums.y.to_bytes(32, "big")),
    }


def _ec_priv_to_jwk(priv_key) -> dict:
    """Export EC P-256 private key as a JWK dict (for local storage only)."""
    pub = priv_key.public_key()
    pnums = pub.public_numbers()
    dnums = priv_key.private_numbers()
    return {
        "crv": "P-256",
        "d": _b64u_enc(dnums.private_value.to_bytes(32, "big")),
        "kty": "EC",
        "x": _b64u_enc(pnums.x.to_bytes(32, "big")),
        "y": _b64u_enc(pnums.y.to_bytes(32, "big")),
    }


def _ec_priv_from_jwk(jwk: dict):
    """Import EC P-256 private key from a JWK dict."""
    x = int.from_bytes(_b64u_dec(jwk["x"]), "big")
    y = int.from_bytes(_b64u_dec(jwk["y"]), "big")
    d = int.from_bytes(_b64u_dec(jwk["d"]), "big")
    pub_nums = EllipticCurvePublicNumbers(x=x, y=y, curve=SECP256R1())
    priv_nums = EllipticCurvePrivateNumbers(d, pub_nums)
    return priv_nums.private_key()


def _ec_pub_from_jwk(jwk: dict):
    """Import EC P-256 public key from a JWK dict."""
    x = int.from_bytes(_b64u_dec(jwk["x"]), "big")
    y = int.from_bytes(_b64u_dec(jwk["y"]), "big")
    pub_nums = EllipticCurvePublicNumbers(x=x, y=y, curve=SECP256R1())
    return pub_nums.public_key()


# ── Transcript builder (mirrors JS se/gn function) ───────────────────────────

def _build_transcript(
    *,
    account_id: int,
    device_id: str,
    connection_id: str,
    server_nonce: str,
    client_nonce: str,
    server_public_key: dict,
    client_public_key: dict,
) -> bytes:
    """Canonical-JSON-encode the crypto handshake transcript.

    Mirrors the JS se() / gn() call in index-DGTyz-tl.js exactly:
      D({ protocol, protocolVersion, accountId, deviceId, connectionId,
          serverNonce, clientNonce, serverPublicKey, clientPublicKey })
    where D() is the canonical-JSON serialiser (sorts object keys).

    The "protocol" field sorts between "deviceId" and "protocolVersion",
    so every byte after "deviceId" was wrong without it — causing 1008.
    """
    return canonical_json({
        "protocol":        "evilquest-game-v2",
        "protocolVersion": PROTOCOL_VERSION,
        "accountId":       account_id,
        "deviceId":        device_id,
        "connectionId":    connection_id,
        "serverNonce":     server_nonce,
        "clientNonce":     client_nonce,
        "serverPublicKey": server_public_key,
        "clientPublicKey": client_public_key,
    }).encode("utf-8")


# ── Browser-side transcript signing ──────────────────────────────────────────

async def _browser_sign(transcript: bytes) -> bytes:
    """Sign the WS transcript using the game's registered device key from Chrome.

    The game stores its ECDSA-P256 device key in IndexedDB with extractable=False,
    so we cannot export the private key.  Instead we call crypto.subtle.sign()
    *inside* the Chrome tab via CDP, using window.gm.network.deviceSigningKeyPair.
    This guarantees the signature matches whatever public key the game already
    registered with the server — no key-registration race conditions.

    Requires _last_cdp_port to be set (done by async_http_login).
    """
    from pydoll.browser.chromium import Chrome
    from pydoll.browser.options import ChromiumOptions
    from pydoll.browser.managers import BrowserProcessManager as _BPM

    port = _last_cdp_port
    if not port:
        raise RuntimeError(
            "No CDP port stored — async_http_login must run before browser signing"
        )

    # Minimal options: we only need to connect, not launch.
    options = ChromiumOptions()
    _chrome_exe = (
        shutil.which("chrome") or
        shutil.which("google-chrome") or
        r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    )
    options.binary_location = _chrome_exe

    # Noop process manager — Chrome is pre-launched; stop() must not kill it.
    class _MockProc:
        pid = 0
        def poll(self): return None
        def terminate(self): pass
        def wait(self, timeout=None): pass

    _pm = _BPM(process_creator=lambda _cmd: _MockProc())

    _log.debug("_browser_sign: connecting to Chrome on port %d", port)
    cdp_meta = json.loads(
        urllib.request.urlopen(
            f"http://localhost:{port}/json/version", timeout=5
        ).read()
    )
    browser_ws = cdp_meta["webSocketDebuggerUrl"]

    async with Chrome(options=options) as browser:
        browser._browser_process_manager = _pm
        tab = await browser.connect(browser_ws)   # browser-level connect; returns tabs[0]

        # ── Find the game tab specifically (avoid blank / wrong tabs) ─────────
        # If Chrome has multiple tabs, tabs[0] might not be the game.
        # Search all tabs for one at evilquest.net.
        try:
            tabs = await browser.get_opened_tabs()
            for _candidate in tabs:
                try:
                    _candidate_url = await _candidate.current_url
                    if "evilquest.net" in _candidate_url:
                        tab = _candidate
                        _log.debug("_browser_sign: using game tab at %s",
                                   _candidate_url[:80])
                        break
                except Exception:
                    pass
        except Exception as _te:
            _log.debug("_browser_sign: tab search failed (%s) — using tabs[0]", _te)

        # ── 1. Wait for the game's deviceSigningKeyPair to be ready ──────────
        # The game sets it asynchronously in connect(token) → Aa(token).then(…).
        _log.debug("_browser_sign: waiting for window.gm.network.deviceSigningKeyPair…")
        for _i in range(100):            # up to 10 seconds
            _r = await tab.execute_script(
                "return window.gm?.network?.deviceSigningKeyPair?.privateKey ? 'ready' : null"
            )
            _v = _r.get("result", {}).get("result", {}).get("value")
            if _v == "ready":
                _log.debug("_browser_sign: deviceSigningKeyPair ready after %d polls", _i)
                break
            await asyncio.sleep(0.1)
        else:
            raise RuntimeError(
                "Browser: game.network.deviceSigningKeyPair not ready after 10 s"
            )

        # ── 2. Inject transcript, sign, store result in localStorage ──────────
        # We base64-encode the bytes to pass through JSON-safe JS string.
        tb64 = base64.b64encode(transcript).decode()
        _log.debug("_browser_sign: transcript to sign (%d bytes, b64=%s…)",
                   len(transcript), tb64[:16])

        await tab.execute_script("localStorage.removeItem('_botSignResult')")
        _sign_js = f"""
(async () => {{
    try {{
        const tb = Uint8Array.from(atob('{tb64}'), c => c.charCodeAt(0));
        const key = window.gm.network.deviceSigningKeyPair.privateKey;
        const sig = await crypto.subtle.sign(
            {{name: 'ECDSA', hash: 'SHA-256'}}, key, tb
        );
        const b   = new Uint8Array(sig);
        const b64 = btoa(String.fromCharCode(...b))
            .replace(/\\+/g, '-').replace(/\\//g, '_').replace(/=/g, '');
        localStorage.setItem('_botSignResult', b64);
    }} catch (e) {{
        localStorage.setItem('_botSignResult', 'err:' + e.message);
    }}
}})();
"""
        await tab.execute_script(_sign_js)

        # ── 3. Poll localStorage for the result (up to 5 s) ──────────────────
        _sig_b64u = None
        for _i in range(50):
            await asyncio.sleep(0.1)
            _r = await tab.execute_script(
                "return localStorage.getItem('_botSignResult')"
            )
            _v = _r.get("result", {}).get("result", {}).get("value")
            if _v:
                _sig_b64u = _v
                break

        if not _sig_b64u:
            raise RuntimeError("Browser signing timed out (no result in 5 s)")
        if str(_sig_b64u).startswith("err:"):
            raise RuntimeError(f"Browser signing JS error: {_sig_b64u}")

        _log.debug("_browser_sign: signature (first 16 chars): %s", _sig_b64u[:16])
        return _b64u_dec(_sig_b64u)


# ── Session keys ──────────────────────────────────────────────────────────────

class SessionKeys:
    def __init__(
        self,
        c2s_key: bytes,
        s2c_key: bytes,
        c2s_iv_prefix: bytes,
        s2c_iv_prefix: bytes,
        connection_id: str,
        account_id: int,
    ):
        self.c2s_key       = c2s_key
        self.s2c_key       = s2c_key
        self.c2s_iv_prefix = c2s_iv_prefix
        self.s2c_iv_prefix = s2c_iv_prefix
        self.connection_id = connection_id
        self.account_id    = account_id


def _derive_session_keys(
    *,
    client_ephemeral_private,
    server_public_jwk: dict,
    auth_token: str,
    transcript: bytes,
    server_nonce: str,
    client_nonce: str,
    connection_id: str,
    account_id: int,
) -> SessionKeys:
    # 1. ECDH shared secret (32 bytes)
    server_pub = _ec_pub_from_jwk(server_public_jwk)
    ecdh_secret = client_ephemeral_private.exchange(ECDH(), server_pub)

    # 2. Hashes
    auth_hash       = _sha256(auth_token.encode("utf-8"))
    transcript_hash = _sha256(transcript)

    # 3. HKDF IKM
    hkdf_ikm = ecdh_secret + auth_hash + transcript_hash

    # 4. Salt = SHA-256("evilquest-game-v2:salt" || serverNonce || clientNonce || authHash)
    salt = _sha256(
        b"evilquest-game-v2:salt",
        _b64u_dec(server_nonce),
        _b64u_dec(client_nonce),
        auth_hash,
    )

    # 5. Derive AES-256 session keys via HKDF
    def _hkdf(info: bytes) -> bytes:
        return HKDF(
            algorithm=SHA256(),
            length=32,
            salt=salt,
            info=info,
        ).derive(hkdf_ikm)

    c2s_key = _hkdf(f"evilquest-game-v2:client-to-server:{connection_id}".encode())
    s2c_key = _hkdf(f"evilquest-game-v2:server-to-client:{connection_id}".encode())

    # 6. IV prefixes
    c2s_iv_prefix = _sha256(b"evilquest-game-v2:iv:client-to-server", transcript_hash)[:4]
    s2c_iv_prefix = _sha256(b"evilquest-game-v2:iv:server-to-client", transcript_hash)[:4]

    return SessionKeys(c2s_key, s2c_key, c2s_iv_prefix, s2c_iv_prefix, connection_id, account_id)


# ── Frame encrypt / decrypt ───────────────────────────────────────────────────

def _build_iv(iv_prefix: bytes, counter: int) -> bytes:
    """Build the 12-byte AES-GCM IV: prefix[4] + counter[uint64 BE 8 bytes]."""
    iv = bytearray(12)
    iv[:4] = iv_prefix
    struct.pack_into(">Q", iv, 4, counter)
    return bytes(iv)


def _build_aad(keys: SessionKeys, direction: str, counter: int) -> bytes:
    """Build the Additional Authenticated Data for the AES-GCM frame."""
    return canonical_json({
        "accountId":    keys.account_id,
        "connectionId": keys.connection_id,
        "counter":      counter,
        "direction":    direction,
        "frame":        "evilquest-game-v2",
        "version":      ENC_BYTE_1,
    }).encode("utf-8")


def encrypt_frame(keys: SessionKeys, counter: int, plaintext: bytes) -> bytes:
    """Encrypt a game frame (client → server)."""
    iv  = _build_iv(keys.c2s_iv_prefix, counter)
    aad = _build_aad(keys, "client-to-server", counter)
    ct  = AESGCM(keys.c2s_key).encrypt(iv, plaintext, aad)
    frame = bytearray(10 + len(ct))
    frame[0] = ENC_BYTE_0
    frame[1] = ENC_BYTE_1
    struct.pack_into(">Q", frame, 2, counter)
    frame[10:] = ct
    return bytes(frame)


def decrypt_frame(keys: SessionKeys, data: bytes) -> tuple[int, bytes]:
    """Decrypt a game frame (server → client). Returns (counter, plaintext)."""
    if len(data) < 11 or data[0] != ENC_BYTE_0 or data[1] != ENC_BYTE_1:
        raise ValueError(f"Not a v2 encrypted frame (header {data[:2].hex() if data else '?'})")
    counter = struct.unpack_from(">Q", data, 2)[0]
    iv  = _build_iv(keys.s2c_iv_prefix, counter)
    aad = _build_aad(keys, "server-to-client", counter)
    plaintext = AESGCM(keys.s2c_key).decrypt(iv, bytes(data[10:]), aad)
    return counter, plaintext


# ── Opcode mapping ────────────────────────────────────────────────────────────

class OpcodeMapping:
    """Per-session opcode translation tables."""

    def __init__(self, client_l2w: dict[int, int], server_w2l: dict[int, int]):
        self.client_l2w = client_l2w   # logical → wire  (for sending)
        self.server_w2l = server_w2l   # wire → logical  (for receiving)

    @classmethod
    def from_json(cls, obj: dict) -> "OpcodeMapping":
        if obj.get("version") != OPCODE_MAPPING_VERSION:
            raise ValueError(f"Unsupported opcode mapping version {obj.get('version')}")
        client_map = obj["client"]  # {str(logical): wire}
        server_map = obj["server"]  # {str(logical): wire}

        client_l2w: dict[int, int] = {}
        for logical in _CLIENT_LOGICAL:
            wire = client_map.get(str(logical))
            if wire is None:
                raise ValueError(f"Missing client opcode mapping for logical {logical}")
            client_l2w[logical] = wire

        server_w2l: dict[int, int] = {}
        for logical in _SERVER_LOGICAL:
            wire = server_map.get(str(logical))
            if wire is None:
                raise ValueError(f"Missing server opcode mapping for logical {logical}")
            server_w2l[wire] = logical

        return cls(client_l2w, server_w2l)

    def to_wire(self, logical: int) -> int:
        """Translate a client logical opcode → wire opcode."""
        wire = self.client_l2w.get(logical)
        if wire is None:
            raise ValueError(f"No wire opcode for logical {logical}")
        return wire

    def to_logical(self, wire: int) -> int:
        """Translate a server wire opcode → logical opcode (returns wire unchanged if not mapped)."""
        return self.server_w2l.get(wire, wire)


def apply_opcode_map_send(data: bytes, mapping: OpcodeMapping) -> bytes:
    """Replace byte 0 with the wire opcode before sending."""
    if not data:
        return data
    logical = data[0]
    wire    = mapping.to_wire(logical)
    out     = bytearray(data)
    out[0]  = wire
    return bytes(out)


def apply_opcode_map_recv(data: bytes, mapping: OpcodeMapping) -> bytes:
    """Replace byte 0 with the logical opcode after receiving."""
    if not data:
        return data
    wire    = data[0]
    logical = mapping.to_logical(wire)
    out     = bytearray(data)
    out[0]  = logical
    return bytes(out)


# ── Persistent auth state ────────────────────────────────────────────────────

import time as _time

_AUTH_TTL = 23 * 3600    # 23 hours — tokens expire after 24 h server-side


def save_auth_state(token: str, device_id: str, cookie: str) -> None:
    """Persist auth token + cookies so the next run can skip the browser login."""
    _state_path("auth.json").write_text(json.dumps({
        "token":     token,
        "device_id": device_id,
        "cookie":    cookie,
        "ts":        _time.time(),
    }))


def load_auth_state() -> tuple[str, str, str] | None:
    """
    Load cached auth state if it is less than 23 hours old.
    Returns (token, device_id, cookie_str) or None if expired / missing.
    """
    p = _state_path("auth.json")
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
        age  = _time.time() - data.get("ts", 0)
        if age < _AUTH_TTL:
            _log.info(
                "Reusing cached auth token (%.1f h old, expires in %.1f h)",
                age / 3600,
                (_AUTH_TTL - age) / 3600,
            )
            return data["token"], data["device_id"], data["cookie"]
        _log.info("Cached auth token expired (%.1f h old) — need fresh login", age / 3600)
    except Exception as exc:
        _log.debug("Could not read auth cache: %s", exc)
    return None


# ── Persistent device state ───────────────────────────────────────────────────

def _state_path(filename: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / filename


def load_device_state() -> dict | None:
    """Load stored device ID and cookie."""
    p = _state_path("device.json")
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:
            return None
    return None


def save_device_state(device_id: str, cookie_value: str) -> None:
    _state_path("device.json").write_text(
        json.dumps({"device_id": device_id, "eq_device_id": cookie_value})
    )


def load_signing_key():
    """Load the persistent ECDSA P-256 signing key, or None if not present."""
    p = _state_path("signing_key.json")
    if p.exists():
        try:
            jwk = json.loads(p.read_text())
            return _ec_priv_from_jwk(jwk)
        except Exception:
            return None
    return None


def save_signing_key(priv_key) -> None:
    _state_path("signing_key.json").write_text(json.dumps(_ec_priv_to_jwk(priv_key)))


# ── HTTP login helpers ────────────────────────────────────────────────────────

_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_API_HEADERS = {
    "User-Agent":       _BROWSER_UA,
    "Accept":           "application/json, text/plain, */*",
    "Accept-Language":  "en-US,en;q=0.9",
    "Accept-Encoding":  "gzip, deflate, br",
    "Origin":           "https://evilquest.net",
    "Referer":          "https://evilquest.net/play",
    "Sec-Fetch-Dest":   "empty",
    "Sec-Fetch-Mode":   "cors",
    "Sec-Fetch-Site":   "same-origin",
}


_log = logging.getLogger("ws_transport")

# ── pydoll / reCAPTCHA-aware browser login ────────────────────────────────────

def _prepare_chrome_profile() -> str | None:
    """
    Copy the user's real Chrome Cookies file into a fresh temp profile
    directory.  When Chrome starts with this profile it will have real
    Google auth cookies, which boosts reCAPTCHA v3 scores dramatically.

    Returns the temp dir path (caller must rmtree it), or None if the real
    profile is unavailable (Chrome running & file locked, profile missing, …).
    """
    real_default = (
        Path.home()
        / "AppData/Local/Google/Chrome/User Data/Default"
    )
    # Chrome 80+ encrypts cookies with a key stored in User Data/Local State.
    # We must copy BOTH the Cookies DB and Local State so Chrome can decrypt them.
    user_data = real_default.parent          # …/Chrome/User Data
    local_state = user_data / "Local State"
    if not local_state.exists():
        _log.debug("pydoll: Chrome Local State not found — using fresh profile")
        return None

    # Chrome 120+ moved cookies into a Network sub-directory; handle both layouts
    for candidate in (
        real_default / "Network" / "Cookies",
        real_default / "Cookies",
    ):
        if candidate.exists():
            cookies_src = candidate
            break
    else:
        _log.debug("pydoll: Chrome Cookies file not found — using fresh profile")
        return None

    tmp = tempfile.mkdtemp(prefix="eq_chrome_")
    try:
        # Copy Local State to the root of the temp User Data dir (Chrome looks there
        # for the AES key it needs to decrypt cookies)
        shutil.copy2(local_state, Path(tmp) / "Local State")

        # Recreate the same sub-directory structure Chrome expects
        cookies_dest_dir = Path(tmp) / "Default" / cookies_src.parent.name
        cookies_dest_dir.mkdir(parents=True)
        shutil.copy2(cookies_src, cookies_dest_dir / "Cookies")

        # Copy the journal file too (needed for WAL consistency)
        journal = cookies_src.parent / "Cookies-journal"
        if journal.exists():
            shutil.copy2(journal, cookies_dest_dir / "Cookies-journal")

        _log.info(
            "pydoll: copied real Chrome profile (cookies from %s)",
            cookies_src.parent.name,
        )
        return tmp
    except (PermissionError, OSError) as exc:
        _log.warning(
            "pydoll: cannot copy Chrome profile (%s) — using fresh profile", exc
        )
        shutil.rmtree(tmp, ignore_errors=True)
        return None


def _get_listening_pid(port: int) -> int | None:
    """Return the PID of the process listening on the given TCP port, or None."""
    try:
        r = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=10,
        )
        for line in r.stdout.splitlines():
            if f":{port}" in line and "LISTENING" in line:
                parts = line.split()
                if parts:
                    return int(parts[-1])
    except Exception:
        pass
    return None


class _MockProc:
    """
    Proc-like wrapper for a Chrome browser process launched via PowerShell.

    We launch Chrome through PowerShell's Start-Process (ShellExecuteEx), which
    avoids all handle-inheritance issues.  The launcher process exits immediately;
    we track the actual browser process by its PID found via netstat.

    Exposes the same interface that pydoll's BrowserProcessManager expects.
    """

    def __init__(self, browser_pid: int):
        self.pid = browser_pid
        self.returncode: int | None = None

    def poll(self) -> int | None:
        # pid=0 is a sentinel meaning "Chrome was pre-launched externally;
        # we have no handle to track — always report alive so pydoll doesn't
        # abort its startup loop prematurely."
        if self.pid == 0:
            return None
        try:
            r = subprocess.run(
                ["tasklist", "/FI", f"PID eq {self.pid}", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            if str(self.pid) in r.stdout:
                return None
        except Exception:
            pass
        self.returncode = 0
        return 0

    def terminate(self) -> None:
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self.pid)],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
            )
        except Exception:
            pass

    def wait(self, timeout: float | None = None) -> int:
        return 0


def _pick_free_port() -> int:
    """Pick a random free TCP port on localhost."""
    import socket as _sock
    with _sock.socket(_sock.AF_INET, _sock.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _launch_chrome_sync(
    chrome_exe: str,
    port: int,
    profile_dir: str,
    extra_args: list,
    timeout: int = 120,
) -> _MockProc:
    """
    Launch Chrome and block until its CDP endpoint responds.

    Launch strategy (tried in order):
    1. os.startfile  — direct ShellExecuteW from Python's own process
                       (Python confirmed in WinSta0\\Default interactive desktop)
    2. Manual prompt — if Chrome isn't up after 20 s, print the exact command
                       for the user to run in a separate terminal; keep polling.

    Returns a _MockProc wrapping the browser PID.
    Raises RuntimeError if Chrome hasn't started within `timeout` seconds.
    """
    chrome_args = [
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--disable-sync",
        "--disable-extensions",
        *extra_args,
    ]

    # ── Attempt 1: os.startfile (ShellExecuteW, same process context as Python)
    args_str = " ".join(f'"{a}"' if " " in a else a for a in chrome_args)
    try:
        _log.debug("Thread: os.startfile Chrome port=%d", port)
        os.startfile(chrome_exe, arguments=args_str)
        _log.debug("Thread: os.startfile returned OK")
    except AttributeError:
        # Python < 3.8 or non-Windows: arguments kwarg not available
        _log.debug("Thread: os.startfile(arguments=) not available — skipping")
    except OSError as exc:
        _log.warning("Thread: os.startfile failed: %s", exc)

    # ── Poll CDP; print manual instructions if Chrome isn't up after 20 s ─────
    deadline      = _time.time() + timeout
    last_err: Exception | None = None
    printed_manual = False
    elapsed_logged = 0

    while _time.time() < deadline:
        _time.sleep(1)
        elapsed = int(_time.time() - (deadline - timeout))
        try:
            urllib.request.urlopen(
                f"http://localhost:{port}/json/version", timeout=5
            ).read()
            browser_pid = _get_listening_pid(port) or 0
            _log.info(
                "Thread: Chrome CDP ready (pid=%d port=%d t=%ds)",
                browser_pid, port, elapsed,
            )
            return _MockProc(browser_pid)
        except Exception as exc:
            last_err = exc
            # After 20 s with no CDP, Chrome auto-launch didn't work.
            # Print clear instructions so the user can open Chrome manually.
            if elapsed >= 20 and not printed_manual:
                printed_manual = True
                cmd_display = f'"{chrome_exe}" {args_str}'
                print("\n" + "=" * 70, flush=True)
                print("  Chrome didn't open automatically.", flush=True)
                print("  Please open a NEW terminal window and run:", flush=True)
                print(f"\n    {cmd_display}\n", flush=True)
                print("  Then log into EvilQuest in that Chrome window.", flush=True)
                print("  The bot will connect automatically once you're logged in.", flush=True)
                print("=" * 70 + "\n", flush=True)
                _log.info(
                    "browser login: waiting for manual Chrome launch on port %d", port
                )
            elif elapsed >= elapsed_logged + 30:
                elapsed_logged = elapsed
                remaining = int(deadline - _time.time())
                _log.debug(
                    "browser login: waiting for Chrome on port %d (%ds remaining)",
                    port, remaining,
                )

    raise RuntimeError(
        f"Chrome not available on port {port} within {timeout} s: {last_err}"
    )


async def async_http_login(username: str, password: str) -> tuple[str, str, str]:
    """
    Browser-assisted login: opens Chrome to evilquest.net/play and waits for
    the user to log in manually.  No form automation — the user handles the
    login and reCAPTCHA themselves.  Once the token appears in localStorage
    the bot registers the device signing key and saves the auth state.

    Returns (auth_token, device_id, cookie_header_string).

    Chrome startup strategy
    ───────────────────────
    On Windows, asyncio's ProactorEventLoop creates IOCP (I/O Completion Port)
    handles.  When subprocess.Popen is called from within the event loop,
    Chrome's GPU/renderer child processes inherit those handles and crash
    immediately — the CDP port is never bound.  The fix is to launch Chrome in
    a thread pool worker (run_in_executor) where no asyncio event loop is
    running, and poll the CDP endpoint in that same thread until Chrome is
    ready.  We then hand the already-running Popen object to pydoll via a noop
    process creator so pydoll's connection logic can attach to it.
    """
    # ── Fast path: reuse a cached token if it's still fresh ──────────────────
    # When EQ_CDP_PORT is set, try to reach Chrome's CDP endpoint.
    # • Chrome accessible → run the full browser flow so the IDB injection
    #   happens on the neutral page BEFORE the game JS starts, guaranteeing
    #   the game reads OUR signing key and registers it with the server.
    # • Chrome not accessible → fall back to cached auth if available.
    #   (The Python key from the last successful injection is likely still
    #   registered; browser signing will fail gracefully and Python signing
    #   will be used as the fallback.)
    _eq_cdp_env = int(os.environ.get("EQ_CDP_PORT", "0")) or 0
    _chrome_accessible = False
    if _eq_cdp_env:
        try:
            urllib.request.urlopen(
                f"http://localhost:{_eq_cdp_env}/json/version", timeout=2
            )
            _chrome_accessible = True
        except Exception:
            pass

    if not _chrome_accessible:
        cached = load_auth_state()
        if cached:
            if _eq_cdp_env:
                _log.info(
                    "Chrome not reachable on port %d — using cached auth",
                    _eq_cdp_env,
                )
            # ── Register our Python key now, while no game session is running ──
            # Without Chrome there's no live game to race us.  Registering our
            # Python key here means the server will accept our Python-signed WS
            # handshake even though we never went through the browser login flow
            # this session.
            _cached_token, _cached_did, _cached_cookies = cached
            _signing_key = load_signing_key()
            if _signing_key is not None:
                _pub_jwk_quick = _ec_pub_to_jwk(_signing_key.public_key(), key_ops=["verify"])
                _log.debug(
                    "cached-auth: registering Python key x=%s…",
                    _pub_jwk_quick["x"][:12],
                )
                try:
                    import requests as _req_mod
                    _qs = _req_mod.Session()
                    _qs.headers.update(_API_HEADERS)
                    # Parse and apply the cached cookies (contains eq_device_id etc.)
                    for _ck in _cached_cookies.split(";"):
                        _ck = _ck.strip()
                        if "=" in _ck:
                            _cn, _cv = _ck.split("=", 1)
                            _qs.cookies.set(_cn.strip(), _cv.strip(),
                                            domain="evilquest.net")
                    _qr = _qs.post(
                        "https://evilquest.net/api/device-key",
                        json={"publicKey": _pub_jwk_quick},
                        headers={"Authorization": f"Bearer {_cached_token}"},
                        timeout=10,
                    )
                    _qr.raise_for_status()
                    _qrd = _qr.json()
                    if _qrd.get("ok"):
                        _log.info("cached-auth: device-key registered (Python key)")
                    else:
                        _log.warning("cached-auth: device-key non-ok: %s", _qrd)
                except Exception as _qe:
                    # 401 = token expired server-side — discard cache and force
                    # a fresh browser login so we get a new token + cookies.
                    _is_401 = (
                        hasattr(_qe, "response")
                        and _qe.response is not None
                        and getattr(_qe.response, "status_code", 0) == 401
                    )
                    if _is_401:
                        _log.info(
                            "cached-auth: token rejected by server (401) "
                            "— discarding cache, need fresh browser login"
                        )
                        try:
                            _state_path("auth.json").unlink(missing_ok=True)
                        except Exception:
                            pass
                        # Fall through to browser login (skip `return cached`)
                    else:
                        _log.warning("cached-auth: device-key registration failed: %s", _qe)
                        return cached
            else:
                _log.warning(
                    "cached-auth: no Python signing key found — "
                    "WS handshake will likely fail; run with Chrome to fix"
                )
                return cached
            # Only reach here when device-key succeeded (or key was not None
            # and registration failed with a non-401 error — already returned).
            # If we got a 401 we fall through to the browser login block below.
            if _state_path("auth.json").exists():
                return cached

    try:
        from pydoll.browser.chromium import Chrome
        from pydoll.browser.options import ChromiumOptions
    except ImportError as exc:
        raise ImportError(
            "pydoll-python is required for reCAPTCHA-aware login. "
            "Install it with:  pip install pydoll-python"
        ) from exc

    # ── Locate Chrome binary ──────────────────────────────────────────────────
    _chrome_win = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    _chrome_exe = _chrome_win if os.path.exists(_chrome_win) else (
        shutil.which("google-chrome") or shutil.which("chromium") or "chrome"
    )

    # ── Choose a free port and a throwaway profile directory ─────────────────
    _chrome_port    = _pick_free_port()
    _chrome_profile = tempfile.mkdtemp(prefix="eq_chrome_")

    # ── EQ_CDP_PORT override: skip auto-launch, connect to pre-started Chrome ──
    # Set this env var to the port of a Chrome already running with
    # --remote-debugging-port=PORT, e.g. launched via PowerShell Start-Process.
    _forced_cdp_port = int(os.environ.get("EQ_CDP_PORT", "0")) or None

    if _forced_cdp_port:
        _chrome_port    = _forced_cdp_port
        _chrome_profile = tempfile.mkdtemp(prefix="eq_chrome_")
        _chrome_proc    = _MockProc(0)   # dummy — Chrome already running
        _log.info(
            "browser login: EQ_CDP_PORT=%d — connecting to pre-started Chrome",
            _chrome_port,
        )
        print("\n" + "=" * 60)
        print(f"  Connecting to Chrome on port {_chrome_port}…")
        print("  Please log into EvilQuest in that Chrome window.")
        print("=" * 60 + "\n", flush=True)
    else:
        print("\n" + "=" * 60)
        print("  Chrome is opening — please log into EvilQuest.")
        print("  The bot will continue automatically once you're in.")
        print("  (Waiting up to 3 minutes...)")
        print("=" * 60 + "\n", flush=True)
        _log.info("browser login: Chrome pid pending — port=%d profile=%s",
                  _chrome_port, _chrome_profile)

        # Chrome cannot be launched from Python's subprocess context on this machine.
        # _launch_chrome_sync tries os.startfile first, then prints manual instructions.
        _loop        = asyncio.get_event_loop()
        _chrome_proc = await _loop.run_in_executor(
            None,
            _launch_chrome_sync,
            _chrome_exe,
            _chrome_port,
            _chrome_profile,
            ["--window-size=1280,800", "--start-maximized"],
            120,
        )
        _log.info("browser login: Chrome CDP ready port=%d", _chrome_port)

    auth_token = None
    device_id  = None
    cookie_str = ""

    try:
        # ── pydoll options ────────────────────────────────────────────────────
        # Do NOT add --remote-debugging-port here: pydoll picks its own port
        # internally (e.g. 9225) and passes it first, so adding ours would
        # create a duplicate flag that Chrome ignores.  We redirect pydoll's
        # ConnectionHandler to our actual port below, after entering the context.
        options = ChromiumOptions()
        options.binary_location = _chrome_exe
        # Chrome is already up; pydoll's start_timeout only covers the initial
        # CDP handshake which will succeed immediately.
        options.start_timeout = 10

        from pydoll.browser.managers import BrowserProcessManager as _BPM

        # Noop process creator: pydoll calls stop_process() on __aexit__; we
        # return our already-running _MockProc so it doesn't kill Chrome.
        _proc_ref = _chrome_proc
        def _noop_creator(cmd: list) -> subprocess.Popen:
            _log.debug("pydoll: noop_creator — returning pre-launched Chrome pid=%d",
                       _proc_ref.pid)
            return _proc_ref

        _pm = _BPM(process_creator=_noop_creator)

        # ── Fetch browser-level WebSocket URL directly from Chrome's CDP ──────
        # This lets us use browser.connect() instead of browser.start(), which
        # bypasses all of pydoll's port-ping / _verify_browser_running logic.
        import json as _json
        _cdp_meta = _json.loads(
            urllib.request.urlopen(
                f"http://localhost:{_chrome_port}/json/version", timeout=5
            ).read()
        )
        _browser_ws = _cdp_meta["webSocketDebuggerUrl"]
        _log.debug("pydoll: browser WS → %s", _browser_ws)

        async with Chrome(options=options) as browser:
            browser._browser_process_manager = _pm
            # connect() sets the WS address directly and returns the first tab.
            # No process launch, no port ping, no FailedToStartBrowser risk.
            tab = await browser.connect(_browser_ws)

            # ── Store CDP port so _browser_sign() can reconnect later ─────────
            # Chrome stays running after this async-with exits (noop_creator).
            # _browser_sign() opens a fresh CDP connection when it needs to sign.
            global _last_cdp_port
            _last_cdp_port = _chrome_port
            _log.debug("browser login: CDP port %d stored for later browser signing",
                       _chrome_port)

            # ── Pre-seed IDB with our signing key BEFORE the game page loads ──
            # Timing problem: if we navigate straight to /play, the game's JS
            # calls Ia() (IDB read) during page init, possibly BEFORE we inject.
            # Fix: navigate to a neutral page first so no game JS is running,
            # inject our key into IDB, then navigate to /play.  The game starts
            # fresh, Ia() reads our key (no cache), Aa() registers it.
            _log.debug("browser login: navigating away to stop any running game JS…")
            await tab.go_to("https://evilquest.net/")

            signing_key = load_signing_key()
            if signing_key is None:
                signing_key = generate_private_key(SECP256R1())
                save_signing_key(signing_key)

            _priv_jwk_idb = {**_ec_priv_to_jwk(signing_key), "ext": False, "key_ops": ["sign"]}
            _pub_jwk_idb  = _ec_pub_to_jwk(signing_key.public_key(), key_ops=["verify"])
            _inject_js = """
(async () => {
    try {
        const privJwk = """ + json.dumps(_priv_jwk_idb) + """;
        const pubJwk  = """ + json.dumps(_pub_jwk_idb) + """;
        const priv = await crypto.subtle.importKey(
            "jwk", privJwk, {name:"ECDSA",namedCurve:"P-256"}, false, ["sign"]);
        const pub  = await crypto.subtle.importKey(
            "jwk", pubJwk,  {name:"ECDSA",namedCurve:"P-256"}, true,  ["verify"]);
        await new Promise((res, rej) => {
            const req = indexedDB.open("evilquest_device_crypto_v1");
            req.onupgradeneeded = (e) => {
                const db = e.target.result;
                if (!db.objectStoreNames.contains("keys"))
                    db.createObjectStore("keys", {keyPath:"id"});
            };
            req.onsuccess = (e) => {
                const db = e.target.result;
                const tx = db.transaction("keys", "readwrite");
                tx.objectStore("keys").put({
                    id: "ecdsa-p256",
                    keyPair: {privateKey: priv, publicKey: pub},
                    publicJwk: pubJwk
                });
                tx.oncomplete = () => res();
                tx.onerror   = () => rej(tx.error);
            };
            req.onerror = () => rej(req.error);
        });
        localStorage.setItem("_botKeyOk", "1");
    } catch(e) {
        localStorage.setItem("_botKeyOk", "err:" + e.message);
    }
})();
"""
            await tab.execute_script(_inject_js)
            for _i in range(40):
                await asyncio.sleep(0.05)
                _r = await tab.execute_script(
                    "return localStorage.getItem('_botKeyOk')"
                )
                _v = _r.get("result", {}).get("result", {}).get("value")
                if _v == "1":
                    _log.info(
                        "browser login: signing key injected into IDB (x=%s…)",
                        _pub_jwk_idb["x"][:12],
                    )
                    break
                if _v and str(_v).startswith("err:"):
                    _log.warning("browser login: IDB injection failed: %s", _v)
                    break
            else:
                _log.warning("browser login: IDB injection timed out — continuing anyway")

            # Now navigate to the game.  The game starts fresh: Ia() reads our
            # key from IDB (oe cache is empty), Aa() registers it with the server.
            _log.debug("browser login: navigating to /play with our key in IDB…")
            await tab.go_to("https://evilquest.net/play")

            # ── Poll localStorage until the token appears ──────────────────────
            for attempt in range(360):      # up to 3 minutes
                await asyncio.sleep(0.5)
                result = await tab.execute_script(
                    "return localStorage.getItem('projectrs_token')"
                )
                value = (
                    result
                    .get("result", {})
                    .get("result", {})
                    .get("value")
                )
                if value and isinstance(value, str) and len(value) > 10:
                    auth_token = value
                    _log.info("browser login: token detected")
                    break
                if attempt % 30 == 29:
                    remaining = (360 - attempt - 1) // 2
                    _log.info("browser login: waiting for login… (%ds remaining)", remaining)

            if not auth_token:
                raise RuntimeError("browser login: no token after 3 minutes — did you log in?")

            # ── Wait for game's Aa() to complete, then register our key last ─────
            # Aa(token) is async: it registers the game's IDB key with the server.
            # We must wait for it to finish before registering our Python key,
            # otherwise the game's Aa() will overwrite our registration.
            # Indicator: window.gm.network.deviceSigningKeyPair is set only after
            # Aa() resolves and assigns keyPair to the network object.
            _log.debug("browser login: waiting for game Aa() to complete…")
            _aa_done = False
            for _i in range(150):      # up to 15 seconds
                await asyncio.sleep(0.1)
                try:
                    _r = await tab.execute_script(
                        "return window.gm?.network?.deviceSigningKeyPair?.privateKey ? 'ready' : null"
                    )
                    _v = _r.get("result", {}).get("result", {}).get("value")
                    if _v == "ready":
                        _aa_done = True
                        _log.info(
                            "browser login: game Aa() complete — deviceSigningKeyPair ready (%.1fs)",
                            _i * 0.1,
                        )
                        break
                except Exception:
                    pass

            if not _aa_done:
                _log.warning(
                    "browser login: deviceSigningKeyPair not detected after 15 s — "
                    "registering our key anyway (game may have signed with different key)"
                )

            # ── Register our Python key via browser fetch() ───────────────────
            # Using the browser's own fetch() sends the game's session cookies
            # automatically, guaranteeing correct auth.  This happens AFTER Aa()
            # so our registration is definitively the last one the server sees.
            _pub_jwk_reg = _ec_pub_to_jwk(signing_key.public_key(), key_ops=["verify"])
            _log.debug("register: Python key x=%s… y=%s…",
                       _pub_jwk_reg["x"][:12], _pub_jwk_reg["y"][:12])

            # Clear any stale result from a previous run before injecting
            await tab.execute_script("localStorage.removeItem('_botKeyReg')")

            _reg_js = """
(async () => {
    try {
        const token = localStorage.getItem('projectrs_token');
        const pubJwk = """ + json.dumps(_pub_jwk_reg) + """;
        const resp = await fetch('/api/device-key', {
            method: 'POST',
            headers: {
                'Content-Type':  'application/json',
                'Authorization': 'Bearer ' + token,
            },
            credentials: 'same-origin',
            body: JSON.stringify({publicKey: pubJwk}),
        });
        const data = await resp.json();
        localStorage.setItem('_botKeyReg', JSON.stringify({status: resp.status, data}));
    } catch (e) {
        localStorage.setItem('_botKeyReg', JSON.stringify({err: e.message}));
    }
})();
"""
            await tab.execute_script(_reg_js)

            # Poll for registration result (up to 5 s)
            _reg_result = None
            for _i in range(50):
                await asyncio.sleep(0.1)
                try:
                    _r = await tab.execute_script(
                        "return localStorage.getItem('_botKeyReg')"
                    )
                    _v = _r.get("result", {}).get("result", {}).get("value")
                    if _v:
                        _reg_result = json.loads(_v)
                        break
                except Exception:
                    pass

            if _reg_result is None:
                _log.warning("browser login: browser fetch() key registration timed out")
            elif "err" in _reg_result:
                _log.warning("browser login: browser fetch() registration JS error: %s",
                             _reg_result["err"])
            elif _reg_result.get("status") == 200 and _reg_result.get("data", {}).get("ok"):
                _log.info("browser login: device-key registered OK (browser fetch)")
            else:
                _log.warning("browser login: browser fetch() registration unexpected result: %s",
                             _reg_result)

            # ── Export cookies so WS upgrade header uses the right identity ────
            cookies = await tab.get_cookies()
            cookie_dict = {
                c["name"]: c["value"]
                for c in cookies
                if "evilquest" in c.get("domain", "")
            }
            _log.debug("browser login: exported %d cookies", len(cookie_dict))

            api_session = requests.Session()
            api_session.headers.update({
                "User-Agent":      _BROWSER_UA,
                "Accept":          "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Origin":          "https://evilquest.net",
                "Referer":         "https://evilquest.net/play",
            })
            api_session.cookies.update(cookie_dict)

            # GET /api/device-id
            try:
                did_resp = api_session.get(
                    "https://evilquest.net/api/device-id", timeout=10
                )
                did_resp.raise_for_status()
                device_id = did_resp.json().get("deviceId", "")
                _log.info("browser login: device_id=%s…", str(device_id)[:8])
            except Exception as exc:
                _log.debug("browser login: /api/device-id failed (%s)", exc)
                device_id = ""

            # ── Belt+suspenders: also register our key from Python ─────────────
            # belt+suspenders: Python HTTP POST as a second registration attempt.
            # The browser fetch() above is the primary mechanism; this adds
            # redundancy in case the browser fetch() failed for any reason.
            try:
                _dk = api_session.post(
                    "https://evilquest.net/api/device-key",
                    json={"publicKey": _pub_jwk_reg},
                    headers={"Authorization": f"Bearer {auth_token}"},
                    timeout=10,
                )
                _dk.raise_for_status()
                _dk_data = _dk.json()
                if not _dk_data.get("ok"):
                    _log.warning("device-key registration non-ok: %s", _dk_data)
                else:
                    _log.info("browser login: device-key registered OK (Python HTTP)")
            except Exception as exc:
                _log.warning("browser login: Python device-key registration failed: %s", exc)

            # ── Build cookie string for the WebSocket upgrade header ──────────
            cookie_str = "; ".join(
                f"{c['name']}={c['value']}"
                for c in cookies
                if "evilquest" in c.get("domain", "")
            )
            eq_cookie = next(
                (c["value"] for c in cookies if c["name"] == "eq_device_id"), ""
            )
            if device_id:
                save_device_state(device_id, eq_cookie)

    finally:
        # Only terminate Chrome if we launched it ourselves
        if not _forced_cdp_port:
            try:
                if _chrome_proc.poll() is None:
                    _chrome_proc.terminate()
                    _chrome_proc.wait(timeout=5)
            except Exception:
                pass
        shutil.rmtree(_chrome_profile, ignore_errors=True)

    save_auth_state(auth_token, device_id, cookie_str)
    _log.info("browser login: complete — auth cached for next 23h")
    return auth_token, device_id, cookie_str


# ── Legacy direct-HTTP login (kept for reference; breaks on reCAPTCHA) ────────

def http_login(username: str, password: str) -> tuple[str, str, str]:
    """
    Full HTTP login flow:
      1. Ensure we have a persistent device identity (GET /api/device-id)
      2. POST /api/login to get an auth token
      3. POST /api/device-key to register our ECDSA signing key (once per token)
    Returns (auth_token, device_id, cookie_header_string).

    NOTE: This function is kept for reference but will fail against the current
    server because /api/login now requires a reCAPTCHA v3 token that can only
    be generated by running the page's JavaScript in a real browser.
    Use async_http_login() instead.
    """
    session = requests.Session()

    # ── 1. Device identity ────────────────────────────────────────────────────
    stored = load_device_state()
    if stored:
        device_id = stored["device_id"]
        session.cookies.set("eq_device_id", stored["eq_device_id"], domain="evilquest.net")
    else:
        device_id = None

    # Always call /api/device-id so the server recognises our cookie
    r = session.get(
        "https://evilquest.net/api/device-id",
        headers={**_API_HEADERS, "Accept": "application/json"},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"device-id failed: {data}")
    server_device_id = data["deviceId"]
    cookie_val       = session.cookies.get("eq_device_id", domain="evilquest.net") or ""

    # If server returned a different ID than stored, update
    if device_id != server_device_id:
        device_id = server_device_id
        save_device_state(device_id, cookie_val)

    # ── 2. Login ──────────────────────────────────────────────────────────────
    r = session.post(
        "https://evilquest.net/api/login",
        json={"username": username, "password": password, "deviceId": device_id},
        headers=_API_HEADERS,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(f"Login failed: {data.get('error', data)}")
    token = data["token"]

    # ── 3. Collect all cookies for the WebSocket upgrade ─────────────────────
    # Login sets eq_device_id AND eq_ws_session; both are required for WS auth.
    all_cookies = "; ".join(f"{c.name}={c.value}" for c in session.cookies)

    # ── 4. Register / refresh device signing key ──────────────────────────────
    signing_key = load_signing_key()
    if signing_key is None:
        signing_key = generate_private_key(SECP256R1())
        save_signing_key(signing_key)

    pub_jwk = _ec_pub_to_jwk(signing_key.public_key(), key_ops=["verify"])
    r = session.post(
        "https://evilquest.net/api/device-key",
        json={"publicKey": pub_jwk},
        headers={**_API_HEADERS, "Authorization": f"Bearer {token}"},
        timeout=15,
    )
    if not r.ok:
        raise RuntimeError(f"device-key registration failed: {r.status_code} {r.text[:200]}")
    dk_data = r.json()
    if not dk_data.get("ok"):
        raise RuntimeError(f"device-key rejected: {dk_data}")

    return token, device_id, all_cookies


# ── WebSocket frame helpers ───────────────────────────────────────────────────

def _ws_encode(payload: bytes, opcode: int = 2, mask: bool = True) -> bytes:
    header = bytearray()
    header.append(0x80 | opcode)
    n = len(payload)
    mask_bit = 0x80 if mask else 0
    if n < 126:
        header.append(mask_bit | n)
    elif n < 65536:
        header.append(mask_bit | 126)
        header += struct.pack(">H", n)
    else:
        header.append(mask_bit | 127)
        header += struct.pack(">Q", n)
    if mask:
        mk = os.urandom(4)
        header += mk
        payload = bytes(b ^ mk[i % 4] for i, b in enumerate(payload))
    return bytes(header) + payload


def _recv_exact(sock: ssl.SSLSocket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("WebSocket connection closed")
        buf += chunk
    return bytes(buf)


def _read_ws_frame(sock: ssl.SSLSocket) -> tuple[int, bytes]:
    """Blocking read of one WebSocket frame. Returns (opcode, payload)."""
    header = _recv_exact(sock, 2)
    opcode = header[0] & 0x0F
    masked = bool(header[1] & 0x80)
    plen   = header[1] & 0x7F
    if plen == 126:
        plen = struct.unpack(">H", _recv_exact(sock, 2))[0]
    elif plen == 127:
        plen = struct.unpack(">Q", _recv_exact(sock, 8))[0]
    mask_key = _recv_exact(sock, 4) if masked else b""
    payload  = _recv_exact(sock, plen)
    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return opcode, payload


def _sync_upgrade(token: str, device_cookie: str) -> ssl.SSLSocket:
    """
    Perform the HTTP→WebSocket upgrade.

    Header order and presence are matched to Chrome 124's observed WebSocket
    upgrade requests.  Differences from the previous version:

    • ORDER: Chrome sends Connection/Pragma/Cache-Control before User-Agent,
      then Upgrade/Origin/Sec-WebSocket-* in a specific order, then
      Accept-Encoding/Accept-Language, then the WebSocket-specific headers,
      then Cookie.  The previous order was scrambled relative to Chrome.

    • ADDED: Accept-Encoding and Accept-Language.  Chrome always sends these
      in WebSocket upgrade requests; omitting them is a fingerprint gap.

    • REMOVED: Referer.  Chrome does NOT include a Referer header in WebSocket
      upgrade requests (the Fetch spec omits it for "websocket" requests).
      Having it was itself a bot fingerprint.

    • TCP_NODELAY: Chrome disables Nagle's algorithm (TCP_NODELAY=1) for all
      WebSocket connections.  Python's default socket has Nagle enabled, which
      can batch small frames differently from a browser — detectable via TCP
      segment timing and size distributions.  We set TCP_NODELAY after the
      TLS handshake to match Chrome's behaviour.
    """
    ctx  = ssl.create_default_context()
    conn = http.client.HTTPSConnection("evilquest.net", 443, context=ctx, timeout=20)

    # Python's http.client._send_request() checks whether 'host' and
    # 'accept-encoding' are present in the headers dict and sets skip_host /
    # skip_accept_encoding accordingly, so including them here gives us full
    # control over their position without duplicating them.
    conn.request("GET", "/ws/game", headers={
        "Host":                     "evilquest.net",
        "Connection":               "Upgrade",
        "Pragma":                   "no-cache",
        "Cache-Control":            "no-cache",
        "User-Agent":               _BROWSER_UA,
        "Upgrade":                  "websocket",
        "Origin":                   "https://evilquest.net",
        "Sec-WebSocket-Version":    "13",
        "Accept-Encoding":          "gzip, deflate, br, zstd",
        "Accept-Language":          "en-US,en;q=0.9",
        "Sec-WebSocket-Key":        base64.b64encode(os.urandom(16)).decode(),
        "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
        "Sec-WebSocket-Protocol":   f"auth.{token}",
        "Cookie":                   device_cookie,
    })
    resp = conn.getresponse()
    if resp.status != 101:
        body = resp.read(256).decode("utf-8", errors="replace")
        raise ConnectionError(f"WebSocket upgrade failed: {resp.status} {resp.reason} — {body}")

    # Log any Set-Cookie headers in the 101 response — the server may issue a
    # fresh eq_ws_session per upgrade that we should carry into the next run.
    for hdr, val in resp.headers.items():
        if hdr.lower() == "set-cookie":
            _log.debug("101 Set-Cookie: %s", val[:120])

    sock = conn.sock
    # Disable Nagle's algorithm to match Chrome's TCP behaviour for WebSocket
    # connections.  Without this, the OS may coalesce multiple small sends into
    # a single TCP segment, producing different segment-size distributions from
    # a browser and triggering packet-timing / TCP-fingerprint detection.
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (OSError, AttributeError):
        # ssl.SSLSocket on some platforms doesn't expose setsockopt directly.
        # Best-effort — connection still works without TCP_NODELAY.
        _log.debug("TCP_NODELAY not available on this platform — skipping")

    return sock


# ── GameWebSocket ─────────────────────────────────────────────────────────────

class GameWebSocket:
    """
    Async WebSocket client with:
      • Chrome-compatible HTTP upgrade
      • Automatic CRYPTO_CHALLENGE/RESPONSE handshake
      • Per-session opcode mapping
      • AES-256-GCM v2 frame encryption
    """

    def __init__(self, auth_token: str, device_id: str, cookie_header: str = ""):
        """
        auth_token    — JWT/hex token from /api/login
        device_id     — server-issued UUID from /api/device-id
        cookie_header — full Cookie: header string (eq_device_id + eq_ws_session)
        """
        self._token         = auth_token
        self._device_id     = device_id
        self._device_cookie = cookie_header

        self._sock:          ssl.SSLSocket | None = None
        self._loop:          asyncio.AbstractEventLoop | None = None
        self._send_lock      = asyncio.Lock()
        self._keys:          SessionKeys | None = None
        self._mapping:       OpcodeMapping | None = None
        self._send_counter:  int = 0
        self._recv_counter:  int = -1

    # ── Connection and handshake ─────────────────────────────────────────────

    async def connect(self) -> None:
        """Connect and complete the full crypto handshake."""
        self._loop = asyncio.get_running_loop()
        self._sock = await self._loop.run_in_executor(
            None, _sync_upgrade, self._token, self._device_cookie
        )
        self._sock.settimeout(30.0)

        # Wait for CRYPTO_CHALLENGE (plain frame, opcode byte = 2)
        challenge_raw = await self._recv_raw_blocking()
        if not challenge_raw or challenge_raw[0] != 2:
            raise ConnectionError(
                f"Expected CRYPTO_CHALLENGE (opcode 2), got "
                f"opcode {challenge_raw[0] if challenge_raw else '?'}"
            )
        challenge = self._parse_str_frame(challenge_raw)
        ch = json.loads(challenge)
        _log.debug("CRYPTO_CHALLENGE: %s", challenge)
        if ch.get("version") != CRYPTO_VERSION:
            raise ConnectionError(f"Unsupported crypto version {ch.get('version')}")

        # Build CRYPTO_RESPONSE
        ephemeral_key  = generate_private_key(SECP256R1())
        client_pub_jwk = _ec_pub_to_jwk(ephemeral_key.public_key(), key_ops=[])
        client_nonce   = _b64u_enc(secrets.token_bytes(16))

        transcript = _build_transcript(
            account_id        = ch["accountId"],
            device_id         = ch["deviceId"],
            connection_id     = ch["connectionId"],
            server_nonce      = ch["serverNonce"],
            client_nonce      = client_nonce,
            server_public_key = ch["serverPublicKey"],
            client_public_key = client_pub_jwk,
        )
        _log.debug("transcript (%d bytes): %s", len(transcript), transcript.decode())

        # ── Sign transcript ───────────────────────────────────────────────────
        # PRIMARY: Ask the Chrome browser to sign using the game's own device key
        # (window.gm.network.deviceSigningKeyPair.privateKey).  This is the key
        # the game already registered with the server via Aa(), so the server's
        # ECDSA verification is guaranteed to match — no key-registration races.
        #
        # FALLBACK: If no browser CDP port is stored (non-browser runs), use our
        # persistent Python signing key from ~/.evilquest/signing_key.json.
        if _last_cdp_port:
            try:
                _log.debug("WS sign: using browser signing (game device key)…")
                _sig_bytes = await _browser_sign(transcript)
                sig_b64    = _b64u_enc(_sig_bytes)
                _log.debug("WS sign: browser signature (first 16): %s", sig_b64[:16])
            except Exception as _bs_err:
                _log.warning(
                    "WS sign: browser signing failed (%s) — falling back to Python key",
                    _bs_err,
                )
                signing_key = load_signing_key()
                if signing_key is None:
                    raise RuntimeError("No Python signing key and browser signing failed")
                _sk_pub = _ec_pub_to_jwk(signing_key.public_key(), key_ops=["verify"])
                _log.debug("WS sign (fallback): key x=%s y=%s", _sk_pub["x"], _sk_pub["y"])
                _der   = signing_key.sign(transcript, ec.ECDSA(hashes.SHA256()))
                _r, _s = decode_dss_signature(_der)
                sig_b64 = _b64u_enc(_r.to_bytes(32, "big") + _s.to_bytes(32, "big"))
        else:
            # No browser available — use local Python key (pre-registered via
            # http_login / manual POST /api/device-key).
            signing_key = load_signing_key()
            if signing_key is None:
                raise RuntimeError("No signing key — run http_login() first")
            _sk_pub = _ec_pub_to_jwk(signing_key.public_key(), key_ops=["verify"])
            _log.debug("WS sign: Python key x=%s y=%s", _sk_pub["x"], _sk_pub["y"])
            _der   = signing_key.sign(transcript, ec.ECDSA(hashes.SHA256()))
            _r, _s = decode_dss_signature(_der)
            sig_b64 = _b64u_enc(_r.to_bytes(32, "big") + _s.to_bytes(32, "big"))
            _log.debug("WS sign: signature (first 16): %s", sig_b64[:16])

        # Derive session keys
        self._keys = _derive_session_keys(
            client_ephemeral_private = ephemeral_key,
            server_public_jwk        = ch["serverPublicKey"],
            auth_token               = self._token,
            transcript               = transcript,
            server_nonce             = ch["serverNonce"],
            client_nonce             = client_nonce,
            connection_id            = ch["connectionId"],
            account_id               = ch["accountId"],
        )
        self._send_counter = 0
        self._recv_counter = -1

        # ── SubtleCrypto processing delay ────────────────────────────────────
        # In a real browser the CRYPTO_RESPONSE is assembled asynchronously
        # after three Web Crypto API calls:
        #   • crypto.subtle.generateKey (P-256 ECDH ephemeral key pair)
        #   • crypto.subtle.sign        (ECDSA over the transcript)
        #   • crypto.subtle.deriveBits  (ECDH shared secret)
        # Chrome's BoringSSL backend takes 8–50 ms for these on typical hardware
        # (measured via DevTools performance timeline).  Our synchronous Python
        # crypto completes in <1 ms, so sending immediately after computation
        # produces a sub-millisecond challenge→response gap that is trivially
        # distinguishable from a real browser.
        #
        # Real browser SubtleCrypto.importKey + deriveKey on P-256 takes 15-300 ms
        # depending on hardware, browser version, and GC pressure.  The true
        # distribution is heavy-tailed lognormal: median ~45 ms, σ_ln = 0.70.
        # The previous [8, 80] ms clamp was too narrow and too fast, making the
        # timing distribution trivially distinguishable from browsers.
        _subtle_delay = math.exp(random.gauss(math.log(0.045), 0.70))
        await asyncio.sleep(max(0.015, min(0.300, _subtle_delay)))

        # Send CRYPTO_RESPONSE (plain, not encrypted, client opcode 2)
        response_json = json.dumps({
            "version":         CRYPTO_VERSION,
            "clientNonce":     client_nonce,
            "clientPublicKey": client_pub_jwk,
            "signature":       sig_b64,
        }, separators=(",", ":"))
        _log.debug("CRYPTO_RESPONSE: %s", response_json)
        response_frame = self._build_str_frame(2, response_json)
        _log.debug("response_frame hex (first 32 bytes): %s", response_frame[:32].hex())
        await self._loop.run_in_executor(
            None, lambda: self._sock.sendall(_ws_encode(response_frame))
        )

        # Wait for OPCODE_MAPPING (first encrypted frame, logical opcode 3)
        mapping_enc = await self._recv_raw_blocking()
        if not mapping_enc or mapping_enc[0] != ENC_BYTE_0:
            raise ConnectionError(
                f"Expected encrypted OPCODE_MAPPING frame, got "
                f"first byte {mapping_enc[0] if mapping_enc else '?'}"
            )
        counter, mapping_plain = decrypt_frame(self._keys, mapping_enc)
        self._recv_counter = counter
        if mapping_plain[0] != 3:
            raise ConnectionError(f"Expected OPCODE_MAPPING (3), got opcode {mapping_plain[0]}")
        mapping_json = self._parse_str_frame(mapping_plain)
        self._mapping = OpcodeMapping.from_json(json.loads(mapping_json))

        # A real browser spends several JS event-loop ticks parsing the opcode
        # mapping JSON, scheduling micro-tasks, and updating internal state before
        # it returns from the async handshake function.  Returning immediately
        # (< 1 ms after decryption) is a machine-speed fingerprint.
        # Lognormal: median ~12 ms, σ_ln = 0.55, clamped to [4, 60] ms.
        _mapping_settle = math.exp(random.gauss(math.log(0.012), 0.55))
        await asyncio.sleep(max(0.004, min(0.060, _mapping_settle)))

    @staticmethod
    def _parse_str_frame(data: bytes) -> str:
        """Parse a string frame: [opcode][str_len uint16][str UTF-8]."""
        if len(data) < 3:
            raise ValueError("String frame too short")
        slen = struct.unpack_from(">H", data, 1)[0]
        return data[3:3 + slen].decode("utf-8")

    @staticmethod
    def _build_str_frame(opcode: int, s: str) -> bytes:
        """Build a string frame: [opcode][str_len uint16][str UTF-8]."""
        enc = s.encode("utf-8")
        return struct.pack(f">BH{len(enc)}s", opcode, len(enc), enc)

    async def _recv_raw_blocking(self) -> bytes | None:
        """Read one WebSocket frame payload from the raw socket."""
        opcode, payload = await self._loop.run_in_executor(
            None, lambda: _read_ws_frame(self._sock)
        )
        if opcode == 9:  # ping → pong
            # A browser responds to a WebSocket ping in the next event loop tick
            # after the network event fires.  That's typically 1–16 ms depending
            # on the browser's event-loop backlog and OS scheduler.  Responding
            # in the same asyncio tick as the read (zero delay) is a machine-speed
            # fingerprint — no human-operated browser ever achieves it.
            # A browser pong delay is NOT uniform — it follows a lognormal
            # distribution driven by event-loop scheduling jitter.  Uniform
            # distributions are a statistical fingerprint (server detects them
            # via KS test over accumulated pong samples).  Use lognormal:
            # median ~5 ms, σ_ln = 0.60, clamped to [1, 50] ms.
            _pong_delay = math.exp(random.gauss(math.log(0.005), 0.60))
            await asyncio.sleep(max(0.001, min(0.050, _pong_delay)))
            await self._send_raw_ws(payload, opcode=10)
            return None
        if opcode == 8:
            # Close frame payload: [close_code uint16 BE][optional reason UTF-8]
            if len(payload) >= 2:
                close_code = struct.unpack_from(">H", payload)[0]
                reason = payload[2:].decode("utf-8", errors="replace") if len(payload) > 2 else ""
                raise ConnectionError(f"Server sent WebSocket close frame: code={close_code} reason={reason!r}")
            raise ConnectionError("Server sent WebSocket close frame (no code)")
        if opcode not in (1, 2):
            return None
        return payload

    # ── Public API ───────────────────────────────────────────────────────────

    async def recv(self) -> bytes | None:
        """
        Read one game message.
        Returns the plaintext with the logical opcode in byte 0.
        Returns None for non-data frames (pings, etc.).
        """
        while True:
            payload = await self._recv_raw_blocking()
            if payload is None:
                continue
            if not payload:
                return payload

            if payload[0] == ENC_BYTE_0:
                if self._keys is None:
                    raise RuntimeError("Encrypted frame before session keys")
                counter, plain = decrypt_frame(self._keys, payload)
                if counter <= self._recv_counter:
                    raise RuntimeError(f"Replayed encrypted frame (counter {counter})")
                self._recv_counter = counter
                if self._mapping is not None:
                    plain = apply_opcode_map_recv(plain, self._mapping)
                return plain
            else:
                # Plain frame — only expected before mapping is ready (shouldn't happen post-handshake)
                return payload

    async def send(self, data: bytes) -> None:
        """
        Send a game packet.
        Applies opcode mapping (logical → wire) and encrypts.
        """
        async with self._send_lock:
            if self._keys is None or self._mapping is None:
                raise RuntimeError("Cannot send before handshake is complete")
            wire_data = apply_opcode_map_send(data, self._mapping)
            self._send_counter += 1
            enc_frame = encrypt_frame(self._keys, self._send_counter, wire_data)
            frame     = _ws_encode(enc_frame)
            await self._loop.run_in_executor(
                None, lambda: self._sock.sendall(frame)
            )

    async def _send_raw_ws(self, data: bytes, opcode: int = 10) -> None:
        """Send a raw WebSocket frame (for pong)."""
        frame = _ws_encode(data, opcode=opcode, mask=True)
        async with self._send_lock:
            await self._loop.run_in_executor(
                None, lambda: self._sock.sendall(frame)
            )

    async def close(self) -> None:
        try:
            if self._sock:
                self._sock.close()
        except Exception:
            pass
        self._sock = None
