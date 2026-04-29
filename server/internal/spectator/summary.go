package spectator

type Summary struct {
	PlayerID       string `json:"player_id"`
	DisplayName    string `json:"display_name"`
	RoomIndex      uint8  `json:"room_index"`
	ElapsedMs      int64  `json:"elapsed_ms"`
	SpectatorCount int    `json:"spectator_count"`

	StartedAt int64 `json:"started_at"`
}

