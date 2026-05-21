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
import os
import secrets
import ssl
import struct
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
PROTOCOL_VERSION = 11            # hs = 11 in GameManager JS
CRYPTO_VERSION   = 2             # qe = 2
OPCODE_MAPPING_VERSION = 1       # bt = 1

STATE_DIR = Path.home() / ".evilquest"

# Client-side logical opcodes that ARE in the opcode mapping
# (all client opcodes except LOGIN=1 and CRYPTO_RESPONSE=2)
_CLIENT_LOGICAL = sorted({
    10, 20, 21, 22, 23, 30, 31, 32, 33, 34, 35, 36, 37, 38, 40, 41, 42, 43, 44, 45,
    50, 60, 70, 71, 80, 81, 82, 83, 90, 91, 92, 93, 94, 95,
    100, 101, 102, 103, 104, 105, 120, 121,
})

# Server-side logical opcodes that ARE in the opcode mapping
# (all server opcodes except CRYPTO_CHALLENGE=2 and OPCODE_MAPPING=3)
_SERVER_LOGICAL = sorted({
    1, 10, 11, 12, 21, 22, 23, 24, 25, 26,
    30, 31, 32, 33, 34, 35, 42, 50, 55, 56, 57, 58, 59,
    60, 61, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
    80, 81, 82, 84, 85, 86, 87, 88,
    90, 91, 92, 93, 94, 95, 96, 97, 98, 99,
    100, 101, 102, 103, 110, 111, 120, 121, 122,
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
    """Canonical-JSON-encode the crypto handshake transcript."""
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


def http_login(username: str, password: str) -> tuple[str, str, str]:
    """
    Full HTTP login flow:
      1. Ensure we have a persistent device identity (GET /api/device-id)
      2. POST /api/login to get an auth token
      3. POST /api/device-key to register our ECDSA signing key (once per token)
    Returns (auth_token, device_id, cookie_header_string).
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
    """Perform the HTTP→WebSocket upgrade."""
    ctx  = ssl.create_default_context()
    conn = http.client.HTTPSConnection("evilquest.net", 443, context=ctx, timeout=20)
    conn.request("GET", "/ws/game", headers={
        "Host":                    "evilquest.net",
        "Upgrade":                 "websocket",
        "Connection":              "Upgrade",
        "Sec-WebSocket-Key":       base64.b64encode(os.urandom(16)).decode(),
        "Sec-WebSocket-Version":   "13",
        "Sec-WebSocket-Protocol":  f"auth.{token}",
        "Sec-WebSocket-Extensions": "permessage-deflate; client_max_window_bits",
        "Origin":                  "https://evilquest.net",
        "User-Agent":              _BROWSER_UA,
        "Referer":                 "https://evilquest.net/play",
        "Cookie":                  device_cookie,   # full "name=val; name=val" header
        "Pragma":                  "no-cache",
        "Cache-Control":           "no-cache",
    })
    resp = conn.getresponse()
    if resp.status != 101:
        body = resp.read(256).decode("utf-8", errors="replace")
        raise ConnectionError(f"WebSocket upgrade failed: {resp.status} {resp.reason} — {body}")
    return conn.sock


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
        if ch.get("version") != CRYPTO_VERSION:
            raise ConnectionError(f"Unsupported crypto version {ch.get('version')}")

        # Build CRYPTO_RESPONSE
        signing_key   = load_signing_key()
        if signing_key is None:
            raise RuntimeError("No signing key — run http_login() first")

        ephemeral_key = generate_private_key(SECP256R1())
        client_pub_jwk = _ec_pub_to_jwk(ephemeral_key.public_key(), key_ops=[])
        client_nonce   = _b64u_enc(secrets.token_bytes(16))

        transcript = _build_transcript(
            account_id       = ch["accountId"],
            device_id        = ch["deviceId"],
            connection_id    = ch["connectionId"],
            server_nonce     = ch["serverNonce"],
            client_nonce     = client_nonce,
            server_public_key = ch["serverPublicKey"],
            client_public_key = client_pub_jwk,
        )

        # Sign transcript with our persistent ECDSA device key (P1363 format)
        der_sig  = signing_key.sign(transcript, ec.ECDSA(hashes.SHA256()))
        r, s     = decode_dss_signature(der_sig)
        p1363    = r.to_bytes(32, "big") + s.to_bytes(32, "big")
        sig_b64  = _b64u_enc(p1363)

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

        # Send CRYPTO_RESPONSE (plain, not encrypted, client opcode 2)
        response_json = json.dumps({
            "version":       CRYPTO_VERSION,
            "clientNonce":   client_nonce,
            "clientPublicKey": client_pub_jwk,
            "signature":     sig_b64,
        }, separators=(",", ":"))
        response_frame = self._build_str_frame(2, response_json)
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
            await self._send_raw_ws(payload, opcode=10)
            return None
        if opcode == 8:
            raise ConnectionError("Server sent WebSocket close frame")
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
