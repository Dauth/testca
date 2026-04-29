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
	mux.HandleFunc("/api/login", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotImplemented)
		_, _ = w.Write([]byte("identity stub"))
	})
	mux.HandleFunc("/api/register", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotImplemented)
		_, _ = w.Write([]byte("identity stub"))
	})
	mux.HandleFunc("/api/verify", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotImplemented)
		_, _ = w.Write([]byte("identity stub"))
	})
}
