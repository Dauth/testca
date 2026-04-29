# Protocol-Aware Speedrun Bot Plan

This folder contains the implementation plan and starter scaffolding for a fast AI/bot for this game. The design is based on verified server code, not on visual/pixel observations.

Primary strategy: use deterministic protocol automation for everything the server already exposes or trusts, then reserve learning/search for combat micro only.

Key verified shortcuts:

- `start_time` is the RNG seed and only has to be within the server's `SeedWindow` of +/- 30 minutes.
- `enter_door` checks only that the door exists and is unlocked; it does not check player distance.
- `interact` uses a huge axis-aligned range of `2500` and applies the client supplied `claimed_type`, not the pickup's real type.
- `shop_purchase` is packet-driven and has no location/shop-open check.
- `switch_weapon` followed by `shoot` in the same server tick can fire the newly selected weapon because of `sameTickSwap`.
- Room transitions apply a `-500 ms` bonus if the kill log duration is under 2 seconds.

Files:

- `AUDIT_AND_DESIGN.md`: full audit, optimization report, bot architecture, training plan, reward plan, and checklist.
- `bot/protocol.py`: packet constants and envelope helpers.
- `bot/world_model.py`: structured game-state cache.
- `bot/scripted_teacher.py`: deterministic combat policy with room geometry, line-of-fire checks, five-tile firing distance, and lead aiming.
- `bot/run_live.py`: live websocket bot loop with pickup claiming, shop automation, visible door walking, and JSONL recording.
- `bot/seed_search.py`: seed ranking scaffold for legal start-time windows.
- `training/policy_model.py`: compact PyTorch policy outline.
- `training/train_bc.py`: behavior cloning outline.
- `training/train_ppo.py`: PPO outline and reward notes.
- `evaluation/evaluate.py`: batch evaluation harness outline.

The live bot uses `websocket-client` if run directly:

```bash
python3 -m venv automate/.venv
automate/.venv/bin/python -m pip install websocket-client
automate/.venv/bin/python -B -m automate.bot.run_live --url ws://localhost:8080/ws --player-id bot-local --verbose
automate/.venv/bin/python -B -m automate.bot.run_live --url ws://localhost:8080/ws --player-id bot-local --verbose --stop-room 2
automate/.venv/bin/python -B -m automate.bot.run_live --url ws://localhost:8080/ws --player-id bot-local --verbose --stop-room 4 --pickup-mode on-way
```

Door walking is now the default so the browser view shows the bot physically moving to the unlocked door. Use `--no-walk-to-door` to test the faster protocol shortcut. Pickup mode defaults to `physical`; use `--pickup-mode remote` only for exploit/speedrun testing. `--pickup-mode on-way` keeps physical interaction but limits coin pickup claims to nearby/path pickups while still allowing low-health recovery.

For fastest offline iteration, put the eventual Go headless runner under `server/internal/...` because Go's `internal` import rule prevents code in this repo-root `automate` folder from importing `server/internal/game` directly.
