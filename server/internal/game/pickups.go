package game

import (
	"math"
	"time"
)

const (
	PickupHealthPotion uint8 = 1
	PickupAmmoCrate    uint8 = 2

	PickupCoin uint8 = 3
)

const CoinDespawnDuration = 30 * time.Second

func HandleInteract(p *PlayerState, r *RoomState, targetID uint32, claimedType uint8, now time.Time) (consumed *PickupState) {
	pickup, ok := r.Pickups[targetID]
	if !ok || pickup.Consumed {
		return nil
	}
	dx := pickup.X - p.X
	dy := pickup.Y - p.Y
	if math.Abs(float64(dx)) < InteractRange && math.Abs(float64(dy)) < InteractRange {
		applyPickup(p, pickup, claimedType, now)
		pickup.Consumed = true
		return pickup
	}
	return nil
}

func applyPickup(p *PlayerState, pk *PickupState, claimedType uint8, _ time.Time) {
	_ = pk
	switch claimedType {
	case PickupHealthPotion:
		ApplyHeal(p, 20)
	case PickupAmmoCrate:
		spec, ok := WeaponSpecs[p.CurrentWeapon]
		if ok {
			cur := p.WeaponAmmo[p.CurrentWeapon]
			cur += 20
			if cur > spec.AmmoMax {
				cur = spec.AmmoMax
			}
			p.WeaponAmmo[p.CurrentWeapon] = cur
		}
	case PickupCoin:
		p.Coins++
	}
}

func SpawnCoinDrop(r *RoomState, x, y float32, now time.Time) uint32 {
	id := r.NextEntityID()
	r.Pickups[id] = &PickupState{
		EntityID:  id,
		Type:      PickupCoin,
		X:         x,
		Y:         y,
		ExpiresAt: now.Add(CoinDespawnDuration),
	}
	return id
}

