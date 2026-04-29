from __future__ import annotations

import json
import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


TILE_SIZE = 32
GRID_COLS = 40
GRID_ROWS = 24
TILED_FLIP_MASK = 0x1FFFFFFF

CELL_EMPTY = 0
CELL_SOLID = 1
CELL_WATER = 2


class RoomGeometry:
    def __init__(self, repo_root: Path):
        self.repo_root = repo_root
        self._cache: dict[int, ParsedRoom] = {}

    def load_room(self, room_index: int) -> "ParsedRoom":
        if room_index not in self._cache:
            self._cache[room_index] = self._parse_room(room_index)
        return self._cache[room_index]

    def _parse_room(self, room_index: int) -> "ParsedRoom":
        path = self._room_path(room_index)
        raw = json.loads(path.read_text(encoding="utf-8"))
        water_gids = self._water_gids(raw)
        cells = [[CELL_EMPTY for _ in range(GRID_COLS)] for _ in range(GRID_ROWS)]

        for layer in raw.get("layers", []):
            if layer.get("type") != "tilelayer" or layer.get("name") != "Walls":
                continue
            if layer.get("width") != GRID_COLS or layer.get("height") != GRID_ROWS:
                break
            for index, raw_gid in enumerate(layer.get("data", [])):
                if not raw_gid:
                    continue
                gid = int(raw_gid) & TILED_FLIP_MASK
                row = index // GRID_COLS
                col = index % GRID_COLS
                cells[row][col] = CELL_WATER if gid in water_gids else CELL_SOLID
            break

        return ParsedRoom(cells=cells)

    def _room_path(self, room_index: int) -> Path:
        candidates = [
            self.repo_root / "server" / "internal" / "game" / "tilemaps" / f"room-{room_index}.json",
            self.repo_root / "client" / "public" / "assets" / "rooms" / f"room-{room_index}.json",
        ]
        for path in candidates:
            if path.exists():
                return path
        raise FileNotFoundError(f"room tilemap not found for room {room_index}")

    def _water_gids(self, tiled_map: dict[str, Any]) -> set[int]:
        out: set[int] = set()
        for tileset in tiled_map.get("tilesets", []):
            first_gid = int(tileset.get("firstgid") or 1)
            for tile in tileset.get("tiles", []):
                tile_id = int(tile.get("id") or 0)
                for prop in tile.get("properties", []):
                    if (
                        prop.get("name") == "water"
                        and prop.get("type") == "bool"
                        and bool(prop.get("value"))
                    ):
                        out.add(tile_id + first_gid)
                        break
        return out


@dataclass(frozen=True)
class ParsedRoom:
    cells: list[list[int]]

    def blocks_player_at(self, x: float, y: float) -> bool:
        return self._cell_at(x, y) != CELL_EMPTY

    def blocks_projectile_at(self, x: float, y: float) -> bool:
        return self._cell_at(x, y) == CELL_SOLID

    def blocked_aabb(self, x: float, y: float, hw: float = 10, hh: float = 10) -> bool:
        return (
            self.blocks_player_at(x - hw, y - hh)
            or self.blocks_player_at(x + hw, y - hh)
            or self.blocks_player_at(x - hw, y + hh)
            or self.blocks_player_at(x + hw, y + hh)
        )

    def line_of_fire_clear(self, ax: float, ay: float, bx: float, by: float) -> bool:
        dist = math.hypot(bx - ax, by - ay)
        steps = max(1, int(dist / 8.0))
        for i in range(1, steps + 1):
            t = i / steps
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            if self.blocks_projectile_at(x, y):
                return False
        return True

    def line_crosses_water(self, ax: float, ay: float, bx: float, by: float) -> bool:
        dist = math.hypot(bx - ax, by - ay)
        steps = max(1, int(dist / 8.0))
        for i in range(1, steps + 1):
            t = i / steps
            x = ax + (bx - ax) * t
            y = ay + (by - ay) * t
            if self._cell_at(x, y) == CELL_WATER:
                return True
        return False

    def direction_to_line_of_fire(
        self, ax: float, ay: float, bx: float, by: float
    ) -> tuple[float, float] | None:
        start = self._nearest_walkable_cell(ax, ay)
        if start is None:
            return None

        q = deque([start])
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        best: tuple[int, int] | None = None
        best_score = float("-inf")

        while q:
            cell = q.popleft()
            cx, cy = self._cell_center(cell)
            if self.line_of_fire_clear(cx, cy, bx, by):
                dist = math.hypot(bx - cx, by - cy)
                score = 1000.0 - abs(dist - 300.0)
                if score > best_score:
                    best_score = score
                    best = cell
                # Keep looking briefly for a better distance, but do not search
                # the whole room once we have a valid reachable firing tile.
                if len(parent) > 160:
                    break

            for nxt in self._neighbors(cell):
                if nxt in parent:
                    continue
                parent[nxt] = cell
                q.append(nxt)

        if best is None or best == start:
            return None

        step = best
        while parent.get(step) is not None and parent[step] != start:
            step = parent[step]  # type: ignore[assignment]

        sx, sy = self._cell_center(step)
        dx = sx - ax
        dy = sy - ay
        mag = math.hypot(dx, dy)
        if mag < 1e-6:
            return None
        return dx / mag, dy / mag

    def direction_to_point(
        self, ax: float, ay: float, bx: float, by: float
    ) -> tuple[float, float] | None:
        start = self._nearest_walkable_cell(ax, ay)
        goal = self._nearest_walkable_cell(bx, by)
        if start is None or goal is None:
            return None
        if start == goal:
            return None

        q = deque([start])
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        while q:
            cell = q.popleft()
            if cell == goal:
                break
            for nxt in self._neighbors(cell):
                if nxt in parent:
                    continue
                parent[nxt] = cell
                q.append(nxt)

        if goal not in parent:
            return None

        step = goal
        while parent.get(step) is not None and parent[step] != start:
            step = parent[step]  # type: ignore[assignment]

        sx, sy = self._cell_center(step)
        dx = sx - ax
        dy = sy - ay
        mag = math.hypot(dx, dy)
        if mag < 1e-6:
            return None
        return dx / mag, dy / mag

    def direction_to_reachable_near_point(
        self, ax: float, ay: float, bx: float, by: float, radius: float
    ) -> tuple[float, float] | None:
        start = self._nearest_walkable_cell(ax, ay)
        if start is None:
            return None

        q = deque([start])
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        best = start
        best_dist = float("inf")

        while q:
            cell = q.popleft()
            cx, cy = self._cell_center(cell)
            dist = math.hypot(bx - cx, by - cy)
            if dist < best_dist:
                best_dist = dist
                best = cell
            if dist <= radius:
                best = cell
                break

            for nxt in self._neighbors(cell):
                if nxt in parent:
                    continue
                parent[nxt] = cell
                q.append(nxt)

        if best == start:
            return None

        step = best
        while parent.get(step) is not None and parent[step] != start:
            step = parent[step]  # type: ignore[assignment]

        sx, sy = self._cell_center(step)
        dx = sx - ax
        dy = sy - ay
        mag = math.hypot(dx, dy)
        if mag < 1e-6:
            return None
        return dx / mag, dy / mag

    def path_cost(self, ax: float, ay: float, bx: float, by: float) -> float | None:
        start = self._nearest_walkable_cell(ax, ay)
        goal = self._nearest_walkable_cell(bx, by)
        if start is None or goal is None:
            return None
        if start == goal:
            return 0.0

        q = deque([start])
        dist: dict[tuple[int, int], float] = {start: 0.0}
        while q:
            cell = q.popleft()
            if cell == goal:
                return dist[cell] * TILE_SIZE

            for nxt in self._neighbors(cell):
                if nxt in dist:
                    continue
                step = 1.41421356237 if nxt[0] != cell[0] and nxt[1] != cell[1] else 1.0
                dist[nxt] = dist[cell] + step
                q.append(nxt)

        return None

    def _cell_at(self, x: float, y: float) -> int:
        col = int(x / TILE_SIZE)
        row = int(y / TILE_SIZE)
        if col < 0 or col >= GRID_COLS or row < 0 or row >= GRID_ROWS:
            return CELL_SOLID
        return self.cells[row][col]

    def _cell_center(self, cell: tuple[int, int]) -> tuple[float, float]:
        col, row = cell
        return col * TILE_SIZE + TILE_SIZE / 2, row * TILE_SIZE + TILE_SIZE / 2

    def _walkable_cell(self, cell: tuple[int, int]) -> bool:
        col, row = cell
        if col < 0 or col >= GRID_COLS or row < 0 or row >= GRID_ROWS:
            return False
        x, y = self._cell_center(cell)
        return not self.blocked_aabb(x, y)

    def _nearest_walkable_cell(self, x: float, y: float) -> tuple[int, int] | None:
        start = (int(x / TILE_SIZE), int(y / TILE_SIZE))
        if self._walkable_cell(start):
            return start
        q = deque([start])
        seen = {start}
        while q:
            cell = q.popleft()
            for nxt in self._neighbor_cells(cell):
                if nxt in seen:
                    continue
                seen.add(nxt)
                if self._walkable_cell(nxt):
                    return nxt
                q.append(nxt)
        return None

    def _neighbors(self, cell: tuple[int, int]) -> list[tuple[int, int]]:
        out: list[tuple[int, int]] = []
        for nxt in self._neighbor_cells(cell):
            if not self._walkable_cell(nxt):
                continue
            dc = nxt[0] - cell[0]
            dr = nxt[1] - cell[1]
            if dc and dr:
                if not self._walkable_cell((cell[0] + dc, cell[1])):
                    continue
                if not self._walkable_cell((cell[0], cell[1] + dr)):
                    continue
            out.append(nxt)
        return out

    def escape_space(self, cell: tuple[int, int]) -> int:
        return sum(1 for nxt in self._neighbors(cell) if self._walkable_cell(nxt))

    def _neighbor_cells(self, cell: tuple[int, int]) -> list[tuple[int, int]]:
        col, row = cell
        return [
            (col + 1, row),
            (col - 1, row),
            (col, row + 1),
            (col, row - 1),
            (col + 1, row + 1),
            (col + 1, row - 1),
            (col - 1, row + 1),
            (col - 1, row - 1),
        ]
