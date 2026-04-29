package spectator

import (
	"context"
	"sort"
	"sync"
)

type LiveRegistry struct {
	updateCh chan Summary
	removeCh chan string

	mu       sync.RWMutex
	snapshot []Summary
}

func NewLiveRegistry(maxConcurrent int) *LiveRegistry {
	if maxConcurrent < 1 {
		maxConcurrent = 1
	}
	return &LiveRegistry{
		updateCh: make(chan Summary, maxConcurrent),
		removeCh: make(chan string, maxConcurrent),
	}
}

func (r *LiveRegistry) Start(ctx context.Context) {
	go r.run(ctx)
}

func (r *LiveRegistry) Update(s Summary) {
	if s.PlayerID == "" {
		return
	}
	select {
	case r.updateCh <- s:
	default:
	}
}

func (r *LiveRegistry) Remove(playerID string) {
	if playerID == "" {
		return
	}
	select {
	case r.removeCh <- playerID:
	default:
	}
}

func (r *LiveRegistry) Snapshot() []Summary {
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.snapshot
}

func (r *LiveRegistry) run(ctx context.Context) {
	state := make(map[string]Summary)
	for {
		select {
		case <-ctx.Done():
			return
		case s := <-r.updateCh:
			state[s.PlayerID] = s
			r.publish(state)
		case id := <-r.removeCh:
			if _, ok := state[id]; ok {
				delete(state, id)
				r.publish(state)
			}
		}
	}
}

func (r *LiveRegistry) publish(state map[string]Summary) {
	out := make([]Summary, 0, len(state))
	for _, s := range state {
		out = append(out, s)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ElapsedMs < out[j].ElapsedMs })
	r.mu.Lock()
	r.snapshot = out
	r.mu.Unlock()
}

