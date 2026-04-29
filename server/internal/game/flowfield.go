package game

const FlowFieldSentinel uint16 = 0xFFFF

type FlowField [GridRows][GridCols]uint16

var flowNeighbours = [8]struct{ dr, dc int }{
	{-1, 0},
	{-1, 1},
	{0, 1},
	{1, 1},
	{1, 0},
	{1, -1},
	{0, -1},
	{-1, -1},
}

func TileOf(x, y float32) (int, int) {
	c := int(x / TileSize)
	r := int(y / TileSize)
	if c < 0 {
		c = 0
	} else if c >= GridCols {
		c = GridCols - 1
	}
	if r < 0 {
		r = 0
	} else if r >= GridRows {
		r = GridRows - 1
	}
	return r, c
}

func TileCenter(r, c int) (x, y float32) {
	return float32(c)*TileSize + TileSize/2, float32(r)*TileSize + TileSize/2
}

func tileIsWall(roomIndex uint8, r, c int) bool {
	if r < 0 || r >= GridRows || c < 0 || c >= GridCols {
		return true
	}
	if roomIndex >= uint8(len(wallGrids)) {
		return true
	}
	g := wallGrids[roomIndex]
	if g == nil {
		return false
	}
	return g[r][c] != cellEmpty
}

func BFSFromTile(roomIndex uint8, sr, sc int) *FlowField {
	f := &FlowField{}
	for r := 0; r < GridRows; r++ {
		for c := 0; c < GridCols; c++ {
			f[r][c] = FlowFieldSentinel
		}
	}
	if sr < 0 || sr >= GridRows || sc < 0 || sc >= GridCols {
		return f
	}
	if tileIsWall(roomIndex, sr, sc) {
		return f
	}

	type cell struct{ r, c int }
	queue := make([]cell, 0, GridRows*GridCols)
	queue = append(queue, cell{sr, sc})
	f[sr][sc] = 0
	for head := 0; head < len(queue); head++ {
		cur := queue[head]
		d := f[cur.r][cur.c]
		for _, n := range flowNeighbours {
			nr, nc := cur.r+n.dr, cur.c+n.dc
			if nr < 0 || nr >= GridRows || nc < 0 || nc >= GridCols {
				continue
			}
			if tileIsWall(roomIndex, nr, nc) {
				continue
			}
			if n.dr != 0 && n.dc != 0 {
				if tileIsWall(roomIndex, cur.r+n.dr, cur.c) || tileIsWall(roomIndex, cur.r, cur.c+n.dc) {
					continue
				}
			}
			if f[nr][nc] != FlowFieldSentinel {
				continue
			}
			f[nr][nc] = d + 1
			queue = append(queue, cell{nr, nc})
		}
	}
	return f
}

func NextStepTile(f *FlowField, roomIndex uint8, mr, mc int) (int, int) {
	if f == nil || mr < 0 || mr >= GridRows || mc < 0 || mc >= GridCols {
		return mr, mc
	}
	best := f[mr][mc]
	br, bc := mr, mc
	for _, n := range flowNeighbours {
		nr, nc := mr+n.dr, mc+n.dc
		if nr < 0 || nr >= GridRows || nc < 0 || nc >= GridCols {
			continue
		}
		if n.dr != 0 && n.dc != 0 {
			if tileIsWall(roomIndex, mr+n.dr, mc) || tileIsWall(roomIndex, mr, mc+n.dc) {
				continue
			}
		}
		d := f[nr][nc]
		if d < best {
			best = d
			br, bc = nr, nc
		}
	}
	return br, bc
}

func BiasedPlayerTile(playerR, playerC int, jX, jY float32, roomIndex uint8) (int, int) {
	dr, dc := 0, 0
	if jX < 0.25 {
		dc = -1
	} else if jX > 0.75 {
		dc = 1
	}
	if jY < 0.25 {
		dr = -1
	} else if jY > 0.75 {
		dr = 1
	}
	r, c := playerR+dr, playerC+dc
	return nearestNonWallTile(roomIndex, r, c)
}

func nearestNonWallTile(roomIndex uint8, r, c int) (int, int) {
	if !tileIsWall(roomIndex, r, c) {
		return r, c
	}
	for radius := 1; radius <= 12; radius++ {
		for dr := -radius; dr <= radius; dr++ {
			for dc := -radius; dc <= radius; dc++ {
				if abs(dr) != radius && abs(dc) != radius {
					continue
				}
				nr, nc := r+dr, c+dc
				if !tileIsWall(roomIndex, nr, nc) {
					return nr, nc
				}
			}
		}
	}
	return r, c
}

type FlowFieldCache struct {
	roomIndex uint8
	fields    map[int]*FlowField
}

func NewFlowFieldCache(roomIndex uint8) *FlowFieldCache {
	return &FlowFieldCache{
		roomIndex: roomIndex,
		fields:    map[int]*FlowField{},
	}
}

func (c *FlowFieldCache) Get(sr, sc int) *FlowField {
	if c == nil {
		return BFSFromTile(0, sr, sc)
	}
	key := sr*GridCols + sc
	if f, ok := c.fields[key]; ok {
		return f
	}
	f := BFSFromTile(c.roomIndex, sr, sc)
	c.fields[key] = f
	return f
}

