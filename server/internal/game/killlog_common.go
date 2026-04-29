package game

import "time"

func CheckRoomClear(r *RoomState) bool {
	return len(r.KillLog) >= len(r.Enemies)
}

func ReconcileKillLog(r *RoomState) {
	if !AllWavesFired(r) {
		return
	}
	actualDead := 0
	for _, e := range r.Enemies {
		if e.HP <= 0 || e.AIState == AIDead {
			actualDead++
		}
	}
	if len(r.Enemies) > 0 && actualDead >= len(r.Enemies) {
		r.AllEnemiesDead = true
	}
}

func ComputeRoomBonus(log []KillRecord) int64 {
	if len(log) == 0 {
		return 0
	}
	duration := log[len(log)-1].Timestamp.Sub(log[0].Timestamp)

	if duration < 0 {
		return int64(duration/time.Millisecond) - 500
	}
	if duration < 2*time.Second {
		return -500
	}
	return 0
}

