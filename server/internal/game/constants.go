package game

import "time"

const (
	TickHz             = 20
	TickDuration       = 50 * time.Millisecond
	RoomWidth          = 1280
	RoomHeight         = 768
	FinalRoom    uint8 = 10
	BossRoom     uint8 = 10

	SwapCooldownMs = 400

	InteractRange = 2500

	SettleTicks = 2

	PlayerSpeed       float32 = 220
	ProjectileSpeed   float32 = 600
	ProjectileLifeSec float32 = 1.5

	MaxPlayerHP int16 = 100

	SeedWindow = 30 * time.Minute

	TsValidationWindow = 2 * time.Second

	MaxRunDuration = 10 * time.Minute

	IdleTimeout = 90 * time.Second

	ReconcileEveryTicks = 10

	InChBuf  = 64
	OutChBuf = 64

	WaveArmDelayMs = 1500

	WaveArmJitterMs = 1500

	WaveEntityIDBase uint32 = 100000
	WaveEntityIDStep uint32 = 1000

	PackAggroRadius float32 = 250.0
)

var WaveTriggers = []float32{0.66, 0.33}

