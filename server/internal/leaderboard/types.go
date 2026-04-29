package leaderboard

import (
	"time"

	"github.com/greyhats/defcon-game/server/internal/protocol"
)

type CompletedRun struct {
	ReplayID    string
	PlayerID    string
	DisplayName string
	TotalMs     int64
	Splits      []protocol.SplitData
	Seed        int64
	InputLog    []byte
	Checksum    [32]byte
	SubmittedAt time.Time
}

