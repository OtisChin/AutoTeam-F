package register

import (
	"context"
	"sync"
)

const defaultAuthConcurrency = 3

type authGate struct {
	slots chan struct{}
}

func newAuthGate(capacity int) *authGate {
	if capacity <= 0 {
		capacity = defaultAuthConcurrency
	}
	return &authGate{slots: make(chan struct{}, capacity)}
}

func (g *authGate) acquire(ctx context.Context) (func(), error) {
	if ctx == nil {
		ctx = context.Background()
	}
	if err := ctx.Err(); err != nil {
		return nil, err
	}
	select {
	case g.slots <- struct{}{}:
		var once sync.Once
		return func() {
			once.Do(func() { <-g.slots })
		}, nil
	case <-ctx.Done():
		return nil, ctx.Err()
	}
}
