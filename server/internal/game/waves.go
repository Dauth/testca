package game

import (
	"math"
	"math/rand"
	"time"
)

func seedWaves(r *RoomState, rng *rand.Rand, waves []WaveDef) {
	for slot, wave := range waves {
		if slot >= len(WaveTriggers) {

			break
		}
		trigger := int(math.Floor(float64(r.InitialPop) * float64(WaveTriggers[slot])))
		if trigger < 1 {

			continue
		}

		jitter := rng.Intn(2*WaveArmJitterMs) - WaveArmJitterMs

		mobs := make([]PrecomputedMob, len(wave.Mobs))
		for i, m := range wave.Mobs {
			mobs[i] = PrecomputedMob{
				Type: m.Type,
				Seed: SeedMob(rng, r.RoomIndex, m.X, m.Y),
			}
		}

		r.PendingWaves = append(r.PendingWaves, PendingWave{
			TriggerRemaining: trigger,
			ArmDelayJitter:   jitter,
			Mobs:             mobs,
		})
	}
}

func livingCount(r *RoomState) int {
	n := 0
	for _, e := range r.Enemies {
		if e.AIState != AIDead && e.HP > 0 {
			n++
		}
	}
	return n
}

func AdvanceWaves(r *RoomState, now time.Time) []uint32 {
	var spawned []uint32

	living := livingCount(r)
	for i := range r.PendingWaves {
		w := &r.PendingWaves[i]
		if w.Armed || w.Fired {
			continue
		}
		if i > 0 && !r.PendingWaves[i-1].Fired {
			continue
		}
		if living <= w.TriggerRemaining {
			w.Armed = true
			w.FireAt = now.Add(time.Duration(WaveArmDelayMs+w.ArmDelayJitter) * time.Millisecond)
		}
	}

	for i := range r.PendingWaves {
		w := &r.PendingWaves[i]
		if !w.Armed || w.Fired {
			continue
		}
		if now.Before(w.FireAt) {
			continue
		}
		if i > 0 && !r.PendingWaves[i-1].Fired {
			continue
		}
		for _, pm := range w.Mobs {
			id := r.NextEnemyID
			r.NextEnemyID++
			r.Enemies[id] = InstantiateEnemy(r.RoomIndex, id, pm.Type, pm.Seed, now)
			spawned = append(spawned, id)
		}
		w.Fired = true
	}

	return spawned
}

func AllWavesFired(r *RoomState) bool {
	for _, w := range r.PendingWaves {
		if !w.Fired {
			return false
		}
	}
	return true
}

