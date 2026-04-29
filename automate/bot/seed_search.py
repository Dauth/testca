from __future__ import annotations

from dataclasses import dataclass


SEED_WINDOW_MS = 30 * 60 * 1000


@dataclass(frozen=True)
class SeedCandidate:
    start_time: int
    score: float = 0.0
    notes: str = ""


def legal_seed_window(server_now_ms: int) -> range:
    return range(server_now_ms - SEED_WINDOW_MS, server_now_ms + SEED_WINDOW_MS + 1)


def coarse_candidates(server_now_ms: int, step_ms: int = 1000) -> list[SeedCandidate]:
    return [
        SeedCandidate(start_time=t)
        for t in range(server_now_ms - SEED_WINDOW_MS, server_now_ms + SEED_WINDOW_MS + 1, step_ms)
    ]


def choose_seed(server_now_ms: int) -> int:
    # Placeholder until the Go headless runner can score seeds. Returning server
    # time is always legal; replace with the best candidate from evaluation.
    return int(server_now_ms)


def rank_with_simulator(server_now_ms: int, simulator, step_ms: int = 1000) -> list[SeedCandidate]:
    ranked: list[SeedCandidate] = []
    for candidate in coarse_candidates(server_now_ms, step_ms):
        result = simulator(candidate.start_time)
        total_ms = float(result.get("total_ms", 10**9))
        completed = bool(result.get("completed", False))
        score = -total_ms if completed else -10**12
        ranked.append(
            SeedCandidate(
                start_time=candidate.start_time,
                score=score,
                notes=f"completed={completed} total_ms={total_ms}",
            )
        )
    ranked.sort(key=lambda c: c.score, reverse=True)
    return ranked
