"""
A* pathfinder for EvilQuest map navigation.

Wall bitmask (per tile): N=1, E=2, S=4, W=8
Wall data: fetched from /maps/kcmap/walls.json as {"x,z": bitmask, ...}

Tile blocking: fetched from /maps/kcmap/tiles/chunk_CX_CZ.json
  Keys are "row,col" (local z, local x within 64x64 chunk).
  Tiles with waterSurface or waterPainted properties are impassable.

Coordinate systems:
  - x10 coords: what OP_OWN_STATE and PLAYER_MOVE packets use (e.g. 1265, 1765)
  - tile coords: x10 // 10  (e.g. 126, 176)
  - tile center x10: tile * 10 + 5  (e.g. 1265, 1765)
"""

import heapq
import json
import logging
import urllib.request
from pathlib import Path

_log = logging.getLogger("pathfinder")

MAP_ID     = "kcmap"
MAP_W      = 320
MAP_H      = 256
CHUNK_SIZE = 64

_GAMEASSETS  = Path(__file__).parent / "gameassets" / "maps" / MAP_ID
_WALLS_PATH  = _GAMEASSETS / "walls.json"
_TILES_DIR   = _GAMEASSETS / "tiles"
_HEIGHTS_DIR = _GAMEASSETS / "heights"

# Wall direction bitmasks
W_N = 1   # north wall on this tile (blocks moving to tile z-1)
W_E = 2   # east wall  (blocks moving to tile x+1)
W_S = 4   # south wall (blocks moving to tile z+1)
W_W = 8   # west wall  (blocks moving to tile x-1)

# Height difference (game units) above which an edge between two adjacent
# tiles is considered a cliff and treated as impassable.  Empirical testing
# against 233 known blocked tiles matched 78 % at 0.75 and 55 % at 1.0,
# so 0.75 is the sweet spot; use a slightly tighter 0.7 to recover a few
# more cliff edges.  Dynamic PATH_TRUNCATED learning catches any misses.
HEIGHT_CLIFF_THRESHOLD = 0.7

_walls: dict[tuple[int,int], int] = {}
_loaded = False

_blocked_tiles: set[tuple[int,int]] = set()
_tiles_loaded = False
_dynamic_blocked: set[tuple[int,int]] = set()

_heights: dict[tuple[int, int], float] = {}
_heights_loaded = False

_WATER_PROPS = {"waterSurface", "waterPainted"}

_EVILQUEST_DIR = Path.home() / ".evilquest"
_BLOCKS_FILE   = _EVILQUEST_DIR / "dynamic_blocks.json"


def load_walls(walls_json_path: str | None = None):
    """Load wall data from the local gameassets file (or an explicit path)."""
    global _walls, _loaded
    if _loaded:
        return

    path = walls_json_path or str(_WALLS_PATH)
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)

    _walls.clear()
    for key, bitmask in raw["walls"].items():
        x_str, z_str = key.split(",")
        _walls[(int(x_str), int(z_str))] = bitmask

    _loaded = True


def _load_chunk(cx: int, cz: int) -> set[tuple[int,int]]:
    """Load one tile chunk from local gameassets and return blocked (water) tile coords."""
    blocked: set[tuple[int,int]] = set()
    path = _TILES_DIR / f"chunk_{cx}_{cz}.json"
    if not path.exists():
        return blocked
    try:
        with open(path) as f:
            data = json.load(f)
        base_x = cx * CHUNK_SIZE
        base_z = cz * CHUNK_SIZE
        for key, props in data.items():
            row_str, col_str = key.split(",")
            local_z, local_x = int(row_str), int(col_str)
            if any(k in _WATER_PROPS for k in props):
                blocked.add((base_x + local_x, base_z + local_z))
    except Exception:
        pass
    return blocked


def load_tiles():
    """Load all local tile chunks and populate the blocked-tile set."""
    global _blocked_tiles, _tiles_loaded
    if _tiles_loaded:
        return

    num_cx = (MAP_W + CHUNK_SIZE - 1) // CHUNK_SIZE  # 5
    num_cz = (MAP_H + CHUNK_SIZE - 1) // CHUNK_SIZE  # 4

    _blocked_tiles.clear()
    for cx in range(num_cx):
        for cz in range(num_cz):
            _blocked_tiles.update(_load_chunk(cx, cz))

    _tiles_loaded = True


def load_heights() -> None:
    """Load per-tile height data from local gameassets height chunks.

    Heights are stored as sparse JSON: {"row,col": float, ...} where
    row = local_z and col = local_x within a 64×64 chunk.  Tiles absent
    from the file are treated as height 0.0 (flat ground).

    Once loaded, _is_wall_blocked() uses HEIGHT_CLIFF_THRESHOLD to reject
    moves across edges where the height difference is too large — this
    pre-blocks cliff tiles without relying solely on PATH_TRUNCATED learning.
    """
    global _heights, _heights_loaded
    if _heights_loaded:
        return

    _heights.clear()
    chunk_files = sorted(_HEIGHTS_DIR.glob("chunk_*.json"))
    for path in chunk_files:
        parts = path.stem.split("_")   # ["chunk", cx, cz]
        if len(parts) != 3:
            continue
        cx, cz = int(parts[1]), int(parts[2])
        base_x = cx * CHUNK_SIZE
        base_z = cz * CHUNK_SIZE
        try:
            with open(path) as f:
                data = json.load(f)
            for key, h in data.items():
                row_str, col_str = key.split(",")
                local_z, local_x = int(row_str), int(col_str)
                _heights[(base_x + local_x, base_z + local_z)] = float(h)
        except Exception as exc:
            _log.warning(f"Could not load height file {path.name}: {exc}")

    _heights_loaded = True
    _log.info(
        f"Loaded height data: {len(_heights)} tiles from {len(chunk_files)} chunks "
        f"(cliff threshold: {HEIGHT_CLIFF_THRESHOLD} game units)"
    )


def _wall_at(tx: int, tz: int) -> int:
    return _walls.get((tx, tz), 0)


def _is_tile_blocked(tx: int, tz: int) -> bool:
    return (tx, tz) in _blocked_tiles or (tx, tz) in _dynamic_blocked


def load_dynamic_blocks() -> None:
    """Load previously persisted dynamic blocks from disk."""
    global _dynamic_blocked
    try:
        if _BLOCKS_FILE.exists():
            with open(_BLOCKS_FILE) as f:
                data = json.load(f)
            before = len(_dynamic_blocked)
            for item in data:
                _dynamic_blocked.add((int(item[0]), int(item[1])))
            added = len(_dynamic_blocked) - before
            if added:
                _log.info(f"Loaded {added} persisted dynamic blocks")
    except Exception as exc:
        _log.warning(f"Could not load dynamic blocks: {exc}")


def _save_dynamic_blocks() -> None:
    """Persist the current dynamic block set to disk (called after each new block)."""
    try:
        _EVILQUEST_DIR.mkdir(parents=True, exist_ok=True)
        with open(_BLOCKS_FILE, "w") as f:
            json.dump(sorted([tx, tz] for tx, tz in _dynamic_blocked), f)
    except Exception as exc:
        _log.warning(f"Could not save dynamic blocks: {exc}")


def add_dynamic_block(tx: int, tz: int) -> None:
    """Add a tile that the server has rejected at runtime (PATH_TRUNCATED feedback)."""
    if (tx, tz) not in _dynamic_blocked:
        _dynamic_blocked.add((tx, tz))
        _save_dynamic_blocks()


def _is_wall_blocked(fx: int, fz: int, tx: int, tz: int) -> bool:
    """Return True if moving from tile (fx,fz) to adjacent tile (tx,tz) is wall-blocked."""
    # Cliff check: large height difference between adjacent tiles → impassable.
    # Tiles absent from _heights default to 0.0 (flat terrain).
    if _heights_loaded:
        h_from = _heights.get((fx, fz), 0.0)
        h_to   = _heights.get((tx, tz), 0.0)
        if abs(h_from - h_to) > HEIGHT_CLIFF_THRESHOLD:
            return True

    dx, dz = tx - fx, tz - fz

    def has_wall(cx, cz, bit):
        return bool(_wall_at(cx, cz) & bit)

    if dx == 0 and dz == -1:   # north
        return has_wall(fx, fz, W_N) or has_wall(tx, tz, W_S)
    if dx == 1 and dz == 0:    # east
        return has_wall(fx, fz, W_E) or has_wall(tx, tz, W_W)
    if dx == 0 and dz == 1:    # south
        return has_wall(fx, fz, W_S) or has_wall(tx, tz, W_N)
    if dx == -1 and dz == 0:   # west
        return has_wall(fx, fz, W_W) or has_wall(tx, tz, W_E)
    # Diagonal: blocked if any cardinal edge on the corners is blocked
    if dx == 1 and dz == -1:
        return (has_wall(fx, fz, W_N) or has_wall(fx, fz, W_E) or
                has_wall(tx, tz, W_S) or has_wall(tx, tz, W_W) or
                has_wall(fx+1, fz, W_N) or has_wall(fx, fz-1, W_E))
    if dx == -1 and dz == -1:
        return (has_wall(fx, fz, W_N) or has_wall(fx, fz, W_W) or
                has_wall(tx, tz, W_S) or has_wall(tx, tz, W_E) or
                has_wall(fx-1, fz, W_N) or has_wall(fx, fz-1, W_W))
    if dx == 1 and dz == 1:
        return (has_wall(fx, fz, W_S) or has_wall(fx, fz, W_E) or
                has_wall(tx, tz, W_N) or has_wall(tx, tz, W_W) or
                has_wall(fx+1, fz, W_S) or has_wall(fx, fz+1, W_E))
    if dx == -1 and dz == 1:
        return (has_wall(fx, fz, W_S) or has_wall(fx, fz, W_W) or
                has_wall(tx, tz, W_N) or has_wall(tx, tz, W_E) or
                has_wall(fx-1, fz, W_S) or has_wall(fx, fz+1, W_W))
    return False


def _in_bounds(tx: int, tz: int) -> bool:
    return 0 <= tx < MAP_W and 0 <= tz < MAP_H


# 4-directional + diagonal neighbours
_DIRS  = [(0,-1),(1,0),(0,1),(-1,0),(1,-1),(1,1),(-1,1),(-1,-1)]
_COSTS = [1,1,1,1,2,2,2,2]


def _is_tile_fully_walled(tx: int, tz: int) -> bool:
    """True if a tile is impassable — fully walled object tile or a water tile."""
    if _is_tile_blocked(tx, tz):
        return True
    return _wall_at(tx, tz) == (W_N | W_E | W_S | W_W)


def _nearest_walkable_adjacent(gx: int, gz: int) -> tuple[int, int] | None:
    """Find the nearest walkable tile adjacent to a fully-walled destination.

    Only requires the neighbour itself to be walkable — we don't check the wall
    between gx/gz and the neighbour because the player only needs to STAND next
    to the object, not enter its tile.
    """
    for dx, dz in [(0,-1),(1,0),(0,1),(-1,0),(1,-1),(1,1),(-1,1),(-1,-1)]:
        nx, nz = gx + dx, gz + dz
        if _in_bounds(nx, nz) and not _is_tile_fully_walled(nx, nz):
            return nx, nz
    return None


def find_path(start_x10: int, start_z10: int,
              dest_x10: int, dest_z10: int,
              max_steps: int = 5000) -> list[tuple[int, int]]:
    """
    A* pathfinding from start to dest.
    Coordinates are x10 (as used in OP_OWN_STATE / PLAYER_MOVE packets).
    If the destination tile is a blocked object/water tile, automatically
    paths to the nearest walkable adjacent tile instead.
    Returns list of (x10, z10) waypoints (NOT including start), or [] if unreachable.
    """
    if not _loaded:
        load_walls()
    if not _heights_loaded:
        load_heights()

    sx, sz = start_x10 // 10, start_z10 // 10
    gx, gz = dest_x10 // 10,  dest_z10 // 10

    # If destination is impassable, redirect to nearest walkable adjacent tile
    if _is_tile_fully_walled(gx, gz):
        adj = _nearest_walkable_adjacent(gx, gz)
        if adj:
            gx, gz = adj

    if sx == gx and sz == gz:
        return []

    def h(x, z):
        return abs(x - gx) + abs(z - gz)

    open_heap: list[tuple[int,int,int,int]] = [(h(sx,sz), 0, sx, sz)]
    came_from: dict[tuple[int,int], tuple[int,int] | None] = {(sx,sz): None}
    g_score: dict[tuple[int,int], int] = {(sx,sz): 0}

    steps = 0
    while open_heap and steps < max_steps * 4:
        steps += 1
        f, g, cx, cz = heapq.heappop(open_heap)

        if cx == gx and cz == gz:
            path = []
            node: tuple[int,int] | None = (cx, cz)
            while node and came_from[node] is not None:
                path.append((node[0]*10+5, node[1]*10+5))
                node = came_from[node]
            path.reverse()
            return path

        for (dx, dz), cost in zip(_DIRS, _COSTS):
            nx, nz = cx + dx, cz + dz
            if not _in_bounds(nx, nz):
                continue
            if _is_tile_blocked(nx, nz):
                continue
            if _is_wall_blocked(cx, cz, nx, nz):
                continue
            # Diagonal: reject if either corner tile is blocked (would cross through water/terrain).
            # Skip this check when standing on a blocked tile (server-placed at spawn/respawn).
            if dx != 0 and dz != 0 and not _is_tile_blocked(cx, cz):
                if _is_tile_blocked(cx + dx, cz) or _is_tile_blocked(cx, cz + dz):
                    continue
            ng = g + cost
            if ng < g_score.get((nx, nz), 10**9):
                g_score[(nx, nz)] = ng
                came_from[(nx, nz)] = (cx, cz)
                heapq.heappush(open_heap, (ng + h(nx, nz), ng, nx, nz))

    return []  # no path found
