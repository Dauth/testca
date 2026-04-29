package auth

import (
	"encoding/json"
	"errors"
	"os"
	"sync"
	"time"
)

type Allowlist struct {
	path             string
	mu               sync.Mutex
	ids              map[string]struct{}
	read             time.Time
	forced           time.Time
	ttl              time.Duration
	forceMinInterval time.Duration
}

func NewAllowlist(path string) *Allowlist {
	return &Allowlist{
		path:             path,
		ttl:              2 * time.Second,
		forceMinInterval: 250 * time.Millisecond,
	}
}

func (a *Allowlist) Has(playerID string) bool {
	a.mu.Lock()
	defer a.mu.Unlock()
	_ = a.refresh(false)
	if a.ids == nil {
		return false
	}
	if _, ok := a.ids[playerID]; ok {
		return true
	}

	if time.Since(a.forced) < a.forceMinInterval {
		return false
	}
	if err := a.refresh(true); err != nil {
		return false
	}
	a.forced = time.Now()
	if a.ids == nil {
		return false
	}
	_, ok := a.ids[playerID]
	return ok
}

func (a *Allowlist) refresh(force bool) error {
	if !force && a.ids != nil && time.Since(a.read) <= a.ttl {
		return nil
	}
	data, err := os.ReadFile(a.path)
	if err != nil {
		if os.IsNotExist(err) {
			a.ids = map[string]struct{}{}
			a.read = time.Now()
			return nil
		}
		return err
	}
	var parsed struct {
		Allowed []string `json:"allowed"`
	}
	if err := json.Unmarshal(data, &parsed); err != nil {
		return err
	}
	ids := make(map[string]struct{}, len(parsed.Allowed))
	for _, id := range parsed.Allowed {
		ids[id] = struct{}{}
	}
	a.ids = ids
	a.read = time.Now()
	return nil
}

func Check(mode Mode, a *Allowlist, playerID string) error {
	if mode == ModeOpen {
		return nil
	}
	if a == nil {
		return errors.New("allowlist not configured")
	}
	if !a.Has(playerID) {
		return errors.New("player not on allowlist")
	}
	return nil
}

