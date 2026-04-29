from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .room_geometry import RoomGeometry
from .world_model import WorldModel


WEAPON_PISTOL = 1
WEAPON_RIFLE = 2
WEAPON_SHOTGUN = 3
TILE_SIZE = 32.0
MIN_SHOOT_DISTANCE = TILE_SIZE * 5.0
EMERGENCY_SHOOT_DISTANCE = TILE_SIZE * 4.0
PREFERRED_FIRE_DISTANCE = 190.0
MAX_SHOOT_DISTANCE = 420.0
PROJECTILE_SPEED = 600.0
SHOTGUN_EFFECTIVE_RANGE = 210.0
LONG_WEAPON_EFFECTIVE_RANGE = 900.0

ENEMY_THREAT = {
    1: 1.0,  # grunt
    2: 1.8,  # runner
    3: 1.4,  # tank
    4: 2.3,  # kamikaze
    5: 3.0,  # boss
}

CANDIDATE_DIRS = [
    (1.0, 0.0),
    (-1.0, 0.0),
    (0.0, 1.0),
    (0.0, -1.0),
    (0.707, 0.707),
    (0.707, -0.707),
    (-0.707, 0.707),
    (-0.707, -0.707),
    (0.0, 0.0),
]

REPOSITION_LOOKAHEADS = (48.0, 96.0, 160.0, 224.0, 288.0)


@dataclass
class Action:
    dx: float = 0.0
    dy: float = 0.0
    aim_angle: float = 0.0
    fire: bool = False
    weapon_id: int | None = None
    target_id: int | None = None
    los_clear: bool = False
    range_ok: bool = False
    distance_to_target: float = 0.0
    reason: str = ""


class ScriptedTeacher:
    def __init__(self, repo_root: Path | None = None):
        if repo_root is None:
            repo_root = Path(__file__).resolve().parents[2]
        self.geometry = RoomGeometry(repo_root)
        self.blocked_target_id: int | None = None
        self.blocked_target_ticks = 0

    def choose(self, world: WorldModel) -> Action:
        player = world.player
        if not player or not world.enemies:
            return Action()

        px = float(player.get("x", 640.0))
        py = float(player.get("y", 384.0))
        target, los_clear = self.choose_target(world, px, py)
        if target is None:
            return Action()

        target_dist = distance(px, py, float(target["x"]), float(target["y"]))
        weapon = self.choose_weapon(world, target, px, py) if los_clear else None
        max_range = min(weapon_effective_range(weapon), MAX_SHOOT_DISTANCE)
        range_ok = MIN_SHOOT_DISTANCE <= target_dist <= max_range
        emergency_close = los_clear and target_dist <= EMERGENCY_SHOOT_DISTANCE
        aim = self.predictive_aim(world, px, py, target)
        dx, dy = self.choose_movement(world, px, py, target, los_clear, range_ok)
        if not los_clear:
            reason = "reposition_for_los"
        elif emergency_close:
            reason = "emergency_close_threat"
        elif target_dist < MIN_SHOOT_DISTANCE:
            reason = "back_up_to_5_steps"
        elif target_dist > max_range:
            reason = "close_distance"
        else:
            reason = "visible_target"
        return Action(
            dx=dx,
            dy=dy,
            aim_angle=aim,
            fire=los_clear and (range_ok or emergency_close),
            weapon_id=weapon,
            target_id=int(target["entity_id"]),
            los_clear=los_clear,
            range_ok=range_ok or emergency_close,
            distance_to_target=target_dist,
            reason=reason,
        )

    def choose_target(
        self, world: WorldModel, px: float, py: float
    ) -> tuple[dict[str, Any] | None, bool]:
        room = self.geometry.load_room(int(world.current_room or 1))
        enemies = list(world.enemies.values())
        if not enemies:
            return None, False

        nearest_dist = min(
            distance(px, py, float(enemy["x"]), float(enemy["y"]))
            for enemy in enemies
        )
        nearest_band = [
            enemy
            for enemy in enemies
            if distance(px, py, float(enemy["x"]), float(enemy["y"])) <= nearest_dist + TILE_SIZE
        ]
        target = min(
            nearest_band,
            key=lambda enemy: (
                int(enemy.get("hp", 1) or 1),
                distance(px, py, float(enemy["x"]), float(enemy["y"])),
                int(enemy.get("entity_id", 0) or 0),
            ),
        )
        los_clear = room.line_of_fire_clear(px, py, float(target["x"]), float(target["y"]))
        return target, los_clear

    def target_score(self, world: WorldModel, px: float, py: float, enemy: dict[str, Any]) -> float:
        ex = float(enemy["x"])
        ey = float(enemy["y"])
        dist = distance(px, py, ex, ey)
        enemy_type = int(enemy.get("type", 1) or 1)
        hp = max(1, int(enemy.get("hp", 1) or 1))
        cluster = self.cluster_score(world, ex, ey)
        return ENEMY_THREAT.get(enemy_type, 1.0) * 120.0 + cluster * 35.0 - dist * 0.35 - hp * 0.5

    def choose_weapon(
        self, world: WorldModel, target: dict[str, Any], px: float, py: float
    ) -> int:
        current = int(world.player.get("weapon_id", WEAPON_PISTOL))
        ammo = int(world.player.get("ammo", 0))
        dist = math.hypot(float(target["x"]) - px, float(target["y"]) - py)
        cluster = self.cluster_score(world, float(target["x"]), float(target["y"]))
        hp = int(target.get("hp", 1))

        # State packets only expose ammo for the current weapon. Use conservative
        # switching unless the current weapon is known to be loaded.
        if current == WEAPON_SHOTGUN and ammo > 0 and dist <= SHOTGUN_EFFECTIVE_RANGE and (cluster >= 2 or hp >= 8):
            return WEAPON_SHOTGUN
        if current == WEAPON_RIFLE and ammo > 0:
            return WEAPON_RIFLE
        return WEAPON_PISTOL

    def choose_movement(
        self,
        world: WorldModel,
        px: float,
        py: float,
        target: dict[str, Any],
        los_clear: bool,
        range_ok: bool,
    ) -> tuple[float, float]:
        if not los_clear:
            return self.reposition_for_los(world, px, py, target)

        tx = float(target["x"]) - px
        ty = float(target["y"]) - py
        tdist = max(1.0, math.hypot(tx, ty))
        if tdist < MIN_SHOOT_DISTANCE:
            return self.escape_close_threats(world, px, py, target)

        vx = 0.0
        vy = 0.0
        for enemy in world.enemies.values():
            ex = float(enemy["x"])
            ey = float(enemy["y"])
            dx = px - ex
            dy = py - ey
            dist = max(1.0, math.hypot(dx, dy))
            if dist < 220:
                weight = (220.0 - dist) / 220.0
                vx += dx / dist * weight
                vy += dy / dist * weight

        # Keep pressure on the target without breaking the five-step spacing.
        if tdist > PREFERRED_FIRE_DISTANCE + 35.0:
            vx += tx / tdist * 0.7
            vy += ty / tdist * 0.7
        elif not range_ok:
            vx += tx / tdist * 0.7
            vy += ty / tdist * 0.7

        door = self.known_door_point(world)
        if door is not None and tdist >= MIN_SHOOT_DISTANCE:
            ddx = door[0] - px
            ddy = door[1] - py
            dmag = math.hypot(ddx, ddy)
            if dmag > 1e-6:
                vx += ddx / dmag * 0.25
                vy += ddy / dmag * 0.25

        mag = math.hypot(vx, vy)
        if mag < 1e-6:
            return 0.0, 0.0
        return vx / mag, vy / mag

    def reposition_for_los(
        self, world: WorldModel, px: float, py: float, target: dict[str, Any]
    ) -> tuple[float, float]:
        room = self.geometry.load_room(int(world.current_room or 1))
        tx = float(target["x"])
        ty = float(target["y"])
        target_id = int(target.get("entity_id", 0) or 0)
        if target_id == self.blocked_target_id:
            self.blocked_target_ticks += 1
        else:
            self.blocked_target_id = target_id
            self.blocked_target_ticks = 1

        if self.blocked_target_ticks >= 12:
            routed_to_target = room.direction_to_reachable_near_point(
                px,
                py,
                tx,
                ty,
                PREFERRED_FIRE_DISTANCE,
            )
            if routed_to_target is not None:
                return normalize_pair(*routed_to_target)

        route_dir = room.direction_to_line_of_fire(px, py, tx, ty)
        if route_dir is not None:
            return normalize_pair(*route_dir)

        routed_to_target = room.direction_to_reachable_near_point(
            px,
            py,
            tx,
            ty,
            PREFERRED_FIRE_DISTANCE,
        )
        if routed_to_target is not None:
            return normalize_pair(*routed_to_target)

        best = (0.0, 0.0)
        best_score = float("-inf")

        for dx, dy in CANDIDATE_DIRS:
            if dx == 0.0 and dy == 0.0:
                continue

            first_x = px + dx * 24.0
            first_y = py + dy * 24.0
            if room.blocked_aabb(first_x, first_y):
                continue

            score = float("-inf")
            for lookahead in REPOSITION_LOOKAHEADS:
                test_x = px + dx * lookahead
                test_y = py + dy * lookahead
                if room.blocked_aabb(test_x, test_y):
                    continue

                dist_to_target = distance(test_x, test_y, tx, ty)
                candidate_score = 25.0 - abs(dist_to_target - PREFERRED_FIRE_DISTANCE) * 0.35
                if room.line_of_fire_clear(test_x, test_y, tx, ty):
                    candidate_score += 2000.0
                    candidate_score -= abs(dist_to_target - PREFERRED_FIRE_DISTANCE) * 0.8
                candidate_score -= self.wall_pressure(room, test_x, test_y) * 80.0

                for enemy in world.enemies.values():
                    ex = float(enemy["x"])
                    ey = float(enemy["y"])
                    d = distance(test_x, test_y, ex, ey)
                    if d < 140.0:
                        candidate_score -= (140.0 - d) * 5.0

                if candidate_score > score:
                    score = candidate_score

            if score == float("-inf"):
                # The next small step is legal even if all longer probes hit
                # walls. Keep moving instead of freezing in a blocked lane.
                score = 1.0 - distance(first_x, first_y, tx, ty) * 0.1

            if score > best_score:
                best_score = score
                best = (dx, dy)

        return best

    def escape_close_threats(
        self, world: WorldModel, px: float, py: float, target: dict[str, Any]
    ) -> tuple[float, float]:
        room = self.geometry.load_room(int(world.current_room or 1))
        tx = float(target["x"])
        ty = float(target["y"])
        routed = self.route_to_safe_firing_position(world, room, px, py, tx, ty)
        if routed is not None:
            return routed

        away_x = px - tx
        away_y = py - ty
        away_mag = max(1.0, math.hypot(away_x, away_y))
        preferred = (away_x / away_mag, away_y / away_mag)
        candidates = [preferred, *CANDIDATE_DIRS]
        best = preferred
        best_score = float("-inf")

        for dx, dy in candidates:
            mag = math.hypot(dx, dy)
            if mag < 1e-6:
                continue
            dx /= mag
            dy /= mag
            first_x = px + dx * 20.0
            first_y = py + dy * 20.0
            if room.blocked_aabb(first_x, first_y):
                continue

            score = 0.0
            for lookahead in (48.0, 96.0, 144.0):
                test_x = px + dx * lookahead
                test_y = py + dy * lookahead
                if room.blocked_aabb(test_x, test_y):
                    score -= 300.0
                    break

                target_dist = distance(test_x, test_y, tx, ty)
                score += min(target_dist, PREFERRED_FIRE_DISTANCE) * 1.2
                if room.line_of_fire_clear(test_x, test_y, tx, ty):
                    score += 40.0
                score -= self.wall_pressure(room, test_x, test_y) * 100.0

                nearest_enemy = min(
                    (
                        distance(test_x, test_y, float(e["x"]), float(e["y"]))
                        for e in world.enemies.values()
                    ),
                    default=999.0,
                )
                score += min(nearest_enemy, 260.0) * 1.6
                if nearest_enemy < 90.0:
                    score -= (90.0 - nearest_enemy) * 10.0

            alignment = dx * preferred[0] + dy * preferred[1]
            score += alignment * 80.0
            if score > best_score:
                best_score = score
                best = (dx, dy)

        return best

    def route_to_safe_firing_position(
        self,
        world: WorldModel,
        room: Any,
        px: float,
        py: float,
        tx: float,
        ty: float,
    ) -> tuple[float, float] | None:
        start = room._nearest_walkable_cell(px, py)
        if start is None:
            return None

        q = deque([start])
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        best: tuple[int, int] | None = None
        best_score = float("-inf")

        while q and len(parent) < 520:
            cell = q.popleft()
            cx, cy = room._cell_center(cell)
            target_dist = distance(cx, cy, tx, ty)
            nearest_enemy = min(
                (
                    distance(cx, cy, float(enemy["x"]), float(enemy["y"]))
                    for enemy in world.enemies.values()
                ),
                default=999.0,
            )

            score = 0.0
            if target_dist >= MIN_SHOOT_DISTANCE + 16.0:
                score += 2000.0
            else:
                score -= (MIN_SHOOT_DISTANCE + 16.0 - target_dist) * 20.0
            score -= abs(target_dist - PREFERRED_FIRE_DISTANCE) * 5.0
            score += min(nearest_enemy, 280.0) * 3.0
            if nearest_enemy < MIN_SHOOT_DISTANCE:
                score -= (MIN_SHOOT_DISTANCE - nearest_enemy) * 18.0
            if room.line_of_fire_clear(cx, cy, tx, ty):
                score += 700.0
            score -= self.wall_pressure(room, cx, cy) * 70.0

            door = self.known_door_point(world)
            if door is not None:
                score -= distance(cx, cy, door[0], door[1]) * 0.05

            if cell != start and score > best_score:
                best_score = score
                best = cell

            for nxt in room._neighbors(cell):
                if nxt in parent:
                    continue
                parent[nxt] = cell
                q.append(nxt)

        if best is None:
            return None

        step = best
        while parent.get(step) is not None and parent[step] != start:
            step = parent[step]  # type: ignore[assignment]

        sx, sy = room._cell_center(step)
        dx = sx - px
        dy = sy - py
        mag = math.hypot(dx, dy)
        if mag < 1e-6:
            return None
        return dx / mag, dy / mag

    def known_door_point(self, world: WorldModel) -> tuple[float, float] | None:
        if not world.doors:
            return None
        door = min(world.doors.values(), key=lambda d: int(d.get("door_id", 0) or 0))
        return float(door.get("x", 0.0) or 0.0), float(door.get("y", 0.0) or 0.0)

    def wall_pressure(self, room: Any, x: float, y: float) -> float:
        pressure = 0.0
        for radius, weight in ((24.0, 2.0), (48.0, 1.0), (72.0, 0.5)):
            blocked = 0
            for dx, dy in CANDIDATE_DIRS[:-1]:
                if room.blocked_aabb(x + dx * radius, y + dy * radius):
                    blocked += 1
            pressure += blocked * weight
        return pressure

    def predictive_aim(
        self, world: WorldModel, px: float, py: float, target: dict[str, Any]
    ) -> float:
        entity_id = int(target.get("entity_id", 0) or 0)
        tx = float(target["x"])
        ty = float(target["y"])
        dist = distance(px, py, tx, ty)
        velocity = world.enemy_velocities.get(entity_id)
        if velocity is not None:
            travel_time = min(1.5, dist / PROJECTILE_SPEED)
            tx += velocity[0] * travel_time
            ty += velocity[1] * travel_time
        return math.atan2(ty - py, tx - px)

    def cluster_score(self, world: WorldModel, x: float, y: float) -> int:
        score = 0
        for enemy in world.enemies.values():
            if math.hypot(float(enemy["x"]) - x, float(enemy["y"]) - y) <= 90:
                score += 1
        return score


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)


def weapon_effective_range(weapon_id: int | None) -> float:
    if weapon_id == WEAPON_SHOTGUN:
        return SHOTGUN_EFFECTIVE_RANGE
    return LONG_WEAPON_EFFECTIVE_RANGE


def normalize_pair(dx: float, dy: float) -> tuple[float, float]:
    mag = math.hypot(dx, dy)
    if mag < 1e-6:
        return 0.0, 0.0
    return dx / mag, dy / mag
