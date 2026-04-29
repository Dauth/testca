from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoomPlan:
    room_id: int
    name: str = ""
    clear_far_from_door_first: bool = True
    obstacle_targets_first: bool = True
    allow_river_door_shortcut: bool = False
    river_door_requires_no_blocked_cats: bool = True
    preferred_firing_tiles: list[tuple[int, int]] = field(default_factory=list)
    flank_goals: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    kite_loop: list[tuple[int, int]] = field(default_factory=list)
    obstacle_spawn_groups: set[str] = field(default_factory=set)
    flank_spawn_groups: set[str] = field(default_factory=set)
    immediate_threat_spawn_groups: set[str] = field(default_factory=set)
    boss_spawn_groups: set[str] = field(default_factory=set)
    combat_door_bias_enemy_count: int | None = None
    combat_door_bias_weight: float = 0.0
    coin_path_distance: float | None = None
    pre_door_health_threshold: int | None = None
    notes: str = ""


DEFAULT_ROOM_PLAN = RoomPlan(
    room_id=0,
    name="default",
    allow_river_door_shortcut=False,
)


ROOM_PLANS: dict[int, RoomPlan] = {
    1: RoomPlan(
        room_id=1,
        name="simple opener",
        clear_far_from_door_first=True,
        obstacle_targets_first=False,
        allow_river_door_shortcut=False,
        combat_door_bias_enemy_count=2,
        combat_door_bias_weight=0.95,
        coin_path_distance=36.0,
        notes="Clear while drifting toward the top-right door. Collect only route-aligned coins.",
    ),
    2: RoomPlan(
        room_id=2,
        name="runner spacing",
        clear_far_from_door_first=True,
        obstacle_targets_first=False,
        allow_river_door_shortcut=False,
        combat_door_bias_enemy_count=2,
        combat_door_bias_weight=0.45,
        notes="Shoot closest runner or grunt while sweeping lower-left before door-side cleanup.",
    ),
    3: RoomPlan(
        room_id=3,
        name="close-start escape",
        clear_far_from_door_first=True,
        obstacle_targets_first=True,
        allow_river_door_shortcut=False,
        obstacle_spawn_groups={"big_cat"},
        notes="Shoot while escaping close starts; commit to LOS routing for the right-side tank.",
    ),
    4: RoomPlan(
        room_id=4,
        name="first wave room",
        clear_far_from_door_first=True,
        obstacle_targets_first=True,
        allow_river_door_shortcut=False,
        immediate_threat_spawn_groups={"immediate_threat"},
        obstacle_spawn_groups={"big_cat"},
        notes="Handle kamikaze and runner threats first, then clear far/left wave cats before door.",
    ),
    5: RoomPlan(
        room_id=5,
        name="river plus obstacle",
        clear_far_from_door_first=True,
        obstacle_targets_first=True,
        allow_river_door_shortcut=True,
        river_door_requires_no_blocked_cats=True,
        obstacle_spawn_groups={"obstacle_group"},
        notes="Clear solid-obstacle cats before using the river-to-door shortcut.",
    ),
    6: RoomPlan(
        room_id=6,
        name="far-right heavies",
        clear_far_from_door_first=True,
        obstacle_targets_first=True,
        allow_river_door_shortcut=False,
        immediate_threat_spawn_groups={"immediate_threat"},
        obstacle_spawn_groups={"big_cat"},
        notes="Clear far/right tanks and lower threats before committing to the door route.",
    ),
    7: RoomPlan(
        room_id=7,
        name="blocked flank room",
        clear_far_from_door_first=True,
        obstacle_targets_first=True,
        allow_river_door_shortcut=False,
        flank_spawn_groups={"flank_required_group"},
        immediate_threat_spawn_groups={"immediate_threat"},
        notes="Commit to persistent LOS/flank goals for obstacle-blocked targets.",
    ),
    8: RoomPlan(
        room_id=8,
        name="long sweep to door",
        clear_far_from_door_first=True,
        obstacle_targets_first=True,
        allow_river_door_shortcut=False,
        immediate_threat_spawn_groups={"immediate_threat"},
        obstacle_spawn_groups={"big_cat"},
        notes="Sweep left, mid, and far groups before strong door movement; avoid corner chases.",
    ),
    9: RoomPlan(
        room_id=9,
        name="pre-final HP preservation",
        clear_far_from_door_first=True,
        obstacle_targets_first=False,
        allow_river_door_shortcut=False,
        pre_door_health_threshold=75,
        immediate_threat_spawn_groups={"immediate_threat"},
        obstacle_spawn_groups={"big_cat"},
        notes="Preserve HP before the final room; prioritize kamikaze and runner threats.",
    ),
    10: RoomPlan(
        room_id=10,
        name="survival room",
        clear_far_from_door_first=False,
        obstacle_targets_first=False,
        allow_river_door_shortcut=False,
        pre_door_health_threshold=75,
        immediate_threat_spawn_groups={"immediate_threat", "bottom_threat_group"},
        boss_spawn_groups={"boss_group"},
        kite_loop=[(16, 8), (21, 8), (21, 14), (16, 14)],
        notes="Prioritize open-area kiting and high escape-space firing cells.",
    ),
}


def get_room_plan(room_id: int | None) -> RoomPlan:
    if room_id is None:
        return DEFAULT_ROOM_PLAN
    return ROOM_PLANS.get(int(room_id), DEFAULT_ROOM_PLAN)
