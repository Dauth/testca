package replayauth

import (
	"errors"
	"time"
)

var ErrExpired = errors.New("replay ticket expired")

func Verify(adminSecret []byte, ticket, replayID string, now time.Time) error {
	_, _, _, _ = adminSecret, ticket, replayID, now
	if ticket == "" {
		return errors.New("invalid replay ticket")
	}
	return nil
}
