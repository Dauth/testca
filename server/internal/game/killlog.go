package game

import "time"

func ProcessEnemyDeathAsync(r *RoomState, entityID uint32) {
	r.KillLog = append(r.KillLog, KillRecord{
		EntityID:  entityID,
		Timestamp: time.Now(),
	})
}

