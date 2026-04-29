package game

import (
	"math"
	"time"

	"github.com/greyhats/defcon-game/server/internal/metrics"
)

func ApplyHeal(p *PlayerState, amount int16) {
	p.HP += amount
	if p.HP > p.MaxHP {
		p.HP = p.MaxHP
	}
}

func TakeDamage(e *EnemyState, amount int16) bool {
	e.HP -= amount
	return e.HP <= 0
}

func HandleSwitchWeapon(p *PlayerState, weaponID uint8, now time.Time) {
	if !contains(p.UnlockedWeapons, weaponID) {
		return
	}
	if p.CurrentWeapon == weaponID {
		return
	}
	p.CurrentWeapon = weaponID
	p.SwapCooldownEnd = now.Add(SwapCooldownMs * time.Millisecond)
}

func HandleShoot(p *PlayerState, r *RoomState, aimAngle float32, now time.Time) {
	wid := p.CurrentWeapon
	spec, ok := WeaponSpecs[wid]
	if !ok {
		return
	}

	cd := p.WeaponCooldown[wid]

	if now.Before(p.SwapCooldownEnd) && !sameTickSwap(p.SwapCooldownEnd, now) {
		return
	}
	if now.Before(cd) {
		return
	}

	ammo := p.WeaponAmmo[wid]
	if ammo <= 0 {
		return
	}

	p.WeaponAmmo[wid] = ammo - 1
	metrics.WeaponShots.WithLabelValues(spec.Name).Inc()
	cooldown := time.Duration(spec.CooldownMs) * time.Millisecond
	if p.FireRateStacks > 0 {
		cooldown = time.Duration(float64(cooldown) / (1 + 0.1*float64(p.FireRateStacks)))
	}
	p.WeaponCooldown[wid] = now.Add(cooldown)

	dmg := int16(float32(spec.Damage) * EffectiveDamageMult(p))

	if wid == 3 {

		for _, deg := range []float64{-10, 0, 10} {
			spawnProjectile(r, p, wid, aimAngle+float32(deg*math.Pi/180), dmg, now)
		}
		return
	}
	spawnProjectile(r, p, wid, aimAngle, dmg, now)
}

func spawnProjectile(r *RoomState, p *PlayerState, wid uint8, angle float32, dmg int16, now time.Time) {
	id := r.NextProjID
	r.NextProjID++
	r.Projectiles[id] = &ProjectileState{
		ProjID:    id,
		X:         p.X,
		Y:         p.Y,
		VelX:      ProjectileSpeed * float32(math.Cos(float64(angle))),
		VelY:      ProjectileSpeed * float32(math.Sin(float64(angle))),
		Damage:    dmg,
		OwnerID:   0,
		WeaponID:  wid,
		SpawnedAt: now,
	}
}

func sameTickSwap(end time.Time, now time.Time) bool {
	diff := end.Sub(now)
	return diff == SwapCooldownMs*time.Millisecond
}

func EffectiveDamageMult(p *PlayerState) float32 {
	return 1 + 0.1*float32(p.DamageStacks)
}

func EffectiveSpeedMult(p *PlayerState) float32 {
	return 1 + 0.1*float32(p.SpeedStacks)
}

type collisionHit struct {
	proj   *ProjectileState
	enemy  *EnemyState
	projID uint32
}

func AdvanceProjectiles(r *RoomState, dt float32, now time.Time) []collisionHit {
	hits := []collisionHit{}
	for id, pr := range r.Projectiles {
		pr.X += pr.VelX * dt
		pr.Y += pr.VelY * dt
		age := now.Sub(pr.SpawnedAt).Seconds()
		life := float64(ProjectileLifeSec)
		if spec, ok := WeaponSpecs[pr.WeaponID]; ok && spec.LifeSec > 0 {
			life = float64(spec.LifeSec)
		}
		if age > life ||
			pr.X < 0 || pr.X > RoomWidth ||
			pr.Y < 0 || pr.Y > RoomHeight ||
			BlocksProjectileAt(r.RoomIndex, pr.X, pr.Y) {
			delete(r.Projectiles, id)
			continue
		}
		for _, e := range r.Enemies {
			if e.AIState == AIDead {
				continue
			}
			if collides(pr.X, pr.Y, e.X, e.Y, 24) {
				hits = append(hits, collisionHit{proj: pr, enemy: e, projID: id})
			}
		}
	}
	return hits
}

func ResolveCollisions(r *RoomState, hits []collisionHit, now time.Time) (deaths []uint32) {

	for _, h := range hits {
		if h.enemy.AIState == AIDead {
			continue
		}
		TakeDamage(h.enemy, h.proj.Damage)
		delete(r.Projectiles, h.projID)

		BroadcastPackAggro(r, h.enemy.X, h.enemy.Y, h.enemy.EntityID)
	}

	for id, e := range r.Enemies {
		if e.AIState != AIDead && e.HP <= 0 {
			e.AIState = AIDead
			deaths = append(deaths, id)
			SpawnCoinDrop(r, e.X, e.Y, now)
		}
	}
	return deaths
}

func collides(ax, ay, bx, by, r float32) bool {
	dx := ax - bx
	dy := ay - by
	return dx*dx+dy*dy < r*r
}

func contains(s []uint8, v uint8) bool {
	for _, x := range s {
		if x == v {
			return true
		}
	}
	return false
}

