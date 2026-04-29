from __future__ import annotations

import argparse
import json
import logging
import math
from pathlib import Path
import time
from typing import Iterable

from . import protocol
from .scripted_teacher import ScriptedTeacher
from .seed_search import choose_seed
from .world_model import WorldModel


class LiveBot:
    def __init__(self, url: str, player_id: str, log_dir: str = "automate/runs"):
        self.url = url
        self.player_id = player_id
        self.logger = logging.getLogger("live-bot")
        self.proto = protocol.ClientProtocol(logger=self.logger)
        self.world = WorldModel()
        self.teacher = ScriptedTeacher()
        self.claimed_pickups: set[int] = set()
        self.last_shot_at = 0.0
        self.last_input_log_at = 0.0
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
            start_msg = self.proto.start_run(start_time)
            ws.send(start_msg)
            self.logger.info("start_run sent start_time=%s", start_time)
            self._record("send", {"packets": [json.loads(start_msg)], "reason": "start_run"})

            while not self.world.run_complete:
                raw = None
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    pass
                if raw:
                    self._apply(raw)
                packets = list(self._decide_messages())
                for msg in packets:
                    ws.send(msg)
                if packets:
                    self._record(
                        "action",
                        {
                            "packets": [json.loads(p) for p in packets],
                            "chosen_action": self._summarize_packets(packets),
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

    def _apply(self, raw: str | bytes) -> dict:
        env = protocol.decode(raw)
        self.proto.observe_server_ts(env.get("server_ts"))
        self.world.apply(env)
        self._log_event(env)
        self._record("recv", {"packet": env})
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
                self.logger.info("pickup seen id=%s claim=health hp=%s", pickup_id, hp)
                yield self.proto.interact(pickup_id, protocol.PICKUP_HEALTH)
            elif current_weapon in (2, 3) and ammo <= 3:
                self.logger.info(
                    "pickup seen id=%s claim=ammo weapon=%s ammo=%s",
                    pickup_id,
                    current_weapon,
                    ammo,
                )
                yield self.proto.interact(pickup_id, protocol.PICKUP_AMMO)
            else:
                self.logger.info("pickup seen id=%s claim=coin", pickup_id)
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
                self.logger.info("shop purchase sent item_id=%s remaining_estimated_coins=%s", item_id, coins)
                yield self.proto.shop_purchase(item_id)

        door_id = self.world.best_unlocked_door()
        if door_id is not None:
            self.logger.info("enter_door sent door_id=%s room=%s", door_id, self.world.current_room)
            yield self.proto.enter_door(door_id)
            return

        action = self.teacher.choose(self.world)
        if action.weapon_id is not None and action.weapon_id != current_weapon:
            self.logger.info("switch weapon %s -> %s", current_weapon, action.weapon_id)
            yield self.proto.switch_weapon(action.weapon_id)
        if action.fire:
            now = time.time()
            if now - self.last_shot_at >= 0.2:
                self.logger.info(
                    "shot fired target_id=%s weapon=%s aim=%.3f enemies=%s",
                    action.target_id,
                    action.weapon_id or current_weapon,
                    action.aim_angle,
                    len(self.world.enemies),
                )
                self.last_shot_at = now
            # Sending switch before shoot in the same burst exercises same-tick
            # swap/shoot behavior when both packets drain in one tick.
            yield self.proto.shoot(float(action.aim_angle))
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
            room = data.get("room") or {}
            self.logger.info(
                "run started seed=%s room=%s enemies=%s pickups=%s doors=%s",
                data.get("seed"),
                room.get("room_index"),
                len(room.get("enemies", [])),
                len(room.get("pickups", [])),
                len(room.get("doors", [])),
            )
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
            **payload,
        }
        self.record_file.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.record_file.flush()

    def _summarize_packets(self, packets: list[str]) -> list[str]:
        return [protocol.packet_name(json.loads(packet).get("type")) for packet in packets]

    def _make_record_path(self, log_dir: str) -> Path:
        path = Path(log_dir)
        path.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        return path / f"live_debug_{stamp}.jsonl"


def normalize(dx: float, dy: float) -> tuple[float, float]:
    mag = math.hypot(dx, dy)
    if mag <= 1.0:
        return dx, dy
    return dx / mag, dy / mag


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="ws://localhost:8080/ws")
    parser.add_argument("--player-id", default="bot-local")
    parser.add_argument("--log-dir", default="automate/runs")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    LiveBot(args.url, args.player_id, args.log_dir).run()


if __name__ == "__main__":
    main()
