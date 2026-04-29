// Package identity is a STUB shipped with the published source so that
// server/ compiles and runs locally for puzzle research. The real
// pkg/identity is not published — see
// docs/specs/foundations/09-ci-cd-deploy.md#what-is-not-published.
//
// This stub accepts every player_id as registered with DisplayName equal
// to the player_id. It performs no authentication, no rate limiting, and
// no persistence. Do not deploy.
package identity

import (
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net/http"

	_ "modernc.org/sqlite"
)

var ErrNotFound = errors.New("identity: player not found")

type Player struct {
	DisplayName string
}

type Service struct {
	db *sql.DB
}

func OpenDB(_ string) (*sql.DB, error) {
	log.Println("identity: STUB build — every player_id is accepted, no auth")
	return sql.Open("sqlite", ":memory:")
}

func Lookup(_ *sql.DB, playerID string) (*Player, error) {
	return &Player{DisplayName: playerID}, nil
}

func NewService(db *sql.DB) *Service {
	return &Service{db: db}
}

func (s *Service) Register(mux *http.ServeMux) {
	_ = s
	mux.HandleFunc("/api/config", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]bool{
			"leaderboard_enabled": true,
			"queue_enabled":       false,
		})
	})
	mux.HandleFunc("/api/login", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			Username string `json:"username"`
			Password string `json:"password"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.Username == "" || req.Password == "" {
			http.Error(w, `{"error":"missing username or password"}`, http.StatusBadRequest)
			return
		}
		writeJSON(w, map[string]string{
			"player_id":    req.Username,
			"display_name": req.Username,
		})
	})
	mux.HandleFunc("/api/register", func(w http.ResponseWriter, r *http.Request) {
		var req struct {
			DisplayName string `json:"display_name"`
			Password    string `json:"password"`
		}
		if err := json.NewDecoder(r.Body).Decode(&req); err != nil || req.DisplayName == "" || req.Password == "" {
			http.Error(w, `{"error":"missing display_name or password"}`, http.StatusBadRequest)
			return
		}
		writeJSON(w, map[string]string{
			"player_id":    req.DisplayName,
			"display_name": req.DisplayName,
		})
	})
	mux.HandleFunc("/api/verify", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]bool{"ok": true})
	})
	mux.HandleFunc("/api/queue/join", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]any{
			"position":    0,
			"est_wait_ms": 0,
			"admitted":    true,
		})
	})
	mux.HandleFunc("/api/queue/status/", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]any{
			"position":    0,
			"est_wait_ms": 0,
			"admitted":    true,
		})
	})
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		http.Error(w, `{"error":"encode response"}`, http.StatusInternalServerError)
	}
}
