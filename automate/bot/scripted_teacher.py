from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .world_model import WorldModel


WEAPON_PISTOL = 1
WEAPON_RIFLE = 2
WEAPON_SHOTGUN = 3

ENEMY_THREAT = {
    1: 1.0,  # grunt
    2: 1.8,  # runner
    3: 1.4,  # tank
    4: 2.3,  # kamikaze
    5: 3.0,  # boss
}


@dataclass
class Action:
    dx: float = 0.0
    dy: float = 0.0
    aim_angle: float = 0.0
    fire: bool = False
    weapon_id: int | None = None
    target_id: int | None = None


class ScriptedTeacher:
    def choose(self, world: WorldModel) -> Action:
        player = world.player
        if not player or not world.enemies:
            return Action()

        px = float(player.get("x", 640.0))
        py = float(player.get("y", 384.0))
        target = self.choose_target(world, px, py)
        if target is None:
            return Action()

        weapon = self.choose_weapon(world, target, px, py)
        aim = math.atan2(float(target["y"]) - py, float(target["x"]) - px)
        dx, dy = self.choose_movement(world, px, py, target)
        return Action(
            dx=dx,
            dy=dy,
            aim_angle=aim,
            fire=True,
            weapon_id=weapon,
            target_id=int(target["entity_id"]),
        )

    def choose_target(
        self, world: WorldModel, px: float, py: float
    ) -> dict[str, Any] | None:
        best_score = -1e9
        best = None
        for enemy in world.enemies.values():
            ex = float(enemy["x"])
            ey = float(enemy["y"])
            hp = max(1.0, float(enemy.get("hp", 1)))
            dist = math.hypot(ex - px, ey - py)
            etype = int(enemy.get("type", 1))
            threat = ENEMY_THREAT.get(etype, 1.0)
            cluster = self.cluster_score(world, ex, ey)
            score = threat * 120.0 + cluster * 35.0 - hp * 10.0 - dist * 0.04
            if dist < 120:
                score += 80.0
            if score > best_score:
                best_score = score
                best = enemy
        return best

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
        if current == WEAPON_SHOTGUN and ammo > 0 and (cluster >= 2 or hp >= 8):
            return WEAPON_SHOTGUN
        if current == WEAPON_RIFLE and ammo > 0:
            return WEAPON_RIFLE
        if dist < 260 and (cluster >= 2 or hp >= 8):
            return WEAPON_SHOTGUN
        return WEAPON_RIFLE if current == WEAPON_RIFLE and ammo > 0 else WEAPON_PISTOL

    def choose_movement(
        self, world: WorldModel, px: float, py: float, target: dict[str, Any]
    ) -> tuple[float, float]:
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
        if tdist > 430:
            vx += tx / tdist * 0.35
            vy += ty / tdist * 0.35

        mag = math.hypot(vx, vy)
        if mag < 1e-6:
            return 0.0, 0.0
        return vx / mag, vy / mag

    def cluster_score(self, world: WorldModel, x: float, y: float) -> int:
        score = 0
        for enemy in world.enemies.values():
            if math.hypot(float(enemy["x"]) - x, float(enemy["y"]) - y) <= 90:
                score += 1
        return score
