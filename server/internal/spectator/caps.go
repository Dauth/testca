package spectator

import (
	"sync"
	"sync/atomic"
	"time"
)

type Caps struct {
	global      int32
	globalCount atomic.Int32

	perIPLimit  int
	perIPWindow time.Duration

	mu     sync.Mutex
	ipHits map[string][]time.Time
}

func NewCaps(globalCap int, perIPLimit int, perIPWindow time.Duration) *Caps {
	return &Caps{
		global:      int32(globalCap),
		perIPLimit:  perIPLimit,
		perIPWindow: perIPWindow,
		ipHits:      make(map[string][]time.Time),
	}
}

func (c *Caps) AcquireGlobal() bool {
	for {
		cur := c.globalCount.Load()
		if cur >= c.global {
			return false
		}
		if c.globalCount.CompareAndSwap(cur, cur+1) {
			return true
		}
	}
}

func (c *Caps) ReleaseGlobal() {
	c.globalCount.Add(-1)
}

func (c *Caps) GlobalCount() int { return int(c.globalCount.Load()) }

func (c *Caps) AllowIP(ip string, now time.Time) bool {
	if ip == "" || c.perIPLimit <= 0 {
		return true
	}
	cutoff := now.Add(-c.perIPWindow)
	c.mu.Lock()
	defer c.mu.Unlock()
	hits := c.ipHits[ip]

	pruned := hits[:0]
	for _, t := range hits {
		if t.After(cutoff) {
			pruned = append(pruned, t)
		}
	}
	if len(pruned) >= c.perIPLimit {
		c.ipHits[ip] = pruned
		return false
	}
	c.ipHits[ip] = append(pruned, now)
	return true
}

