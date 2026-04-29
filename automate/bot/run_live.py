from __future__ import annotations

import argparse
import json
import math
import time
from typing import Iterable

from . import protocol
from .scripted_teacher import ScriptedTeacher
from .seed_search import choose_seed
from .world_model import WorldModel


class LiveBot:
    def __init__(self, url: str, player_id: str):
        self.url = url
        self.player_id = player_id
        self.proto = protocol.ClientProtocol()
        self.world = WorldModel()
        self.teacher = ScriptedTeacher()
        self.claimed_pickups: set[int] = set()

    def run(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise SystemExit("Install websocket-client: python -m pip install websocket-client") from exc

        ws = websocket.create_connection(self.url, timeout=2)
        try:
            ws.send(self.proto.auth(self.player_id))
            self._read_until(ws, {protocol.S2C_AUTH_OK})
            server_now = int(time.time() * 1000) + self.proto.server_offset_ms
            ws.send(self.proto.start_run(choose_seed(server_now)))

            while not self.world.run_complete:
                try:
                    raw = ws.recv()
                except TimeoutError:
                    raw = None
                if raw:
                    self._apply(raw)
                for msg in self._decide_messages():
                    ws.send(msg)
                time.sleep(0.05)
        finally:
            ws.close()

    def _read_until(self, ws, types: set[int]) -> None:
        while True:
            env = self._apply(ws.recv())
            if env.get("type") in types:
                return

    def _apply(self, raw: str | bytes) -> dict:
        env = protocol.decode(raw)
        self.proto.observe_server_ts(env.get("server_ts"))
        self.world.apply(env)
        return env

    def _decide_messages(self) -> Iterable[str]:
        # Remote pickup conversion: claim as coins by default. If health is low,
        # convert the next pickup to health. Ammo refills should switch weapon
        # first, then claim as ammo.
        hp = int(self.world.player.get("hp", 100) or 100)
        ammo = int(self.world.player.get("ammo", 9999) or 9999)
        current_weapon = int(self.world.player.get("weapon_id", 1) or 1)

        for pickup_id in self.world.visible_pickup_ids():
            if pickup_id in self.claimed_pickups:
                continue
            self.claimed_pickups.add(pickup_id)
            if hp <= 45:
                yield self.proto.interact(pickup_id, protocol.PICKUP_HEALTH)
            elif current_weapon in (2, 3) and ammo <= 3:
                yield self.proto.interact(pickup_id, protocol.PICKUP_AMMO)
            else:
                yield self.proto.interact(pickup_id, protocol.PICKUP_COIN)

        # Direct shop purchases. Spend toward combat speed first; ammo only when
        # the active limited-ammo weapon is low.
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
                yield self.proto.shop_purchase(item_id)

        door_id = self.world.best_unlocked_door()
        if door_id is not None:
            yield self.proto.enter_door(door_id)
            return

        action = self.teacher.choose(self.world)
        if action.weapon_id is not None and action.weapon_id != current_weapon:
            yield self.proto.switch_weapon(action.weapon_id)
        if action.fire:
            # Sending switch before shoot in the same burst exercises same-tick
            # swap/shoot behavior when both packets drain in one tick.
            yield self.proto.shoot(float(action.aim_angle))
        dx, dy = normalize(action.dx, action.dy)
        yield self.proto.input(dx, dy)


def normalize(dx: float, dy: float) -> tuple[float, float]:
    mag = math.hypot(dx, dy)
    if mag <= 1.0:
        return dx, dy
    return dx / mag, dy / mag


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8080/ws")
    parser.add_argument("--player-id", default="bot-local")
    args = parser.parse_args()
    LiveBot(args.url, args.player_id).run()


if __name__ == "__main__":
    main()
