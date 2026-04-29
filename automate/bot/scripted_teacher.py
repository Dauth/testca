from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .room_geometry import RoomGeometry
from .world_model import WorldModel


WEAPON_PISTOL = 1
WEAPON_RIFLE = 2
WEAPON_SHOTGUN = 3
PREFERRED_FIRE_DISTANCE = 160.0
MIN_SAFE_DISTANCE = 115.0

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
    reason: str = ""


class ScriptedTeacher:
    def __init__(self, repo_root: Path | None = None):
        if repo_root is None:
            repo_root = Path(__file__).resolve().parents[2]
        self.geometry = RoomGeometry(repo_root)

    def choose(self, world: WorldModel) -> Action:
        player = world.player
        if not player or not world.enemies:
            return Action()

        px = float(player.get("x", 640.0))
        py = float(player.get("y", 384.0))
        target, los_clear = self.choose_target(world, px, py)
        if target is None:
            return Action()

        weapon = self.choose_weapon(world, target, px, py) if los_clear else None
        aim = math.atan2(float(target["y"]) - py, float(target["x"]) - px)
        dx, dy = self.choose_movement(world, px, py, target, los_clear)
        return Action(
            dx=dx,
            dy=dy,
            aim_angle=aim,
            fire=los_clear,
            weapon_id=weapon,
            target_id=int(target["entity_id"]),
            los_clear=los_clear,
            reason="visible_target" if los_clear else "reposition_for_los",
        )

    def choose_target(
        self, world: WorldModel, px: float, py: float
    ) -> tuple[dict[str, Any] | None, bool]:
        room = self.geometry.load_room(int(world.current_room or 1))
        visible: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []

        for enemy in world.enemies.values():
            ex = float(enemy["x"])
            ey = float(enemy["y"])
            if room.line_of_fire_clear(px, py, ex, ey):
                visible.append(enemy)
            else:
                blocked.append(enemy)

        if visible:
            return max(visible, key=lambda e: self.target_score(world, px, py, e)), True
        if blocked:
            return min(blocked, key=lambda e: distance(px, py, float(e["x"]), float(e["y"]))), False
        return None, False

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
        if current == WEAPON_SHOTGUN and ammo > 0 and dist < 280 and (cluster >= 2 or hp >= 8):
            return WEAPON_SHOTGUN
        if current == WEAPON_RIFLE and ammo > 0:
            return WEAPON_RIFLE
        if dist < 220 and (cluster >= 3 or hp >= 10):
            return WEAPON_SHOTGUN
        return WEAPON_PISTOL

    def choose_movement(
        self, world: WorldModel, px: float, py: float, target: dict[str, Any], los_clear: bool
    ) -> tuple[float, float]:
        if not los_clear:
            return self.reposition_for_los(world, px, py, target)

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

        # Keep pressure on the target without walking into melee range.
        tx = float(target["x"]) - px
        ty = float(target["y"]) - py
        tdist = max(1.0, math.hypot(tx, ty))
        if tdist > PREFERRED_FIRE_DISTANCE + 35.0:
            vx += tx / tdist * 0.7
            vy += ty / tdist * 0.7
        elif tdist < MIN_SAFE_DISTANCE:
            vx -= tx / tdist * 0.8
            vy -= ty / tdist * 0.8

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
        route_dir = room.direction_to_line_of_fire(px, py, tx, ty)
        if route_dir is not None:
            return route_dir

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

    def cluster_score(self, world: WorldModel, x: float, y: float) -> int:
        score = 0
        for enemy in world.enemies.values():
            if math.hypot(float(enemy["x"]) - x, float(enemy["y"]) - y) <= 90:
                score += 1
        return score


def distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(bx - ax, by - ay)
