package spectator

import "sync"

type Engines struct {
	mu sync.RWMutex
	m  map[string]chan<- Req
}

func NewEngines() *Engines {
	return &Engines{m: make(map[string]chan<- Req)}
}

func (r *Engines) Register(playerID string, ch chan<- Req) {
	if playerID == "" {
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	r.m[playerID] = ch
}

func (r *Engines) Unregister(playerID string) {
	if playerID == "" {
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	delete(r.m, playerID)
}

func (r *Engines) Lookup(playerID string) (chan<- Req, bool) {
	r.mu.RLock()
	defer r.mu.RUnlock()
	ch, ok := r.m[playerID]
	return ch, ok
}

