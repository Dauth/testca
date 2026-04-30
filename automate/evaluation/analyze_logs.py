from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def load_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def room_id(row: dict[str, Any]) -> int | None:
    value = row.get("room_id")
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def action(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("action")
    return value if isinstance(value, dict) else {}


def snapshot(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("world_snapshot")
    return value if isinstance(value, dict) else {}


def packets(row: dict[str, Any]) -> list[str]:
    value = row.get("chosen_action")
    return value if isinstance(value, list) else []


def player_state(row: dict[str, Any]) -> dict[str, Any]:
    snap = snapshot(row)
    player = snap.get("player")
    if isinstance(player, dict):
        return player
    player = row.get("player")
    return player if isinstance(player, dict) else {}


def compact_counter(counter: Counter, limit: int) -> list[tuple[str, int]]:
    return [(str(key), count) for key, count in counter.most_common(limit)]


def summarize_room(rows: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [float(row.get("timestamp", 0.0) or 0.0) for row in rows]
    wall_s = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0

    packet_counts: Counter[str] = Counter()
    objectives: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    held_reasons: Counter[str] = Counter()
    route_modes: Counter[str] = Counter()
    route_groups: Counter[str] = Counter()
    fire_groups: Counter[str] = Counter()
    target_groups: Counter[str] = Counter()
    coin_reasons: Counter[str] = Counter()
    pickup_reasons: Counter[str] = Counter()
    shop_items: Counter[str] = Counter()
    weapon_actions: Counter[str] = Counter()
    action_targets: Counter[str] = Counter()
    stuck_ticks_max = 0
    failed_goal_max = 0
    los_blocked_ticks = 0
    fire_ticks = 0
    input_ticks = 0
    coin_route_ticks = 0
    door_ticks = 0
    pickup_ticks = 0

    hp_min: int | None = None
    hp_last: int | None = None
    coins_last: int | None = None
    speed_last: int | None = None
    fire_last: int | None = None
    damage_last: int | None = None
    enemies_last: int | None = None
    pickups_last: int | None = None

    first_elapsed: int | None = None
    last_elapsed: int | None = None

    for row in rows:
        for packet in packets(row):
            packet_counts[packet] += 1
            if packet == "C2S_INPUT":
                input_ticks += 1

        act = action(row)
        if act:
            objective = str(act.get("objective_type"))
            reason = str(act.get("reason"))
            objectives[objective] += 1
            reasons[reason] += 1
            if objective == "coin_kite":
                coin_route_ticks += 1
            if objective == "door":
                door_ticks += 1
            if objective == "pickup":
                pickup_ticks += 1
            if act.get("fire"):
                fire_ticks += 1
            elif act.get("target_id") is not None:
                held_reasons[reason] += 1
                if not bool(act.get("los_clear", True)):
                    los_blocked_ticks += 1
            if act.get("route_mode") is not None:
                route_modes[str(act.get("route_mode"))] += 1
            if act.get("route_target_spawn_group") is not None:
                route_groups[str(act.get("route_target_spawn_group"))] += 1
            if act.get("fire_target_spawn_group") is not None:
                fire_groups[str(act.get("fire_target_spawn_group"))] += 1
            if act.get("target_spawn_group") is not None:
                target_groups[str(act.get("target_spawn_group"))] += 1
            if act.get("coin_decision_reason") is not None:
                coin_reasons[str(act.get("coin_decision_reason"))] += 1
            if act.get("pickup_reason") is not None:
                pickup_reasons[str(act.get("pickup_reason"))] += 1
            if act.get("weapon_id") is not None:
                weapon_actions[str(act.get("weapon_id"))] += 1
            if act.get("target_id") is not None:
                action_targets[str(act.get("target_id"))] += 1
            for item in act.get("shop_purchases", []) or []:
                shop_items[str(item)] += 1
            try:
                stuck_ticks_max = max(stuck_ticks_max, int(act.get("stuck_ticks", 0) or 0))
                failed_goal_max = max(failed_goal_max, int(act.get("failed_goal_count", 0) or 0))
            except (TypeError, ValueError):
                pass

        snap = snapshot(row)
        if snap:
            elapsed = snap.get("elapsed_ms")
            if elapsed is not None:
                try:
                    elapsed_i = int(elapsed)
                    first_elapsed = elapsed_i if first_elapsed is None else min(first_elapsed, elapsed_i)
                    last_elapsed = elapsed_i if last_elapsed is None else max(last_elapsed, elapsed_i)
                except (TypeError, ValueError):
                    pass
            enemies = snap.get("enemies")
            pickups = snap.get("pickups")
            if isinstance(enemies, list):
                enemies_last = len(enemies)
            if isinstance(pickups, list):
                pickups_last = len(pickups)

        player = player_state(row)
        if player:
            try:
                hp = int(player.get("hp", 0) or 0)
                if hp > 0:
                    hp_min = hp if hp_min is None else min(hp_min, hp)
                    hp_last = hp
            except (TypeError, ValueError):
                pass
            for key, dest in (
                ("coins", "coins_last"),
                ("speed_stacks", "speed_last"),
                ("fire_rate_stacks", "fire_last"),
                ("damage_stacks", "damage_last"),
            ):
                try:
                    value = int(player.get(key, 0) or 0)
                except (TypeError, ValueError):
                    continue
                if dest == "coins_last":
                    coins_last = value
                elif dest == "speed_last":
                    speed_last = value
                elif dest == "fire_last":
                    fire_last = value
                elif dest == "damage_last":
                    damage_last = value

    return {
        "time_s_wall": round(wall_s, 2),
        "time_ms_elapsed": (
            None
            if first_elapsed is None or last_elapsed is None
            else max(0, last_elapsed - first_elapsed)
        ),
        "rows": len(rows),
        "packets": compact_counter(packet_counts, 10),
        "objectives": compact_counter(objectives, 10),
        "reasons": compact_counter(reasons, 12),
        "held_reasons": compact_counter(held_reasons, 10),
        "route_modes": compact_counter(route_modes, 10),
        "route_groups": compact_counter(route_groups, 10),
        "fire_groups": compact_counter(fire_groups, 10),
        "target_groups": compact_counter(target_groups, 10),
        "coin_reasons": compact_counter(coin_reasons, 10),
        "pickup_reasons": compact_counter(pickup_reasons, 10),
        "shop_items": compact_counter(shop_items, 10),
        "weapon_actions": compact_counter(weapon_actions, 10),
        "top_action_targets": compact_counter(action_targets, 8),
        "fire_ticks": fire_ticks,
        "input_ticks": input_ticks,
        "los_blocked_ticks": los_blocked_ticks,
        "coin_route_ticks": coin_route_ticks,
        "door_ticks": door_ticks,
        "pickup_ticks": pickup_ticks,
        "stuck_ticks_max": stuck_ticks_max,
        "failed_goal_max": failed_goal_max,
        "hp_min": hp_min,
        "hp_last": hp_last,
        "coins_last": coins_last,
        "upgrades_last": {
            "speed": speed_last,
            "fire_rate": fire_last,
            "damage": damage_last,
        },
        "enemies_last": enemies_last,
        "pickups_last": pickups_last,
    }


def print_text(path: Path, summary: dict[int, dict[str, Any]], rows: list[dict[str, Any]]) -> None:
    complete = next(
        (
            row.get("packet", {}).get("data", {})
            for row in rows
            if row.get("kind") == "recv"
            and isinstance(row.get("packet"), dict)
            and row.get("packet", {}).get("type") == 12
        ),
        None,
    )
    print(f"\n=== {path} rows={len(rows)} ===")
    if complete:
        print(
            "run_complete "
            f"outcome={complete.get('outcome')} total_ms={complete.get('total_ms')} "
            f"splits={complete.get('splits')}"
        )
    for rid in sorted(summary):
        data = summary[rid]
        print(f"\nRoom {rid}")
        print(
            f"  time_s_wall={data['time_s_wall']} time_ms_elapsed={data['time_ms_elapsed']} rows={data['rows']}"
        )
        print(
            f"  fire_ticks={data['fire_ticks']} input_ticks={data['input_ticks']} "
            f"los_blocked_ticks={data['los_blocked_ticks']} coin_route_ticks={data['coin_route_ticks']} "
            f"door_ticks={data['door_ticks']} pickup_ticks={data['pickup_ticks']}"
        )
        print(
            f"  hp_min={data['hp_min']} hp_last={data['hp_last']} coins_last={data['coins_last']} "
            f"upgrades={data['upgrades_last']} stuck_max={data['stuck_ticks_max']} failed_goal_max={data['failed_goal_max']}"
        )
        for key in (
            "packets",
            "objectives",
            "reasons",
            "held_reasons",
            "route_modes",
            "route_groups",
            "fire_groups",
            "coin_reasons",
            "pickup_reasons",
            "shop_items",
            "weapon_actions",
        ):
            print(f"  {key}={data[key]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON summary.")
    args = parser.parse_args()

    output: dict[str, Any] = {}
    for path in args.logs:
        rows = load_rows(path)
        by_room: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            rid = room_id(row)
            if rid is not None:
                by_room[rid].append(row)
        summary = {rid: summarize_room(room_rows) for rid, room_rows in by_room.items()}
        if args.json:
            output[str(path)] = summary
        else:
            print_text(path, summary, rows)

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
