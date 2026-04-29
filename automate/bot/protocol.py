from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any


C2S_AUTH = 0x01
C2S_START_RUN = 0x02
C2S_INPUT = 0x03
C2S_SHOOT = 0x04
C2S_SWITCH_WEAPON = 0x05
C2S_INTERACT = 0x06
C2S_ENTER_DOOR = 0x07
C2S_SHOP_PURCHASE = 0x09

S2C_AUTH_OK = 0x81
S2C_RUN_STARTED = 0x82
S2C_STATE = 0x83
S2C_ROOM_LOAD = 0x84
S2C_RUN_COMPLETE = 0x85
S2C_LEADERBOARD = 0x86
S2C_ERROR = 0x87
S2C_DOOR_UNLOCKED = 0x88
S2C_ENTITY_DIED = 0x89

PICKUP_HEALTH = 1
PICKUP_AMMO = 2
PICKUP_COIN = 3

SHOP_AMMO = 1
SHOP_SPEED = 2
SHOP_FIRE_RATE = 3
SHOP_DAMAGE = 4


@dataclass
class ClientProtocol:
    seq: int = 0
    server_offset_ms: int = 0

    def now_ms(self) -> int:
        return int(time.time() * 1000) + self.server_offset_ms

    def observe_server_ts(self, server_ts: int | None) -> None:
        if isinstance(server_ts, int) and server_ts > 0:
            self.server_offset_ms = server_ts - int(time.time() * 1000)

    def envelope(self, packet_type: int, data: dict[str, Any]) -> str:
        self.seq += 1
        return json.dumps(
            {
                "type": packet_type,
                "seq": self.seq,
                "ts": self.now_ms(),
                "data": data,
            },
            separators=(",", ":"),
        )

    def auth(self, player_id: str) -> str:
        return self.envelope(C2S_AUTH, {"player_id": player_id})

    def start_run(self, start_time: int) -> str:
        return self.envelope(C2S_START_RUN, {"start_time": start_time})

    def input(self, dx: float, dy: float) -> str:
        return self.envelope(C2S_INPUT, {"dx": clamp(dx), "dy": clamp(dy)})

    def shoot(self, aim_angle: float) -> str:
        return self.envelope(C2S_SHOOT, {"aim_angle": aim_angle})

    def switch_weapon(self, weapon_id: int) -> str:
        return self.envelope(C2S_SWITCH_WEAPON, {"weapon_id": weapon_id})

    def interact(self, target_id: int, claimed_type: int) -> str:
        return self.envelope(
            C2S_INTERACT,
            {"target_id": int(target_id), "claimed_type": int(claimed_type)},
        )

    def enter_door(self, door_id: int) -> str:
        return self.envelope(C2S_ENTER_DOOR, {"door_id": int(door_id)})

    def shop_purchase(self, item_id: int) -> str:
        return self.envelope(C2S_SHOP_PURCHASE, {"item_id": int(item_id)})


def decode(raw: str | bytes) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    return json.loads(raw)


def clamp(value: float) -> float:
    if value < -1.0:
        return -1.0
    if value > 1.0:
        return 1.0
    return float(value)
