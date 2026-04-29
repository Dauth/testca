package game

import (
	"math/rand"
	"time"

	"github.com/greyhats/defcon-game/server/internal/protocol"
)

type RoomTemplate struct {
	TilemapID string
}

type EnemySpawnDef struct {
	EntityID uint32
	Type     uint8
	X, Y     float32
}

type WaveDef struct {
	Mobs []WaveMobDef
}

type WaveMobDef struct {
	Type uint8
	X, Y float32
}

type PickupSpawnDef struct {
	EntityID uint32
	Type     uint8
	X, Y     float32
}

type DoorDef struct {
	DoorID       uint32
	X, Y         float32
	TargetRoom   uint8
	TileX, TileY int
	UnlockedGID  int
}

func HandleEnterDoor(p *PlayerState, r *RoomState, doorID uint32) (nextRoom uint8, ok bool) {
	_ = p
	door, exists := r.Doors[doorID]
	if !exists {
		return 0, false
	}
	if !door.Unlocked {
		return 0, false
	}
	return door.TargetRoom, true
}

func UnlockDoorsIfClear(r *RoomState) []*DoorState {
	if !r.AllEnemiesDead {
		return nil
	}
	var transitioned []*DoorState
	for _, d := range r.Doors {
		if !d.Unlocked {
			d.Unlocked = true
			transitioned = append(transitioned, d)
		}
	}
	return transitioned
}

func CheckAllEnemiesDead(r *RoomState) {
	if !AllWavesFired(r) {
		return
	}
	for _, e := range r.Enemies {
		if e.HP > 0 && e.AIState != AIDead {
			return
		}
	}
	r.AllEnemiesDead = true
}

func LoadRoom(r *RoomState, rng *rand.Rand, tmpl *RoomTemplate, enemies []EnemySpawnDef, waves []WaveDef, now time.Time) protocol.RoomData {

	r.Enemies = map[uint32]*EnemyState{}
	r.Pickups = map[uint32]*PickupState{}
	r.Projectiles = map[uint32]*ProjectileState{}
	r.Doors = map[uint32]*DoorState{}
	r.AllEnemiesDead = false
	r.Settled = false
	r.TicksSinceLoad = 0
	r.KillLog = r.KillLog[:0]
	r.PendingWaves = r.PendingWaves[:0]
	r.NextEnemyID = WaveEntityIDBase + uint32(r.RoomIndex)*WaveEntityIDStep

	ordered := make([]EnemySpawnDef, len(enemies))
	copy(ordered, enemies)
	sortEnemySpawnsByID(ordered)

	enemyOut := make([]protocol.EnemySpawn, 0, len(ordered))
	for _, def := range ordered {
		e := SpawnEnemy(rng, r.RoomIndex, def.EntityID, def.Type, def.X, def.Y, now)
		r.Enemies[def.EntityID] = e
		enemyOut = append(enemyOut, protocol.EnemySpawn{
			EntityID: e.EntityID,
			Type:     e.Type,
			X:        e.X,
			Y:        e.Y,
			HP:       e.HP,
		})
	}

	r.InitialPop = len(ordered)
	seedWaves(r, rng, waves)

	pickups := TilemapPickups(r.RoomIndex)
	pickupOut := make([]protocol.PickupSpawn, 0, len(pickups))
	for _, def := range pickups {
		r.Pickups[def.EntityID] = &PickupState{
			EntityID: def.EntityID,
			Type:     def.Type,
			X:        def.X,
			Y:        def.Y,
		}
		pickupOut = append(pickupOut, protocol.PickupSpawn{
			EntityID: def.EntityID,
			Type:     def.Type,
			X:        def.X,
			Y:        def.Y,
		})
	}

	doors := TilemapDoors(r.RoomIndex)
	doorOut := make([]protocol.DoorDef, 0, len(doors))
	for _, def := range doors {
		r.Doors[def.DoorID] = &DoorState{
			DoorID:      def.DoorID,
			X:           def.X,
			Y:           def.Y,
			TargetRoom:  def.TargetRoom,
			Unlocked:    false,
			TileX:       def.TileX,
			TileY:       def.TileY,
			UnlockedGID: def.UnlockedGID,
		}
		doorOut = append(doorOut, protocol.DoorDef{
			DoorID:      def.DoorID,
			X:           def.X,
			Y:           def.Y,
			TargetRoom:  def.TargetRoom,
			Locked:      true,
			TileX:       def.TileX,
			TileY:       def.TileY,
			UnlockedGID: def.UnlockedGID,
		})
	}

	return protocol.RoomData{
		RoomIndex: r.RoomIndex,
		TilemapID: tmpl.TilemapID,
		Enemies:   enemyOut,
		Pickups:   pickupOut,
		Doors:     doorOut,
	}
}

func sortEnemySpawnsByID(xs []EnemySpawnDef) {
	for i := 1; i < len(xs); i++ {
		j := i
		for j > 0 && xs[j-1].EntityID > xs[j].EntityID {
			xs[j-1], xs[j] = xs[j], xs[j-1]
			j--
		}
	}
}

