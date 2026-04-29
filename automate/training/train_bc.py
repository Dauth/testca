from __future__ import annotations


def train_behavior_cloning(dataset_path: str, output_path: str) -> None:
    """Behavior cloning outline.

    Expected dataset rows:
    - player_features
    - enemy_features[K, D]
    - enemy_mask[K]
    - move target dx/dy
    - aim target cos/sin
    - fire target
    - weapon target
    - target index

    Loss:
    - MSE for movement vector
    - cosine/MSE loss for aim vector
    - BCE for fire
    - cross entropy for weapon
    - cross entropy for target index
    """
    raise NotImplementedError(
        "Wire this to the Go headless trajectory recorder once trajectories exist."
    )


if __name__ == "__main__":
    train_behavior_cloning("teacher_trajectories.parquet", "combat_policy.pt")
