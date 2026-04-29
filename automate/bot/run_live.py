from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
import time
from typing import Iterable

from . import protocol
from .room_plans import get_room_plan
from .room_geometry import RoomGeometry
from .scripted_teacher import ScriptedTeacher
from .seed_search import choose_seed
from .spawn_catalog import spawn_label
from .world_model import WorldModel


LOW_HEALTH_THRESHOLD = 45
LOW_AMMO_THRESHOLD = 3
COIN_NEAR_DISTANCE = 140.0
COIN_PATH_DISTANCE = 96.0
PICKUP_INTERACT_DISTANCE = 48.0
WEAPON_SHOTGUN = 3
BIG_CAT_TYPES = {3, 5}


class LiveBot:
    def __init__(
        self,
        url: str,
        player_id: str,
        log_dir: str = "automate/runs",
        stop_room: int = 0,
        start_room: int = 0,
        walk_to_door: bool = True,
        door_enter_distance: float = 48.0,
        pickup_mode: str = "physical",
        pickup_interact_distance: float = PICKUP_INTERACT_DISTANCE,
    ):
        self.url = url
        self.player_id = player_id
        self.logger = logging.getLogger("live-bot")
        self.proto = protocol.ClientProtocol(logger=self.logger)
        self.world = WorldModel()
        self.teacher = ScriptedTeacher()
        self.geometry = RoomGeometry(Path(__file__).resolve().parents[2])
        self.claimed_pickups: set[int] = set()
        self.last_shot_at = 0.0
        self.last_input_log_at = 0.0
        self.last_los_log_at = 0.0
        self.last_action_summary: dict = {}
        self.reached_room2 = False
        self.stop_room = stop_room
        self.start_room = start_room
        self.walk_to_door = walk_to_door
        self.door_enter_distance = door_enter_distance
        self.pickup_mode = pickup_mode
        self.pickup_interact_distance = pickup_interact_distance
        self.stop_requested = False
        self.record_path = self._make_record_path(log_dir)
        self.record_file = self.record_path.open("a", encoding="utf-8")

    def run(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise SystemExit("Install websocket-client: python -m pip install websocket-client") from exc

        self.logger.info("connecting websocket url=%s", self.url)
        ws = None
        try:
            try:
                ws = websocket.create_connection(self.url, timeout=2)
            except OSError as exc:
                raise SystemExit(f"websocket connection failed for {self.url}: {exc}") from exc
            self.logger.info("websocket connected")
            auth_msg = self.proto.auth(self.player_id)
            ws.send(auth_msg)
            self.logger.info("auth sent player_id=%s", self.player_id)
            self._record("send", {"packets": [json.loads(auth_msg)], "reason": "auth"})
            self._read_until(ws, {protocol.S2C_AUTH_OK})
            server_now = int(time.time() * 1000) + self.proto.server_offset_ms
            start_time = choose_seed(server_now)
            start_msg = self.proto.start_run(start_time, self.start_room)
            ws.send(start_msg)
            self.logger.info("start_run sent start_time=%s start_room=%s", start_time, self.start_room or 1)
            self._record("send", {"packets": [json.loads(start_msg)], "reason": "start_run"})
            ws.settimeout(0.001)

            while not self.world.run_complete and not self.stop_requested:
                self._drain_available(ws)
                if self.world.run_complete or self.stop_requested:
                    break
                packets = list(self._decide_messages())
                for msg in packets:
                    ws.send(msg)
                if packets:
                    self._record(
                        "action",
                        {
                            "packets": [json.loads(p) for p in packets],
                            "chosen_action": self._summarize_packets(packets),
                            "action": self.last_action_summary,
                        },
                    )
                time.sleep(0.05)
        finally:
            self.logger.info(
                "run finished outcome=%s total_ms=%s log=%s",
                self.world.outcome,
                self.world.total_ms,
                self.record_path,
            )
            self.record_file.close()
            if ws is not None:
                ws.close()

    def _read_until(self, ws, types: set[int]) -> None:
        while True:
            env = self._apply(ws.recv())
            if env.get("type") in types:
                return

    def _drain_available(self, ws) -> int:
        count = 0
        while True:
            try:
                raw = ws.recv()
            except TimeoutError:
                break
            except Exception as exc:
                if exc.__class__.__name__ == "WebSocketTimeoutException":
                    break
                raise
            if not raw:
                break
            self._apply(raw)
            count += 1
        return count

    def _apply(self, raw: str | bytes) -> dict:
        env = protocol.decode(raw)
        self.proto.observe_server_ts(env.get("server_ts"))
        if env.get("type") == protocol.S2C_ERROR:
            self._log_event(env)
            self._record("recv", {"packet": env})
            self.world.apply(env)
            return env
        self.world.apply(env)
        self._log_event(env)
        self._record("recv", {"packet": env})
        return env

    def _decide_messages(self) -> Iterable[str]:
        self.last_action_summary = {}
        hp = int(self.world.player.get("hp", 100) or 100)
        ammo = int(self.world.player.get("ammo", 9999) or 9999)
        current_weapon = int(self.world.player.get("weapon_id", 1) or 1)

        priority_pickup = self._priority_pickup_target(hp, ammo, current_weapon)
        if priority_pickup is not None and not self._near_pickup(priority_pickup):
            dx, dy = self._pickup_direction(priority_pickup)
            pickup = self.world.pickups.get(priority_pickup) or {}
            action = self.teacher.choose(self.world)
            self.last_action_summary = {
                "objective_type": "pickup",
                "objective_id": priority_pickup,
                "pickup_id": priority_pickup,
                "pickup_type": pickup.get("type"),
                "pickup_reason": self._priority_pickup_reason(hp, priority_pickup),
                "physical_interact_allowed": False,
                "dx": dx,
                "dy": dy,
                "fire": action.fire,
                "target_id": action.target_id,
                "los_clear": action.los_clear,
                "range_ok": action.range_ok,
                "distance_to_target": action.distance_to_target,
                "weapon_id": action.weapon_id,
                "reason": "move_to_priority_pickup",
                **self._teacher_debug_fields(action.target_id),
            }
            if action.weapon_id is not None and action.weapon_id != current_weapon:
                self.logger.info("switch weapon %s -> %s", current_weapon, action.weapon_id)
                yield self.proto.switch_weapon(action.weapon_id)
            if action.fire:
                now = time.time()
                if now - self.last_shot_at >= 0.2:
                    self.logger.info(
                        "shot fired target_id=%s weapon=%s aim=%.3f enemies=%s distance=%.1f los_clear=%s range_ok=%s reason=%s+pickup",
                        action.target_id,
                        action.weapon_id or current_weapon,
                        action.aim_angle,
                        len(self.world.enemies),
                        action.distance_to_target,
                        action.los_clear,
                        action.range_ok,
                        action.reason,
                    )
                    self.last_shot_at = now
                yield self.proto.shoot(float(action.aim_angle))
            self.logger.info(
                "move_to_pickup id=%s type=%s reason=%s distance=%.1f dx=%.3f dy=%.3f",
                priority_pickup,
                pickup.get("type"),
                self.last_action_summary["pickup_reason"],
                self._pickup_distance(priority_pickup),
                dx,
                dy,
            )
            yield self.proto.input(dx, dy)
            return

        for pickup_id in self.world.visible_pickup_ids():
            if pickup_id in self.claimed_pickups:
                continue
            pickup_type, pickup_reason = self._pickup_claim(pickup_id, hp, ammo, current_weapon)
            if pickup_type is None:
                continue
            self.claimed_pickups.add(pickup_id)
            if pickup_type == protocol.PICKUP_HEALTH:
                self.logger.info(
                    "pickup seen id=%s claim=health reason=%s hp=%s",
                    pickup_id,
                    pickup_reason,
                    hp,
                )
            elif pickup_type == protocol.PICKUP_AMMO:
                self.logger.info(
                    "pickup seen id=%s claim=ammo reason=%s weapon=%s ammo=%s",
                    pickup_id,
                    pickup_reason,
                    current_weapon,
                    ammo,
                )
                if pickup_reason.startswith("shotgun_ammo") and current_weapon != WEAPON_SHOTGUN:
                    self.logger.info("switch weapon %s -> %s for shotgun ammo pickup", current_weapon, WEAPON_SHOTGUN)
                    self.teacher.empty_weapons.discard(WEAPON_SHOTGUN)
                    yield self.proto.switch_weapon(WEAPON_SHOTGUN)
            else:
                self.logger.info("pickup seen id=%s claim=coin reason=%s", pickup_id, pickup_reason)
            self.last_action_summary = {
                "objective_type": "pickup",
                "objective_id": pickup_id,
                "pickup_id": pickup_id,
                "pickup_type": pickup_type,
                "pickup_reason": pickup_reason,
                "physical_interact_allowed": self._near_pickup(pickup_id) or self.pickup_mode == "remote",
                "distance_to_pickup": self._pickup_distance(pickup_id),
                "reason": "interact_pickup",
            }
            yield self.proto.interact(pickup_id, pickup_type)

        # Direct shop purchases. Spend toward combat speed first; ammo only when
        # the active limited-ammo weapon is low. In physical modes, avoid
        # invisible protocol-only upgrades so the visible run reflects movement.
        if self.pickup_mode == "remote":
            coins = int(self.world.player.get("coins", 0) or 0)
            for item_id, cost in (
                (protocol.SHOP_DAMAGE, 20),
                (protocol.SHOP_FIRE_RATE, 15),
                (protocol.SHOP_SPEED, 10),
                (protocol.SHOP_AMMO, 5),
            ):
                while coins >= cost:
                    if item_id == protocol.SHOP_AMMO and ammo > 3:
                        break
                    coins -= cost
                    self.logger.info("shop purchase sent item_id=%s remaining_estimated_coins=%s", item_id, coins)
                    yield self.proto.shop_purchase(item_id)

        door_id = self.world.best_unlocked_door()
        if door_id is not None:
            if self.walk_to_door and not self._near_door(door_id):
                dx, dy = self._door_direction(door_id)
                self.last_action_summary = {
                    "objective_type": "door",
                    "objective_id": door_id,
                    "target_id": door_id,
                    "los_clear": True,
                    "range_ok": False,
                    "distance_to_target": self._door_distance(door_id),
                    "reason": "move_to_door",
                    "dx": dx,
                    "dy": dy,
                    "fire": False,
                    "weapon_id": None,
                    "door_id": door_id,
                    "distance_to_door": self._door_distance(door_id),
                    "physical_interact_allowed": False,
                }
                self.logger.info(
                    "move_to_door door_id=%s room=%s dx=%.3f dy=%.3f",
                    door_id,
                    self.world.current_room,
                    dx,
                    dy,
                )
                yield self.proto.input(dx, dy)
                return
            self.logger.info(
                "enter_door sent door_id=%s room=%s distance=%.1f",
                door_id,
                self.world.current_room,
                self._door_distance(door_id),
            )
            yield self.proto.enter_door(door_id)
            return

        action = self.teacher.choose(self.world)
        self.last_action_summary = {
            "objective_type": "combat",
            "objective_id": action.target_id,
            "target_id": action.target_id,
            "los_clear": action.los_clear,
            "range_ok": action.range_ok,
            "distance_to_target": action.distance_to_target,
            "reason": action.reason,
            "dx": action.dx,
            "dy": action.dy,
            "fire": action.fire,
            "weapon_id": action.weapon_id,
            **self._teacher_debug_fields(action.target_id),
        }
        if action.weapon_id is not None and action.weapon_id != current_weapon:
            self.logger.info("switch weapon %s -> %s", current_weapon, action.weapon_id)
            yield self.proto.switch_weapon(action.weapon_id)
        if action.fire:
            now = time.time()
            if now - self.last_shot_at >= 0.2:
                self.logger.info(
                    "shot fired target_id=%s weapon=%s aim=%.3f enemies=%s distance=%.1f los_clear=%s range_ok=%s reason=%s",
                    action.target_id,
                    action.weapon_id or current_weapon,
                    action.aim_angle,
                    len(self.world.enemies),
                    action.distance_to_target,
                    action.los_clear,
                    action.range_ok,
                    action.reason,
                )
                self.last_shot_at = now
            # Sending switch before shoot in the same burst exercises same-tick
            # swap/shoot behavior when both packets drain in one tick.
            yield self.proto.shoot(float(action.aim_angle))
        elif action.target_id is not None:
            now = time.time()
            if now - self.last_los_log_at >= 0.5:
                self.logger.info(
                    "shot held target_id=%s distance=%.1f los_clear=%s range_ok=%s reason=%s room=%s",
                    action.target_id,
                    action.distance_to_target,
                    action.los_clear,
                    action.range_ok,
                    action.reason,
                    self.world.current_room,
                )
                if action.reason == "reposition_for_los":
                    self.logger.info(
                        "target blocked target_id=%s reason=%s room=%s",
                        action.target_id,
                        action.reason,
                        self.world.current_room,
                    )
                self.last_los_log_at = now
        dx, dy = normalize(action.dx, action.dy)
        now = time.time()
        if now - self.last_input_log_at >= 1.0:
            self.logger.info("movement input dx=%.3f dy=%.3f", dx, dy)
            self.last_input_log_at = now
        yield self.proto.input(dx, dy)

    def _log_event(self, env: dict) -> None:
        typ = env.get("type")
        name = protocol.packet_name(typ)
        data = env.get("data") or {}
        if typ == protocol.S2C_AUTH_OK:
            self.logger.info("auth ok received display_name=%s", data.get("display_name"))
        elif typ == protocol.S2C_RUN_STARTED:
            self.claimed_pickups.clear()
            room = data.get("room") or {}
            self.logger.info(
                "run started seed=%s room=%s enemies=%s pickups=%s doors=%s",
                data.get("seed"),
                room.get("room_index"),
                len(room.get("enemies", [])),
                len(room.get("pickups", [])),
                len(room.get("doors", [])),
            )
            self._log_known_doors(room)
        elif typ == protocol.S2C_ROOM_LOAD:
            room = data.get("room") or {}
            self.claimed_pickups.clear()
            self.logger.info(
                "room loaded room=%s split_ms=%s enemies=%s pickups=%s doors=%s",
                room.get("room_index"),
                data.get("split_ms"),
                len(room.get("enemies", [])),
                len(room.get("pickups", [])),
                len(room.get("doors", [])),
            )
            self._log_known_doors(room)
            if room.get("room_index") == 2 and not self.reached_room2:
                self.reached_room2 = True
                self.logger.info("SUCCESS: reached room 2")
            if self.stop_room and int(room.get("room_index") or 0) >= self.stop_room:
                self.logger.info("stop-room reached room=%s", room.get("room_index"))
                self.stop_requested = True
        elif typ == protocol.S2C_STATE:
            self.logger.debug(
                "state received room=%s elapsed=%s hp=%s enemies=%s pickups=%s coins=%s",
                self.world.current_room,
                self.world.elapsed_ms,
                self.world.player.get("hp"),
                len(self.world.enemies),
                len(self.world.pickups),
                self.world.player.get("coins"),
            )
        elif typ == protocol.S2C_DOOR_UNLOCKED:
            self.logger.info("door unlocked door_id=%s room=%s", data.get("door_id"), self.world.current_room)
        elif typ == protocol.S2C_ENTITY_DIED:
            self.logger.info("entity died id=%s", data.get("entity_id"))
        elif typ == protocol.S2C_RUN_COMPLETE:
            self.logger.info(
                "run complete outcome=%s total_ms=%s splits=%s",
                data.get("outcome"),
                data.get("total_ms"),
                data.get("splits"),
            )
        elif typ == protocol.S2C_ERROR:
            self.logger.error("server error code=%s message=%s", data.get("code"), data.get("message"))
        elif typ != protocol.S2C_LEADERBOARD:
            self.logger.debug("received %s", name)

    def _record(self, kind: str, payload: dict) -> None:
        row = {
            "timestamp": time.time(),
            "kind": kind,
            "room_id": self.world.current_room,
            "player": self.world.player,
            "enemy_count": len(self.world.enemies),
            "pickup_count": len(self.world.pickups),
            "projectile_count": len(self.world.projectiles),
            **payload,
        }
        self.record_file.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.record_file.flush()

    def _summarize_packets(self, packets: list[str]) -> list[str]:
        return [protocol.packet_name(json.loads(packet).get("type")) for packet in packets]

    def _pickup_claim(
        self, pickup_id: int, hp: int, ammo: int, current_weapon: int
    ) -> tuple[int | None, str]:
        pickup = self.world.pickups.get(int(pickup_id)) or {}
        actual_type = int(pickup.get("type", protocol.PICKUP_COIN) or protocol.PICKUP_COIN)
        if self.pickup_mode == "remote":
            if actual_type == protocol.PICKUP_HEALTH and hp <= LOW_HEALTH_THRESHOLD:
                return actual_type, "low_hp_remote"
            if (
                actual_type == protocol.PICKUP_AMMO
                and not self.world.enemies
                and current_weapon in (2, 3)
                and ammo <= LOW_AMMO_THRESHOLD
            ):
                return actual_type, "low_ammo_remote"
            if actual_type == protocol.PICKUP_COIN:
                return actual_type, "coin_remote"
            return None, "skip_remote_not_needed"

        if not self._near_pickup(pickup_id):
            return None, "not_near_pickup"

        if actual_type == protocol.PICKUP_HEALTH:
            if hp <= LOW_HEALTH_THRESHOLD:
                return actual_type, "low_hp"
            if self.world.enemies:
                return None, "skip_health_combat_not_low"
            return actual_type, "health_near"
        if actual_type == protocol.PICKUP_AMMO:
            if self.world.enemies:
                if self._pickup_on_way(pickup_id) and self._should_save_shotgun_ammo(current_weapon, ammo):
                    return actual_type, "shotgun_ammo_on_way_combat"
                return None, "skip_ammo_combat"
            if current_weapon in (2, 3) and ammo <= LOW_AMMO_THRESHOLD:
                return actual_type, "low_ammo"
            if self._pickup_on_way(pickup_id):
                if self._should_save_shotgun_ammo(current_weapon, ammo):
                    return actual_type, "shotgun_ammo_on_way_safe"
                return actual_type, "ammo_on_way_safe"
            return None, "skip_ammo_not_needed"
        if actual_type == protocol.PICKUP_COIN:
            if self.pickup_mode == "on-way" and not self._pickup_on_way(pickup_id):
                return None, "coin_off_path"
            if self._pickup_on_way(pickup_id):
                return actual_type, "coin_on_way"
            return None, "coin_not_on_way"
        return None, "unknown_pickup_type"

    def _priority_pickup_target(self, hp: int, ammo: int, current_weapon: int) -> int | None:
        wanted_type: int | None = None
        if hp <= LOW_HEALTH_THRESHOLD:
            wanted_type = protocol.PICKUP_HEALTH
        elif self._should_collect_pre_door_health(hp):
            wanted_type = protocol.PICKUP_HEALTH
        elif (
            not self.world.enemies
            and current_weapon in (2, 3)
            and ammo <= LOW_AMMO_THRESHOLD
        ):
            wanted_type = protocol.PICKUP_AMMO
        if wanted_type is None or self.pickup_mode == "remote":
            return None

        player = self.world.player or {}
        px = float(player.get("x", 0.0) or 0.0)
        py = float(player.get("y", 0.0) or 0.0)
        candidates = [
            pickup
            for pickup in self.world.pickups.values()
            if int(pickup.get("type", 0) or 0) == wanted_type
        ]
        if not candidates:
            return None
        target = min(
            candidates,
            key=lambda pickup: math.hypot(
                float(pickup.get("x", px) or px) - px,
                float(pickup.get("y", py) or py) - py,
            ),
        )
        return int(target["entity_id"])

    def _priority_pickup_reason(self, hp: int, pickup_id: int) -> str:
        pickup = self.world.pickups.get(int(pickup_id)) or {}
        pickup_type = int(pickup.get("type", 0) or 0)
        if pickup_type == protocol.PICKUP_HEALTH:
            if hp <= LOW_HEALTH_THRESHOLD:
                return "low_hp"
            if self._should_collect_pre_door_health(hp):
                return "pre_room_health"
        if pickup_type == protocol.PICKUP_AMMO:
            return "low_ammo"
        return "priority_pickup"

    def _should_collect_pre_door_health(self, hp: int) -> bool:
        if self.world.enemies:
            return False
        door_id = self.world.best_unlocked_door()
        if door_id is None:
            return False
        door = self.world.doors.get(int(door_id)) or {}
        next_room = int(door.get("target_room", 0) or 0)
        threshold = get_room_plan(next_room).pre_door_health_threshold
        if threshold is None or hp >= threshold:
            return False
        return any(
            int(pickup.get("type", 0) or 0) == protocol.PICKUP_HEALTH
            for pickup in self.world.pickups.values()
        )

    def _near_pickup(self, pickup_id: int) -> bool:
        return self._pickup_distance(pickup_id) <= self.pickup_interact_distance

    def _pickup_distance(self, pickup_id: int) -> float:
        pickup = self.world.pickups.get(int(pickup_id)) or {}
        player = self.world.player or {}
        px = float(player.get("x", 0.0) or 0.0)
        py = float(player.get("y", 0.0) or 0.0)
        dx = float(pickup.get("x", px) or px) - px
        dy = float(pickup.get("y", py) or py) - py
        return math.hypot(dx, dy)

    def _pickup_direction(self, pickup_id: int) -> tuple[float, float]:
        pickup = self.world.pickups.get(int(pickup_id)) or {}
        player = self.world.player or {}
        px = float(player.get("x", 0.0) or 0.0)
        py = float(player.get("y", 0.0) or 0.0)
        tx = float(pickup.get("x", px) or px)
        ty = float(pickup.get("y", py) or py)
        try:
            room = self.geometry.load_room(int(self.world.current_room or 1))
            if walk_path_clear(room, px, py, tx, ty):
                return normalize(tx - px, ty - py)
            routed = room.direction_to_reachable_near_point(
                px,
                py,
                tx,
                ty,
                self.pickup_interact_distance,
            )
            if routed is None:
                routed = room.direction_to_point(px, py, tx, ty)
            if routed is not None:
                return normalize(*routed)
        except Exception as exc:
            self.logger.debug("pickup routing fallback pickup_id=%s error=%s", pickup_id, exc)
        return normalize(tx - px, ty - py)

    def _pickup_on_way(self, pickup_id: int) -> bool:
        pickup = self.world.pickups.get(int(pickup_id)) or {}
        player = self.world.player or {}
        px = float(player.get("x", 0.0) or 0.0)
        py = float(player.get("y", 0.0) or 0.0)
        x = float(pickup.get("x", px) or px)
        y = float(pickup.get("y", py) or py)
        if math.hypot(x - px, y - py) <= COIN_NEAR_DISTANCE:
            return True

        objective = self._current_objective_point()
        if objective is None:
            return False
        return distance_to_segment(x, y, px, py, objective[0], objective[1]) <= COIN_PATH_DISTANCE

    def _should_save_shotgun_ammo(self, current_weapon: int, ammo: int) -> bool:
        if current_weapon == WEAPON_SHOTGUN and ammo <= LOW_AMMO_THRESHOLD:
            return True
        if self._has_big_cat_alive():
            return True
        if int(self.world.current_room or 0) >= 8:
            return True
        return False

    def _has_big_cat_alive(self) -> bool:
        return any(
            int(enemy.get("type", 1) or 1) in BIG_CAT_TYPES
            for enemy in self.world.enemies.values()
        )

    def _current_objective_point(self) -> tuple[float, float] | None:
        player = self.world.player or {}
        px = float(player.get("x", 0.0) or 0.0)
        py = float(player.get("y", 0.0) or 0.0)
        if self.world.enemies:
            try:
                if self.teacher.current_goal_cell is not None:
                    room = self.geometry.load_room(int(self.world.current_room or 1))
                    return room._cell_center(self.teacher.current_goal_cell)
            except Exception:
                pass
            route_target = self.world.enemies.get(self.teacher.route_target_id or -1)
            if route_target is not None:
                return (
                    float(route_target.get("x", px) or px),
                    float(route_target.get("y", py) or py),
                )
            target = min(
                self.world.enemies.values(),
                key=lambda e: math.hypot(
                    float(e.get("x", px) or px) - px,
                    float(e.get("y", py) or py) - py,
                ),
            )
            return float(target.get("x", px) or px), float(target.get("y", py) or py)

        door_id = self.world.best_unlocked_door()
        if door_id is None:
            return None
        door = self.world.doors.get(int(door_id)) or {}
        return float(door.get("x", px) or px), float(door.get("y", py) or py)

    def _near_door(self, door_id: int) -> bool:
        return self._door_distance(door_id) <= self.door_enter_distance

    def _log_known_doors(self, room: dict) -> None:
        doors = room.get("doors", [])
        if not doors:
            return
        summary = [
            {
                "door_id": door.get("door_id"),
                "x": door.get("x"),
                "y": door.get("y"),
                "target_room": door.get("target_room"),
                "locked": door.get("locked"),
            }
            for door in doors
        ]
        self.logger.info("known doors room=%s doors=%s", room.get("room_index"), summary)

    def _door_distance(self, door_id: int) -> float:
        door = self.world.doors.get(int(door_id)) or {}
        player = self.world.player or {}
        px = float(player.get("x", 0.0) or 0.0)
        py = float(player.get("y", 0.0) or 0.0)
        dx = float(door.get("x", px) or px) - px
        dy = float(door.get("y", py) or py) - py
        return math.hypot(dx, dy)

    def _door_direction(self, door_id: int) -> tuple[float, float]:
        door = self.world.doors.get(int(door_id)) or {}
        player = self.world.player or {}
        px = float(player.get("x", 0.0) or 0.0)
        py = float(player.get("y", 0.0) or 0.0)
        tx = float(door.get("x", px) or px)
        ty = float(door.get("y", py) or py)
        try:
            room = self.geometry.load_room(int(self.world.current_room or 1))
            if walk_path_clear(room, px, py, tx, ty):
                return normalize(tx - px, ty - py)
            routed = room.direction_to_reachable_near_point(
                px,
                py,
                tx,
                ty,
                self.door_enter_distance,
            )
            if routed is None:
                routed = room.direction_to_point(px, py, tx, ty)
            if routed is not None:
                return normalize(*routed)
        except Exception as exc:
            self.logger.debug("door routing fallback door_id=%s error=%s", door_id, exc)
        return normalize(tx - px, ty - py)

    def _make_record_path(self, log_dir: str) -> Path:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return path / f"live_debug_{stamp}.jsonl"

    def _teacher_debug_fields(self, target_id: int | None) -> dict:
        fire_target = self.world.enemies.get(self.teacher.fire_target_id or -1)
        route_target = self.world.enemies.get(self.teacher.route_target_id or -1)
        target = self.world.enemies.get(int(target_id or -1))
        fire_spawn = spawn_label(self.world.current_room, fire_target)
        route_spawn = spawn_label(self.world.current_room, route_target)
        target_spawn = spawn_label(self.world.current_room, target)
        solid_blocked_exists = False
        try:
            player = self.world.player or {}
            px = float(player.get("x", 0.0) or 0.0)
            py = float(player.get("y", 0.0) or 0.0)
            room = self.geometry.load_room(int(self.world.current_room or 1))
            solid_blocked_exists = self.teacher.has_solid_blocked_reachable_cat(self.world, room, px, py)
        except Exception:
            solid_blocked_exists = False
        return {
            "route_target_id": self.teacher.route_target_id,
            "fire_target_id": self.teacher.fire_target_id,
            "movement_goal_cell": self.teacher.current_goal_cell,
            "goal_reason": self.teacher.goal_reason,
            "route_mode": self.teacher.route_mode,
            "stuck_ticks": self.teacher.stuck_ticks,
            "failed_goal_count": sum(len(cells) for cells in self.teacher.failed_goal_cells.values()),
            "fire_target_spawn_label": fire_spawn.get("spawn_label"),
            "route_target_spawn_label": route_spawn.get("spawn_label"),
            "target_spawn_label": target_spawn.get("spawn_label"),
            "spawn_phase": target_spawn.get("spawn_phase"),
            "spawn_group": target_spawn.get("spawn_group"),
            "distance_to_spawn_base": target_spawn.get("distance_to_spawn_base"),
            "river_door_shortcut_used": self.teacher.route_mode == "river_door",
            "solid_blocked_cat_exists": solid_blocked_exists,
            "room10_survival_mode": self.world.current_room == 10 and self.teacher.route_mode == "spawn_immediate_threat",
        }


def normalize(dx: float, dy: float) -> tuple[float, float]:
    mag = math.hypot(dx, dy)
    if mag <= 1.0:
        return dx, dy
    return dx / mag, dy / mag


def distance_to_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    vx = bx - ax
    vy = by - ay
    wx = px - ax
    wy = py - ay
    denom = vx * vx + vy * vy
    if denom <= 1e-6:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (wx * vx + wy * vy) / denom))
    cx = ax + t * vx
    cy = ay + t * vy
    return math.hypot(px - cx, py - cy)


def walk_path_clear(room, ax: float, ay: float, bx: float, by: float) -> bool:
    dist = math.hypot(bx - ax, by - ay)
    steps = max(1, int(dist / 12.0))
    for i in range(1, steps + 1):
        t = i / steps
        x = ax + (bx - ax) * t
        y = ay + (by - ay) * t
        if room.blocked_aabb(x, y):
            return False
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8080/ws")
    parser.add_argument("--player-id", default="bot-local")
    parser.add_argument("--log-dir", default="automate/runs")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--stop-room", type=int, default=0)
    parser.add_argument("--start-room", type=int, default=0)
    parser.add_argument("--no-walk-to-door", action="store_true")
    parser.add_argument("--door-enter-distance", type=float, default=48.0)
    parser.add_argument("--pickup-mode", choices=("physical", "on-way", "remote"), default="physical")
    parser.add_argument("--pickup-interact-distance", type=float, default=PICKUP_INTERACT_DISTANCE)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    LiveBot(
        args.url,
        args.player_id,
        args.log_dir,
        args.stop_room,
        args.start_room,
        not args.no_walk_to_door,
        args.door_enter_distance,
        args.pickup_mode,
        args.pickup_interact_distance,
    ).run()


if __name__ == "__main__":
    main()
