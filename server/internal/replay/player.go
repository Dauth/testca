package replay

import (
	"context"
	"encoding/json"
	"log"
	"time"

	"github.com/greyhats/defcon-game/server/internal/game"
	"github.com/greyhats/defcon-game/server/internal/protocol"
)

const (
	MinSpeed = 0.25
	MaxSpeed = 8.0
)

const OutChBuf = 64

const FastForwardSpeed = 1000.0

type commandKind uint8

const (
	cmdPlay commandKind = iota
	cmdPause
	cmdSetSpeed
	cmdRestart
)

type command struct {
	Kind  commandKind
	Speed float32
}

type Player struct {
	PlayerID    string
	DisplayName string
	Seed        int64
	Log         []game.InputRecord

	OutCh chan protocol.S2CEnvelope

	cmdCh chan command

	activeInCh chan []byte

	nextTick  uint64
	logCursor int
	speed     float32
	paused    bool
	restart   bool
	ctx       context.Context
}

func New(playerID, displayName string, seed int64, log []game.InputRecord) *Player {
	return &Player{
		PlayerID:    playerID,
		DisplayName: displayName,
		Seed:        seed,
		Log:         log,
		OutCh:       make(chan protocol.S2CEnvelope, OutChBuf),
		cmdCh:       make(chan command, 8),
	}
}

func (p *Player) Pause() { p.enqueue(command{Kind: cmdPause}) }

func (p *Player) Play() { p.enqueue(command{Kind: cmdPlay}) }

func (p *Player) SetSpeed(s float32) {
	if s < MinSpeed {
		s = MinSpeed
	}
	if s > MaxSpeed {
		s = MaxSpeed
	}
	p.enqueue(command{Kind: cmdSetSpeed, Speed: s})
}

func (p *Player) Restart() { p.enqueue(command{Kind: cmdRestart}) }

func (p *Player) enqueue(c command) {
	select {
	case p.cmdCh <- c:
	default:

	}
}

func (p *Player) Run(ctx context.Context) {
	defer close(p.OutCh)
	for {
		if !p.runOnce(ctx) {
			return
		}
	}
}

func (p *Player) runOnce(parent context.Context) bool {
	ctx, cancel := context.WithCancel(parent)
	defer cancel()
	p.ctx = ctx
	p.nextTick = 0
	p.logCursor = 0
	p.speed = 1.0
	p.paused = false
	p.restart = false

drainCmds:
	for {
		select {
		case <-p.cmdCh:
		default:
			break drainCmds
		}
	}

	inCh := make(chan []byte, game.InChBuf)
	outCh := make(chan protocol.S2CEnvelope, game.OutChBuf)
	p.activeInCh = inCh

	eng := game.NewEngine(inCh, outCh, nil, nil)
	eng.ReplayMode = true
	eng.PlayerID = p.PlayerID
	eng.DisplayName = p.DisplayName

	p.feedAuth(inCh)
	p.feedStartRun(inCh)

	forwardDone := make(chan struct{})
	go p.forward(ctx, outCh, forwardDone)

	eng.RunReplay(ctx, p.advance)

	close(inCh)
	close(outCh)
	<-forwardDone

	if p.restart {
		select {
		case <-parent.Done():
			return false
		default:
			return true
		}
	}
	return false
}

func (p *Player) advance(prev time.Time) (time.Time, bool) {
	p.nextTick++
	for p.logCursor < len(p.Log) && p.Log[p.logCursor].Tick == p.nextTick {
		p.feedRecord(p.activeInCh, p.Log[p.logCursor])
		p.logCursor++
	}
	if !p.sleepForSpeed() {
		return time.Time{}, false
	}
	return prev.Add(game.TickDuration), true
}

func (p *Player) sleepForSpeed() bool {
	for {
		if p.paused {
			select {
			case <-p.ctx.Done():
				return false
			case c := <-p.cmdCh:
				p.applyCmd(c)
				if p.restart {
					return false
				}
				continue
			}
		}
		d := time.Duration(float64(game.TickDuration) / float64(p.speed))

		if d <= 0 {
			d = time.Microsecond
		}
		t := time.NewTimer(d)
		select {
		case <-p.ctx.Done():
			t.Stop()
			return false
		case c := <-p.cmdCh:
			t.Stop()
			p.applyCmd(c)
			if p.restart {
				return false
			}
			continue
		case <-t.C:
			return true
		}
	}
}

func (p *Player) applyCmd(c command) {
	switch c.Kind {
	case cmdPlay:
		p.paused = false
	case cmdPause:
		p.paused = true
	case cmdSetSpeed:
		s := c.Speed
		if s < MinSpeed {
			s = MinSpeed
		}
		if s > MaxSpeed {
			s = MaxSpeed
		}
		p.speed = s
	case cmdRestart:
		p.restart = true
	}
}

func (p *Player) feedAuth(in chan<- []byte) {
	data, _ := json.Marshal(protocol.AuthPacket{PlayerID: p.PlayerID})
	env := protocol.Envelope{Type: protocol.C2SAuth, Seq: 0, Ts: 0, Data: data}
	raw, err := json.Marshal(env)
	if err != nil {
		log.Printf("replay: marshal auth: %v", err)
		return
	}
	in <- raw
}

func (p *Player) feedStartRun(in chan<- []byte) {
	data, _ := json.Marshal(protocol.StartRunPacket{StartTime: p.Seed})
	env := protocol.Envelope{Type: protocol.C2SStartRun, Seq: 0, Ts: 0, Data: data}
	raw, err := json.Marshal(env)
	if err != nil {
		log.Printf("replay: marshal start_run: %v", err)
		return
	}
	in <- raw
}

func (p *Player) feedRecord(in chan<- []byte, rec game.InputRecord) {
	env := protocol.Envelope{
		Type: rec.Type,
		Seq:  rec.Seq,
		Ts:   rec.Ts,
		Data: rec.Data,
	}
	raw, err := json.Marshal(env)
	if err != nil {
		return
	}
	select {
	case in <- raw:
	default:
		log.Printf("replay: inCh full at tick %d, dropping record", rec.Tick)
	}
}

func (p *Player) forward(ctx context.Context, in <-chan protocol.S2CEnvelope, done chan<- struct{}) {
	defer close(done)
	for {
		select {
		case <-ctx.Done():
			return
		case env, ok := <-in:
			if !ok {
				return
			}
			select {
			case p.OutCh <- env:
			default:

			}
		}
	}
}

