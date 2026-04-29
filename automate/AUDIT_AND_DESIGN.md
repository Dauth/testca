# Audit And Design

## Concise Strategy

The fastest practical bot should be protocol-aware and mostly deterministic. Use the legal `start_time` seed window to search favorable enemy jitter/wave timing, collect pickups remotely as the currently best claimed type, buy upgrades directly, switch/shoot in the same tick when needed, and enter doors immediately after unlock. Train only combat micro if scripted targeting/kiting plateaus.

## Important Files

- `server/internal/protocol/envelope.go`: packet IDs and envelope shape.
- `server/internal/protocol/packets.go`: packet payloads and structured server state.
- `server/internal/game/loop.go`: auth/start, seed validation, 20 Hz tick loop, dispatch order, state snapshots, room transitions, leaderboard completion.
- `server/internal/game/state.go`: player, room, enemy, projectile, pickup, door, wave state structs.
- `server/internal/game/constants.go`: tick duration, seed window, pickup range, player/projectile speeds, wave delay/jitter.
- `server/internal/game/rooms.go`: room load, door unlock and enter behavior.
- `server/internal/game/walls.go`: Tiled room parsing, spawns, pickups, doors, walls, projectile blockers.
- `server/internal/game/waves.go`: wave trigger and RNG jitter logic.
- `server/internal/game/combat.go`: weapon switching, shooting, projectile movement/collision, damage, coin drops.
- `server/internal/game/weapons.go`: weapon stats.
- `server/internal/game/mobai.go`: enemy archetypes, aggro, flow-field movement, melee attacks.
- `server/internal/game/pickups.go`: pickup interaction and claimed-type application.
- `server/internal/game/shop.go`: direct shop purchase effects.
- `server/internal/game/killlog_common.go`: room-clear bonus.
- `server/internal/leaderboard/db.go`: leaderboard ordering by `total_ms`.
- `server/internal/replay/player.go`: replay feeds recorded inputs by server tick.
- `client/src/game/net/GameStateSync.ts`: client packet sending reference.

## Server Simulation Loop

The game runs at 20 Hz (`TickDuration = 50 ms`) in `server/internal/game/constants.go:5-8`. Every tick, `stepTick` drains all queued client packets before simulation, advances the player, enemies, projectiles, collisions, waves, death checks, pickup expiry, door unlocks, elapsed time, and sends state (`server/internal/game/loop.go:353-408`).

Packet order inside a tick matters because `drainInput` processes websocket messages sequentially before movement/combat advancement (`server/internal/game/loop.go:353-358`, `server/internal/game/loop.go:585-626`). A bot should send `switch_weapon`, then `shoot`, then movement/input as needed, with timestamps inside the +/- 2 second validation window.

Leaderboard completion records `total_ms` from elapsed wall time plus time adjustments (`server/internal/game/loop.go:741-758`). `TopRuns` sorts by lowest `total_ms` (`server/internal/leaderboard/db.go`).

## Protocol

Client-to-server packet IDs are defined in `server/internal/protocol/envelope.go:8-18`. Envelope fields are `type`, `seq`, `ts`, and `data` (`server/internal/protocol/envelope.go:32-37`). Server-to-client state includes `RUN_STARTED`, `STATE`, `ROOM_LOAD`, `RUN_COMPLETE`, `DOOR_UNLOCKED`, and `ENTITY_DIED` (`server/internal/protocol/envelope.go:20-30`).

Structured payloads include player position/HP/weapon/ammo/coins/upgrades, entity positions/HP/state, projectiles, pickups, doors, room data, and splits (`server/internal/protocol/packets.go:70-140`). This is enough for a non-visual bot.

## Verified Mechanics And Optimizations

### Seed Search

Location: `server/internal/game/loop.go:256-272`, `server/internal/game/constants.go:25`.

Why it works: `initRun` seeds `rand.NewSource(startTime)`, and non-replay runs only require `start_time` within +/- 30 minutes. Search legal millisecond values around current server time for favorable mob offsets, patrol paths, wave jitter, and first attack delays.

Safe use: choose `start_time = estimated_server_now + offset` where `offset` is inside `[-30 min, +30 min]`. Use server `server_ts` from any response to correct clock drift.

Expected impact: high, especially rooms with waves and obstructed maps.

### Remote Door Entry

Location: `server/internal/game/rooms.go:43-53`, dispatch at `server/internal/game/loop.go:614-634`.

Why it works: `HandleEnterDoor` ignores player position and only checks door existence and `Unlocked`. On unlock, send `enter_door` immediately.

Safe use: maintain current room's door IDs from `RUN_STARTED`/`ROOM_LOAD`, then send `enter_door` when `DOOR_UNLOCKED` arrives or when state indicates all enemies are gone.

Expected impact: removes all exit traversal time, likely seconds over 9 transitions.

### Remote Pickup Conversion

Location: `server/internal/game/pickups.go:17-49`, `server/internal/game/constants.go:15`.

Why it works: range is `abs(dx) < 2500 && abs(dy) < 2500` in a `1280 x 768` room, and `applyPickup` switches on `claimedType` while ignoring the pickup's real type.

Safe use: send `interact` for every visible pickup and coin drop with `claimed_type = 3` for coins unless HP/ammo is urgently needed. For ammo, switch to the weapon that needs refill before claiming ammo.

Expected impact: high. Converts all map pickups/coin drops into useful currency/ammo/health without movement.

### Packet-Driven Shop

Location: `server/internal/game/shop.go:16-54`, dispatch at `server/internal/game/loop.go:620-625`.

Why it works: `HandleShopPurchase` has only item ID and coin checks; no distance, room, or menu state check.

Safe use: after remote coin claims, buy in priority order: damage, fire rate, speed, ammo as needed. Damage costs 20, fire rate 15, speed 10, ammo 5.

Expected impact: medium to high once coin economy is exploited.

### Same-Tick Switch/Shoot

Location: `server/internal/game/combat.go:22-31`, `server/internal/game/combat.go:33-72`, `server/internal/game/combat.go:90-93`.

Why it works: switch sets `SwapCooldownEnd = now + 400 ms`, and shoot is allowed if `sameTickSwap` sees exactly that newly set value. This only holds when shoot is processed in the same tick as switch.

Safe use: send `switch_weapon` then `shoot` back-to-back in the same websocket burst.

Expected impact: medium. Enables shotgun/rifle burst without waiting swap cooldown.

### Burst-Clear Bonus

Location: `server/internal/game/killlog_common.go:24-37`, applied in `server/internal/game/loop.go:637-644`.

Why it works: if the time between first and last kill in the room kill log is under 2 seconds, transition applies `-500 ms`.

Safe use: avoid killing one enemy early if it would start the kill window too soon. Cluster/soften enemies, then finish them rapidly.

Expected impact: up to `500 ms` per non-final room transition if reachable. Note: the async kill log uses `time.Now`, so offline replay timing may differ from simulated combat time.

### Multi-Hit Projectile Collision

Location: `server/internal/game/combat.go:109-148`.

Why it works: `AdvanceProjectiles` can append multiple hits for the same projectile before `ResolveCollisions` deletes it. If enemies overlap within the same tick/collision radius, one projectile damage record can apply to multiple enemies.

Safe use: kite/cluster enemies and aim through dense packs. Shotgun creates three projectiles and benefits most.

Expected impact: medium in packed rooms, high with intentional clustering.

### Wave Jitter Search

Location: `server/internal/game/waves.go:9-35`, `server/internal/game/waves.go:49-87`, constants at `server/internal/game/constants.go:38-48`.

Why it works: wave arm delay is `1500 ms + jitter`, where jitter is uniform in `[-1500, +1499]`. Seeds can make waves fire immediately after trigger or much later.

Safe use: rank seeds by low wave arm jitter and favorable spawned mob positions.

Expected impact: high for wave-heavy rooms.

## AI Architecture

### Layer 1: Protocol Automation

Responsibilities:

- Connect `/ws`, send `auth`, then optimized `start_run`.
- Cache room ID, enemies, pickups, doors from `RUN_STARTED` and `ROOM_LOAD`.
- On every state, interact with all visible pickups and coin drops. Claim as coin by default, ammo/health only when needed.
- Buy damage/fire-rate/speed/ammo whenever affordable.
- On `DOOR_UNLOCKED`, immediately send `enter_door`.
- Emit packet bursts in deterministic order: pickups/shop, weapon switch, shoot, input, door entry.

### Layer 2: Scripted Tactical Teacher

Use state packets, not pixels.

Target score:

- Prefer enemies with lower time-to-kill.
- Add priority for runners/kamikazes close to player.
- Add priority for enemies in clusters or aligned behind current target.
- Penalize targets behind walls/projectile blockers.
- For wave rooms, avoid starting the kill-log window until enough enemies are softened if a burst bonus is plausible.

Weapon policy:

- Shotgun for clusters, tanks/boss at close-mid range, or same-tick burst.
- Rifle for high DPS while ammo remains.
- Pistol for cleanup or ammo conservation.

Movement:

- Use a potential field over candidate movement directions.
- Repel from enemies inside melee threat radius, walls, and projectile blockers.
- Attract toward line-of-sight firing lanes and cluster-forming positions.
- Keep enough distance to runners/kamikazes while allowing mobs to clump.

Aim:

- Use projectile interception: solve target relative position plus estimated target velocity from previous snapshots.
- Aim as `atan2(intercept_y - player_y, intercept_x - player_x)`.

### Layer 3: Combat Micro Policy

Train only movement, aim, firing, target choice, and weapon choice.

Input features:

- Player: position, HP, weapon, ammo, coins, speed/fire-rate/damage stacks.
- Room: room ID, local wall/LOS samples, distance to firing lanes.
- Enemies: nearest `K` relative positions, HP, type, state, estimated velocity, distance, LOS.
- Projectiles: nearby projectile positions/angles if enemy projectiles are added later.
- Weapon cooldown and swap estimates.
- Wave status if exposed by a local headless runner.

Model:

- DeepSets or attention encoder over enemies.
- Small MLP trunk.
- Heads: movement vector, aim `(cos(theta), sin(theta))`, fire logit, weapon ID logits, target index logits.

## Training Plan

1. Add a Go headless runner under `server/internal/...` to import `server/internal/game` directly.
2. Implement the deterministic scripted bot and verify it completes runs.
3. Search legal `start_time` seeds with the scripted bot.
4. Record teacher trajectories: state features, action labels, reward/time metrics.
5. Train behavior cloning.
6. Run DAgger: execute learned policy, ask scripted teacher for recovery labels on drift states.
7. Fine-tune PPO only after completion rate is stable.
8. Run local search/CEM over seed, shop priority, weapon schedule, target ordering, and clustering positions.

## PPO Reward

Use leaderboard time as the primary signal:

- `-1` per server tick.
- `+damage_dealt * 0.1`.
- `+kill_value`, scaled by enemy max HP/threat.
- `+room_clear`.
- `+run_complete`.
- `-damage_taken`.
- `-death`.
- `-wasted_ammo`, especially shotgun/rifle misses.
- `+burst_clear_bonus` when kill window is under 2 seconds.

Do not let damage/kill shaping dominate tick penalty; otherwise the policy optimizes score-like behavior instead of time.

## Live Bot Pseudocode

```text
connect websocket /ws
send AUTH(player_id)
read AUTH_OK and server_ts
start_time = seed_search.choose(server_ts)
send START_RUN(start_time)

loop until RUN_COMPLETE:
    read all pending events
    update world model

    for each visible pickup:
        claimed_type = best_claim_type(player_hp, ammo, coins, shop_plan)
        if claimed_type == AMMO:
            switch to weapon needing ammo first
        send INTERACT(pickup_id, claimed_type)

    while affordable useful shop item:
        send SHOP_PURCHASE(item_id)

    if any unlocked door:
        send ENTER_DOOR(door_id)
        continue

    target = choose_target(enemies, player, walls, wave_plan)
    weapon = choose_weapon(target, clusters, ammo, cooldowns)
    if weapon != current:
        send SWITCH_WEAPON(weapon)

    aim = intercept_angle(player, target, projectile_speed)
    move = potential_field_move(player, enemies, walls, target)
    if shot_quality_ok:
        send SHOOT(aim)
    send INPUT(move.dx, move.dy)
```

## Headless Simulator Wrapper

Because Go `internal` packages cannot be imported from `automate`, create a runner under `server/internal/botbench` or `server/cmd/botbench` that:

- Instantiates `game.NewEngine(inCh, outCh, nil, nil)`.
- Sets `ReplayMode = true` for deterministic time stepping and to bypass real timestamp windows.
- Feeds `AUTH` and `START_RUN` envelopes.
- Advances by `game.TickDuration`.
- Lets the scripted bot consume `S2CEnvelope` values and enqueue C2S envelopes for the next tick.
- Returns total ticks, total_ms, splits, damage taken, shots fired, pickup claims, and seed.

The replay player in `server/internal/replay/player.go:95-145` is a close template for this wrapper.

## Evaluation Metrics

- completion rate
- average `total_ms`
- best `total_ms`
- deaths/failures
- damage taken
- ammo efficiency by weapon
- room clear times/splits
- kills per second
- pickup claims by type
- shop purchases by type
- seed ranking

## Prioritized Checklist

1. Implement and test Layer 1 live automation.
2. Verify remote pickup claims and door entry on a local server.
3. Add Go headless runner under `server/internal` for fast seed search.
4. Implement scripted teacher target/weapon/movement policy.
5. Search seeds in the +/- 30 minute window.
6. Record teacher trajectories from the best seeds.
7. Train behavior cloning model.
8. Add DAgger recovery collection.
9. Add PPO fine-tuning only if scripted/BC micro cannot improve.
10. Run final CEM/local search over seed and schedule parameters.
