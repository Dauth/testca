from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Any

from .spawn_catalog import spawn_group


TOUCHING_DISTANCE = 48.0


@dataclass(frozen=True)
class CoinDecision:
    pickup_id: int
    should_pick: bool
    reason: str
    detour_px: float = 0.0
    priority: float = 0.0


class CoinPlanner:
    def __init__(self, geometry: Any):
        self.geometry = geometry

    def decide_coin(
        self,
        world: Any,
        pickup: dict[str, Any],
        objective: tuple[float, float] | None,
        nearest_enemy_distance: float,
        reaches_shop_threshold: bool,
        source_spawn_group: str | None = None,
    ) -> CoinDecision:
        player = world.player or {}
        px = float(player.get("x", 0.0) or 0.0)
        py = float(player.get("y", 0.0) or 0.0)
        cx = float(pickup.get("x", px) or px)
        cy = float(pickup.get("y", py) or py)
        pickup_id = int(pickup.get("entity_id", 0) or 0)
        direct_dist = math.hypot(cx - px, cy - py)
        room_id = int(world.current_room or 1)

        if direct_dist <= TOUCHING_DISTANCE:
            return CoinDecision(pickup_id, True, "coin_touching", priority=1000.0)
        if room_id == 10:
            return CoinDecision(pickup_id, False, "skip_coin_room10")
        if nearest_enemy_distance < 160.0:
            return CoinDecision(pickup_id, False, "skip_coin_enemy_too_close")
        if source_spawn_group and self._route_locked_group(world, source_spawn_group):
            return CoinDecision(pickup_id, False, "skip_coin_breaks_locked_route")
        if objective is None:
            allowed = 160.0 if reaches_shop_threshold else 96.0
            return CoinDecision(
                pickup_id,
                direct_dist <= allowed,
                "coin_near_shop" if reaches_shop_threshold else "coin_near_safe",
                detour_px=direct_dist,
                priority=500.0 - direct_dist,
            )

        room = self.geometry.load_room(room_id)
        detour = self.route_detour(room, px, py, cx, cy, objective[0], objective[1])
        allowed = self.allowed_detour(world, nearest_enemy_distance, reaches_shop_threshold)
        if detour <= allowed:
            return CoinDecision(
                pickup_id,
                True,
                "coin_on_route_shop" if reaches_shop_threshold else "coin_on_route",
                detour_px=detour,
                priority=600.0 - detour,
            )
        return CoinDecision(pickup_id, False, "coin_detour_too_large", detour_px=detour)

    def allowed_detour(
        self, world: Any, nearest_enemy_distance: float, reaches_shop_threshold: bool
    ) -> float:
        if int(world.current_room or 1) == 10:
            return 32.0
        if nearest_enemy_distance < 260.0:
            return 96.0 if reaches_shop_threshold else 32.0
        if not world.enemies:
            if reaches_shop_threshold and int(world.current_room or 1) >= 8:
                return 420.0
            return 320.0 if reaches_shop_threshold else 96.0
        return 224.0 if reaches_shop_threshold else 64.0

    def route_detour(
        self,
        room: Any,
        px: float,
        py: float,
        cx: float,
        cy: float,
        ox: float,
        oy: float,
    ) -> float:
        base = room.path_cost(px, py, ox, oy)
        via_coin_a = room.path_cost(px, py, cx, cy)
        via_coin_b = room.path_cost(cx, cy, ox, oy)
        if base is None or via_coin_a is None or via_coin_b is None:
            return float("inf")
        return max(0.0, via_coin_a + via_coin_b - base)

    def _route_locked_group(self, world: Any, source_spawn_group: str) -> bool:
        room_id = int(world.current_room or 0)
        if (
            room_id == 5
            and source_spawn_group != "obstacle_group"
            and any(spawn_group(room_id, enemy) == "obstacle_group" for enemy in world.enemies.values())
        ):
            return True
        if (
            room_id == 7
            and source_spawn_group != "flank_required_group"
            and any(spawn_group(room_id, enemy) == "flank_required_group" for enemy in world.enemies.values())
        ):
            return True
        return False
