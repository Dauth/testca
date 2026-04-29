package game

import (
	"embed"
	"encoding/json"
	"fmt"
)

//go:embed tilemaps/*.json
var tilemapsFS embed.FS

const (
	TileSize   float32 = 32
	GridCols   int     = 40
	GridRows   int     = 24
	solidRoom0 uint8   = 0
)

type cellKind uint8

const (
	cellEmpty cellKind = iota
	cellSolid
	cellWater
)

type wallGrid [GridRows][GridCols]cellKind

var wallGrids [12]*wallGrid

var roomWaterGIDs [12]map[int]struct{}

func parseWaterGIDs(m *tiledMap) map[int]struct{} {
	out := map[int]struct{}{}
	for _, ts := range m.Tilesets {
		first := ts.FirstGID
		if first <= 0 {
			first = 1
		}
		for _, t := range ts.Tiles {
			for _, p := range t.Properties {
				if p.Name != "water" || p.Type != "bool" {
					continue
				}
				if v, ok := p.Value.(bool); ok && v {
					out[t.ID+first] = struct{}{}
					break
				}
			}
		}
	}
	return out
}

type tiledLayer struct {
	Name    string        `json:"name"`
	Type    string        `json:"type"`
	Width   int           `json:"width"`
	Height  int           `json:"height"`
	Data    []int         `json:"data"`
	Objects []tiledObject `json:"objects"`
}

type tiledObject struct {
	Name string `json:"name"`

	Type       string              `json:"type"`
	Class      string              `json:"class"`
	X          float32             `json:"x"`
	Y          float32             `json:"y"`
	Properties []tiledTileProperty `json:"properties"`
}

type tiledMap struct {
	Width    int             `json:"width"`
	Height   int             `json:"height"`
	Layers   []tiledLayer    `json:"layers"`
	Tilesets []tiledTilesetR `json:"tilesets"`
}

type tiledTilesetR struct {
	FirstGID int                `json:"firstgid"`
	Tiles    []tiledTilesetTile `json:"tiles"`
}

type tiledTilesetTile struct {
	ID         int                 `json:"id"`
	Properties []tiledTileProperty `json:"properties"`
}

type tiledTileProperty struct {
	Name string `json:"name"`
	Type string `json:"type"`

	Value any `json:"value"`
}

type playerSpawn struct {
	X, Y float32
	ok   bool
}

var playerSpawns [12]playerSpawn

var tilemapPickups [12][]PickupSpawnDef

var tilemapEnemies [12][]EnemySpawnDef

var tilemapWaves [12][]WaveDef

var tilemapDoors [12][]DoorDef

var lockedToUnlockedDoorGID = map[int]int{
	146: 147,
	150: 151,
	154: 155,
}

func init() {
	for i := 1; i <= 10; i++ {
		name := fmt.Sprintf("tilemaps/room-%d.json", i)
		raw, err := tilemapsFS.ReadFile(name)
		if err != nil {
			panic(fmt.Sprintf("walls: read %s: %v", name, err))
		}
		var m tiledMap
		if err := json.Unmarshal(raw, &m); err != nil {
			panic(fmt.Sprintf("walls: parse %s: %v", name, err))
		}

		roomWaterGIDs[i] = parseWaterGIDs(&m)
		wallGrids[i] = parseWallGrid(uint8(i), &m)
		playerSpawns[i] = parsePlayerSpawn(&m)
		tilemapPickups[i] = parseTilemapPickups(uint8(i), &m)
		tilemapEnemies[i], tilemapWaves[i] = parseTilemapEnemiesAndWaves(uint8(i), &m)
		tilemapDoors[i] = parseTilemapDoors(uint8(i), &m)
	}
}

func parsePlayerSpawn(m *tiledMap) playerSpawn {
	for _, L := range m.Layers {
		if L.Type != "objectgroup" {
			continue
		}
		for _, o := range L.Objects {
			if o.Type == "PlayerSpawn" || o.Name == "PlayerSpawn" {
				return playerSpawn{X: o.X, Y: o.Y, ok: true}
			}
		}
	}
	return playerSpawn{}
}

func PlayerSpawnAt(roomIndex uint8) (x, y float32, ok bool) {
	if roomIndex >= uint8(len(playerSpawns)) {
		return 0, 0, false
	}
	s := playerSpawns[roomIndex]
	return s.X, s.Y, s.ok
}

func parseTilemapPickups(roomIndex uint8, m *tiledMap) []PickupSpawnDef {
	var out []PickupSpawnDef
	for _, L := range m.Layers {
		if L.Type != "objectgroup" {
			continue
		}
		for _, o := range L.Objects {
			var t uint8
			switch {
			case o.Type == "Health" || o.Name == "Health":
				t = PickupHealthPotion
			case o.Type == "Ammo" || o.Name == "Ammo":
				t = PickupAmmoCrate
			default:
				continue
			}
			id := uint32(roomIndex)*100 + 50 + uint32(len(out)+1)
			out = append(out, PickupSpawnDef{
				EntityID: id,
				Type:     t,
				X:        o.X,
				Y:        o.Y,
			})
		}
	}
	return out
}

func TilemapPickups(roomIndex uint8) []PickupSpawnDef {
	if int(roomIndex) >= len(tilemapPickups) {
		return nil
	}
	return tilemapPickups[roomIndex]
}

func archetypeFromString(s string) (uint8, bool) {
	switch s {
	case "Grunt":
		return EnemyGrunt, true
	case "Runner":
		return EnemyRunner, true
	case "Tank":
		return EnemyTank, true
	case "Kamikaze":
		return EnemyKamikaze, true
	case "Boss":
		return EnemyBoss, true
	}
	return 0, false
}

func archetypeFromMarker(o tiledObject) (uint8, bool) {
	for _, s := range [3]string{o.Class, o.Type, o.Name} {
		if t, ok := archetypeFromString(s); ok {
			return t, true
		}
	}
	return 0, false
}

func waveSlotFromObject(o tiledObject) (int, bool) {
	for _, p := range o.Properties {
		if p.Name != "wave" {
			continue
		}

		switch v := p.Value.(type) {
		case float64:
			n := int(v)
			if n >= 1 {
				return n, true
			}
		case int:
			if v >= 1 {
				return v, true
			}
		}
		return 0, false
	}
	return 0, false
}

func parseTilemapEnemiesAndWaves(roomIndex uint8, m *tiledMap) ([]EnemySpawnDef, []WaveDef) {
	var initial []EnemySpawnDef
	waveBuckets := map[int][]WaveMobDef{}
	maxSlot := -1
	for _, L := range m.Layers {
		if L.Type != "objectgroup" {
			continue
		}
		for _, o := range L.Objects {
			arch, ok := archetypeFromMarker(o)
			if !ok {
				continue
			}
			if slot1, isWave := waveSlotFromObject(o); isWave {
				slot := slot1 - 1
				waveBuckets[slot] = append(waveBuckets[slot], WaveMobDef{
					Type: arch,
					X:    o.X,
					Y:    o.Y,
				})
				if slot > maxSlot {
					maxSlot = slot
				}
				continue
			}
			id := uint32(roomIndex)*100 + uint32(len(initial)+1)
			initial = append(initial, EnemySpawnDef{
				EntityID: id,
				Type:     arch,
				X:        o.X,
				Y:        o.Y,
			})
		}
	}
	if maxSlot < 0 {
		return initial, nil
	}
	waves := make([]WaveDef, maxSlot+1)
	for slot, mobs := range waveBuckets {
		waves[slot] = WaveDef{Mobs: mobs}
	}
	return initial, waves
}

func TilemapEnemies(roomIndex uint8) []EnemySpawnDef {
	if int(roomIndex) >= len(tilemapEnemies) {
		return nil
	}
	return tilemapEnemies[roomIndex]
}

func TilemapWaves(roomIndex uint8) []WaveDef {
	if int(roomIndex) >= len(tilemapWaves) {
		return nil
	}
	return tilemapWaves[roomIndex]
}

func parseTilemapDoors(roomIndex uint8, m *tiledMap) []DoorDef {
	var out []DoorDef
	for _, L := range m.Layers {
		if L.Type != "tilelayer" || L.Name != "Walls" {
			continue
		}
		if L.Width != GridCols || L.Height != GridRows {
			return nil
		}
		for i, raw := range L.Data {
			if raw == 0 {
				continue
			}
			gid := raw & 0x1FFFFFFF
			unlocked, ok := lockedToUnlockedDoorGID[gid]
			if !ok {
				continue
			}
			col := i % GridCols
			row := i / GridCols
			id := uint32(roomIndex)*100 + 90 + uint32(len(out)+1)
			out = append(out, DoorDef{
				DoorID:      id,
				X:           float32(col)*TileSize + TileSize/2,
				Y:           float32(row)*TileSize + TileSize/2,
				TargetRoom:  roomIndex + 1,
				TileX:       col,
				TileY:       row,
				UnlockedGID: unlocked,
			})
		}
	}
	return out
}

func TilemapDoors(roomIndex uint8) []DoorDef {
	if int(roomIndex) >= len(tilemapDoors) {
		return nil
	}
	return tilemapDoors[roomIndex]
}

func parseWallGrid(roomIndex uint8, m *tiledMap) *wallGrid {
	var g wallGrid
	water := roomWaterGIDs[roomIndex]
	for _, L := range m.Layers {
		if L.Type != "tilelayer" {
			continue
		}
		if L.Name != "Walls" {
			continue
		}
		if L.Width != GridCols || L.Height != GridRows {

			return &g
		}
		for i, tileID := range L.Data {
			if tileID == 0 {
				continue
			}

			gid := tileID & 0x1FFFFFFF
			r := i / GridCols
			c := i % GridCols
			if _, isWater := water[gid]; isWater {
				g[r][c] = cellWater
			} else {
				g[r][c] = cellSolid
			}
		}
	}
	return &g
}

func IsWallAt(roomIndex uint8, x, y float32) bool {
	return cellAt(roomIndex, x, y) != cellEmpty
}

func BlocksProjectileAt(roomIndex uint8, x, y float32) bool {
	return cellAt(roomIndex, x, y) == cellSolid
}

func cellAt(roomIndex uint8, x, y float32) cellKind {
	if roomIndex >= uint8(len(wallGrids)) {
		return cellSolid
	}
	g := wallGrids[roomIndex]
	if g == nil {
		return cellEmpty
	}
	c := int(x / TileSize)
	r := int(y / TileSize)
	if c < 0 || c >= GridCols || r < 0 || r >= GridRows {
		return cellSolid
	}
	return g[r][c]
}

func NearestNonWall(roomIndex uint8, x, y float32) (float32, float32) {
	const hw, hh float32 = 12, 12
	if !BlockedAABB(roomIndex, x, y, hw, hh) {
		return x, y
	}

	startC := int(x / TileSize)
	startR := int(y / TileSize)
	for radius := 1; radius <= 12; radius++ {
		for dr := -radius; dr <= radius; dr++ {
			for dc := -radius; dc <= radius; dc++ {

				if abs(dr) != radius && abs(dc) != radius {
					continue
				}
				r := startR + dr
				c := startC + dc
				if r < 0 || r >= GridRows || c < 0 || c >= GridCols {
					continue
				}
				cx := float32(c)*TileSize + TileSize/2
				cy := float32(r)*TileSize + TileSize/2
				if !BlockedAABB(roomIndex, cx, cy, hw, hh) {
					return cx, cy
				}
			}
		}
	}
	return x, y
}

func abs(v int) int {
	if v < 0 {
		return -v
	}
	return v
}

func BlockedAABB(roomIndex uint8, cx, cy, hw, hh float32) bool {
	if IsWallAt(roomIndex, cx-hw, cy-hh) {
		return true
	}
	if IsWallAt(roomIndex, cx+hw, cy-hh) {
		return true
	}
	if IsWallAt(roomIndex, cx-hw, cy+hh) {
		return true
	}
	if IsWallAt(roomIndex, cx+hw, cy+hh) {
		return true
	}
	return false
}
