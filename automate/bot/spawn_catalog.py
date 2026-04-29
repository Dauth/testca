from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any


KIND_TO_TYPE = {
    "Grunt": 1,
    "Runner": 2,
    "Tank": 3,
    "Kamikaze": 4,
    "Boss": 5,
}


@dataclass(frozen=True)
class SpawnPoint:
    room: int
    phase: str
    kind: str
    x: float
    y: float
    label: str = ""
    group: str = ""

    @property
    def type_id(self) -> int:
        return KIND_TO_TYPE[self.kind]


ROOM_SPAWNS: dict[int, list[SpawnPoint]] = {
    1: [
        SpawnPoint(1, "initial", "Grunt", 400, 300, "left_grunt"),
        SpawnPoint(1, "initial", "Grunt", 800, 300, "door_side_grunt"),
        SpawnPoint(1, "initial", "Grunt", 600, 420, "lower_grunt"),
    ],
    2: [
        SpawnPoint(2, "initial", "Grunt", 368, 136, "upper_left_grunt"),
        SpawnPoint(2, "initial", "Grunt", 960, 260, "door_side_grunt"),
        SpawnPoint(2, "initial", "Runner", 640, 180, "upper_runner"),
        SpawnPoint(2, "initial", "Runner", 640, 450, "mid_runner"),
        SpawnPoint(2, "initial", "Grunt", 368, 648, "lower_left_grunt"),
    ],
    3: [
        SpawnPoint(3, "initial", "Grunt", 300, 240, "left_grunt"),
        SpawnPoint(3, "initial", "Runner", 900, 240, "right_runner"),
        SpawnPoint(3, "initial", "Tank", 976, 416, "right_tank", "big_cat"),
        SpawnPoint(3, "initial", "Grunt", 496, 416, "center_grunt"),
        SpawnPoint(3, "initial", "Grunt", 308, 568, "lower_left_grunt"),
    ],
    4: [
        SpawnPoint(4, "initial", "Grunt", 576, 424, "mid_grunt"),
        SpawnPoint(4, "initial", "Grunt", 808, 152, "upper_right_grunt"),
        SpawnPoint(4, "initial", "Runner", 784, 320, "mid_runner"),
        SpawnPoint(4, "initial", "Kamikaze", 760, 576, "lower_kamikaze", "immediate_threat"),
        SpawnPoint(4, "initial", "Kamikaze", 824, 424, "mid_kamikaze", "immediate_threat"),
        SpawnPoint(4, "wave1", "Kamikaze", 952, 632, "lower_right_kamikaze", "immediate_threat"),
        SpawnPoint(4, "wave1", "Kamikaze", 1096, 632, "far_lower_right_kamikaze", "immediate_threat"),
        SpawnPoint(4, "wave1", "Grunt", 280, 608, "left_wave_grunt"),
        SpawnPoint(4, "wave2", "Grunt", 320, 180, "upper_left_grunt"),
        SpawnPoint(4, "wave2", "Tank", 360, 352, "left_tank", "big_cat"),
        SpawnPoint(4, "wave2", "Runner", 304, 296, "left_runner"),
    ],
    5: [
        SpawnPoint(5, "initial", "Runner", 760, 680, "river_side_runner", "river_group"),
        SpawnPoint(5, "initial", "Tank", 1112, 632, "far_right_tank", "river_group"),
        SpawnPoint(5, "initial", "Grunt", 528, 656, "lower_obstacle_grunt", "obstacle_group"),
        SpawnPoint(5, "initial", "Grunt", 472, 376, "center_obstacle_grunt", "obstacle_group"),
        SpawnPoint(5, "wave1", "Runner", 736, 464, "mid_wave_runner", "obstacle_group"),
        SpawnPoint(5, "wave1", "Runner", 888, 472, "right_wave_runner", "river_group"),
        SpawnPoint(5, "wave1", "Runner", 672, 376, "center_wave_runner", "obstacle_group"),
        SpawnPoint(5, "wave1", "Kamikaze", 1048, 472, "right_wave_kamikaze", "river_group"),
        SpawnPoint(5, "wave2", "Tank", 912, 296, "upper_right_tank", "river_group"),
        SpawnPoint(5, "wave2", "Grunt", 968, 224, "upper_right_grunt", "river_group"),
        SpawnPoint(5, "wave2", "Grunt", 856, 216, "upper_mid_grunt", "river_group"),
    ],
    6: [
        SpawnPoint(6, "initial", "Tank", 1008, 664, "far_lower_tank", "big_cat"),
        SpawnPoint(6, "initial", "Tank", 1160, 480, "far_right_tank", "big_cat"),
        SpawnPoint(6, "initial", "Runner", 336, 448, "left_runner"),
        SpawnPoint(6, "initial", "Grunt", 464, 664, "lower_grunt"),
        SpawnPoint(6, "initial", "Grunt", 1000, 440, "right_grunt"),
        SpawnPoint(6, "initial", "Kamikaze", 680, 656, "lower_kamikaze", "immediate_threat"),
        SpawnPoint(6, "wave1", "Kamikaze", 936, 416, "right_kamikaze", "immediate_threat"),
        SpawnPoint(6, "wave1", "Kamikaze", 936, 504, "lower_right_kamikaze", "immediate_threat"),
        SpawnPoint(6, "wave1", "Runner", 504, 432, "mid_runner"),
        SpawnPoint(6, "wave2", "Tank", 512, 608, "lower_mid_tank", "big_cat"),
        SpawnPoint(6, "wave2", "Runner", 360, 256, "upper_left_runner"),
        SpawnPoint(6, "wave2", "Runner", 296, 256, "far_upper_left_runner"),
    ],
    7: [
        SpawnPoint(7, "initial", "Runner", 552, 442, "left_mid_runner", "flank_required_group"),
        SpawnPoint(7, "initial", "Runner", 791, 628, "lower_mid_runner"),
        SpawnPoint(7, "initial", "Runner", 796, 682, "lower_runner"),
        SpawnPoint(7, "initial", "Runner", 831, 348, "upper_mid_runner"),
        SpawnPoint(7, "initial", "Grunt", 1196, 470, "right_grunt"),
        SpawnPoint(7, "initial", "Kamikaze", 951, 531, "right_kamikaze", "immediate_threat"),
        SpawnPoint(7, "wave1", "Runner", 432, 639, "left_lower_runner", "flank_required_group"),
        SpawnPoint(7, "wave1", "Runner", 636, 379, "left_mid_wave_runner", "flank_required_group"),
        SpawnPoint(7, "wave2", "Tank", 304, 187, "upper_left_tank", "flank_required_group"),
        SpawnPoint(7, "wave2", "Runner", 1159, 133, "upper_right_runner"),
        SpawnPoint(7, "wave2", "Runner", 932, 124, "upper_mid_runner"),
    ],
    8: [
        SpawnPoint(8, "initial", "Grunt", 163, 401, "left_grunt"),
        SpawnPoint(8, "initial", "Grunt", 1114, 161, "upper_right_grunt"),
        SpawnPoint(8, "initial", "Tank", 498, 648, "lower_tank", "big_cat"),
        SpawnPoint(8, "initial", "Runner", 840, 639, "lower_right_runner"),
        SpawnPoint(8, "initial", "Runner", 492, 402, "mid_runner"),
        SpawnPoint(8, "initial", "Kamikaze", 1137, 646, "lower_right_kamikaze", "immediate_threat"),
        SpawnPoint(8, "wave1", "Runner", 468, 153, "upper_left_runner"),
        SpawnPoint(8, "wave1", "Runner", 818, 156, "upper_mid_runner"),
        SpawnPoint(8, "wave1", "Kamikaze", 1128, 405, "right_kamikaze", "immediate_threat"),
        SpawnPoint(8, "wave2", "Tank", 638, 151, "upper_tank", "big_cat"),
        SpawnPoint(8, "wave2", "Grunt", 168, 160, "upper_left_grunt"),
        SpawnPoint(8, "wave2", "Grunt", 819, 401, "mid_right_grunt"),
    ],
    9: [
        SpawnPoint(9, "initial", "Kamikaze", 416, 208, "upper_left_kamikaze", "immediate_threat"),
        SpawnPoint(9, "initial", "Kamikaze", 976, 344, "right_kamikaze", "immediate_threat"),
        SpawnPoint(9, "initial", "Runner", 640, 160, "upper_runner"),
        SpawnPoint(9, "initial", "Tank", 856, 392, "right_tank", "big_cat"),
        SpawnPoint(9, "initial", "Grunt", 576, 480, "lower_left_grunt"),
        SpawnPoint(9, "initial", "Grunt", 704, 480, "lower_right_grunt"),
        SpawnPoint(9, "wave1", "Kamikaze", 416, 624, "lower_left_kamikaze", "immediate_threat"),
        SpawnPoint(9, "wave1", "Kamikaze", 456, 624, "lower_left_kamikaze_2", "immediate_threat"),
        SpawnPoint(9, "wave1", "Runner", 608, 432, "center_runner"),
        SpawnPoint(9, "wave1", "Kamikaze", 824, 616, "lower_right_kamikaze", "immediate_threat"),
        SpawnPoint(9, "wave1", "Kamikaze", 864, 616, "lower_right_kamikaze_2", "immediate_threat"),
        SpawnPoint(9, "wave1", "Tank", 640, 392, "center_tank", "big_cat"),
        SpawnPoint(9, "wave1", "Runner", 672, 432, "center_runner_2"),
        SpawnPoint(9, "wave1", "Grunt", 192, 392, "left_grunt"),
        SpawnPoint(9, "wave1", "Grunt", 1088, 392, "right_grunt"),
        SpawnPoint(9, "wave2", "Tank", 1080, 88, "upper_right_tank", "big_cat"),
        SpawnPoint(9, "wave2", "Kamikaze", 712, 144, "upper_mid_kamikaze", "immediate_threat"),
        SpawnPoint(9, "wave2", "Kamikaze", 576, 144, "upper_mid_kamikaze_2", "immediate_threat"),
        SpawnPoint(9, "wave2", "Grunt", 1032, 80, "upper_right_grunt"),
        SpawnPoint(9, "wave2", "Grunt", 1136, 80, "far_upper_right_grunt"),
        SpawnPoint(9, "wave2", "Grunt", 144, 80, "upper_left_grunt"),
        SpawnPoint(9, "wave2", "Runner", 200, 80, "upper_left_runner"),
        SpawnPoint(9, "wave2", "Runner", 256, 80, "upper_left_runner_2"),
    ],
    10: [
        SpawnPoint(10, "initial", "Tank", 288, 216, "left_tank", "big_cat"),
        SpawnPoint(10, "initial", "Tank", 1008, 216, "right_tank", "big_cat"),
        SpawnPoint(10, "initial", "Runner", 260, 360, "left_runner", "immediate_threat"),
        SpawnPoint(10, "initial", "Runner", 1020, 360, "right_runner", "immediate_threat"),
        SpawnPoint(10, "initial", "Grunt", 480, 320, "left_grunt"),
        SpawnPoint(10, "initial", "Grunt", 784, 280, "upper_right_grunt"),
        SpawnPoint(10, "initial", "Kamikaze", 420, 500, "lower_left_kamikaze", "immediate_threat"),
        SpawnPoint(10, "initial", "Kamikaze", 860, 500, "lower_right_kamikaze", "immediate_threat"),
        SpawnPoint(10, "initial", "Boss", 648, 440, "boss", "boss_group"),
        SpawnPoint(10, "initial", "Grunt", 780, 384, "right_grunt"),
        SpawnPoint(10, "initial", "Grunt", 570, 505, "lower_mid_grunt", "immediate_threat"),
        SpawnPoint(10, "initial", "Grunt", 570, 263, "upper_mid_grunt"),
        SpawnPoint(10, "wave1", "Runner", 925, 477, "right_wave_runner", "immediate_threat"),
        SpawnPoint(10, "wave1", "Runner", 600, 688, "bottom_wave_runner", "bottom_threat_group"),
        SpawnPoint(10, "wave1", "Runner", 355, 477, "left_wave_runner", "immediate_threat"),
        SpawnPoint(10, "wave1", "Runner", 464, 141, "upper_left_wave_runner"),
        SpawnPoint(10, "wave1", "Runner", 816, 141, "upper_right_wave_runner"),
        SpawnPoint(10, "wave2", "Kamikaze", 120, 80, "upper_left_edge_kamikaze", "immediate_threat"),
        SpawnPoint(10, "wave2", "Kamikaze", 520, 80, "upper_mid_kamikaze", "immediate_threat"),
        SpawnPoint(10, "wave2", "Kamikaze", 760, 80, "upper_mid_right_kamikaze", "immediate_threat"),
        SpawnPoint(10, "wave2", "Kamikaze", 1160, 80, "upper_right_edge_kamikaze", "immediate_threat"),
        SpawnPoint(10, "wave2", "Kamikaze", 320, 688, "bottom_left_kamikaze", "bottom_threat_group"),
        SpawnPoint(10, "wave2", "Kamikaze", 680, 632, "bottom_mid_kamikaze", "bottom_threat_group"),
        SpawnPoint(10, "wave2", "Kamikaze", 960, 688, "bottom_right_kamikaze", "bottom_threat_group"),
        SpawnPoint(10, "wave2", "Kamikaze", 80, 384, "left_edge_kamikaze", "immediate_threat"),
        SpawnPoint(10, "wave2", "Kamikaze", 1200, 200, "right_upper_edge_kamikaze", "immediate_threat"),
        SpawnPoint(10, "wave2", "Kamikaze", 1200, 568, "right_lower_edge_kamikaze", "immediate_threat"),
    ],
}


def _build_entity_spawn_index() -> dict[int, SpawnPoint]:
    index: dict[int, SpawnPoint] = {}
    for room, spawns in ROOM_SPAWNS.items():
        initial_idx = 1
        wave_idx = 0
        for spawn in spawns:
            if spawn.phase == "initial":
                index[room * 100 + initial_idx] = spawn
                initial_idx += 1
            elif spawn.phase.startswith("wave"):
                index[100000 + room * 1000 + wave_idx] = spawn
                wave_idx += 1
    return index


ENTITY_SPAWN_BY_ID = _build_entity_spawn_index()


def spawn_match_tolerance(spawn: SpawnPoint) -> float:
    return 140.0 if spawn.phase.startswith("wave") else 110.0


def match_enemy_to_spawn(
    room_id: int | None,
    enemy_or_x: dict[str, Any] | float,
    y: float | None = None,
    phase_hint: str | None = None,
) -> tuple[SpawnPoint | None, float]:
    if room_id is None:
        return None, float("inf")
    if isinstance(enemy_or_x, dict):
        ex = float(enemy_or_x.get("x", 0.0) or 0.0)
        ey = float(enemy_or_x.get("y", 0.0) or 0.0)
        enemy_type = int(enemy_or_x.get("type", 0) or 0)
        entity_id = int(enemy_or_x.get("entity_id", 0) or 0)
        indexed = ENTITY_SPAWN_BY_ID.get(entity_id)
        if indexed is not None and indexed.room == int(room_id):
            return indexed, math.hypot(indexed.x - ex, indexed.y - ey)
    else:
        ex = float(enemy_or_x)
        ey = float(y if y is not None else 0.0)
        enemy_type = 0

    candidates = ROOM_SPAWNS.get(int(room_id), [])
    if phase_hint:
        candidates = [spawn for spawn in candidates if spawn.phase == phase_hint]
    if enemy_type:
        typed = [spawn for spawn in candidates if spawn.type_id == enemy_type]
        if typed:
            candidates = typed
    if not candidates:
        return None, float("inf")

    best = min(candidates, key=lambda spawn: math.hypot(spawn.x - ex, spawn.y - ey))
    dist = math.hypot(best.x - ex, best.y - ey)
    if dist > spawn_match_tolerance(best):
        return None, dist
    return best, dist


def spawn_group(room_id: int | None, enemy: dict[str, Any]) -> str:
    spawn, _ = match_enemy_to_spawn(room_id, enemy)
    return spawn.group if spawn is not None else ""


def spawn_label(room_id: int | None, enemy: dict[str, Any] | None) -> dict[str, Any]:
    if enemy is None:
        return {}
    spawn, dist = match_enemy_to_spawn(room_id, enemy)
    if spawn is None:
        return {
            "spawn_label": None,
            "spawn_phase": None,
            "spawn_group": None,
            "distance_to_spawn_base": None,
        }
    return {
        "spawn_label": spawn.label,
        "spawn_phase": spawn.phase,
        "spawn_group": spawn.group or None,
        "distance_to_spawn_base": round(dist, 1),
    }
