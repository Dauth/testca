package leaderboard

import (
	"crypto/sha256"
	"encoding/binary"
)

func Checksum(seed int64, inputLog []byte) [32]byte {
	h := sha256.New()
	var sb [8]byte
	binary.LittleEndian.PutUint64(sb[:], uint64(seed))
	h.Write(sb[:])
	h.Write(inputLog)
	var out [32]byte
	copy(out[:], h.Sum(nil))
	return out
}

