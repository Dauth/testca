from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from . import protocol
from .spawn_catalog import spawn_label


@dataclass
class CoinMemory:
    pickup_id: int
    x: float
    y: float
    room_id: int
    source_enemy_id: int | None = None
    source_spawn_group: str | None = None
    created_elapsed_ms: int = 0
    expires_elapsed_ms: int = 0
    claimed: bool = False


@dataclass
class WorldModel:
    seed: int | None = None
    current_room: int | None = None
    room_data: dict[str, Any] = field(default_factory=dict)
    tilemap_id: str | None = None
    player: dict[str, Any] = field(default_factory=dict)
    enemies: dict[int, dict[str, Any]] = field(default_factory=dict)
    previous_enemies: dict[int, dict[str, Any]] = field(default_factory=dict)
    enemy_velocities: dict[int, tuple[float, float]] = field(default_factory=dict)
    pickups: dict[int, dict[str, Any]] = field(default_factory=dict)
    projectiles: dict[int, dict[str, Any]] = field(default_factory=dict)
    doors: dict[int, dict[str, Any]] = field(default_factory=dict)
    unlocked_doors: set[int] = field(default_factory=set)
    dead_entities: set[int] = field(default_factory=set)
    elapsed_ms: int = 0
    splits: list[dict[str, Any]] = field(default_factory=list)
    run_complete: bool = False
    outcome: str | None = None
    total_ms: int | None = None
    latest_server_ts: int | None = None
    last_state_elapsed_ms: int | None = None
    last_error: str | None = None
    recent_enemy_deaths: list[dict[str, Any]] = field(default_factory=list)
    coin_sources: dict[int, CoinMemory] = field(default_factory=dict)

    def apply(self, env: dict[str, Any]) -> None:
        typ = env.get("type")
        data = env.get("data") or {}
        server_ts = env.get("server_ts")
        if isinstance(server_ts, int):
            self.latest_server_ts = server_ts

        if typ == protocol.S2C_RUN_STARTED:
            self.seed = data.get("seed")
            self._load_room(data.get("room") or {})
            self.elapsed_ms = 0
            self.run_complete = False
            self.outcome = None
            self.total_ms = None
            self.splits = []
            self.last_state_elapsed_ms = None
        elif typ == protocol.S2C_STATE:
            new_elapsed_ms = int(data.get("elapsed_ms") or 0)
            dt = 0.05
            if self.last_state_elapsed_ms is not None and new_elapsed_ms > self.last_state_elapsed_ms:
                dt = max(0.001, (new_elapsed_ms - self.last_state_elapsed_ms) / 1000.0)
            self.elapsed_ms = new_elapsed_ms
            self.last_state_elapsed_ms = new_elapsed_ms
            self.player = data.get("player") or {}
            self.previous_enemies = self.enemies
            new_enemies = {
                int(e["entity_id"]): e
                for e in data.get("entities", [])
                if int(e.get("entity_id", 0)) not in self.dead_entities
            }
            velocities: dict[int, tuple[float, float]] = {}
            for entity_id, enemy in new_enemies.items():
                previous = self.previous_enemies.get(entity_id)
                if previous is None:
                    continue
                vx = (float(enemy.get("x", 0.0) or 0.0) - float(previous.get("x", 0.0) or 0.0)) / dt
                vy = (float(enemy.get("y", 0.0) or 0.0) - float(previous.get("y", 0.0) or 0.0)) / dt
                velocities[entity_id] = (vx, vy)
            self.enemies = new_enemies
            self.enemy_velocities = velocities
            self.pickups = {
                int(p["entity_id"]): p
                for p in data.get("pickups", [])
                if int(p.get("entity_id", 0)) not in self.dead_entities
            }
            self._link_coin_sources()
            self.projectiles = {
                int(p["proj_id"]): p
                for p in data.get("projectiles", [])
            }
        elif typ == protocol.S2C_ROOM_LOAD:
            self.elapsed_ms = int(data.get("split_ms") or self.elapsed_ms)
            self._load_room(data.get("room") or {})
        elif typ == protocol.S2C_DOOR_UNLOCKED:
            door_id = int(data.get("door_id", 0))
            if door_id:
                self.unlocked_doors.add(door_id)
                if door_id in self.doors:
                    self.doors[door_id]["locked"] = False
        elif typ == protocol.S2C_ENTITY_DIED:
            entity_id = int(data.get("entity_id", 0))
            if entity_id:
                enemy = self.enemies.get(entity_id) or self.previous_enemies.get(entity_id)
                if enemy is not None:
                    spawn = spawn_label(self.current_room, enemy)
                    self.recent_enemy_deaths.append(
                        {
                            "entity_id": entity_id,
                            "room_id": self.current_room,
                            "x": float(enemy.get("x", 0.0) or 0.0),
                            "y": float(enemy.get("y", 0.0) or 0.0),
                            "spawn_group": spawn.get("spawn_group"),
                            "elapsed_ms": self.elapsed_ms,
                        }
                    )
                self.dead_entities.add(entity_id)
                self.enemies.pop(entity_id, None)
                self.pickups.pop(entity_id, None)
        elif typ == protocol.S2C_RUN_COMPLETE:
            self.run_complete = True
            self.outcome = data.get("outcome")
            self.total_ms = data.get("total_ms")
            self.splits = data.get("splits") or []
        elif typ == protocol.S2C_ERROR:
            self.last_error = f"{data.get('code')}: {data.get('message')}"
            raise RuntimeError(self.last_error)

    def _load_room(self, room: dict[str, Any]) -> None:
        self.room_data = room
        self.tilemap_id = room.get("tilemap_id")
        self.current_room = room.get("room_index")
        self.previous_enemies = self.enemies
        self.enemies = {int(e["entity_id"]): e for e in room.get("enemies", [])}
        self.enemy_velocities = {}
        self.pickups = {int(p["entity_id"]): p for p in room.get("pickups", [])}
        self.projectiles = {}
        self.doors = {int(d["door_id"]): d for d in room.get("doors", [])}
        self.unlocked_doors = {
            int(d["door_id"]) for d in room.get("doors", []) if not d.get("locked", True)
        }
        self.dead_entities = set()
        self.recent_enemy_deaths = []
        self.coin_sources = {}

    def _link_coin_sources(self) -> None:
        room_id = int(self.current_room or 0)
        self.recent_enemy_deaths = [
            death
            for death in self.recent_enemy_deaths
            if int(death.get("room_id") or 0) == room_id
            and self.elapsed_ms - int(death.get("elapsed_ms") or 0) <= 30_000
        ]
        for pickup_id, pickup in self.pickups.items():
            if int(pickup.get("type", 0) or 0) != protocol.PICKUP_COIN:
                continue
            if pickup_id in self.coin_sources:
                continue
            px = float(pickup.get("x", 0.0) or 0.0)
            py = float(pickup.get("y", 0.0) or 0.0)
            candidates = [
                death
                for death in self.recent_enemy_deaths
                if math.hypot(float(death.get("x", px) or px) - px, float(death.get("y", py) or py) - py)
                <= 96.0
            ]
            if not candidates:
                continue
            death = min(
                candidates,
                key=lambda item: math.hypot(
                    float(item.get("x", px) or px) - px,
                    float(item.get("y", py) or py) - py,
                ),
            )
            self.coin_sources[pickup_id] = CoinMemory(
                pickup_id=pickup_id,
                x=px,
                y=py,
                room_id=room_id,
                source_enemy_id=int(death.get("entity_id") or 0),
                source_spawn_group=death.get("spawn_group"),
                created_elapsed_ms=self.elapsed_ms,
                expires_elapsed_ms=self.elapsed_ms + 30_000,
            )

    def visible_pickup_ids(self) -> list[int]:
        return list(self.pickups.keys())

    def best_unlocked_door(self) -> int | None:
        if not self.unlocked_doors:
            return None
        return min(self.unlocked_doors)
