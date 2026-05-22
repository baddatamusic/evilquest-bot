"""
EvilQuest binary WebSocket protocol — logical opcodes (v2).

All opcodes here are *logical* values that match the JS enum constants.
The transport layer translates them to/from per-session *wire* opcodes via the
OPCODE_MAPPING packet received after the CRYPTO_CHALLENGE handshake.

Packet format (binary):  [opcode: uint8][val0: int16 BE][val1: int16 BE]...
Packet format (string):  [opcode: uint8][str_len: uint16 BE][str UTF-8][int16 BE...]
"""

import struct


# ── Client → Server opcodes ───────────────────────────────────────────────────

class C:
    LOGIN                = 1    # not in opcode map; handled by transport
    CRYPTO_RESPONSE      = 2    # not in opcode map; handled by transport
    PLAYER_MOVE          = 10
    PLAYER_ATTACK_NPC    = 20
    PLAYER_TALK_NPC      = 21
    DIALOGUE_CHOOSE      = 22
    PLAYER_FOLLOW        = 23
    PLAYER_PICKUP_ITEM   = 30   # was PLAYER_PICKUP
    PLAYER_DROP_ITEM     = 31
    PLAYER_EQUIP_ITEM    = 32
    PLAYER_UNEQUIP_ITEM  = 33
    PLAYER_EAT_ITEM      = 34
    PLAYER_SET_STANCE    = 35
    PLAYER_BUY_ITEM      = 36
    PLAYER_SELL_ITEM     = 37
    PLAYER_MOVE_INV_ITEM = 38
    PLAYER_INTERACT_OBJECT   = 40
    PLAYER_USE_ITEM_ON_ITEM  = 41
    PLAYER_USE_ITEM_ON_OBJECT = 42
    PLAYER_USE_ITEM_ON_NPC   = 43
    PLAYER_CAST_SPELL    = 44
    PLAYER_SET_AUTOCAST  = 45
    MAP_READY            = 50
    SET_APPEARANCE       = 60
    CLIENT_FLOOR_HINT    = 70
    CLIENT_POSITION_Y    = 71
    BANK_REQUEST_OPEN    = 80
    BANK_DEPOSIT         = 81
    BANK_WITHDRAW        = 82
    BANK_CLOSE           = 83
    TRADE_REQUEST        = 90
    TRADE_ACCEPT_REQUEST = 91
    TRADE_DECLINE        = 92
    TRADE_OFFER_ITEM     = 93
    TRADE_REMOVE_OFFERED = 94
    TRADE_ACCEPT         = 95
    # DUEL opcodes 100-105 removed from game (duel system entirely removed)
    CLIENT_PING          = 120
    # CLIENT_ACTIVITY = 121  — removed from game client enum; do NOT send


# ── Server → Client opcodes ───────────────────────────────────────────────────

class S:
    LOGIN_OK               = 1
    CRYPTO_CHALLENGE       = 2   # not in opcode map; handled by transport
    OPCODE_MAPPING         = 3   # not in opcode map; handled by transport
    PLAYER_SYNC            = 10
    NPC_SYNC               = 11
    GROUND_ITEM_SYNC       = 12  # was OP_GROUND_ITEM
    PLAYER_STATS           = 21
    PLAYER_SKILLS          = 22
    PLAYER_EQUIPMENT       = 23
    PLAYER_INVENTORY_BATCH = 24
    PLAYER_SKILLS_BATCH    = 25
    PLAYER_EQUIPMENT_BATCH = 26
    COMBAT_HIT             = 30
    ENTITY_DEATH           = 31
    XP_GAIN                = 32
    LEVEL_UP               = 33
    COMBAT_PROJECTILE      = 34
    SPELL_CAST             = 35
    CHAT_SYSTEM            = 42
    SHOP_OPEN              = 50
    WORLD_OBJECT_SYNC      = 55  # was OP_OBJECT_SYNC
    WORLD_OBJECT_DEPLETED  = 56
    SKILLING_START         = 57
    SKILLING_STOP          = 58
    SMITHING_OPEN          = 59
    MAP_CHANGE             = 60
    FLOOR_CHANGE           = 61
    SHOW_CHARACTER_CREATOR = 70
    PLAYER_TELEPORT        = 71
    PLAYER_REMOTE_EQUIPMENT = 72
    NPC_APPEARANCE         = 73
    NPC_EQUIPMENT          = 74
    PLAYER_REMOTE_STANCE   = 75
    DIALOGUE_OPEN          = 76
    DIALOGUE_CLOSE         = 77
    NPC_INTERACTIONS       = 78
    PLAYER_ANIMATION       = 79
    BANK_OPEN              = 80
    BANK_UPDATE_SLOT       = 81
    BANK_CLOSE             = 82
    NPC_NAME               = 84
    NPC_FACING             = 85
    NPC_CUSTOM_COLORS      = 86
    NPC_ATTACK_ANIM        = 87
    RENOWN_SYNC            = 88
    TRADE_REQUEST_RECEIVED = 90
    TRADE_OPEN             = 91
    TRADE_OFFER_UPDATE     = 92
    TRADE_ACCEPT_STATE     = 93
    TRADE_CLOSE            = 94
    TRADE_TEST_OPEN        = 95
    # DUEL server opcodes 96-99, 101-103 removed (duel system entirely removed)
    PATH_TRUNCATED         = 100
    QUEST_STATE_SYNC       = 110
    QUEST_STAGE_ADVANCED   = 111
    ADMIN_FLAGS            = 120
    SERVER_PONG            = 121
    PLAYER_SELF_SYNC       = 122  # was OP_OWN_STATE


# ── Packet builders ───────────────────────────────────────────────────────────

def pack(opcode: int, *values: int) -> bytes:
    """Build a binary packet: uint8 opcode + int16[] values (big-endian)."""
    return struct.pack(">B" + "h" * len(values), opcode, *values)


def pack_str(opcode: int, s: str, *values: int) -> bytes:
    """Build a string packet: uint8 opcode + uint16 len + UTF-8 str + int16[] values."""
    enc = s.encode("utf-8")
    return struct.pack(f">BH{len(enc)}s" + "h" * len(values), opcode, len(enc), enc, *values)


# ── Packet parsers ────────────────────────────────────────────────────────────

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


# ── Human-readable opcode names (for sniff mode) ─────────────────────────────

SERVER_NAMES = {v: k for k, v in vars(S).items() if not k.startswith("_")}
CLIENT_NAMES = {v: k for k, v in vars(C).items() if not k.startswith("_")}
