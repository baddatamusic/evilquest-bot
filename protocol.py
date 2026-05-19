"""
EvilQuest binary WebSocket protocol.

Packet format (client → server, via V() in GameManager JS):
  Binary:  [opcode: uint8][val0: int16 BE][val1: int16 BE]...
  String:  [opcode: uint8][str_len: uint16 BE][str_bytes: UTF-8][val0: int16 BE]...

Packet format (server → client, parsed by nn() / qt() in GameManager JS):
  Same layouts — nn() reads binary, qt() reads string.
"""

import struct


# ── Client → Server opcodes (enum Y in GameManager JS) ──────────────────────

class C:
    LOGIN            = 1
    PLAYER_MOVE      = 10
    PLAYER_ATTACK_NPC = 20
    PLAYER_TALK_NPC  = 21
    DIALOGUE_CHOOSE  = 22
    PLAYER_PICKUP    = 30
    PLAYER_DROP      = 31
    PLAYER_EQUIP     = 32
    PLAYER_UNEQUIP   = 33
    PLAYER_EAT       = 34
    PLAYER_SELL_ITEM = 37
    PLAYER_INTERACT_OBJECT = 40
    MAP_READY        = 50
    CLIENT_PING      = 120
    BANK_OPEN        = 80
    BANK_DEPOSIT     = 81
    BANK_WITHDRAW    = 82


# ── Server → Client opcodes (enum j in GameManager JS) ──────────────────────

class S:
    LOGIN_OK       = 1
    PLAYER_SYNC    = 10
    NPC_SYNC       = 11
    PLAYER_STATS   = 21
    PLAYER_SKILLS  = 22
    PLAYER_EQUIP   = 23
    COMBAT_HIT     = 30
    ENTITY_DEATH   = 31
    XP_GAIN        = 32
    LEVEL_UP       = 33
    CHAT_SYSTEM    = 42
    SHOP_OPEN      = 50
    SKILLING_START = 57
    SKILLING_STOP  = 58
    MAP_CHANGE     = 60
    FLOOR_CHANGE   = 61
    NPC_APPEARANCE = 73
    DIALOGUE_OPEN  = 76
    PATH_TRUNCATED = 100
    SERVER_PONG    = 121


# ── Packet builders ──────────────────────────────────────────────────────────

def pack(opcode: int, *values: int) -> bytes:
    """Build a binary packet: uint8 opcode + int16[] values (big-endian)."""
    return struct.pack(">B" + "h" * len(values), opcode, *values)


def pack_str(opcode: int, s: str, *values: int) -> bytes:
    """Build a string packet: uint8 opcode + uint16 len + UTF-8 str + int16[] values."""
    enc = s.encode("utf-8")
    return struct.pack(f">BH{len(enc)}s" + "h" * len(values), opcode, len(enc), enc, *values)


# ── Packet parsers ───────────────────────────────────────────────────────────

def unpack(data: bytes) -> tuple[int, list[int]]:
    """Parse a binary packet → (opcode, [int16 values])."""
    if not data:
        raise ValueError("empty packet")
    op  = data[0]
    n   = (len(data) - 1) // 2
    vals = list(struct.unpack_from(">" + "h" * n, data, 1)) if n else []
    return op, vals


def try_unpack_str(data: bytes) -> tuple[str, list[int]] | None:
    """
    Attempt to parse as a string packet.
    Returns (str, [int16 values]) or None if the packet isn't string-shaped.
    """
    if len(data) < 3:
        return None
    slen = struct.unpack_from(">H", data, 1)[0]
    if 3 + slen > len(data):
        return None
    try:
        s = data[3:3 + slen].decode("utf-8")
    except UnicodeDecodeError:
        return None
    rest = data[3 + slen:]
    n    = len(rest) // 2
    vals = list(struct.unpack_from(">" + "h" * n, rest)) if n else []
    return s, vals


# ── Human-readable opcode names (for sniff mode) ────────────────────────────

SERVER_NAMES = {v: k for k, v in vars(S).items() if not k.startswith("_")}
CLIENT_NAMES = {v: k for k, v in vars(C).items() if not k.startswith("_")}
