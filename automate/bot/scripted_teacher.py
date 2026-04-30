from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .room_plans import RoomPlan, get_room_plan
from .room_geometry import RoomGeometry
from .spawn_catalog import EXTRA_SPAWN_GROUPS, ROOM_SPAWNS, spawn_group, spawn_groups
from .world_model import WorldModel


WEAPON_PISTOL = 1
WEAPON_RIFLE = 2
WEAPON_SHOTGUN = 3
TILE_SIZE = 32.0
MIN_SHOOT_DISTANCE = TILE_SIZE * 5.0
EMERGENCY_SHOOT_DISTANCE = TILE_SIZE * 4.0
PREFERRED_FIRE_DISTANCE = 190.0
IDEAL_FIRE_MIN = 160.0
IDEAL_FIRE_MAX = 260.0
MAX_SHOOT_DISTANCE = 420.0
PROJECTILE_SPEED = 600.0
SHOTGUN_EFFECTIVE_RANGE = 210.0
LONG_WEAPON_EFFECTIVE_RANGE = 900.0
ROOM10_SHOTGUN_MIN = 150.0
ROOM10_SHOTGUN_MAX = 205.0
ROOM10_RIFLE_MIN = 240.0
ROOM10_RIFLE_MAX = 420.0
TARGET_SWITCH_ADVANTAGE = 64.0
DOOR_TARGET_SWITCH_ADVANTAGE = 96.0
RIVER_DOOR_CLOSE_DISTANCE = 520.0
GOAL_REACHED_DISTANCE = 24.0
GOAL_LOCK_TICKS = 18
STUCK_TICKS_FOR_REPLAN = 8
TRAPPED_WALL_PRESSURE = 10.0
TRAPPED_ESCAPE_SPACE = 2

ENEMY_THREAT = {
    1: 1.0,  # grunt
    2: 1.8,  # runner
    3: 1.4,  # tank
    4: 2.3,  # kamikaze
    5: 3.0,  # boss
}

SMALL_CAT_TYPES = {1, 2, 4}
FAST_CAT_TYPES = {2, 4}
BIG_CAT_TYPES = {3, 5}

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
        self.current_target_id: int | None = None
        self.route_target_id: int | None = None
        self.fire_target_id: int | None = None
        self.farthest_from_door_target_id: int | None = None
        self.current_goal_cell: tuple[int, int] | None = None
        self.goal_target_id: int | None = None
        self.goal_expires_at_tick = 0
        self.goal_reason = ""
        self.route_mode = ""
        self.macro_waypoint: tuple[int, int] | None = None
        self.wave_preposition_goal: tuple[float, float] | None = None
        self.failed_goal_cells: dict[int, set[tuple[int, int]]] = {}
        self.empty_weapons: set[int] = set()
        self.last_move: tuple[float, float] = (0.0, 0.0)
        self.last_position: tuple[float, float] | None = None
        self.stuck_ticks = 0
        self.tick = 0
        self.current_room: int | None = None

    def choose(self, world: WorldModel) -> Action:
        self.tick += 1
        if world.current_room != self.current_room:
            self.current_room = world.current_room
            self._clear_locks(clear_target=True)

        player = world.player
        if not player or not world.enemies:
            self._clear_locks(clear_target=True)
            return Action()

        px = float(player.get("x", 640.0))
        py = float(player.get("y", 384.0))
        self._update_stuck(px, py)
        route_target = self.choose_route_target(world, px, py)
        fire_target, fire_los_clear = self.choose_fire_target(world, px, py)
        if route_target is None and fire_target is None:
            self._clear_locks(clear_target=True)
            return Action()

        target = fire_target or route_target
        assert target is not None
        route_target = route_target or target
        self.current_target_id = self.route_target_id
        route_los_clear = self.geometry.load_room(int(world.current_room or 1)).line_of_fire_clear(
            px, py, float(route_target["x"]), float(route_target["y"])
        )
        if route_los_clear:
            self.blocked_target_id = None
            self.blocked_target_ticks = 0

        target_dist = distance(px, py, float(target["x"]), float(target["y"]))
        weapon = self.choose_weapon(world, target, px, py) if fire_los_clear else None
        max_range = weapon_effective_range(weapon)
        closer_tile_exists = False
        if route_los_clear and distance(px, py, float(route_target["x"]), float(route_target["y"])) > IDEAL_FIRE_MAX:
            closer_tile_exists = self.has_better_firing_tile(world, px, py, target, target_dist)
        river_door_shot = self.river_door_opportunity(world, px, py, target) if fire_los_clear else False
        range_ok = target_dist <= max_range or river_door_shot
        emergency_close = fire_los_clear and target_dist <= EMERGENCY_SHOOT_DISTANCE
        aim = self.predictive_aim(world, px, py, target)
        dx, dy = self.choose_movement(
            world,
            px,
            py,
            route_target,
            route_los_clear,
            range_ok,
            fire_target=fire_target,
        )
        if fire_target is None:
            reason = "reposition_for_los"
        elif emergency_close:
            reason = "emergency_close_threat"
        elif target_dist < MIN_SHOOT_DISTANCE:
            reason = "shoot_while_maintaining_spacing"
        elif river_door_shot:
            reason = "shoot_across_river_to_door"
        elif closer_tile_exists:
            reason = "shoot_while_moving_closer"
        elif target_dist > min(IDEAL_FIRE_MAX, max_range):
            reason = "close_distance"
        else:
            reason = "visible_target"
        self.last_move = (dx, dy)
        return Action(
            dx=dx,
            dy=dy,
            aim_angle=aim,
            fire=fire_los_clear and range_ok,
            weapon_id=weapon,
            target_id=int(target["entity_id"]),
            los_clear=fire_los_clear,
            range_ok=range_ok or emergency_close,
            distance_to_target=target_dist,
            reason=reason,
        )

    def choose_fire_target(
        self, world: WorldModel, px: float, py: float
    ) -> tuple[dict[str, Any] | None, bool]:
        room = self.geometry.load_room(int(world.current_room or 1))
        visible = [
            enemy
            for enemy in world.enemies.values()
            if room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
        ]
        if not visible:
            self.fire_target_id = None
            return None, False

        nearest = min(distance(px, py, float(e["x"]), float(e["y"])) for e in visible)
        nearest_band = [
            enemy
            for enemy in visible
            if distance(px, py, float(enemy["x"]), float(enemy["y"])) <= nearest + TILE_SIZE
        ]
        target = min(
            nearest_band,
            key=lambda enemy: (
                int(enemy.get("hp", 1) or 1),
                0 if int(enemy.get("type", 1) or 1) in FAST_CAT_TYPES else 1,
                distance(px, py, float(enemy["x"]), float(enemy["y"])),
                int(enemy.get("entity_id", 0) or 0),
            ),
        )
        self.fire_target_id = int(target["entity_id"])
        return target, True

    def choose_route_target(self, world: WorldModel, px: float, py: float) -> dict[str, Any] | None:
        room = self.geometry.load_room(int(world.current_room or 1))
        plan = get_room_plan(world.current_room)
        enemies = list(world.enemies.values())
        if not enemies:
            self.route_target_id = None
            return None
        self.route_mode = ""

        visible_close = [
            enemy
            for enemy in enemies
            if distance(px, py, float(enemy["x"]), float(enemy["y"])) <= EMERGENCY_SHOOT_DISTANCE
            and room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
        ]
        if visible_close:
            target = min(
                visible_close,
                key=lambda enemy: (
                    distance(px, py, float(enemy["x"]), float(enemy["y"])),
                    int(enemy.get("hp", 1) or 1),
                    int(enemy.get("entity_id", 0) or 0),
                ),
            )
            self.route_mode = "emergency"
            self.route_target_id = int(target["entity_id"])
            return target

        door = self.known_door_point(world)
        if door is not None and self.should_use_river_door_shortcut(world, px, py):
            self.route_mode = "river_door"
            return self.choose_fire_target(world, px, py)[0] or enemies[0]

        locked = world.enemies.get(self.route_target_id or -1)
        preferred_pool = self.room_plan_target_pool(world, room, plan, px, py, enemies)
        if door is not None and plan.clear_far_from_door_first and plan.route_farthest_from_door:
            preferred = max(
                preferred_pool,
                key=lambda enemy: (
                    distance(float(enemy["x"]), float(enemy["y"]), door[0], door[1]),
                    -distance(px, py, float(enemy["x"]), float(enemy["y"])),
                    -int(enemy.get("hp", 1) or 1),
                    -int(enemy.get("entity_id", 0) or 0),
                ),
            )
            self.farthest_from_door_target_id = int(preferred["entity_id"])
            if self.route_mode in ("", "visible_sweep", "combat"):
                self.route_mode = "farthest_from_door"
        else:
            preferred = min(
                preferred_pool,
                key=lambda enemy: (
                    distance(px, py, float(enemy["x"]), float(enemy["y"])),
                    int(enemy.get("hp", 1) or 1),
                    int(enemy.get("entity_id", 0) or 0),
                ),
            )
            self.farthest_from_door_target_id = None

        if locked is not None:
            preferred_dist = distance(px, py, float(preferred["x"]), float(preferred["y"]))
            locked_dist = distance(px, py, float(locked["x"]), float(locked["y"]))
            obstacle_priority = (
                plan.obstacle_targets_first
                and not room.line_of_fire_clear(px, py, float(preferred["x"]), float(preferred["y"]))
                and room.line_of_fire_clear(px, py, float(locked["x"]), float(locked["y"]))
                and int(preferred["entity_id"]) != self.route_target_id
            )
            door_advantage = False
            if door is not None and int(preferred["entity_id"]) != self.route_target_id:
                door_advantage = (
                    distance(float(preferred["x"]), float(preferred["y"]), door[0], door[1])
                    >= distance(float(locked["x"]), float(locked["y"]), door[0], door[1])
                    + DOOR_TARGET_SWITCH_ADVANTAGE
                )
            blocked_too_long = (
                self.blocked_target_id == self.route_target_id
                and self.blocked_target_ticks >= 45
                and int(preferred["entity_id"]) != self.route_target_id
            )
            if (
                preferred_dist > locked_dist - TARGET_SWITCH_ADVANTAGE
                and not obstacle_priority
                and not door_advantage
                and not blocked_too_long
            ):
                preferred = locked

        if self.route_mode == "":
            self.route_mode = "combat"
        self.route_target_id = int(preferred["entity_id"])
        return preferred

    def room_plan_target_pool(
        self,
        world: WorldModel,
        room: Any,
        plan: RoomPlan,
        px: float,
        py: float,
        enemies: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        visible_enemies = [
            enemy
            for enemy in enemies
            if room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
        ]
        room_id = int(world.current_room or 1)
        for group in plan.target_groups_order:
            group_enemies = [
                enemy for enemy in enemies if self.enemy_in_group(world, enemy, group)
            ]
            if group_enemies:
                self.route_mode = f"group_{group}"
                return group_enemies

        if plan.immediate_threat_spawn_groups:
            immediate = [
                enemy
                for enemy in enemies
                if self.enemy_in_any_group(world, enemy, plan.immediate_threat_spawn_groups)
            ]
            if immediate:
                visible_immediate = [
                    enemy
                    for enemy in immediate
                    if room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
                ]
                if visible_immediate:
                    self.route_mode = "spawn_visible_immediate_threat"
                    return visible_immediate
                if visible_enemies:
                    self.route_mode = "visible_sweep"
                    return visible_enemies
                non_boss = [
                    enemy
                    for enemy in immediate
                    if spawn_group(world.current_room, enemy) not in plan.boss_spawn_groups
                ]
                self.route_mode = "spawn_immediate_threat"
                return non_boss or immediate

        if plan.obstacle_spawn_groups:
            obstacle_group = [
                enemy
                for enemy in enemies
                if self.enemy_in_any_group(world, enemy, plan.obstacle_spawn_groups)
            ]
            blocked_obstacle_group = [
                enemy
                for enemy in obstacle_group
                if not room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
            ]
            if blocked_obstacle_group and (room_id == 5 or not visible_enemies):
                self.route_mode = "spawn_obstacle_first"
                return blocked_obstacle_group
            if (
                obstacle_group
                and (room_id == 5 or not visible_enemies)
                and not self.should_use_river_door_shortcut(world, px, py)
            ):
                self.route_mode = "spawn_obstacle_group"
                return obstacle_group

        if plan.flank_spawn_groups:
            flank_group = [
                enemy
                for enemy in enemies
                if self.enemy_in_any_group(world, enemy, plan.flank_spawn_groups)
            ]
            blocked_flank_group = [
                enemy
                for enemy in flank_group
                if not room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
            ]
            if blocked_flank_group and not visible_enemies:
                self.route_mode = "spawn_flank_required"
                return blocked_flank_group

        if visible_enemies:
            self.route_mode = "visible_sweep"
            return visible_enemies

        if plan.obstacle_targets_first:
            blocked = [
                enemy
                for enemy in enemies
                if not room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
            ]
            if blocked and not visible_enemies:
                self.route_mode = "obstacle_first"
                return blocked
        return enemies

    def choose_target(
        self, world: WorldModel, px: float, py: float
    ) -> tuple[dict[str, Any] | None, bool]:
        room = self.geometry.load_room(int(world.current_room or 1))
        enemies = list(world.enemies.values())
        if not enemies:
            return None, False

        closest = min(
            enemies,
            key=lambda enemy: distance(px, py, float(enemy["x"]), float(enemy["y"])),
        )
        closest_dist = distance(px, py, float(closest["x"]), float(closest["y"]))
        if closest_dist <= EMERGENCY_SHOOT_DISTANCE:
            preferred = closest
        else:
            door = self.known_door_point(world)
            if door is None:
                nearest_dist = min(
                    distance(px, py, float(enemy["x"]), float(enemy["y"]))
                    for enemy in enemies
                )
                nearest_band = [
                    enemy
                    for enemy in enemies
                    if distance(px, py, float(enemy["x"]), float(enemy["y"])) <= nearest_dist + TILE_SIZE
                ]
                preferred = min(
                    nearest_band,
                    key=lambda enemy: (
                        int(enemy.get("hp", 1) or 1),
                        distance(px, py, float(enemy["x"]), float(enemy["y"])),
                        int(enemy.get("entity_id", 0) or 0),
                    ),
                )
            else:
                solid_blocked = [
                    enemy
                    for enemy in enemies
                    if not room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
                ]
                river_door_targets = [
                    enemy
                    for enemy in enemies
                    if self.river_door_opportunity(world, px, py, enemy)
                ]
                visible_close_threat = any(
                    room.line_of_fire_clear(px, py, float(enemy["x"]), float(enemy["y"]))
                    and distance(px, py, float(enemy["x"]), float(enemy["y"])) <= MIN_SHOOT_DISTANCE
                    for enemy in enemies
                )
                if river_door_targets:
                    target_pool = river_door_targets
                elif solid_blocked and not visible_close_threat:
                    target_pool = solid_blocked
                else:
                    target_pool = enemies
                preferred = max(
                    target_pool,
                    key=lambda enemy: (
                        distance(float(enemy["x"]), float(enemy["y"]), door[0], door[1]),
                        -int(enemy.get("hp", 1) or 1),
                        -distance(px, py, float(enemy["x"]), float(enemy["y"])),
                        -int(enemy.get("entity_id", 0) or 0),
                    ),
                )
        target = preferred
        locked = world.enemies.get(self.current_target_id or -1)
        if locked is not None:
            locked_dist = distance(px, py, float(locked["x"]), float(locked["y"]))
            preferred_dist = distance(px, py, float(preferred["x"]), float(preferred["y"]))
            emergency = preferred_dist <= EMERGENCY_SHOOT_DISTANCE and int(preferred["entity_id"]) != self.current_target_id
            much_closer = preferred_dist <= locked_dist - TARGET_SWITCH_ADVANTAGE
            door = self.known_door_point(world)
            much_farther_from_door = False
            if door is not None and int(preferred["entity_id"]) != self.current_target_id:
                preferred_door_dist = distance(float(preferred["x"]), float(preferred["y"]), door[0], door[1])
                locked_door_dist = distance(float(locked["x"]), float(locked["y"]), door[0], door[1])
                much_farther_from_door = preferred_door_dist >= locked_door_dist + DOOR_TARGET_SWITCH_ADVANTAGE
            preferred_blocked = not room.line_of_fire_clear(
                px, py, float(preferred["x"]), float(preferred["y"])
            )
            locked_blocked = not room.line_of_fire_clear(
                px, py, float(locked["x"]), float(locked["y"])
            )
            solid_blocker_priority = (
                preferred_blocked
                and not locked_blocked
                and not self.river_door_opportunity(world, px, py, locked)
                and int(preferred["entity_id"]) != self.current_target_id
            )
            blocked_too_long = (
                self.blocked_target_id == self.current_target_id
                and self.blocked_target_ticks >= 35
                and int(preferred["entity_id"]) != self.current_target_id
            )
            if (
                not emergency
                and not much_closer
                and not much_farther_from_door
                and not solid_blocker_priority
                and not blocked_too_long
            ):
                target = locked
        self.current_target_id = int(target["entity_id"])
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
        if ammo <= 0:
            self.empty_weapons.add(current)
        dist = math.hypot(float(target["x"]) - px, float(target["y"]) - py)
        cluster = self.cluster_score(world, float(target["x"]), float(target["y"]))
        hp = int(target.get("hp", 1))
        enemy_type = int(target.get("type", 1) or 1)

        room_id = int(world.current_room or 1)

        # State packets only expose ammo for the current weapon. Treat weapons as
        # usable until a current-weapon state proves they are empty.
        if room_id == 10 and enemy_type in BIG_CAT_TYPES:
            if dist <= SHOTGUN_EFFECTIVE_RANGE:
                if current == WEAPON_SHOTGUN and ammo > 0:
                    return WEAPON_SHOTGUN
                if current != WEAPON_SHOTGUN and WEAPON_SHOTGUN not in self.empty_weapons:
                    return WEAPON_SHOTGUN
            if dist <= LONG_WEAPON_EFFECTIVE_RANGE:
                if current == WEAPON_RIFLE and ammo > 0:
                    return WEAPON_RIFLE
                if current != WEAPON_RIFLE and WEAPON_RIFLE not in self.empty_weapons:
                    return WEAPON_RIFLE

        if room_id == 10 and enemy_type in SMALL_CAT_TYPES:
            # Keep limited ammo for room-10 tanks/boss unless a fast threat is
            # close enough that survival matters more than conserving ammo.
            if dist < MIN_SHOOT_DISTANCE or cluster >= 3:
                if current == WEAPON_RIFLE and ammo > 0:
                    return WEAPON_RIFLE
                if current != WEAPON_RIFLE and WEAPON_RIFLE not in self.empty_weapons:
                    return WEAPON_RIFLE

        if enemy_type in BIG_CAT_TYPES and dist <= SHOTGUN_EFFECTIVE_RANGE:
            if current == WEAPON_SHOTGUN and ammo > 0:
                return WEAPON_SHOTGUN
            if current != WEAPON_SHOTGUN and WEAPON_SHOTGUN not in self.empty_weapons:
                return WEAPON_SHOTGUN
        if (
            room_id >= 5
            and dist <= LONG_WEAPON_EFFECTIVE_RANGE
            and (hp >= 3 or cluster >= 2 or enemy_type in FAST_CAT_TYPES)
        ):
            if current == WEAPON_RIFLE and ammo > 0:
                return WEAPON_RIFLE
            if current != WEAPON_RIFLE and WEAPON_RIFLE not in self.empty_weapons:
                return WEAPON_RIFLE
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
        fire_target: dict[str, Any] | None = None,
    ) -> tuple[float, float]:
        if fire_target is not None:
            fdist = distance(px, py, float(fire_target["x"]), float(fire_target["y"]))
            if fdist < MIN_SHOOT_DISTANCE:
                breakthrough = self.break_out_if_trapped(world, px, py)
                if breakthrough is not None:
                    return breakthrough
                return self.escape_close_threats(world, px, py, fire_target)

        if self.route_mode == "river_door" and self.should_use_river_door_shortcut(world, px, py):
            routed = self.route_to_door(world, px, py)
            if routed is not None:
                self.current_goal_cell = None
                return self.avoid_trap_move(world, px, py, routed[0], routed[1])

        if not los_clear:
            return self.reposition_for_los(world, px, py, target)

        tx = float(target["x"]) - px
        ty = float(target["y"]) - py
        tdist = max(1.0, math.hypot(tx, ty))
        nearest_enemy = min(
            world.enemies.values(),
            key=lambda enemy: distance(px, py, float(enemy["x"]), float(enemy["y"])),
        )
        nearest_enemy_dist = distance(
            px,
            py,
            float(nearest_enemy["x"]),
            float(nearest_enemy["y"]),
        )
        if nearest_enemy_dist <= EMERGENCY_SHOOT_DISTANCE * 0.75:
            breakthrough = self.break_out_if_trapped(world, px, py)
            if breakthrough is not None:
                return breakthrough
            return self.escape_close_threats(world, px, py, nearest_enemy)
        if self.room10_last_heavy_active(world, target):
            return self.room10_last_heavy_movement(world, px, py, target, range_ok)

        if self.river_door_opportunity(world, px, py, target) and self.should_use_river_door_shortcut(world, px, py):
            routed = self.route_to_door(world, px, py)
            if routed is not None:
                self.current_goal_cell = None
                return self.avoid_trap_move(world, px, py, routed[0], routed[1])

        if IDEAL_FIRE_MIN <= tdist <= IDEAL_FIRE_MAX and nearest_enemy_dist >= MIN_SHOOT_DISTANCE:
            plan = get_room_plan(world.current_room)
            self.current_goal_cell = None
            door_bias = self.combat_door_bias(world, px, py)
            if door_bias is not None:
                return self.avoid_trap_move(world, px, py, door_bias[0], door_bias[1])
            wave_bias = self.wave_preposition_direction(world, px, py)
            if wave_bias is not None:
                return self.avoid_trap_move(world, px, py, wave_bias[0], wave_bias[1])
            if plan.force_motion_when_ideal:
                routed = self.route_to_safe_firing_position(
                    world,
                    self.geometry.load_room(int(world.current_room or 1)),
                    px,
                    py,
                    float(target["x"]),
                    float(target["y"]),
                )
                if routed is not None:
                    return self.avoid_trap_move(world, px, py, routed[0], routed[1])
                strafe = normalize_pair(-ty / tdist, tx / tdist)
                return self.avoid_trap_move(world, px, py, strafe[0], strafe[1])
            return 0.0, 0.0

        if tdist < MIN_SHOOT_DISTANCE or tdist > IDEAL_FIRE_MAX:
            routed = self.route_to_safe_firing_position(
                world,
                self.geometry.load_room(int(world.current_room or 1)),
                px,
                py,
                float(target["x"]),
                float(target["y"]),
            )
            if routed is not None:
                return self.avoid_trap_move(world, px, py, routed[0], routed[1])
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

        # Keep pressure on the selected target; firing can continue while moving.
        if tdist > PREFERRED_FIRE_DISTANCE + 35.0:
            vx += tx / tdist * 0.7
            vy += ty / tdist * 0.7
        elif not range_ok:
            vx += tx / tdist * 0.7
            vy += ty / tdist * 0.7

        door_bias = self.combat_door_bias(world, px, py)
        if door_bias is not None:
            plan = get_room_plan(world.current_room)
            vx += door_bias[0] * plan.combat_door_bias_weight
            vy += door_bias[1] * plan.combat_door_bias_weight
        wave_bias = self.wave_preposition_direction(world, px, py)
        if wave_bias is not None:
            vx += wave_bias[0] * 0.35
            vy += wave_bias[1] * 0.35

        mag = math.hypot(vx, vy)
        if mag < 1e-6:
            return 0.0, 0.0
        return self.avoid_trap_move(world, px, py, vx / mag, vy / mag)

    def wave_preposition_direction(self, world: WorldModel, px: float, py: float) -> tuple[float, float] | None:
        plan = get_room_plan(world.current_room)
        room_id = int(world.current_room or 0)
        self.wave_preposition_goal = None
        if not plan.preposition_waves or room_id <= 3 or room_id == 10:
            return None
        if not world.wave_preposition_active or len(world.enemies) > 2:
            return None
        nearest = min(
            (distance(px, py, float(enemy["x"]), float(enemy["y"])) for enemy in world.enemies.values()),
            default=9999.0,
        )
        if nearest < MIN_SHOOT_DISTANCE:
            return None
        target_spawn = self.next_wave_spawn_zone(world, plan, px, py)
        if target_spawn is None:
            return None
        room = self.geometry.load_room(room_id)
        routed = room.direction_to_reachable_near_point(px, py, target_spawn[0], target_spawn[1], 96.0)
        if routed is None:
            routed = room.direction_to_point(px, py, target_spawn[0], target_spawn[1])
        if routed is None:
            return None
        self.wave_preposition_goal = target_spawn
        self.macro_waypoint = (int(target_spawn[0] // TILE_SIZE), int(target_spawn[1] // TILE_SIZE))
        return normalize_pair(*routed)

    def next_wave_spawn_zone(
        self, world: WorldModel, plan: RoomPlan, px: float, py: float
    ) -> tuple[float, float] | None:
        room_id = int(world.current_room or 0)
        phases = sorted({spawn.phase for spawn in ROOM_SPAWNS.get(room_id, []) if spawn.phase.startswith("wave")})
        if world.current_wave_index >= len(phases):
            return None
        phase = phases[world.current_wave_index]
        candidates = [spawn for spawn in ROOM_SPAWNS.get(room_id, []) if spawn.phase == phase]
        if not candidates:
            return None
        if plan.wave_spawn_groups_order:
            for group in plan.wave_spawn_groups_order:
                grouped = [spawn for spawn in candidates if group in self.spawn_groups_for_spawn(room_id, spawn)]
                if grouped:
                    candidates = grouped
                    break
        door = self.known_door_point(world)
        if door is not None:
            spawn = max(
                candidates,
                key=lambda item: (
                    distance(item.x, item.y, door[0], door[1]),
                    -distance(px, py, item.x, item.y),
                ),
            )
        else:
            spawn = min(candidates, key=lambda item: distance(px, py, item.x, item.y))
        return spawn.x, spawn.y

    def spawn_groups_for_spawn(self, room_id: int, spawn: Any) -> set[str]:
        groups = set(EXTRA_SPAWN_GROUPS.get(room_id, {}).get(spawn.label, set()))
        if spawn.group:
            groups.add(spawn.group)
        return groups

    def only_big_cats_remain(self, world: WorldModel) -> bool:
        return bool(world.enemies) and all(
            int(enemy.get("type", 1) or 1) in BIG_CAT_TYPES
            for enemy in world.enemies.values()
        )

    def room10_last_heavy_active(self, world: WorldModel, target: dict[str, Any]) -> bool:
        return (
            int(world.current_room or 0) == 10
            and self.only_big_cats_remain(world)
            and int(target.get("type", 1) or 1) in BIG_CAT_TYPES
        )

    def room10_last_heavy_movement(
        self,
        world: WorldModel,
        px: float,
        py: float,
        target: dict[str, Any],
        range_ok: bool,
    ) -> tuple[float, float]:
        tx = float(target["x"]) - px
        ty = float(target["y"]) - py
        tdist = max(1.0, math.hypot(tx, ty))
        current = int(world.player.get("weapon_id", WEAPON_PISTOL))
        ammo = int(world.player.get("ammo", 0))

        if current == WEAPON_SHOTGUN and ammo > 0:
            preferred_min = ROOM10_SHOTGUN_MIN
            preferred_max = ROOM10_SHOTGUN_MAX
        elif current == WEAPON_RIFLE and ammo > 0:
            preferred_min = ROOM10_RIFLE_MIN
            preferred_max = ROOM10_RIFLE_MAX
        else:
            preferred_min = IDEAL_FIRE_MIN
            preferred_max = IDEAL_FIRE_MAX

        if tdist > preferred_max:
            self.current_goal_cell = None
            return self.avoid_trap_move(world, px, py, tx / tdist, ty / tdist)
        if tdist < preferred_min:
            self.current_goal_cell = None
            return self.avoid_trap_move(world, px, py, -tx / tdist, -ty / tdist)

        # Hold LOS and DPS pressure; use light strafe instead of the full room-10
        # survival loop once only a heavy remains.
        strafe = normalize_pair(-ty / tdist, tx / tdist)
        return self.avoid_trap_move(world, px, py, strafe[0], strafe[1])

    def combat_door_bias(self, world: WorldModel, px: float, py: float) -> tuple[float, float] | None:
        plan = get_room_plan(world.current_room)
        if plan.combat_door_bias_enemy_count is None or plan.combat_door_bias_weight <= 0.0:
            return None
        if plan.door_bias_blocked_until_groups_clear and any(
            self.enemy_in_any_group(world, enemy, plan.door_bias_blocked_until_groups_clear)
            for enemy in world.enemies.values()
        ):
            return None
        if not world.enemies or len(world.enemies) > plan.combat_door_bias_enemy_count:
            return None
        if plan.door_bias_requires_no_far_cats and self.far_from_door_cats_alive(
            world, plan.far_cat_door_distance_threshold
        ):
            return None
        door = self.known_door_point(world)
        if door is None:
            return None
        nearest_enemy_dist = min(
            (
                distance(px, py, float(enemy["x"]), float(enemy["y"]))
                for enemy in world.enemies.values()
            ),
            default=999.0,
        )
        if nearest_enemy_dist < MIN_SHOOT_DISTANCE:
            return None
        room = self.geometry.load_room(int(world.current_room or 1))
        routed = room.direction_to_reachable_near_point(px, py, door[0], door[1], 48.0)
        if routed is None:
            routed = room.direction_to_point(px, py, door[0], door[1])
        if routed is None:
            return None
        return normalize_pair(*routed)

    def far_from_door_cats_alive(self, world: WorldModel, threshold: float = 320.0) -> bool:
        door = self.known_door_point(world)
        if door is None:
            return False
        for enemy in world.enemies.values():
            if distance(float(enemy["x"]), float(enemy["y"]), door[0], door[1]) >= threshold:
                return True
        return False

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

        tdist = distance(px, py, tx, ty)
        macro = self.route_to_macro_goal_position(world, room, px, py, target)
        if macro is not None:
            return self.avoid_trap_move(world, px, py, macro[0], macro[1])

        if self.blocked_target_ticks >= 8 and tdist <= IDEAL_FIRE_MIN:
            routed = self.run_past_blocked_target(world, room, px, py, tx, ty)
            if routed is not None:
                self.current_goal_cell = None
                self.goal_reason = "run_past_blocked_target"
                return routed

        routed = self.route_to_line_of_fire_position(world, room, px, py, tx, ty)
        if routed is not None:
            nearest_enemy_dist = min(
                (
                    distance(px, py, float(enemy["x"]), float(enemy["y"]))
                    for enemy in world.enemies.values()
                ),
                default=999.0,
            )
            if nearest_enemy_dist <= EMERGENCY_SHOOT_DISTANCE:
                return self.avoid_trap_move(world, px, py, routed[0], routed[1])
            return normalize_pair(routed[0], routed[1])

        if self.blocked_target_ticks >= 12:
            routed_to_target = room.direction_to_reachable_near_point(
                px,
                py,
                tx,
                ty,
                PREFERRED_FIRE_DISTANCE,
            )
            if routed_to_target is not None:
                dx, dy = normalize_pair(*routed_to_target)
                return self.avoid_trap_move(world, px, py, dx, dy)

        route_dir = room.direction_to_line_of_fire(px, py, tx, ty)
        if route_dir is not None:
            dx, dy = normalize_pair(*route_dir)
            return self.avoid_trap_move(world, px, py, dx, dy)

        routed_to_target = room.direction_to_reachable_near_point(
            px,
            py,
            tx,
            ty,
            PREFERRED_FIRE_DISTANCE,
        )
        if routed_to_target is not None:
            dx, dy = normalize_pair(*routed_to_target)
            return self.avoid_trap_move(world, px, py, dx, dy)

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

        return self.avoid_trap_move(world, px, py, best[0], best[1])

    def run_past_blocked_target(
        self,
        world: WorldModel,
        room: Any,
        px: float,
        py: float,
        tx: float,
        ty: float,
    ) -> tuple[float, float] | None:
        door = self.known_door_point(world)
        if door is not None:
            routed = room.direction_to_reachable_near_point(px, py, door[0], door[1], 48.0)
            if routed is not None:
                return normalize_pair(*routed)

        vx = tx - px
        vy = ty - py
        mag = math.hypot(vx, vy)
        if mag < 1e-6:
            return None
        ux = vx / mag
        uy = vy / mag
        for gx, gy, radius in (
            (tx + ux * 220.0, ty + uy * 220.0, 32.0),
            (tx + ux * 120.0, ty + uy * 120.0, 32.0),
            (tx, ty, 32.0),
        ):
            routed = room.direction_to_reachable_near_point(px, py, gx, gy, radius)
            if routed is not None:
                return normalize_pair(*routed)
        return None

    def route_to_macro_goal_position(
        self,
        world: WorldModel,
        room: Any,
        px: float,
        py: float,
        target: dict[str, Any],
    ) -> tuple[float, float] | None:
        plan = get_room_plan(world.current_room)
        target_id = int(target.get("entity_id", 0) or 0)
        failed = self.failed_goal_cells.get(target_id, set())
        target_groups = spawn_groups(world.current_room, target)

        macro_cells: list[tuple[int, int]] = []
        for group in target_groups:
            macro_cells.extend(plan.flank_goals.get(group, []))

        if not macro_cells:
            return None

        if (
            self.current_goal_cell is not None
            and self.goal_target_id == target_id
            and self.current_goal_cell not in failed
            and self.current_goal_cell in macro_cells
            and self.stuck_ticks < STUCK_TICKS_FOR_REPLAN
        ):
            gx, gy = room._cell_center(self.current_goal_cell)
            if distance(px, py, gx, gy) > GOAL_REACHED_DISTANCE:
                routed = self._direction_to_cell(room, px, py, self.current_goal_cell)
                if routed is not None:
                    return routed

        best: tuple[int, int] | None = None
        best_score = float("-inf")
        tx = float(target["x"])
        ty = float(target["y"])
        for cell in macro_cells:
            if cell in failed:
                continue
            if not room._walkable_cell(cell):
                continue
            routed = self._direction_to_cell(room, px, py, cell)
            if routed is None:
                continue
            cx, cy = room._cell_center(cell)
            score = -distance(px, py, cx, cy) * 0.25
            if room.line_of_fire_clear(cx, cy, tx, ty):
                score += 1200.0
            score -= abs(distance(cx, cy, tx, ty) - PREFERRED_FIRE_DISTANCE) * 1.2
            score += room.escape_space(cell) * 80.0
            score -= self.wall_pressure(room, cx, cy) * 80.0
            if score > best_score:
                best_score = score
                best = cell

        if best is None:
            return None
        self.current_goal_cell = best
        self.goal_target_id = target_id
        self.goal_expires_at_tick = self.tick + GOAL_LOCK_TICKS
        self.goal_reason = "macro_goal"
        self.macro_waypoint = best
        return self._direction_to_cell(room, px, py, best)

    def avoid_trap_move(
        self, world: WorldModel, px: float, py: float, dx: float, dy: float
    ) -> tuple[float, float]:
        if not world.enemies:
            return dx, dy
        mag = math.hypot(dx, dy)
        if mag < 1e-6:
            return dx, dy
        dx /= mag
        dy /= mag
        room = self.geometry.load_room(int(world.current_room or 1))
        desired = (dx, dy)
        if not self.move_is_trappy(world, room, px, py, desired[0], desired[1]):
            return desired
        trapped_now = self.is_trapped_now(world, room, px, py)
        candidates = [
            desired,
            normalize_pair(dx * 0.85 - dy * 0.5, dy * 0.85 + dx * 0.5),
            normalize_pair(dx * 0.85 + dy * 0.5, dy * 0.85 - dx * 0.5),
            normalize_pair(-dx, -dy),
            normalize_pair(-dy, dx),
            normalize_pair(dy, -dx),
            *CANDIDATE_DIRS[:-1],
        ]
        best = desired
        best_score = float("-inf")

        current_nearest = min(
            (
                distance(px, py, float(enemy["x"]), float(enemy["y"]))
                for enemy in world.enemies.values()
            ),
            default=999.0,
        )

        for cx, cy in candidates:
            cmag = math.hypot(cx, cy)
            if cmag < 1e-6:
                continue
            cx /= cmag
            cy /= cmag
            first_x = px + cx * 22.0
            first_y = py + cy * 22.0
            if room.blocked_aabb(first_x, first_y):
                continue

            score = (cx * desired[0] + cy * desired[1]) * 220.0
            blocked = False
            for lookahead, weight in ((42.0, 1.0), (84.0, 0.8), (132.0, 0.55)):
                test_x = px + cx * lookahead
                test_y = py + cy * lookahead
                if room.blocked_aabb(test_x, test_y):
                    score -= 900.0 * weight
                    blocked = True
                    break
                cell = room._nearest_walkable_cell(test_x, test_y)
                escape_space = room.escape_space(cell) if cell is not None else 0
                if escape_space <= 1:
                    score -= 900.0 * weight
                elif escape_space == 2:
                    score -= 450.0 * weight
                else:
                    score += escape_space * 40.0 * weight
                score -= self.wall_pressure(room, test_x, test_y) * 95.0 * weight

                nearest_enemy = min(
                    (
                        distance(test_x, test_y, float(enemy["x"]), float(enemy["y"]))
                        for enemy in world.enemies.values()
                    ),
                    default=999.0,
                )
                score += min(nearest_enemy, 260.0) * 1.4 * weight
                if nearest_enemy < EMERGENCY_SHOOT_DISTANCE:
                    score -= (EMERGENCY_SHOOT_DISTANCE - nearest_enemy) * 12.0 * weight
                if (
                    not trapped_now
                    and current_nearest < MIN_SHOOT_DISTANCE
                    and nearest_enemy < current_nearest
                ):
                    score -= (current_nearest - nearest_enemy) * 16.0 * weight
                if trapped_now and lookahead >= 84.0:
                    score += max(0.0, nearest_enemy - current_nearest) * 5.0 * weight

            if blocked and (cx, cy) == desired:
                score -= 600.0
            if score > best_score:
                best_score = score
                best = (cx, cy)

        return best

    def move_is_trappy(
        self, world: WorldModel, room: Any, px: float, py: float, dx: float, dy: float
    ) -> bool:
        current_nearest = min(
            (
                distance(px, py, float(enemy["x"]), float(enemy["y"]))
                for enemy in world.enemies.values()
            ),
            default=999.0,
        )
        for lookahead in (32.0, 72.0, 112.0):
            test_x = px + dx * lookahead
            test_y = py + dy * lookahead
            if room.blocked_aabb(test_x, test_y):
                return True
            cell = room._nearest_walkable_cell(test_x, test_y)
            if cell is None or room.escape_space(cell) <= 1:
                return True
            if self.wall_pressure(room, test_x, test_y) >= 12.0:
                return True
            nearest_enemy = min(
                (
                    distance(test_x, test_y, float(enemy["x"]), float(enemy["y"]))
                    for enemy in world.enemies.values()
                ),
                default=999.0,
            )
            if current_nearest < MIN_SHOOT_DISTANCE and nearest_enemy < current_nearest - 8.0:
                return True
        return False

    def is_trapped_now(self, world: WorldModel, room: Any, px: float, py: float) -> bool:
        cell = room._nearest_walkable_cell(px, py)
        escape_space = room.escape_space(cell) if cell is not None else 0
        wall_pressure = self.wall_pressure(room, px, py)
        close_enemies = sum(
            1
            for enemy in world.enemies.values()
            if distance(px, py, float(enemy["x"]), float(enemy["y"])) <= MIN_SHOOT_DISTANCE
        )
        return (
            escape_space <= TRAPPED_ESCAPE_SPACE
            or wall_pressure >= TRAPPED_WALL_PRESSURE
            or close_enemies >= 2
            or self.stuck_ticks >= max(2, STUCK_TICKS_FOR_REPLAN // 2)
        )

    def break_out_if_trapped(
        self, world: WorldModel, px: float, py: float
    ) -> tuple[float, float] | None:
        room = self.geometry.load_room(int(world.current_room or 1))
        if not self.is_trapped_now(world, room, px, py):
            return None

        current_nearest = min(
            (
                distance(px, py, float(enemy["x"]), float(enemy["y"]))
                for enemy in world.enemies.values()
            ),
            default=999.0,
        )
        best: tuple[float, float] | None = None
        best_score = float("-inf")
        for dx, dy in CANDIDATE_DIRS[:-1]:
            mag = math.hypot(dx, dy)
            if mag < 1e-6:
                continue
            dx /= mag
            dy /= mag
            if room.blocked_aabb(px + dx * 18.0, py + dy * 18.0):
                continue

            score = 0.0
            blocked = False
            for lookahead, weight in ((40.0, 0.7), (96.0, 1.0), (168.0, 1.25), (240.0, 1.4)):
                test_x = px + dx * lookahead
                test_y = py + dy * lookahead
                if room.blocked_aabb(test_x, test_y):
                    score -= 1200.0 * weight
                    blocked = True
                    break
                cell = room._nearest_walkable_cell(test_x, test_y)
                escape_space = room.escape_space(cell) if cell is not None else 0
                wall_pressure = self.wall_pressure(room, test_x, test_y)
                nearest_enemy = min(
                    (
                        distance(test_x, test_y, float(enemy["x"]), float(enemy["y"]))
                        for enemy in world.enemies.values()
                    ),
                    default=999.0,
                )

                score += escape_space * 180.0 * weight
                score -= wall_pressure * 140.0 * weight
                score += min(nearest_enemy, 320.0) * 2.0 * weight
                if lookahead >= 96.0 and nearest_enemy > current_nearest:
                    score += (nearest_enemy - current_nearest) * 5.0 * weight
                if escape_space <= 1:
                    score -= 800.0 * weight

            if blocked:
                score -= 200.0
            if score > best_score:
                best_score = score
                best = (dx, dy)

        return best

    def route_to_line_of_fire_position(
        self,
        world: WorldModel,
        room: Any,
        px: float,
        py: float,
        tx: float,
        ty: float,
    ) -> tuple[float, float] | None:
        start = room._nearest_walkable_cell(px, py)
        target_id = self.route_target_id or self.current_target_id
        failed = self.failed_goal_cells.get(int(target_id or 0), set())
        if start is None:
            return None
        if (
            self.current_goal_cell is not None
            and self.goal_target_id == target_id
            and self.stuck_ticks < STUCK_TICKS_FOR_REPLAN
            and self._los_goal_cell_valid(world, room, self.current_goal_cell, tx, ty)
        ):
            gx, gy = room._cell_center(self.current_goal_cell)
            if distance(px, py, gx, gy) > GOAL_REACHED_DISTANCE:
                routed = self._direction_to_cell(room, px, py, self.current_goal_cell)
                if routed is not None:
                    return routed

        q = deque([start])
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        best: tuple[int, int] | None = None
        best_score = float("-inf")

        while q:
            cell = q.popleft()
            if cell in failed:
                continue
            cx, cy = room._cell_center(cell)
            if room.line_of_fire_clear(cx, cy, tx, ty):
                target_dist = distance(cx, cy, tx, ty)
                escape_space = room.escape_space(cell)
                nearest_enemy = min(
                    (
                        distance(cx, cy, float(enemy["x"]), float(enemy["y"]))
                        for enemy in world.enemies.values()
                    ),
                    default=999.0,
                )
                score = 2000.0
                score -= abs(target_dist - PREFERRED_FIRE_DISTANCE) * 4.0
                if target_dist < EMERGENCY_SHOOT_DISTANCE:
                    score -= (EMERGENCY_SHOOT_DISTANCE - target_dist) * 24.0
                score += min(nearest_enemy, 260.0) * 2.0
                score += escape_space * 70.0
                if escape_space <= 2:
                    score -= 700.0
                score -= self.wall_pressure(room, cx, cy) * 100.0
                # Prefer goals that are not just one side-step away from the
                # blocked sightline; room 7 needs commitment around the wall.
                score += min(distance(px, py, cx, cy), 260.0) * 0.35
                if cell != start and score > best_score:
                    best_score = score
                    best = cell

            for nxt in room._neighbors(cell):
                if nxt in parent:
                    continue
                parent[nxt] = cell
                q.append(nxt)

        if best is None:
            self.current_goal_cell = None
            return None
        self.current_goal_cell = best
        self.goal_target_id = target_id
        self.goal_expires_at_tick = self.tick + GOAL_LOCK_TICKS
        self.goal_reason = "line_of_fire"
        return self._direction_to_cell(room, px, py, best)

    def escape_close_threats(
        self, world: WorldModel, px: float, py: float, target: dict[str, Any]
    ) -> tuple[float, float]:
        room = self.geometry.load_room(int(world.current_room or 1))
        tx = float(target["x"])
        ty = float(target["y"])
        breakthrough = self.break_out_if_trapped(world, px, py)
        if breakthrough is not None:
            return breakthrough
        away_x = px - tx
        away_y = py - ty
        away_mag = max(1.0, math.hypot(away_x, away_y))
        preferred = (away_x / away_mag, away_y / away_mag)
        tangent = (-preferred[1], preferred[0])
        candidates = [
            preferred,
            normalize_pair(preferred[0] + tangent[0] * 0.7, preferred[1] + tangent[1] * 0.7),
            normalize_pair(preferred[0] - tangent[0] * 0.7, preferred[1] - tangent[1] * 0.7),
            *CANDIDATE_DIRS,
        ]
        best = preferred
        best_score = float("-inf")

        for dx, dy in candidates:
            mag = math.hypot(dx, dy)
            if mag < 1e-6:
                continue
            dx /= mag
            dy /= mag
            if dx * preferred[0] + dy * preferred[1] < 0.2:
                continue
            first_x = px + dx * 20.0
            first_y = py + dy * 20.0
            if room.blocked_aabb(first_x, first_y):
                continue
            if distance(first_x, first_y, tx, ty) <= distance(px, py, tx, ty):
                continue

            score = 0.0
            for lookahead in (48.0, 96.0, 144.0):
                test_x = px + dx * lookahead
                test_y = py + dy * lookahead
                if room.blocked_aabb(test_x, test_y):
                    score -= 300.0
                    break
                if segment_point_distance(px, py, test_x, test_y, tx, ty) < 72.0:
                    score -= 500.0

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

        if best_score > float("-inf"):
            return best

        routed = self.route_to_safe_firing_position(world, room, px, py, tx, ty)
        if routed is not None:
            return routed
        return preferred

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
        target_id = self.route_target_id or self.current_target_id
        failed = self.failed_goal_cells.get(int(target_id or 0), set())
        plan = get_room_plan(world.current_room)
        if (
            self.current_goal_cell is not None
            and self.goal_target_id == target_id
            and self.stuck_ticks < STUCK_TICKS_FOR_REPLAN
            and self._goal_cell_valid(world, room, self.current_goal_cell, tx, ty)
        ):
            gx, gy = room._cell_center(self.current_goal_cell)
            if distance(px, py, gx, gy) > GOAL_REACHED_DISTANCE:
                routed = self._direction_to_cell(room, px, py, self.current_goal_cell)
                if routed is not None:
                    return routed

        self.current_goal_cell = None

        q = deque([start])
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        best: tuple[int, int] | None = None
        best_score = float("-inf")

        while q and len(parent) < 1200:
            cell = q.popleft()
            if cell in failed:
                continue
            cx, cy = room._cell_center(cell)
            target_dist = distance(cx, cy, tx, ty)
            nearest_enemy = min(
                (
                    distance(cx, cy, float(enemy["x"]), float(enemy["y"]))
                    for enemy in world.enemies.values()
                ),
                default=999.0,
            )
            escape_space = room.escape_space(cell)
            los_clear = room.line_of_fire_clear(cx, cy, tx, ty)

            score = 0.0
            if los_clear:
                score += 1000.0
            if IDEAL_FIRE_MIN <= target_dist <= 240.0:
                score += 800.0
            else:
                score -= abs(target_dist - PREFERRED_FIRE_DISTANCE) * 6.0
            if target_dist < MIN_SHOOT_DISTANCE:
                score -= (MIN_SHOOT_DISTANCE - target_dist) * 24.0
            if target_dist >= MIN_SHOOT_DISTANCE + 16.0:
                score += 400.0
            score += min(nearest_enemy, 280.0) * 3.0
            if nearest_enemy < MIN_SHOOT_DISTANCE:
                score -= (MIN_SHOOT_DISTANCE - nearest_enemy) * 18.0
            score += escape_space * 80.0
            if escape_space <= 2:
                score -= 850.0
            score -= self.wall_pressure(room, cx, cy) * 120.0
            if plan.kite_loop:
                kite_points = [
                    room._cell_center(kite_cell)
                    for kite_cell in plan.kite_loop
                    if room._walkable_cell(kite_cell)
                ]
                if kite_points:
                    kite_dist = min(distance(cx, cy, kx, ky) for kx, ky in kite_points)
                    score += max(0.0, 260.0 - kite_dist) * 2.5
                    if escape_space >= 4:
                        score += 250.0

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
        self.current_goal_cell = best
        self.goal_target_id = target_id
        self.goal_expires_at_tick = self.tick + GOAL_LOCK_TICKS
        self.goal_reason = "safe_firing"

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

    def has_better_firing_tile(
        self,
        world: WorldModel,
        px: float,
        py: float,
        target: dict[str, Any],
        current_dist: float,
    ) -> bool:
        room = self.geometry.load_room(int(world.current_room or 1))
        plan = get_room_plan(world.current_room)
        start = room._nearest_walkable_cell(px, py)
        if start is None:
            return False
        tx = float(target["x"])
        ty = float(target["y"])
        door = self.known_door_point(world)
        current_door_dist = distance(px, py, door[0], door[1]) if door is not None else 0.0
        q = deque([start])
        seen = {start}
        while q and len(seen) < 420:
            cell = q.popleft()
            cx, cy = room._cell_center(cell)
            target_dist = distance(cx, cy, tx, ty)
            if (
                target_dist <= current_dist - TILE_SIZE
                and target_dist >= MIN_SHOOT_DISTANCE
                and room.line_of_fire_clear(cx, cy, tx, ty)
                and room.escape_space(cell) > 2
                and self.wall_pressure(room, cx, cy) < 9.0
            ):
                if door is None or distance(cx, cy, door[0], door[1]) <= current_door_dist + 96.0:
                    return True
            for nxt in room._neighbors(cell):
                if nxt in seen:
                    continue
                seen.add(nxt)
                q.append(nxt)
        return False

    def river_door_opportunity(
        self, world: WorldModel, px: float, py: float, target: dict[str, Any]
    ) -> bool:
        door = self.known_door_point(world)
        if door is None:
            return False
        plan = get_room_plan(world.current_room)
        if not plan.allow_river_door_shortcut:
            return False
        tx = float(target["x"])
        ty = float(target["y"])
        target_dist = distance(px, py, tx, ty)
        if target_dist > LONG_WEAPON_EFFECTIVE_RANGE or target_dist < MIN_SHOOT_DISTANCE:
            return False
        door_dist = distance(px, py, door[0], door[1])
        if door_dist > RIVER_DOOR_CLOSE_DISTANCE:
            return False
        room = self.geometry.load_room(int(world.current_room or 1))
        return room.line_of_fire_clear(px, py, tx, ty) and room.line_crosses_water(px, py, tx, ty)

    def should_use_river_door_shortcut(self, world: WorldModel, px: float, py: float) -> bool:
        door = self.known_door_point(world)
        if door is None:
            return False
        plan = get_room_plan(world.current_room)
        if not plan.allow_river_door_shortcut:
            return False
        if distance(px, py, door[0], door[1]) > RIVER_DOOR_CLOSE_DISTANCE:
            return False
        room = self.geometry.load_room(int(world.current_room or 1))
        if plan.river_door_requires_no_blocked_cats:
            blocking_groups = plan.river_door_blocking_groups or plan.obstacle_spawn_groups
            if blocking_groups:
                for enemy in world.enemies.values():
                    if spawn_group(world.current_room, enemy) in blocking_groups:
                        return False
            if self.has_solid_blocked_reachable_cat(world, room, px, py):
                return False
        for enemy in world.enemies.values():
            ex = float(enemy["x"])
            ey = float(enemy["y"])
            if distance(px, py, ex, ey) <= EMERGENCY_SHOOT_DISTANCE:
                return False
            if not room.line_of_fire_clear(px, py, ex, ey):
                continue
            if room.line_crosses_water(px, py, ex, ey):
                return True
        return False

    def has_solid_blocked_reachable_cat(
        self, world: WorldModel, room: Any, px: float, py: float
    ) -> bool:
        for enemy in world.enemies.values():
            ex = float(enemy["x"])
            ey = float(enemy["y"])
            if room.line_of_fire_clear(px, py, ex, ey):
                continue
            if room.direction_to_reachable_near_point(px, py, ex, ey, PREFERRED_FIRE_DISTANCE) is not None:
                return True
        return False

    def route_to_door(
        self, world: WorldModel, px: float, py: float
    ) -> tuple[float, float] | None:
        door = self.known_door_point(world)
        if door is None:
            return None
        room = self.geometry.load_room(int(world.current_room or 1))
        routed = room.direction_to_reachable_near_point(px, py, door[0], door[1], 40.0)
        if routed is None:
            routed = room.direction_to_point(px, py, door[0], door[1])
        if routed is None:
            return None
        return normalize_pair(*routed)

    def _goal_cell_valid(
        self,
        world: WorldModel,
        room: Any,
        cell: tuple[int, int],
        tx: float,
        ty: float,
    ) -> bool:
        if not room._walkable_cell(cell):
            return False
        cx, cy = room._cell_center(cell)
        if room.escape_space(cell) <= 2:
            return False
        if self.wall_pressure(room, cx, cy) >= 10.0:
            return False
        target_dist = distance(cx, cy, tx, ty)
        if target_dist < MIN_SHOOT_DISTANCE:
            return False
        nearest_enemy = min(
            (
                distance(cx, cy, float(enemy["x"]), float(enemy["y"]))
                for enemy in world.enemies.values()
            ),
            default=999.0,
        )
        return nearest_enemy >= EMERGENCY_SHOOT_DISTANCE

    def _los_goal_cell_valid(
        self,
        world: WorldModel,
        room: Any,
        cell: tuple[int, int],
        tx: float,
        ty: float,
    ) -> bool:
        if not self._goal_cell_valid(world, room, cell, tx, ty):
            return False
        cx, cy = room._cell_center(cell)
        return room.line_of_fire_clear(cx, cy, tx, ty)

    def _direction_to_cell(
        self, room: Any, px: float, py: float, goal: tuple[int, int]
    ) -> tuple[float, float] | None:
        start = room._nearest_walkable_cell(px, py)
        if start is None or start == goal:
            return None
        q = deque([start])
        parent: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
        while q:
            cell = q.popleft()
            if cell == goal:
                break
            for nxt in room._neighbors(cell):
                if nxt in parent:
                    continue
                parent[nxt] = cell
                q.append(nxt)
        if goal not in parent:
            return None
        step = goal
        while parent.get(step) is not None and parent[step] != start:
            step = parent[step]  # type: ignore[assignment]
        sx, sy = room._cell_center(step)
        return normalize_pair(sx - px, sy - py)

    def _update_stuck(self, px: float, py: float) -> None:
        if self.last_position is None:
            self.last_position = (px, py)
            return
        moved = distance(px, py, self.last_position[0], self.last_position[1])
        intended = math.hypot(self.last_move[0], self.last_move[1])
        if intended > 0.2 and moved < 3.0:
            self.stuck_ticks += 1
        else:
            self.stuck_ticks = 0
        self.last_position = (px, py)
        if self.stuck_ticks >= STUCK_TICKS_FOR_REPLAN:
            if self.current_goal_cell is not None and self.goal_target_id is not None:
                self.failed_goal_cells.setdefault(int(self.goal_target_id), set()).add(self.current_goal_cell)
            self.current_goal_cell = None

    def _clear_locks(self, clear_target: bool = False) -> None:
        if clear_target:
            self.current_target_id = None
            self.route_target_id = None
            self.fire_target_id = None
        self.current_goal_cell = None
        self.goal_target_id = None
        self.goal_expires_at_tick = 0
        self.goal_reason = ""
        self.route_mode = ""
        self.macro_waypoint = None
        self.blocked_target_id = None
        self.blocked_target_ticks = 0
        if clear_target:
            self.failed_goal_cells.clear()

    def known_door_point(self, world: WorldModel) -> tuple[float, float] | None:
        if not world.doors:
            return None
        door = min(world.doors.values(), key=lambda d: int(d.get("door_id", 0) or 0))
        return float(door.get("x", 0.0) or 0.0), float(door.get("y", 0.0) or 0.0)

    def enemy_in_group(self, world: WorldModel, enemy: dict[str, Any], group: str) -> bool:
        return group in spawn_groups(world.current_room, enemy)

    def enemy_in_any_group(
        self, world: WorldModel, enemy: dict[str, Any], groups: set[str]
    ) -> bool:
        return bool(spawn_groups(world.current_room, enemy).intersection(groups))

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


def segment_point_distance(
    ax: float, ay: float, bx: float, by: float, px: float, py: float
) -> float:
    vx = bx - ax
    vy = by - ay
    length_sq = vx * vx + vy * vy
    if length_sq <= 1e-6:
        return distance(ax, ay, px, py)
    t = ((px - ax) * vx + (py - ay) * vy) / length_sq
    t = max(0.0, min(1.0, t))
    return distance(ax + vx * t, ay + vy * t, px, py)


def weapon_effective_range(weapon_id: int | None) -> float:
    if weapon_id == WEAPON_SHOTGUN:
        return SHOTGUN_EFFECTIVE_RANGE
    return LONG_WEAPON_EFFECTIVE_RANGE


def normalize_pair(dx: float, dy: float) -> tuple[float, float]:
    mag = math.hypot(dx, dy)
    if mag < 1e-6:
        return 0.0, 0.0
    return dx / mag, dy / mag
