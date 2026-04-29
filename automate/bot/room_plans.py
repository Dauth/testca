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
    pre_door_health_threshold: int | None = None
    notes: str = ""


DEFAULT_ROOM_PLAN = RoomPlan(
    room_id=0,
    name="default",
    allow_river_door_shortcut=False,
)


ROOM_PLANS: dict[int, RoomPlan] = {
    5: RoomPlan(
        room_id=5,
        name="river plus obstacle",
        obstacle_targets_first=True,
        allow_river_door_shortcut=True,
        river_door_requires_no_blocked_cats=True,
        obstacle_spawn_groups={"obstacle_group"},
        notes="Clear solid-obstacle cats before using the river-to-door shortcut.",
    ),
    7: RoomPlan(
        room_id=7,
        name="blocked final cat",
        obstacle_targets_first=True,
        allow_river_door_shortcut=False,
        flank_spawn_groups={"flank_required_group"},
        notes="Commit to persistent LOS/flank goals for obstacle-blocked targets.",
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
