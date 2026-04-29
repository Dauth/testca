package spectator

import "github.com/greyhats/defcon-game/server/internal/protocol"

const OutChBuf = 64

type Conn struct {
	OutCh chan protocol.S2CEnvelope
	Seq   uint32

	Closed bool
}

func NewConn() *Conn {
	return &Conn{OutCh: make(chan protocol.S2CEnvelope, OutChBuf)}
}

type Action int

const (
	ActionRegister Action = iota

	ActionDeregister
)

type Req struct {
	Action Action
	Conn   *Conn
	Reply  chan bool
}

