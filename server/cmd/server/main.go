package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"regexp"
	"strconv"
	"strings"
	"syscall"
	"time"

	"github.com/coder/websocket"

	"github.com/greyhats/defcon-game/pkg/identity"
	"github.com/greyhats/defcon-game/pkg/replayauth"
	"github.com/greyhats/defcon-game/server/internal/auth"
	"github.com/greyhats/defcon-game/server/internal/game"
	"github.com/greyhats/defcon-game/server/internal/leaderboard"
	"github.com/greyhats/defcon-game/server/internal/metrics"
	"github.com/greyhats/defcon-game/server/internal/protocol"
	"github.com/greyhats/defcon-game/server/internal/replay"
	"github.com/greyhats/defcon-game/server/internal/spectator"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lmicroseconds)
	addr := envDefault("LISTEN_ADDR", ":8080")
	dbPath := envDefault("GAME_DB", "game.db")
	identityDBPath := envDefault("IDENTITY_DB", "identity.db")
	allowlistPath := envDefault("ALLOWLIST_PATH", "/data/allowlist.json")
	maxConcurrent := envInt("MAX_CONCURRENT", 64)
	spectatorGlobal := envInt("SPECTATOR_GLOBAL", 200)
	spectatorPerIP := envInt("SPECTATOR_PER_IP", 5)
	replayGlobal := envInt("REPLAY_GLOBAL", 16)
	replayPerIP := envInt("REPLAY_PER_IP", 5)

	adminSecret := []byte(os.Getenv("ADMIN_SESSION_SECRET"))

	leaderboardEnabled := !strings.EqualFold(os.Getenv("LEADERBOARD_ENABLED"), "false")

	var db *sql.DB
	if leaderboardEnabled {
		var err error
		db, err = leaderboard.OpenDB(dbPath)
		if err != nil {
			log.Fatalf("open db: %v", err)
		}
		defer db.Close()
	}

	identityDB, err := identity.OpenDB(identityDBPath)
	if err != nil {
		log.Fatalf("open identity db: %v", err)
	}
	defer identityDB.Close()

	mode := auth.ModeFromEnv()
	switch mode {
	case auth.ModeOpen:
		log.Printf("auth mode: open")
		metrics.AuthModeInfo.WithLabelValues("open").Set(1)
	case auth.ModeToken:
		log.Printf("auth mode: token (allowlist=%s)", allowlistPath)
		metrics.AuthModeInfo.WithLabelValues("token").Set(1)
	case auth.ModeIdentity:
		log.Printf("auth mode: identity (db=%s)", identityDBPath)
		metrics.AuthModeInfo.WithLabelValues("identity").Set(1)
	}
	metrics.ConcurrentCap.Set(float64(maxConcurrent))
	if !leaderboardEnabled {
		log.Printf("leaderboard: disabled (LEADERBOARD_ENABLED=false)")
	} else if len(adminSecret) >= 16 {
		log.Printf("leaderboard: enabled; replay viewer: enabled (global=%d per_ip=%d)", replayGlobal, replayPerIP)
	} else {
		log.Printf("leaderboard: enabled; replay viewer: disabled (ADMIN_SESSION_SECRET unset; /ws/replay returns 503)")
	}

	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()

	var lbSvc *leaderboard.Service
	if leaderboardEnabled {
		lbSvc = leaderboard.NewService(db)
		lbSvc.Start(ctx)
	}

	liveReg := spectator.NewLiveRegistry(maxConcurrent)
	liveReg.Start(ctx)

	engineReg := spectator.NewEngines()
	specCaps := spectator.NewCaps(spectatorGlobal, spectatorPerIP, time.Minute)

	replayCaps := spectator.NewCaps(replayGlobal, replayPerIP, time.Minute)

	allowlist := auth.NewAllowlist(allowlistPath)

	authCheck := buildAuthCheck(mode, identityDB, allowlist)

	sem := make(chan struct{}, maxConcurrent)

	mux := http.NewServeMux()
	mux.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		handleWS(ctx, w, r, sem, authCheck, lbSvc, liveReg, engineReg)
	})
	mux.HandleFunc("/ws/spectate", func(w http.ResponseWriter, r *http.Request) {
		handleSpectateWS(ctx, w, r, engineReg, specCaps)
	})
	if leaderboardEnabled {

		mux.HandleFunc("/ws/replay", func(w http.ResponseWriter, r *http.Request) {
			handleReplayWS(ctx, w, r, db, adminSecret, replayCaps)
		})
	}
	mux.HandleFunc("/internal/slot-status", func(w http.ResponseWriter, r *http.Request) {
		if !gateInternal(w, r) {
			return
		}
		used := len(sem)
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"used":` + strconv.Itoa(used) + `,"max":` + strconv.Itoa(maxConcurrent) + `}`))
	})
	mux.HandleFunc("/internal/live-games", func(w http.ResponseWriter, r *http.Request) {
		if !gateInternal(w, r) {
			return
		}

		entries := liveReg.Snapshot()
		if entries == nil {
			entries = []spectator.Summary{}
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(entries)
	})
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte("ok"))
	})

	mux.Handle("/metrics", metrics.Handler())

	if envDefault("DEV_MOUNT_IDENTITY", "") != "" {
		identity.NewService(identityDB).Register(mux)
		log.Printf("dev: mounted identity routes (/api/login, /api/register, /api/verify)")
	}

	srv := &http.Server{
		Addr:              addr,
		Handler:           mux,
		ReadHeaderTimeout: 10 * time.Second,
	}

	go func() {
		log.Printf("listening on %s", addr)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("listen: %v", err)
		}
	}()

	<-ctx.Done()
	log.Printf("shutting down")
	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer shutdownCancel()
	_ = srv.Shutdown(shutdownCtx)
}

func buildAuthCheck(mode auth.Mode, identityDB *sql.DB, allowlist *auth.Allowlist) func(string) (string, error) {
	return func(playerID string) (string, error) {
		switch mode {
		case auth.ModeIdentity:
			return lookupDisplayName(identityDB, playerID)
		case auth.ModeToken:
			if err := auth.Check(mode, allowlist, playerID); err != nil {
				return "", err
			}
			return lookupDisplayName(identityDB, playerID)
		default:
			return "", auth.Check(mode, allowlist, playerID)
		}
	}
}

var errAuthUnavailable = errors.New("auth unavailable")

func lookupDisplayName(identityDB *sql.DB, playerID string) (string, error) {
	p, err := identity.Lookup(identityDB, playerID)
	if err != nil {
		if errors.Is(err, identity.ErrNotFound) {
			return "", errors.New("player not registered")
		}
		log.Printf("auth: identity lookup for %s: %v", playerID, err)
		return "", errAuthUnavailable
	}
	return p.DisplayName, nil
}

func handleWS(ctx context.Context, w http.ResponseWriter, r *http.Request, sem chan struct{}, authCheck func(string) (string, error), lb *leaderboard.Service, liveReg *spectator.LiveRegistry, engineReg *spectator.Engines) {
	select {
	case sem <- struct{}{}:
		metrics.SlotInUse.Set(float64(len(sem)))
	default:
		http.Error(w, "server full", http.StatusServiceUnavailable)
		return
	}
	releaseSlot := func() {
		<-sem
		metrics.SlotInUse.Set(float64(len(sem)))
	}

	conn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true,
	})
	if err != nil {
		releaseSlot()
		metrics.Errors.WithLabelValues("ws_accept").Inc()
		log.Printf("ws accept: %v", err)
		return
	}
	metrics.WSConnsActive.Inc()

	connCtx, cancel := context.WithCancel(ctx)

	inCh := make(chan []byte, game.InChBuf)
	outCh := make(chan protocol.S2CEnvelope, game.OutChBuf)

	var submit func(*leaderboard.CompletedRun) bool
	if lb != nil {
		submit = lb.Submit
	}
	engine := game.NewEngine(inCh, outCh, submit, authCheck)
	if lb != nil {
		engine.SubmitAndRefresh = lb.SubmitAndRefresh
		engine.RegisterLeaderboard = func(playerID string) {
			lb.Register(playerID, outCh)
			entries := lb.Top(leaderboard.TopBroadcastN)
			if entries == nil {
				return
			}
			select {
			case outCh <- protocol.NewS2C(
				protocol.S2CLeaderboard,
				0,
				protocol.LeaderboardData{Entries: entries},
			):
			default:
			}
		}
	}
	engine.Live = liveReg
	engine.Engines = engineReg

	writerDone := make(chan struct{})
	go connReader(connCtx, conn, inCh, cancel)
	go func() {
		defer close(writerDone)
		connWriter(connCtx, conn, outCh, cancel)
	}()

	go func() {
		defer cancel()
		defer releaseSlot()
		defer metrics.WSConnsActive.Dec()

		engine.Run(connCtx)

		if engine.PlayerID != "" {
			if lb != nil {
				lb.Unregister(engine.PlayerID)
			}
			liveReg.Remove(engine.PlayerID)
		}

		close(outCh)
		select {
		case <-writerDone:
		case <-time.After(500 * time.Millisecond):
		}
		conn.Close(websocket.StatusNormalClosure, "bye")
	}()
}

const SpectatorPingInterval = 30 * time.Second

const SpectatorPingTimeout = 10 * time.Second

const SpectatorRegisterTimeout = 1 * time.Second

func gateInternal(w http.ResponseWriter, r *http.Request) bool {
	if r.Method != http.MethodGet {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return false
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	if !isPrivatePeer(host) {
		http.Error(w, "forbidden", http.StatusForbidden)
		return false
	}
	return true
}

func handleSpectateWS(ctx context.Context, w http.ResponseWriter, r *http.Request, engineReg *spectator.Engines, caps *spectator.Caps) {
	playerID := r.URL.Query().Get("player_id")
	if playerID == "" {
		http.Error(w, "player_id required", http.StatusBadRequest)
		return
	}

	if !caps.AllowIP(clientIP(r), time.Now()) {
		w.Header().Set("Retry-After", "60")
		http.Error(w, "rate limited", http.StatusTooManyRequests)
		return
	}

	if !caps.AcquireGlobal() {
		w.Header().Set("Retry-After", "5")
		http.Error(w, "spectator capacity reached", http.StatusServiceUnavailable)
		return
	}

	registerCh, ok := engineReg.Lookup(playerID)
	if !ok {
		caps.ReleaseGlobal()
		http.Error(w, "no live run for player_id", http.StatusNotFound)
		return
	}

	conn := spectator.NewConn()
	bestEffortDeregister := func() {
		select {
		case registerCh <- spectator.Req{Action: spectator.ActionDeregister, Conn: conn}:
		default:
		}
	}

	reply := make(chan bool, 1)
	select {
	case registerCh <- spectator.Req{Action: spectator.ActionRegister, Conn: conn, Reply: reply}:
	case <-time.After(SpectatorRegisterTimeout):
		caps.ReleaseGlobal()
		http.Error(w, "engine busy", http.StatusServiceUnavailable)
		return
	case <-ctx.Done():
		caps.ReleaseGlobal()
		http.Error(w, "shutting down", http.StatusServiceUnavailable)
		return
	}

	var accepted bool
	select {
	case accepted = <-reply:
	case <-time.After(SpectatorRegisterTimeout):
		bestEffortDeregister()
		caps.ReleaseGlobal()
		http.Error(w, "engine busy", http.StatusServiceUnavailable)
		return
	case <-ctx.Done():
		bestEffortDeregister()
		caps.ReleaseGlobal()
		http.Error(w, "shutting down", http.StatusServiceUnavailable)
		return
	}
	if !accepted {
		caps.ReleaseGlobal()
		w.Header().Set("Retry-After", "5")
		http.Error(w, "spectator capacity reached", http.StatusServiceUnavailable)
		return
	}

	wsConn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true,
	})
	if err != nil {
		log.Printf("spectate accept: %v", err)
		bestEffortDeregister()
		caps.ReleaseGlobal()
		return
	}
	metrics.SpectatorConnsActive.Inc()

	connCtx, cancel := context.WithCancel(ctx)

	go func() {
		defer cancel()
		wsConn.SetReadLimit(1024)
		for {
			_, _, readErr := wsConn.Read(connCtx)
			if readErr != nil {
				return
			}
			env := protocol.NewS2C(protocol.S2CError, 0, protocol.ErrorData{
				Code:    "SPECTATOR_READ_ONLY",
				Message: "spectator connections are read-only",
			})
			if raw, mErr := json.Marshal(env); mErr == nil {
				_ = wsConn.Write(connCtx, websocket.MessageText, raw)
			}
			_ = wsConn.Close(websocket.StatusPolicyViolation, "spectator_read_only")
			return
		}
	}()

	go func() {
		defer cancel()
		t := time.NewTicker(SpectatorPingInterval)
		defer t.Stop()
		for {
			select {
			case <-connCtx.Done():
				return
			case <-t.C:
				pingCtx, pingCancel := context.WithTimeout(connCtx, SpectatorPingTimeout)
				pingErr := wsConn.Ping(pingCtx)
				pingCancel()
				if pingErr != nil {
					return
				}
			}
		}
	}()

	go func() {
		defer cancel()
		defer caps.ReleaseGlobal()
		defer metrics.SpectatorConnsActive.Dec()
		defer wsConn.Close(websocket.StatusNormalClosure, "bye")
		defer bestEffortDeregister()
		for {
			select {
			case <-connCtx.Done():
				return
			case env, ok := <-conn.OutCh:
				if !ok {
					return
				}
				raw, err := json.Marshal(env)
				if err != nil {
					continue
				}
				if err := wsConn.Write(connCtx, websocket.MessageText, raw); err != nil {
					return
				}
			}
		}
	}()
}

var uuidPattern = regexp.MustCompile(`^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$`)

func handleReplayWS(parent context.Context, w http.ResponseWriter, r *http.Request, db *sql.DB, adminSecret []byte, caps *spectator.Caps) {
	if len(adminSecret) < 16 {
		http.Error(w, "admin disabled", http.StatusServiceUnavailable)
		return
	}
	replayID := r.URL.Query().Get("replay_id")
	ticket := r.URL.Query().Get("ticket")
	if !uuidPattern.MatchString(replayID) {
		http.Error(w, "invalid replay_id", http.StatusBadRequest)
		return
	}
	if err := replayauth.Verify(adminSecret, ticket, replayID, time.Now()); err != nil {
		w.Header().Set("WWW-Authenticate", "Replay")
		if errors.Is(err, replayauth.ErrExpired) {
			http.Error(w, "ticket expired", http.StatusUnauthorized)
		} else {
			http.Error(w, "invalid ticket", http.StatusUnauthorized)
		}
		return
	}

	if !caps.AllowIP(clientIP(r), time.Now()) {
		w.Header().Set("Retry-After", "60")
		http.Error(w, "rate limited", http.StatusTooManyRequests)
		return
	}
	if !caps.AcquireGlobal() {
		w.Header().Set("Retry-After", "5")
		http.Error(w, "replay capacity reached", http.StatusServiceUnavailable)
		return
	}

	rep, err := leaderboard.GetReplay(db, replayID)
	if err != nil {
		caps.ReleaseGlobal()
		if errors.Is(err, leaderboard.ErrNotFound) {
			http.Error(w, "not found", http.StatusNotFound)
			return
		}
		if errors.Is(err, leaderboard.ErrChecksumMismatch) {
			log.Printf("replay: %s: checksum mismatch", replayID)
			http.Error(w, "REPLAY_INTEGRITY_FAILED", http.StatusInternalServerError)
			return
		}
		log.Printf("replay: %s: load: %v", replayID, err)
		http.Error(w, "replay unavailable", http.StatusInternalServerError)
		return
	}

	var records []game.InputRecord
	if err := json.Unmarshal(rep.InputLog, &records); err != nil {
		caps.ReleaseGlobal()
		log.Printf("replay: %s: unmarshal log: %v", replayID, err)
		http.Error(w, "replay corrupt", http.StatusInternalServerError)
		return
	}

	wsConn, err := websocket.Accept(w, r, &websocket.AcceptOptions{
		InsecureSkipVerify: true,
	})
	if err != nil {
		caps.ReleaseGlobal()
		log.Printf("replay: accept: %v", err)
		return
	}
	metrics.ReplayViewersActive.Inc()

	connCtx, cancel := context.WithCancel(parent)
	player := replay.New(rep.PlayerID, rep.DisplayName, rep.Seed, records)

	go func() {
		defer cancel()

		wsConn.SetReadLimit(1024)
		for {
			_, raw, readErr := wsConn.Read(connCtx)
			if readErr != nil {
				return
			}
			env, decErr := protocol.DecodeEnvelope(raw)
			if decErr != nil {
				continue
			}
			if env.Type != protocol.C2SReplayControl {
				writeReplayError(connCtx, wsConn, "REPLAY_READ_ONLY", "replay connections accept C2S_REPLAY_CONTROL only")
				_ = wsConn.Close(websocket.StatusPolicyViolation, "replay_read_only")
				return
			}
			var pkt protocol.ReplayControlPacket
			if err := json.Unmarshal(env.Data, &pkt); err != nil {
				continue
			}
			switch pkt.Action {
			case "play":
				player.Play()
			case "pause":
				player.Pause()
			case "set_speed":
				player.SetSpeed(pkt.Speed)
			case "restart":
				player.Restart()
			default:

			}
		}
	}()

	go func() {
		defer cancel()
		t := time.NewTicker(SpectatorPingInterval)
		defer t.Stop()
		for {
			select {
			case <-connCtx.Done():
				return
			case <-t.C:
				pingCtx, pingCancel := context.WithTimeout(connCtx, SpectatorPingTimeout)
				pingErr := wsConn.Ping(pingCtx)
				pingCancel()
				if pingErr != nil {
					return
				}
			}
		}
	}()

	go player.Run(connCtx)

	go func() {
		defer cancel()
		defer caps.ReleaseGlobal()
		defer metrics.ReplayViewersActive.Dec()
		defer wsConn.Close(websocket.StatusNormalClosure, "bye")
		for {
			select {
			case <-connCtx.Done():
				return
			case env, ok := <-player.OutCh:
				if !ok {

					select {
					case <-time.After(game.SpectatorCatchupGrace):
					case <-connCtx.Done():
					}
					return
				}
				raw, err := json.Marshal(env)
				if err != nil {
					continue
				}
				if err := wsConn.Write(connCtx, websocket.MessageText, raw); err != nil {
					return
				}
			}
		}
	}()
}

func writeReplayError(ctx context.Context, ws *websocket.Conn, code, msg string) {
	env := protocol.NewS2C(protocol.S2CError, 0, protocol.ErrorData{
		Code:    code,
		Message: msg,
	})
	raw, err := json.Marshal(env)
	if err != nil {
		return
	}
	_ = ws.Write(ctx, websocket.MessageText, raw)
}

func clientIP(r *http.Request) string {
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	if !isPrivatePeer(host) {
		return host
	}
	if xf := r.Header.Get("X-Forwarded-For"); xf != "" {
		if i := strings.IndexByte(xf, ','); i > 0 {
			return strings.TrimSpace(xf[:i])
		}
		return strings.TrimSpace(xf)
	}
	return host
}

func isPrivatePeer(host string) bool {
	ip := net.ParseIP(host)
	if ip == nil {
		return false
	}
	return ip.IsLoopback() || ip.IsPrivate()
}

func connReader(ctx context.Context, conn *websocket.Conn, inCh chan<- []byte, cancel context.CancelFunc) {
	defer cancel()
	defer close(inCh)
	for {
		_, data, err := conn.Read(ctx)
		if err != nil {
			return
		}
		select {
		case inCh <- data:
		case <-ctx.Done():
			return
		}
	}
}

func connWriter(ctx context.Context, conn *websocket.Conn, outCh <-chan protocol.S2CEnvelope, cancel context.CancelFunc) {
	defer cancel()
	for {
		select {
		case <-ctx.Done():
			return
		case env, ok := <-outCh:
			if !ok {
				return
			}
			raw, err := json.Marshal(env)
			if err != nil {
				log.Printf("marshal: %v", err)
				continue
			}
			if err := conn.Write(ctx, websocket.MessageText, raw); err != nil {
				return
			}
		}
	}
}

func envDefault(k, def string) string {
	if v := os.Getenv(k); v != "" {
		return v
	}
	return def
}

func envInt(k string, def int) int {
	if v := os.Getenv(k); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

