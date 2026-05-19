"""
A* pathfinder for EvilQuest map navigation.

Wall bitmask (per tile): N=1, E=2, S=4, W=8
Wall data: fetched from /maps/kcmap/walls.json as {"x,z": bitmask, ...}

Coordinate systems:
  - x10 coords: what OP_OWN_STATE and PLAYER_MOVE packets use (e.g. 1265, 1765)
  - tile coords: x10 // 10  (e.g. 126, 176)
  - tile center x10: tile * 10 + 5  (e.g. 1265, 1765)
"""

import heapq
import json
import urllib.request
from functools import lru_cache

MAP_ID   = "kcmap"
MAP_W    = 320
MAP_H    = 256

# Wall direction bitmasks
W_N = 1   # north wall on this tile (blocks moving to tile z-1)
W_E = 2   # east wall  (blocks moving to tile x+1)
W_S = 4   # south wall (blocks moving to tile z+1)
W_W = 8   # west wall  (blocks moving to tile x-1)

_walls: dict[tuple[int,int], int] = {}
_loaded = False


def load_walls(walls_json_path: str | None = None):
    """Load wall data from a local file or fetch from the server."""
    global _walls, _loaded
    if _loaded:
        return

    if walls_json_path:
        with open(walls_json_path, encoding="utf-8") as f:
            raw = json.load(f)
    else:
        url = f"https://evilquest.net/maps/{MAP_ID}/walls.json"
        with urllib.request.urlopen(url, timeout=10) as r:
            raw = json.loads(r.read())

    _walls.clear()
    for key, bitmask in raw["walls"].items():
        x_str, z_str = key.split(",")
        _walls[(int(x_str), int(z_str))] = bitmask

    _loaded = True


def _wall_at(tx: int, tz: int) -> int:
    return _walls.get((tx, tz), 0)


def _is_wall_blocked(fx: int, fz: int, tx: int, tz: int) -> bool:
    """Return True if moving from tile (fx,fz) to adjacent tile (tx,tz) is wall-blocked."""
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
_DIRS = [(0,-1),(1,0),(0,1),(-1,0),(1,-1),(1,1),(-1,1),(-1,-1)]
# Diagonal cost slightly higher so cardinal is preferred over diagonal
_COSTS = [1,1,1,1,2,2,2,2]


def _is_tile_fully_walled(tx: int, tz: int) -> bool:
    """True if a tile is completely surrounded by walls (e.g. an object/tree tile)."""
    w = _wall_at(tx, tz)
    return w == (W_N | W_E | W_S | W_W)


def _nearest_walkable_adjacent(gx: int, gz: int) -> tuple[int, int] | None:
    """Find the nearest walkable tile adjacent to a blocked destination tile."""
    for dx, dz in [(0,-1),(1,0),(0,1),(-1,0),(1,-1),(1,1),(-1,1),(-1,-1)]:
        nx, nz = gx + dx, gz + dz
        if _in_bounds(nx, nz) and not _is_wall_blocked(gx, gz, nx, nz):
            return nx, nz
    return None


def find_path(start_x10: int, start_z10: int,
              dest_x10: int, dest_z10: int,
              max_steps: int = 500) -> list[tuple[int, int]]:
    """
    A* pathfinding from start to dest.
    Coordinates are x10 (as used in OP_OWN_STATE / PLAYER_MOVE packets).
    If the destination tile is a blocked object tile (e.g. a tree), automatically
    paths to the nearest walkable adjacent tile instead.
    Returns list of (x10, z10) waypoints (NOT including start), or [] if unreachable.
    """
    if not _loaded:
        load_walls()

    sx, sz = start_x10 // 10, start_z10 // 10
    gx, gz = dest_x10 // 10,  dest_z10 // 10

    # If destination is a fully-walled tile, redirect to nearest adjacent tile
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
            if _is_wall_blocked(cx, cz, nx, nz):
                continue
            ng = g + cost
            if ng < g_score.get((nx, nz), 10**9):
                g_score[(nx, nz)] = ng
                came_from[(nx, nz)] = (cx, cz)
                heapq.heappush(open_heap, (ng + h(nx, nz), ng, nx, nz))

    return []  # no path found
