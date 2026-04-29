from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from . import protocol


@dataclass
class WorldModel:
    seed: int | None = None
    current_room: int | None = None
    room_data: dict[str, Any] = field(default_factory=dict)
    tilemap_id: str | None = None
    player: dict[str, Any] = field(default_factory=dict)
    enemies: dict[int, dict[str, Any]] = field(default_factory=dict)
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
    last_error: str | None = None

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
        elif typ == protocol.S2C_STATE:
            self.elapsed_ms = int(data.get("elapsed_ms") or 0)
            self.player = data.get("player") or {}
            self.enemies = {
                int(e["entity_id"]): e
                for e in data.get("entities", [])
                if int(e.get("entity_id", 0)) not in self.dead_entities
            }
            self.pickups = {
                int(p["entity_id"]): p
                for p in data.get("pickups", [])
                if int(p.get("entity_id", 0)) not in self.dead_entities
            }
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
        self.enemies = {int(e["entity_id"]): e for e in room.get("enemies", [])}
        self.pickups = {int(p["entity_id"]): p for p in room.get("pickups", [])}
        self.projectiles = {}
        self.doors = {int(d["door_id"]): d for d in room.get("doors", [])}
        self.unlocked_doors = {
            int(d["door_id"]) for d in room.get("doors", []) if not d.get("locked", True)
        }
        self.dead_entities = set()

    def visible_pickup_ids(self) -> list[int]:
        return list(self.pickups.keys())

    def best_unlocked_door(self) -> int | None:
        if not self.unlocked_doors:
            return None
        return min(self.unlocked_doors)
