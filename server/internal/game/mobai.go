package game

import (
	"math"
	"math/rand"
	"time"
)

type ArchetypeSpec struct {
	Name             string
	HP               int16
	Speed            float32
	AggroRange       float32
	AttackCooldownMs int
	MeleeDamage      int16
}

var Archetypes = map[uint8]ArchetypeSpec{
	1: {Name: "grunt", HP: 3, Speed: 95, AggroRange: 200, AttackCooldownMs: 800, MeleeDamage: 5},
	2: {Name: "runner", HP: 2, Speed: 165, AggroRange: 260, AttackCooldownMs: 600, MeleeDamage: 4},
	3: {Name: "tank", HP: 12, Speed: 60, AggroRange: 160, AttackCooldownMs: 1200, MeleeDamage: 8},
	4: {Name: "kamikaze", HP: 1, Speed: 145, AggroRange: 220, AttackCooldownMs: 0, MeleeDamage: 15},
	5: {Name: "boss", HP: 120, Speed: 70, AggroRange: 360, AttackCooldownMs: 900, MeleeDamage: 20},
}

func roomTier(roomIndex uint8) (hpMult, speedMult float32) {
	switch {
	case roomIndex >= 9:
		return 1.6, 1.2
	case roomIndex >= 6:
		return 1.3, 1.1
	default:
		return 1.0, 1.0
	}
}

func SpawnEnemy(rng *rand.Rand, roomIndex uint8, baseID uint32, etype uint8, baseX, baseY float32, now time.Time) *EnemyState {
	seed := SeedMob(rng, roomIndex, baseX, baseY)
	return InstantiateEnemy(roomIndex, baseID, etype, seed, now)
}

func SeedMob(rng *rand.Rand, roomIndex uint8, baseX, baseY float32) MobSeed {
	offsetX := float32(rng.Intn(100) - 50)
	offsetY := float32(rng.Intn(100) - 50)

	waypointCount := rng.Intn(3) + 2
	path := make([]Vec2, waypointCount)
	for i := range waypointCount {
		wx := clampFloat(float32(rng.Intn(RoomWidth)), 40, RoomWidth-40)
		wy := clampFloat(float32(rng.Intn(RoomHeight)), 40, RoomHeight-40)
		path[i] = Vec2{X: wx, Y: wy}
	}

	jitterX := rng.Float32()
	jitterY := rng.Float32()

	firstAttackDelay := rng.Intn(500)

	spawnX, spawnY := NearestNonWall(roomIndex, baseX+offsetX, baseY+offsetY)
	for i, wp := range path {
		nx, ny := NearestNonWall(roomIndex, wp.X, wp.Y)
		path[i] = Vec2{X: nx, Y: ny}
	}

	return MobSeed{
		SpawnX:           spawnX,
		SpawnY:           spawnY,
		PatrolPath:       path,
		JitterX:          jitterX,
		JitterY:          jitterY,
		FirstAttackDelay: firstAttackDelay,
	}
}

func InstantiateEnemy(roomIndex uint8, id uint32, etype uint8, seed MobSeed, now time.Time) *EnemyState {
	spec := Archetypes[etype]
	hpMult, speedMult := roomTier(roomIndex)
	hp := int16(float32(spec.HP) * hpMult)
	if hp < 1 {
		hp = 1
	}
	return &EnemyState{
		EntityID:       id,
		Type:           etype,
		X:              seed.SpawnX,
		Y:              seed.SpawnY,
		HP:             hp,
		MaxHP:          hp,
		AIState:        AIPatrol,
		PatrolPath:     seed.PatrolPath,
		AggroRange:     spec.AggroRange,
		AttackCooldown: now.Add(time.Duration(seed.FirstAttackDelay) * time.Millisecond),
		Speed:          spec.Speed * speedMult,
		JitterX:        seed.JitterX,
		JitterY:        seed.JitterY,
	}
}

func UpdateEnemy(e *EnemyState, p *PlayerState, roomIndex uint8, dt float32, now time.Time, fields *FlowFieldCache) (didAttack bool) {
	if e.AIState == AIDead {
		return false
	}

	dx := p.X - e.X
	dy := p.Y - e.Y
	dist := float32(math.Sqrt(float64(dx*dx + dy*dy)))

	if e.AIState != AIAggro && dist < e.AggroRange {
		e.AIState = AIAggro
	}

	switch e.AIState {
	case AIIdle:
		e.AIState = AIPatrol
	case AIPatrol:
		if len(e.PatrolPath) == 0 {
			return false
		}
		tgt := e.PatrolPath[e.PatrolIndex]
		moveTowardWithWalls(e, tgt.X, tgt.Y, dt, roomIndex)
		if near(e.X, e.Y, tgt.X, tgt.Y, 8) {
			e.PatrolIndex = (e.PatrolIndex + 1) % uint8(len(e.PatrolPath))
		}
	case AIAggro:

		if fields == nil {
			fields = NewFlowFieldCache(roomIndex)
		}
		mr, mc := TileOf(e.X, e.Y)
		pr, pc := TileOf(p.X, p.Y)
		fr, fc := BiasedPlayerTile(pr, pc, e.JitterX, e.JitterY, roomIndex)
		field := fields.Get(fr, fc)

		var aimX, aimY float32
		if field[mr][mc] <= 1 {
			aimX, aimY = p.X, p.Y
		} else {
			nr, nc := NextStepTile(field, roomIndex, mr, mc)
			aimX, aimY = TileCenter(nr, nc)
		}

		if e.Type == EnemyKamikaze || dist > meleeStandoff {
			moveTowardWithWalls(e, aimX, aimY, dt, roomIndex)
		}

		if dist < meleeAttackRange && now.After(e.AttackCooldown) {
			didAttack = true
			cd := Archetypes[e.Type].AttackCooldownMs
			e.AttackCooldown = now.Add(time.Duration(cd) * time.Millisecond)
		}
	}
	return didAttack
}

const (
	meleeStandoff    float32 = 38
	meleeAttackRange float32 = 48
)

func moveToward(e *EnemyState, tx, ty, dt float32) {
	dx := tx - e.X
	dy := ty - e.Y
	mag := float32(math.Sqrt(float64(dx*dx + dy*dy)))
	if mag < 0.001 {
		return
	}
	step := e.Speed * dt
	e.X += dx / mag * step
	e.Y += dy / mag * step
}

func moveTowardWithWalls(e *EnemyState, tx, ty, dt float32, roomIndex uint8) {
	dx := tx - e.X
	dy := ty - e.Y
	mag := float32(math.Sqrt(float64(dx*dx + dy*dy)))
	if mag < 0.001 {
		return
	}
	step := e.Speed * dt
	if step > mag {
		step = mag
	}
	const hw float32 = 12
	const hh float32 = 12
	newX := e.X + dx/mag*step
	if !BlockedAABB(roomIndex, newX, e.Y, hw, hh) {
		e.X = newX
	}
	newY := e.Y + dy/mag*step
	if !BlockedAABB(roomIndex, e.X, newY, hw, hh) {
		e.Y = newY
	}
}

func near(ax, ay, bx, by, eps float32) bool {
	dx := ax - bx
	dy := ay - by
	return dx*dx+dy*dy < eps*eps
}

func BroadcastPackAggro(r *RoomState, victimX, victimY float32, victimID uint32) {
	_ = victimID
	rSq := PackAggroRadius * PackAggroRadius
	for _, other := range r.Enemies {
		if other.AIState == AIDead || other.AIState == AIAggro {
			continue
		}
		dx := other.X - victimX
		dy := other.Y - victimY
		if dx*dx+dy*dy <= rSq {
			other.AIState = AIAggro
		}
	}
}

func clampFloat(v, lo, hi float32) float32 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

