from __future__ import annotations

import argparse
import json
import time

from automate.bot.seed_search import coarse_candidates


def evaluate_with_simulator(server_now_ms: int, simulator, step_ms: int, limit: int) -> list[dict]:
    rows = []
    for candidate in coarse_candidates(server_now_ms, step_ms)[:limit]:
        result = simulator(candidate.start_time)
        rows.append({"seed": candidate.start_time, **result})
    rows.sort(key=lambda r: (not r.get("completed", False), r.get("total_ms", 10**12)))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--step-ms", type=int, default=1000)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    def placeholder_simulator(seed: int) -> dict:
        return {
            "completed": False,
            "total_ms": 10**12,
            "note": "replace with server/internal headless runner",
        }

    rows = evaluate_with_simulator(int(time.time() * 1000), placeholder_simulator, args.step_ms, args.limit)
    print(json.dumps(rows[:20], indent=2))


if __name__ == "__main__":
    main()
