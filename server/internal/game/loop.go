package game

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"math"
	"math/rand"
	"strconv"
	"time"

	"github.com/google/uuid"

	"github.com/greyhats/defcon-game/server/internal/leaderboard"
	"github.com/greyhats/defcon-game/server/internal/metrics"
	"github.com/greyhats/defcon-game/server/internal/protocol"
	"github.com/greyhats/defcon-game/server/internal/spectator"
)

const SpectatorPerGame = 50

const SpectatorCatchupGrace = 500 * time.Millisecond

type Engine struct {
	InCh   <-chan []byte
	OutCh  chan<- protocol.S2CEnvelope
	Submit func(*leaderboard.CompletedRun) bool

	SubmitAndRefresh func(*leaderboard.CompletedRun) leaderboard.SubmitResult

	RegisterLeaderboard func(playerID string)

	AuthCheck func(playerID string) (string, error)

	Live *spectator.LiveRegistry

	Engines *spectator.Engines

	PlayerID    string
	DisplayName string

	ReplayMode bool

	run    *RunState
	player *PlayerState
	room   *RoomState

	seq          uint32
	tick         uint64
	lastClientTs int64

	lastInputAt time.Time
	dirtyInput  struct{ dx, dy float32 }

	RegisterCh chan spectator.Req

	spectators []*spectator.Conn

	lastRunStarted *protocol.RunStartedData
	lastRoomLoad   *protocol.RoomLoadData
	lastState      *protocol.StateData
}

func NewEngine(in <-chan []byte, out chan<- protocol.S2CEnvelope, submit func(*leaderboard.CompletedRun) bool, authCheck func(string) (string, error)) *Engine {
	return &Engine{
		InCh:       in,
		OutCh:      out,
		Submit:     submit,
		AuthCheck:  authCheck,
		RegisterCh: make(chan spectator.Req, 8),
	}
}

func (e *Engine) Run(ctx context.Context) {
	defer func() {
		if e.Engines != nil && e.PlayerID != "" {
			e.Engines.Unregister(e.PlayerID)
		}

		e.closeSpectators()
	}()
	if !e.handshake(ctx) {
		return
	}
	e.tickLoop(ctx)
}

func (e *Engine) send(typ uint8, data any) {
	e.seq++
	metrics.WSMessages.WithLabelValues("s2c", metrics.PacketTypeName(typ)).Inc()
	env := protocol.NewS2C(typ, e.seq, data)
	select {
	case e.OutCh <- env:
	default:
	}
	e.cacheCatchup(typ, data)
	e.fanOutToSpectators(typ, data)
}

func (e *Engine) cacheCatchup(typ uint8, data any) {
	switch typ {
	case protocol.S2CRunStarted:
		if d, ok := data.(protocol.RunStartedData); ok {
			c := d
			e.lastRunStarted = &c
		}
	case protocol.S2CRoomLoad:
		if d, ok := data.(protocol.RoomLoadData); ok {
			c := d
			e.lastRoomLoad = &c
		}
	case protocol.S2CState:
		if d, ok := data.(protocol.StateData); ok {
			c := d
			e.lastState = &c
		}
	}
}

func (e *Engine) fanOutToSpectators(typ uint8, data any) {
	if typ == protocol.S2CAuthOk || len(e.spectators) == 0 {
		return
	}
	for _, sp := range e.spectators {
		if sp.Closed {
			continue
		}
		sp.Seq++
		env := protocol.NewS2C(typ, sp.Seq, data)
		select {
		case sp.OutCh <- env:
		default:
		}
	}
}

func (e *Engine) sendError(code, msg string) {
	e.send(protocol.S2CError, protocol.ErrorData{Code: code, Message: msg})
}

func (e *Engine) validateTsWindow(ts int64, now time.Time) bool {
	if e.ReplayMode || ts == 0 {
		return true
	}
	diff := now.UnixMilli() - ts
	windowMs := int64(TsValidationWindow / time.Millisecond)
	if diff > windowMs || diff < -windowMs {
		offsetMs := diff
		direction := "behind"
		if diff < 0 {
			offsetMs = -diff
			direction = "ahead of"
		}
		e.sendError("ts_out_of_window",
			fmt.Sprintf("client clock is %d ms %s server (max ±%d ms) — please sync your system clock",
				offsetMs, direction, windowMs))
		return false
	}
	return true
}

func (e *Engine) handshake(ctx context.Context) bool {
	if !e.awaitAuth(ctx) {
		return false
	}
	return e.awaitStartRun(ctx)
}

func (e *Engine) awaitAuth(ctx context.Context) bool {
	for {
		select {
		case <-ctx.Done():
			return false
		case raw, ok := <-e.InCh:
			if !ok {
				return false
			}
			env, err := protocol.DecodeEnvelope(raw)
			if err != nil {
				e.sendError("bad_envelope", err.Error())
				continue
			}
			if env.Type != protocol.C2SAuth {
				e.sendError("auth_required", "send C2S_AUTH first")
				continue
			}

			if !e.validateTsWindow(env.Ts, time.Now()) {
				return false
			}
			var pkt protocol.AuthPacket
			if err := json.Unmarshal(env.Data, &pkt); err != nil {
				e.sendError("bad_auth", err.Error())
				continue
			}
			displayName := ""
			if e.AuthCheck != nil {
				name, err := e.AuthCheck(pkt.PlayerID)
				if err != nil {
					e.sendError("auth_failed", err.Error())
					return false
				}
				displayName = name
			}
			e.PlayerID = pkt.PlayerID
			if displayName != "" {
				e.DisplayName = displayName
			} else if e.DisplayName == "" {
				e.DisplayName = pkt.PlayerID
			}

			e.send(protocol.S2CAuthOk, protocol.AuthOkData{DisplayName: e.DisplayName})
			if e.RegisterLeaderboard != nil && !e.ReplayMode {
				e.RegisterLeaderboard(e.PlayerID)
			}
			return true
		}
	}
}

func (e *Engine) awaitStartRun(ctx context.Context) bool {
	for {
		select {
		case <-ctx.Done():
			return false
		case raw, ok := <-e.InCh:
			if !ok {
				return false
			}
			env, err := protocol.DecodeEnvelope(raw)
			if err != nil {
				e.sendError("bad_envelope", err.Error())
				continue
			}
			if env.Type != protocol.C2SStartRun {
				e.sendError("start_required", "send C2S_START_RUN")
				continue
			}
			if !e.validateTsWindow(env.Ts, time.Now()) {
				return false
			}
			var pkt protocol.StartRunPacket
			if err := json.Unmarshal(env.Data, &pkt); err != nil {
				e.sendError("bad_start", err.Error())
				continue
			}
			if !e.initRun(pkt.StartTime, pkt.StartRoom) {
				return false
			}
			return true
		}
	}
}

func (e *Engine) initRun(startTime int64, startRoom uint8) bool {
	now := time.Now()
	if !e.ReplayMode {
		seedTime := time.UnixMilli(startTime)
		if diff := now.Sub(seedTime); diff > SeedWindow || diff < -SeedWindow {
			e.sendError("seed_out_of_window", "start_time must be within ±30min of server now")
			return false
		}
	}
	if startRoom == 0 {
		startRoom = 1
	}
	if int(startRoom) <= 0 || int(startRoom) >= len(RoomTemplates) || RoomTemplates[startRoom] == nil {
		e.sendError("bad_start_room", "start_room must reference a valid room")
		return false
	}
	e.run = &RunState{
		Status:       RunRunning,
		PlayerID:     e.PlayerID,
		DisplayName:  e.DisplayName,
		RunStartTime: now,
		Seed:         startTime,
		MobRNG:       rand.New(rand.NewSource(startTime)),
		CurrentRoom:  startRoom,
		Splits:       []protocol.SplitData{},
		InputLog:     []InputRecord{},
	}
	e.player = NewPlayerState()
	e.room = NewRoomState(startRoom)
	e.lastInputAt = now

	tmpl := RoomTemplates[startRoom]
	roomData := LoadRoom(e.room, e.run.MobRNG, tmpl, TilemapEnemies(startRoom), TilemapWaves(startRoom), now)

	placePlayerSpawn(e.player, startRoom)

	e.send(protocol.S2CRunStarted, protocol.RunStartedData{
		Seed:        startTime,
		Room:        roomData,
		DisplayName: e.DisplayName,
	})

	if e.Engines != nil && !e.ReplayMode {
		e.Engines.Register(e.PlayerID, e.RegisterCh)
	}
	return true
}

func (e *Engine) RunReplay(ctx context.Context, advance func(prev time.Time) (time.Time, bool)) {
	defer e.closeSpectators()
	if !e.handshake(ctx) {
		return
	}
	now := e.run.RunStartTime
	for {
		select {
		case <-ctx.Done():
			return
		default:
		}
		next, ok := advance(now)
		if !ok {
			return
		}
		now = next
		e.stepTick(now)
		if e.run.Status.IsTerminal() {
			return
		}
	}
}

func (e *Engine) RunStartTime() time.Time {
	if e.run == nil {
		return time.Time{}
	}
	return e.run.RunStartTime
}

func (e *Engine) tickLoop(ctx context.Context) {

	metrics.ActivePlayers.Inc()
	defer metrics.ActivePlayers.Dec()

	ticker := time.NewTicker(TickDuration)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case _, ok := <-ticker.C:
			if !ok {
				return
			}
			tickStart := time.Now()
			e.stepTick(tickStart)
			metrics.GameTickDuration.Observe(time.Since(tickStart).Seconds())
			if e.run.Status.IsTerminal() {
				return
			}
		}
	}
}

func (e *Engine) stepTick(now time.Time) {
	e.tick++
	dt := float32(TickDuration.Seconds())

	e.drainSpectatorRegister()
	e.drainInput(now)

	if !e.ReplayMode && e.run.Status == RunRunning {
		if elapsed := now.Sub(e.run.RunStartTime); elapsed >= MaxRunDuration {
			log.Printf("run %s force-ended: max duration cap (elapsed=%v, cap=%v)", e.PlayerID, elapsed, MaxRunDuration)
			e.finishRun(now, elapsed.Milliseconds(), RunFailed)
			return
		}
		if !e.lastInputAt.IsZero() {
			if idle := now.Sub(e.lastInputAt); idle >= IdleTimeout {
				log.Printf("run %s force-ended: idle timeout (idle=%v, cap=%v)", e.PlayerID, idle, IdleTimeout)
				e.finishRun(now, e.currentElapsed(now), RunFailed)
				return
			}
		}
	}

	e.advancePlayer(dt, now)
	deaths := e.advanceEnemies(dt, now)
	hits := AdvanceProjectiles(e.room, dt, now)
	deaths = append(deaths, ResolveCollisions(e.room, hits, now)...)
	for _, id := range deaths {
		go ProcessEnemyDeathAsync(e.room, id)
		e.send(protocol.S2CEntityDied, protocol.EntityDiedData{EntityID: id})
	}

	AdvanceWaves(e.room, now)

	if e.run.Status == RunRunning && e.player.HP <= 0 {
		e.finishRun(now, e.currentElapsed(now), RunFailed)
		return
	}

	if !e.room.Settled {
		e.room.TicksSinceLoad++
		if e.room.TicksSinceLoad >= SettleTicks {
			e.room.Settled = true
		}
	}

	if e.tick%ReconcileEveryTicks == 0 {
		ReconcileKillLog(e.room)
	} else {
		CheckAllEnemiesDead(e.room)
	}

	for id, pk := range e.room.Pickups {
		if pk.Consumed || pk.ExpiresAt.IsZero() {
			continue
		}
		if now.After(pk.ExpiresAt) {
			pk.Consumed = true
			e.send(protocol.S2CEntityDied, protocol.EntityDiedData{EntityID: id})
		}
	}

	for _, d := range UnlockDoorsIfClear(e.room) {
		e.send(protocol.S2CDoorUnlocked, protocol.DoorUnlockedData{
			DoorID:      d.DoorID,
			TileX:       d.TileX,
			TileY:       d.TileY,
			UnlockedGID: d.UnlockedGID,
		})
	}

	e.updateElapsed(now)
	e.sendState(now)
	e.publishLiveSummary()
}

func (e *Engine) publishLiveSummary() {
	if e.Live == nil || e.run == nil || e.PlayerID == "" || e.ReplayMode {
		return
	}
	live := 0
	for _, sp := range e.spectators {
		if !sp.Closed {
			live++
		}
	}
	e.Live.Update(spectator.Summary{
		PlayerID:       e.PlayerID,
		DisplayName:    e.DisplayName,
		RoomIndex:      e.run.CurrentRoom,
		ElapsedMs:      e.run.ElapsedMs,
		SpectatorCount: live,
		StartedAt:      e.run.RunStartTime.UnixMilli(),
	})
}

func (e *Engine) drainSpectatorRegister() {
	for {
		select {
		case req := <-e.RegisterCh:
			switch req.Action {
			case spectator.ActionRegister:
				e.handleRegister(req)
			case spectator.ActionDeregister:
				e.handleDeregister(req)
			}
		default:
			return
		}
	}
}

func (e *Engine) handleRegister(req spectator.Req) {
	if req.Conn == nil {
		if req.Reply != nil {
			req.Reply <- false
		}
		return
	}
	live := 0
	for _, sp := range e.spectators {
		if !sp.Closed {
			live++
		}
	}
	if live >= SpectatorPerGame {
		if req.Reply != nil {
			req.Reply <- false
		}
		return
	}
	e.spectators = append(e.spectators, req.Conn)
	if req.Reply != nil {
		req.Reply <- true
	}
	e.sendCatchup(req.Conn)
}

func (e *Engine) handleDeregister(req spectator.Req) {
	if req.Conn == nil {
		return
	}
	for i, sp := range e.spectators {
		if sp == req.Conn {
			e.spectators = append(e.spectators[:i], e.spectators[i+1:]...)
			return
		}
	}
}

func (e *Engine) sendCatchup(sp *spectator.Conn) {
	push := func(typ uint8, data any) {
		sp.Seq++
		env := protocol.NewS2C(typ, sp.Seq, data)
		select {
		case sp.OutCh <- env:
		default:
		}
	}
	if e.lastRunStarted != nil {
		push(protocol.S2CRunStarted, *e.lastRunStarted)
	}
	if e.lastRoomLoad != nil {
		push(protocol.S2CRoomLoad, *e.lastRoomLoad)
	}
	if e.lastState != nil {
		push(protocol.S2CState, *e.lastState)
	}
}

func (e *Engine) closeSpectators() {
	if len(e.spectators) == 0 {
		return
	}
	conns := make([]*spectator.Conn, len(e.spectators))
	copy(conns, e.spectators)
	e.spectators = nil
	go func() {
		time.Sleep(SpectatorCatchupGrace)
		for _, sp := range conns {
			if !sp.Closed {
				sp.Closed = true
				close(sp.OutCh)
			}
		}
	}()
}

func (e *Engine) drainInput(now time.Time) {
	for {
		select {
		case raw, ok := <-e.InCh:
			if !ok {
				return
			}
			e.lastInputAt = now
			e.dispatch(raw, now)
		default:
			return
		}
	}
}

func (e *Engine) dispatch(raw []byte, now time.Time) {
	start := time.Now()
	env, err := protocol.DecodeEnvelope(raw)
	if err != nil {
		metrics.WSMessages.WithLabelValues("c2s", "unknown").Inc()
		metrics.Errors.WithLabelValues("ws_parse_fail").Inc()
		e.sendError("bad_envelope", err.Error())
		return
	}
	pktName := metrics.PacketTypeName(env.Type)
	metrics.WSMessages.WithLabelValues("c2s", pktName).Inc()
	defer func() {
		metrics.WSHandlerDuration.WithLabelValues(pktName).Observe(time.Since(start).Seconds())
	}()

	if !e.validateTsWindow(env.Ts, now) {
		return
	}
	if env.Ts != 0 && !e.ReplayMode {
		e.lastClientTs = env.Ts
	}

	e.run.InputLog = append(e.run.InputLog, InputRecord{
		Tick: e.tick,
		Type: env.Type,
		Seq:  env.Seq,
		Ts:   env.Ts,
		Data: append([]byte(nil), env.Data...),
	})

	switch env.Type {
	case protocol.C2SInput:
		var pkt protocol.InputPacket
		if err := json.Unmarshal(env.Data, &pkt); err != nil {
			return
		}
		e.dirtyInput.dx = clampInput(pkt.DX)
		e.dirtyInput.dy = clampInput(pkt.DY)
	case protocol.C2SShoot:
		var pkt protocol.ShootPacket
		if err := json.Unmarshal(env.Data, &pkt); err != nil {
			return
		}
		e.player.LastAimAngle = pkt.AimAngle
		HandleShoot(e.player, e.room, pkt.AimAngle, now)
	case protocol.C2SSwitchWeapon:
		var pkt protocol.SwitchWeaponPacket
		if err := json.Unmarshal(env.Data, &pkt); err != nil {
			return
		}
		HandleSwitchWeapon(e.player, pkt.WeaponID, now)
	case protocol.C2SInteract:
		var pkt protocol.InteractPacket
		if err := json.Unmarshal(env.Data, &pkt); err != nil {
			return
		}
		if consumed := HandleInteract(e.player, e.room, pkt.TargetID, pkt.ClaimedType, now); consumed != nil {
			e.send(protocol.S2CEntityDied, protocol.EntityDiedData{EntityID: pkt.TargetID})
		}
	case protocol.C2SEnterDoor:
		var pkt protocol.EnterDoorPacket
		if err := json.Unmarshal(env.Data, &pkt); err != nil {
			return
		}
		e.tryEnterDoor(pkt.DoorID, now)
	case protocol.C2SShopPurchase:
		var pkt protocol.ShopPurchasePacket
		if err := json.Unmarshal(env.Data, &pkt); err != nil {
			return
		}
		HandleShopPurchase(e.player, pkt.ItemID)
	}
}

func (e *Engine) tryEnterDoor(doorID uint32, now time.Time) {
	nextRoom, ok := HandleEnterDoor(e.player, e.room, doorID)
	if !ok {
		return
	}
	e.transitionToRoom(nextRoom, now)
}

func (e *Engine) transitionToRoom(nextRoom uint8, now time.Time) {

	elapsed := e.currentElapsed(now)
	bonus := ComputeRoomBonus(e.room.KillLog)
	if bonus != 0 {
		e.run.TimeAdjustmentMs += bonus
		elapsed += bonus
	}
	e.run.ElapsedMs = elapsed

	roomDuration := elapsed
	if n := len(e.run.Splits); n > 0 {
		roomDuration = elapsed - e.run.Splits[n-1].TimeMs
	}
	if roomDuration < 0 {
		roomDuration = 0
	}
	if !e.ReplayMode {
		metrics.RoomSplitDuration.
			WithLabelValues(strconv.Itoa(int(e.run.CurrentRoom))).
			Observe(float64(roomDuration) / 1000.0)
	}
	e.run.Splits = append(e.run.Splits, protocol.SplitData{
		RoomIndex: e.run.CurrentRoom,
		TimeMs:    elapsed,
		Kills:     uint8(len(e.room.KillLog)),
	})

	if nextRoom > FinalRoom {

		e.finishRun(now, elapsed, RunCompleted)
		return
	}

	e.run.CurrentRoom = nextRoom
	e.room = NewRoomState(nextRoom)
	tmpl := RoomTemplates[nextRoom]
	if tmpl == nil {
		e.sendError("bad_room", "no template for room")
		return
	}
	roomData := LoadRoom(e.room, e.run.MobRNG, tmpl, TilemapEnemies(nextRoom), TilemapWaves(nextRoom), now)

	placePlayerSpawn(e.player, nextRoom)

	e.send(protocol.S2CRoomLoad, protocol.RoomLoadData{
		RoomIndex: nextRoom,
		Room:      roomData,
		SplitMs:   elapsed,
	})

	if nextRoom == FinalRoom {

	}
}

func (e *Engine) advancePlayer(dt float32, now time.Time) {
	speed := PlayerSpeed * EffectiveSpeedMult(e.player)

	const hw float32 = 10
	const hh float32 = 10

	newX := e.player.X + e.dirtyInput.dx*speed*dt
	newX = clampFloat(newX, 16, RoomWidth-16)
	if !BlockedAABB(e.run.CurrentRoom, newX, e.player.Y, hw, hh) {
		e.player.X = newX
	}

	newY := e.player.Y + e.dirtyInput.dy*speed*dt
	newY = clampFloat(newY, 16, RoomHeight-16)
	if !BlockedAABB(e.run.CurrentRoom, e.player.X, newY, hw, hh) {
		e.player.Y = newY
	}
}

func (e *Engine) advanceEnemies(dt float32, now time.Time) []uint32 {

	fields := NewFlowFieldCache(e.run.CurrentRoom)

	var deaths []uint32
	for id, en := range e.room.Enemies {
		if UpdateEnemy(en, e.player, e.run.CurrentRoom, dt, now, fields) {
			dmg := Archetypes[en.Type].MeleeDamage
			e.player.HP -= dmg
			e.player.DamageTaken += int32(dmg)
			if en.Type == EnemyKamikaze {

				en.AIState = AIDead
				en.HP = 0
				deaths = append(deaths, id)
			}
		}
	}
	return deaths
}

func (e *Engine) updateElapsed(now time.Time) {
	e.run.ElapsedMs = e.currentElapsed(now)

	if e.run.CurrentRoom == FinalRoom && e.room.AllEnemiesDead && e.run.Status == RunRunning {
		e.finishRun(now, e.run.ElapsedMs, RunCompleted)
	}
}

func (e *Engine) currentElapsed(now time.Time) int64 {
	return now.Sub(e.run.RunStartTime).Milliseconds() + e.run.TimeAdjustmentMs
}

func (e *Engine) finishRun(now time.Time, totalMs int64, status RunStatus) {
	e.run.Status = status
	e.run.ElapsedMs = totalMs

	if !e.ReplayMode {
		outcome := string(status.Outcome())
		metrics.RunsCompleted.WithLabelValues(outcome).Inc()
		metrics.RunDuration.WithLabelValues(outcome).Observe(float64(totalMs) / 1000.0)
	}

	e.run.Splits = append(e.run.Splits, protocol.SplitData{
		RoomIndex: e.run.CurrentRoom,
		TimeMs:    totalMs,
		Kills:     uint8(len(e.room.KillLog)),
	})

	rank := 0
	if status == RunCompleted && !e.ReplayMode {
		inputLog, _ := json.Marshal(e.run.InputLog)
		replayID := uuid.NewString()
		checksum := leaderboard.Checksum(e.run.Seed, inputLog)
		cr := &leaderboard.CompletedRun{
			ReplayID:    replayID,
			PlayerID:    e.PlayerID,
			DisplayName: e.DisplayName,
			TotalMs:     totalMs,
			Splits:      append([]protocol.SplitData(nil), e.run.Splits...),
			Seed:        e.run.Seed,
			InputLog:    inputLog,
			Checksum:    checksum,
			SubmittedAt: now,
		}
		if e.SubmitAndRefresh != nil {
			result := e.SubmitAndRefresh(cr)
			if result.Err != nil {
				log.Printf("leaderboard: submit run %s: %v", replayID, result.Err)
			} else {
				rank = result.Rank
				e.send(protocol.S2CLeaderboard, protocol.LeaderboardData{
					Entries: result.Entries,
				})
			}
		} else if e.Submit != nil {
			if !e.Submit(cr) {
				log.Printf("completedCh full, dropping run %s", replayID)
			}
		}
	}

	e.send(protocol.S2CRunComplete, protocol.RunCompleteData{
		Outcome: status.Outcome(),
		TotalMs: totalMs,
		Rank:    rank,
		Splits:  e.run.Splits,
	})

	e.closeSpectators()

	if e.Engines != nil && e.PlayerID != "" {
		e.Engines.Unregister(e.PlayerID)
	}
}

func (e *Engine) sendState(now time.Time) {
	entities := make([]protocol.EntitySnapshot, 0, len(e.room.Enemies))
	for _, en := range e.room.Enemies {

		if en.AIState == AIDead {
			continue
		}
		entities = append(entities, protocol.EntitySnapshot{
			EntityID: en.EntityID,
			Type:     en.Type,
			X:        en.X,
			Y:        en.Y,
			HP:       en.HP,
			State:    uint8(en.AIState),
		})
	}
	pickups := make([]protocol.PickupSpawn, 0, len(e.room.Pickups))
	for _, pk := range e.room.Pickups {
		if pk.Consumed {
			continue
		}
		pickups = append(pickups, protocol.PickupSpawn{
			EntityID: pk.EntityID,
			Type:     pk.Type,
			X:        pk.X,
			Y:        pk.Y,
		})
	}

	projs := make([]protocol.ProjSnapshot, 0, len(e.room.Projectiles))
	for _, pr := range e.room.Projectiles {
		projs = append(projs, protocol.ProjSnapshot{
			ProjID: pr.ProjID,
			X:      pr.X,
			Y:      pr.Y,
			Angle:  float32(math.Atan2(float64(pr.VelY), float64(pr.VelX))),
			Owner:  pr.OwnerID,
		})
	}
	data := protocol.StateData{
		ElapsedMs: e.run.ElapsedMs,
		Player: protocol.PlayerSnapshot{
			X:              e.player.X,
			Y:              e.player.Y,
			HP:             e.player.HP,
			WeaponID:       e.player.CurrentWeapon,
			Ammo:           e.player.WeaponAmmo[e.player.CurrentWeapon],
			Coins:          e.player.Coins,
			SpeedStacks:    e.player.SpeedStacks,
			FireRateStacks: e.player.FireRateStacks,
			DamageStacks:   e.player.DamageStacks,
			AimAngle:       e.player.LastAimAngle,
		},
		Entities:    entities,
		Projectiles: projs,
		Pickups:     pickups,
	}
	e.send(protocol.S2CState, data)
}

func placePlayerSpawn(p *PlayerState, roomIndex uint8) {
	const hw, hh float32 = 10, 10
	if sx, sy, ok := PlayerSpawnAt(roomIndex); ok {

		if !BlockedAABB(roomIndex, sx, sy, hw, hh) {
			p.X, p.Y = sx, sy
			return
		}
		nx, ny := NearestNonWall(roomIndex, sx, sy)
		p.X, p.Y = nx, ny
		return
	}
	candidates := [][2]float32{
		{RoomWidth / 2, RoomHeight - 100},
		{RoomWidth / 2, RoomHeight / 2},
		{64, RoomHeight - 64},
		{RoomWidth - 64, RoomHeight - 64},
	}
	for _, c := range candidates {
		if !BlockedAABB(roomIndex, c[0], c[1], hw, hh) {
			p.X, p.Y = c[0], c[1]
			return
		}
	}

	for ty := 1; ty < GridRows-1; ty++ {
		for tx := 1; tx < GridCols-1; tx++ {
			cx := float32(tx)*TileSize + TileSize/2
			cy := float32(ty)*TileSize + TileSize/2
			if !BlockedAABB(roomIndex, cx, cy, hw, hh) {
				p.X, p.Y = cx, cy
				return
			}
		}
	}

}

func clampInput(v float32) float32 {
	if v > 1 {
		return 1
	}
	if v < -1 {
		return -1
	}
	return v
}
