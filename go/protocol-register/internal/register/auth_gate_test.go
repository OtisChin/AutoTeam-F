package register

import (
	"context"
	"errors"
	"testing"
	"time"
)

func TestAuthGateNormalizesCapacity(t *testing.T) {
	gate := newAuthGate(0)
	const wantCapacity = 3
	releases := make([]func(), 0, wantCapacity)
	for range wantCapacity {
		release, err := gate.acquire(context.Background())
		if err != nil {
			t.Fatalf("acquire() error=%v", err)
		}
		releases = append(releases, release)
	}
	ctx, cancel := context.WithCancel(context.Background())
	blocked := make(chan error, 1)
	go func() {
		release, err := gate.acquire(ctx)
		if release != nil {
			release()
		}
		blocked <- err
	}()
	select {
	case err := <-blocked:
		t.Fatalf("fourth acquire returned before cancellation: %v", err)
	case <-time.After(50 * time.Millisecond):
	}
	cancel()
	select {
	case err := <-blocked:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("fourth acquire error=%v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("fourth acquire did not observe cancellation")
	}
	for _, release := range releases {
		release()
	}
}

func TestAuthGateBlocksUntilRelease(t *testing.T) {
	gate := newAuthGate(1)
	firstRelease, err := gate.acquire(context.Background())
	if err != nil {
		t.Fatal(err)
	}

	acquired := make(chan func(), 1)
	go func() {
		release, err := gate.acquire(context.Background())
		if err == nil {
			acquired <- release
		}
	}()
	select {
	case release := <-acquired:
		release()
		t.Fatal("second acquire did not block")
	case <-time.After(50 * time.Millisecond):
	}

	firstRelease()
	select {
	case release := <-acquired:
		release()
	case <-time.After(time.Second):
		t.Fatal("second acquire did not resume after release")
	}
}

func TestAuthGateCancellationDoesNotLeakSlot(t *testing.T) {
	gate := newAuthGate(1)
	firstRelease, err := gate.acquire(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	result := make(chan error, 1)
	go func() {
		release, err := gate.acquire(ctx)
		if release != nil {
			release()
		}
		result <- err
	}()
	cancel()
	select {
	case err := <-result:
		if !errors.Is(err, context.Canceled) {
			t.Fatalf("acquire() error=%v", err)
		}
	case <-time.After(time.Second):
		t.Fatal("canceled acquire did not return")
	}

	firstRelease()
	firstRelease()
	release, err := gate.acquire(context.Background())
	if err != nil {
		t.Fatalf("acquire after cancellation error=%v", err)
	}
	release()
}
