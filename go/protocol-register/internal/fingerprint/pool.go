package fingerprint

import (
	cryptorand "crypto/rand"
	"errors"
	"fmt"
	"math/big"
	"strings"
)

const DefaultPool = "chrome144,chrome146,chrome150"

var (
	ErrEmptyPool          = errors.New("fingerprint pool is empty")
	ErrUnsupportedProfile = errors.New("unsupported fingerprint profile")
	ErrDrawOutOfRange     = errors.New("fingerprint draw is out of range")
)

type DrawFunc func(max int) (int, error)

type Pool struct {
	names []string
}

func ParsePool(raw string) (Pool, error) {
	names := make([]string, 0, len(supportedProfileNames))
	seen := make(map[string]struct{}, len(supportedProfileNames))
	for _, item := range strings.Split(raw, ",") {
		name := strings.TrimSpace(item)
		if name == "" {
			continue
		}
		if _, ok := Lookup(name); !ok {
			return Pool{}, fmt.Errorf("%w: %q", ErrUnsupportedProfile, name)
		}
		if _, ok := seen[name]; ok {
			continue
		}
		seen[name] = struct{}{}
		names = append(names, name)
	}
	if len(names) == 0 {
		return Pool{}, ErrEmptyPool
	}
	return Pool{names: names}, nil
}

func (p Pool) Names() []string {
	return append([]string(nil), p.names...)
}

func (p Pool) Select(draw DrawFunc) (Profile, error) {
	if len(p.names) == 0 {
		return Profile{}, ErrEmptyPool
	}
	if draw == nil {
		draw = CryptoDraw
	}
	index, err := draw(len(p.names))
	if err != nil {
		return Profile{}, fmt.Errorf("draw fingerprint profile: %w", err)
	}
	if index < 0 || index >= len(p.names) {
		return Profile{}, fmt.Errorf("%w: index=%d size=%d", ErrDrawOutOfRange, index, len(p.names))
	}
	profile, ok := Lookup(p.names[index])
	if !ok {
		return Profile{}, fmt.Errorf("%w: %q", ErrUnsupportedProfile, p.names[index])
	}
	return profile, nil
}

func CryptoDraw(max int) (int, error) {
	if max <= 0 {
		return 0, ErrEmptyPool
	}
	value, err := cryptorand.Int(cryptorand.Reader, big.NewInt(int64(max)))
	if err != nil {
		return 0, fmt.Errorf("draw fingerprint profile: %w", err)
	}
	return int(value.Int64()), nil
}
