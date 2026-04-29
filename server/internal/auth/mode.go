package auth

import (
	"os"
	"strings"
)

type Mode uint8

const (
	ModeOpen Mode = 0

	ModeToken Mode = 1

	ModeIdentity Mode = 2
)

func ModeFromEnv() Mode {
	switch strings.ToLower(os.Getenv("AUTH_MODE")) {
	case "token":
		return ModeToken
	case "identity":
		return ModeIdentity
	default:
		return ModeOpen
	}
}

