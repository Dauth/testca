from __future__ import annotations


REWARD_SPEC = {
    "per_tick": -1.0,
    "damage_dealt": 0.1,
    "kill": 5.0,
    "room_clear": 50.0,
    "run_complete": 500.0,
    "damage_taken": -2.0,
    "death": -500.0,
    "wasted_ammo": -0.5,
    "burst_clear_bonus": 25.0,
}


def train_ppo(policy_path: str, output_path: str) -> None:
    """PPO outline.

    Fine-tune only after scripted/BC policy reliably completes runs. Keep the
    tick penalty dominant enough that lower total_ms beats farming kills/damage.
    """
    raise NotImplementedError("Requires the headless Go vectorized environment.")


if __name__ == "__main__":
    train_ppo("combat_policy.pt", "combat_policy_ppo.pt")
