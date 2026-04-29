package leaderboard

import (
	"context"
	"database/sql"
	"fmt"
	"log"
	"sync"

	"github.com/greyhats/defcon-game/server/internal/protocol"
)

const TopBroadcastN = 10

type Service struct {
	db       *sql.DB
	inCh     chan submitReq
	mu       sync.RWMutex
	outChans map[string]chan<- protocol.S2CEnvelope
}

type submitReq struct {
	run    *CompletedRun
	result chan SubmitResult
}

type SubmitResult struct {
	Entries []protocol.LeaderboardEntry
	Rank    int
	Err     error
}

func NewService(db *sql.DB) *Service {
	return &Service{
		db:       db,
		inCh:     make(chan submitReq, 128),
		outChans: make(map[string]chan<- protocol.S2CEnvelope),
	}
}

func (s *Service) Start(ctx context.Context) {
	go s.run(ctx)
}

func (s *Service) Submit(run *CompletedRun) bool {
	select {
	case s.inCh <- submitReq{run: run}:
		return true
	default:
		return false
	}
}

func (s *Service) SubmitAndRefresh(run *CompletedRun) SubmitResult {
	result := make(chan SubmitResult, 1)
	select {
	case s.inCh <- submitReq{run: run, result: result}:
	default:
		return SubmitResult{Err: fmt.Errorf("leaderboard: submit queue full")}
	}
	return <-result
}

func (s *Service) Register(playerID string, ch chan<- protocol.S2CEnvelope) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.outChans[playerID] = ch
}

func (s *Service) Unregister(playerID string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.outChans, playerID)
}

func (s *Service) Top(n int) []protocol.LeaderboardEntry {
	entries, err := TopRuns(s.db, n)
	if err != nil {
		log.Printf("leaderboard: top: %v", err)
		return nil
	}
	return entries
}

func (s *Service) run(ctx context.Context) {
	for {
		select {
		case <-ctx.Done():
			return
		case req, ok := <-s.inCh:
			if !ok {
				return
			}
			result := s.handleSubmit(req.run)
			if req.result != nil {
				req.result <- result
			}
			if result.Err == nil {
				s.broadcast(result.Entries)
			}
		}
	}
}

func (s *Service) handleSubmit(run *CompletedRun) SubmitResult {
	if run == nil {
		return SubmitResult{Err: fmt.Errorf("leaderboard: nil run")}
	}
	if err := InsertRun(s.db, run); err != nil {
		log.Printf("leaderboard: insert run %s: %v", run.ReplayID, err)
		return SubmitResult{Err: err}
	}
	entries, err := TopRuns(s.db, TopBroadcastN)
	if err != nil {
		log.Printf("leaderboard: refresh top: %v", err)
		return SubmitResult{Err: err}
	}
	rank, err := RankOfRun(s.db, run.ReplayID)
	if err != nil {
		log.Printf("leaderboard: rank run %s: %v", run.ReplayID, err)
		return SubmitResult{Err: err}
	}
	return SubmitResult{Entries: entries, Rank: rank}
}

func (s *Service) broadcast(entries []protocol.LeaderboardEntry) {
	env := protocol.NewS2C(
		protocol.S2CLeaderboard,
		0,
		protocol.LeaderboardData{Entries: entries},
	)
	s.mu.RLock()
	defer s.mu.RUnlock()
	for _, ch := range s.outChans {
		select {
		case ch <- env:
		default:

		}
	}
}

