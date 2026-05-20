"""
Raw http.client-based async WebSocket transport for evilquest.net.

Caddy rejects the websockets/websocket-client libraries but accepts a raw
http.client HTTP/1.1 upgrade with Chrome-like headers.

After LOGIN_OK, all frames use AES-256-GCM:
  Key  = SHA-256("evilquest-game-v1:" + nonce8 + authToken_utf8)
  Nonce= 4 × uint16 BE words from LOGIN_OK vals[5:9]
  IV   = nonce[0:8], byte[7] ^= 60 (s→c) / 195 (c→s), then counter uint32 BE
  Frame= [0xFF][counter uint32 BE][ciphertext+16B GCM tag]
"""

import asyncio
import base64
import hashlib
import http.client
import os
import ssl
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

VI = 0xFF  # Encrypted frame marker byte


# ── Cipher helpers ────────────────────────────────────────────────────────────

def derive_key(auth_token: str, nonce: bytes) -> bytes:
    """SHA-256("evilquest-game-v1:" + nonce + token) → 32-byte AES-256 key."""
    data = b"evilquest-game-v1:" + nonce + auth_token.encode("utf-8")
    return hashlib.sha256(data).digest()


def build_nonce(nonce_words: list) -> bytes:
    """Pack 4 raw uint16 values (& 0xFFFF each) into an 8-byte nonce."""
    buf = bytearray(8)
    for i, v in enumerate(nonce_words[:4]):
        struct.pack_into(">H", buf, i * 2, v & 0xFFFF)
    return bytes(buf)


def _build_iv(nonce: bytes, direction: str, counter: int) -> bytes:
    iv = bytearray(12)
    iv[:8] = nonce[:8]
    iv[7] ^= 60 if direction == "server-to-client" else 195
    struct.pack_into(">I", iv, 8, counter & 0xFFFFFFFF)
    return bytes(iv)


def encrypt_game_frame(key: bytes, nonce: bytes, counter: int, plaintext: bytes) -> bytes:
    iv = _build_iv(nonce, "client-to-server", counter)
    ct = AESGCM(key).encrypt(iv, plaintext, None)
    frame = bytearray(5 + len(ct))
    frame[0] = VI
    struct.pack_into(">I", frame, 1, counter & 0xFFFFFFFF)
    frame[5:] = ct
    return bytes(frame)


def decrypt_game_frame(key: bytes, nonce: bytes, data: bytes) -> bytes:
    if len(data) < 6 or data[0] != VI:
        raise ValueError("not an encrypted game frame")
    counter = struct.unpack_from(">I", data, 1)[0]
    iv = _build_iv(nonce, "server-to-client", counter)
    return AESGCM(key).decrypt(iv, data[5:], None)


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


def _read_ws_frame(sock: ssl.SSLSocket) -> tuple:
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


# ── HTTP/1.1 WebSocket upgrade ────────────────────────────────────────────────

def _sync_upgrade(token: str) -> ssl.SSLSocket:
    """Perform the HTTP→WebSocket upgrade using raw http.client (Caddy-compatible)."""
    ctx  = ssl.create_default_context()
    conn = http.client.HTTPSConnection("evilquest.net", 443, context=ctx, timeout=20)
    conn.request("GET", "/ws/game", headers={
        "Host":                    "evilquest.net",
        "Upgrade":                 "websocket",
        "Connection":              "Upgrade",
        "Sec-WebSocket-Key":       base64.b64encode(os.urandom(16)).decode(),
        "Sec-WebSocket-Version":   "13",
        "Sec-WebSocket-Protocol":  f"auth.{token}",
        "Sec-WebSocket-Extensions":"permessage-deflate; client_max_window_bits",
        "Origin":                  "https://evilquest.net",
        "User-Agent":              "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                                   "Chrome/124.0.0.0 Safari/537.36",
        "Referer":                 "https://evilquest.net/play",
        "Pragma":                  "no-cache",
        "Cache-Control":           "no-cache",
    })
    resp = conn.getresponse()
    if resp.status != 101:
        body = resp.read(256).decode("utf-8", errors="replace")
        raise ConnectionError(
            f"WebSocket upgrade failed: {resp.status} {resp.reason} — {body}"
        )
    return conn.sock


# ── Async WebSocket wrapper ───────────────────────────────────────────────────

class GameWebSocket:
    """
    Async WebSocket client that uses raw http.client for the Caddy-compatible
    HTTP upgrade and transparently handles AES-256-GCM per-frame encryption.

    Usage:
        ws = GameWebSocket()
        await ws.connect(token)        # token sets Sec-WebSocket-Protocol
        ws.set_cipher(key, nonce)      # call once after LOGIN_OK
        data = await ws.recv()         # decrypts automatically
        await ws.send(data)            # encrypts automatically
        await ws.close()
    """

    def __init__(self):
        self._sock:         ssl.SSLSocket | None = None
        self._loop:         asyncio.AbstractEventLoop | None = None
        self._send_lock     = asyncio.Lock()
        self._key:          bytes | None = None
        self._nonce:        bytes | None = None
        self._send_counter: int = 0

    async def connect(self, token: str) -> None:
        self._loop = asyncio.get_running_loop()
        self._sock = await self._loop.run_in_executor(None, _sync_upgrade, token)
        self._sock.settimeout(30.0)

    def set_cipher(self, key: bytes, nonce: bytes) -> None:
        self._key   = key
        self._nonce = nonce

    @property
    def cipher_active(self) -> bool:
        return self._key is not None

    async def recv(self) -> bytes | None:
        """
        Read one game message. Decrypts encrypted frames transparently.
        Returns the plaintext payload, or None for non-data/ping frames.
        Raises ConnectionError on disconnect or close frame.
        """
        opcode, payload = await self._loop.run_in_executor(
            None, lambda: _read_ws_frame(self._sock)
        )
        if opcode == 9:  # ping → pong
            await self._send_raw(payload, opcode=10)
            return None
        if opcode == 8:
            raise ConnectionError("Server sent WebSocket close frame")
        if opcode not in (1, 2):
            return None

        if payload and payload[0] == VI and self._key is not None:
            return decrypt_game_frame(self._key, self._nonce, payload)

        return payload

    async def send(self, data: bytes) -> None:
        """Send a game packet, encrypting it once the cipher is active."""
        async with self._send_lock:
            if self._key is not None:
                self._send_counter += 1
                payload = encrypt_game_frame(
                    self._key, self._nonce, self._send_counter, data
                )
            else:
                payload = data
            frame = _ws_encode(payload)
            await self._loop.run_in_executor(
                None, lambda: self._sock.sendall(frame)
            )

    async def _send_raw(self, data: bytes, opcode: int = 10) -> None:
        """Send a raw WebSocket frame without game-level encryption (for pong)."""
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
