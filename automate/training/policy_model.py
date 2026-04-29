from __future__ import annotations

try:
    import torch
    from torch import nn
except ImportError:  # Allows importing docs/tools without torch installed.
    torch = None
    nn = None


if nn is not None:

    class CombatPolicy(nn.Module):
        def __init__(self, player_dim: int, enemy_dim: int, hidden: int = 128, max_enemies: int = 16):
            super().__init__()
            self.max_enemies = max_enemies
            self.enemy_encoder = nn.Sequential(
                nn.Linear(enemy_dim, hidden),
                nn.ReLU(),
                nn.Linear(hidden, hidden),
                nn.ReLU(),
            )
            self.trunk = nn.Sequential(
                nn.Linear(player_dim + hidden, hidden),
                nn.ReLU(),
                nn.Linear(hidden, hidden),
                nn.ReLU(),
            )
            self.move_head = nn.Linear(hidden, 2)
            self.aim_head = nn.Linear(hidden, 2)
            self.fire_head = nn.Linear(hidden, 1)
            self.weapon_head = nn.Linear(hidden, 3)
            self.target_head = nn.Linear(hidden, max_enemies)

        def forward(self, player_features, enemy_features, enemy_mask):
            encoded = self.enemy_encoder(enemy_features)
            mask = enemy_mask.unsqueeze(-1).float()
            pooled = (encoded * mask).sum(dim=1) / mask.sum(dim=1).clamp_min(1.0)
            x = self.trunk(torch.cat([player_features, pooled], dim=-1))
            aim = self.aim_head(x)
            aim = aim / aim.norm(dim=-1, keepdim=True).clamp_min(1e-6)
            return {
                "move": torch.tanh(self.move_head(x)),
                "aim": aim,
                "fire_logit": self.fire_head(x).squeeze(-1),
                "weapon_logits": self.weapon_head(x),
                "target_logits": self.target_head(x).masked_fill(~enemy_mask, -1e9),
            }
