package readiness

import (
	"slices"
	"sync"
	"testing"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/sentinel"
)

func TestSourceCombinesFingerprintPoolAndSentinelStatus(t *testing.T) {
	validPool, err := fingerprint.ParsePool(fingerprint.DefaultPool)
	if err != nil {
		t.Fatal(err)
	}
	tests := []struct {
		name       string
		pool       fingerprint.Pool
		status     sentinel.Status
		wantReady  bool
		wantReason string
	}{
		{
			name:       "invalid pool wins",
			status:     sentinel.Status{Ready: true, SDKVersion: "lastGoodA1"},
			wantReason: ReasonFingerprintPoolInvalid,
		},
		{
			name:       "not checked",
			pool:       validPool,
			status:     sentinel.Status{Reason: sentinel.StatusReasonNotChecked},
			wantReason: sentinel.StatusReasonNotChecked,
		},
		{
			name:       "SDK resolution failed",
			pool:       validPool,
			status:     sentinel.Status{Reason: sentinel.StatusReasonSDKResolutionFailed},
			wantReason: sentinel.StatusReasonSDKResolutionFailed,
		},
		{
			name:       "SDK compile failed",
			pool:       validPool,
			status:     sentinel.Status{Reason: sentinel.StatusReasonSDKCompileFailed},
			wantReason: sentinel.StatusReasonSDKCompileFailed,
		},
		{
			name:       "requirements failed",
			pool:       validPool,
			status:     sentinel.Status{Reason: sentinel.StatusReasonRequirementsFailed},
			wantReason: sentinel.StatusReasonRequirementsFailed,
		},
		{
			name:       "unknown reason is sanitized",
			pool:       validPool,
			status:     sentinel.Status{Reason: "private upstream token and URL"},
			wantReason: ReasonSentinelUnavailable,
		},
		{
			name:      "ready",
			pool:      validPool,
			status:    sentinel.Status{Ready: true, SDKVersion: "currentA1"},
			wantReady: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			provider := &mutableSentinelStatus{status: tt.status}
			snapshot := NewSource(tt.pool, provider).Snapshot()
			if snapshot.ProtocolReady != tt.wantReady || snapshot.ReadyReason != tt.wantReason {
				t.Fatalf("Snapshot()=%#v", snapshot)
			}
			if snapshot.SentinelReady != tt.status.Ready {
				t.Fatalf("sentinel_ready=%v, want %v", snapshot.SentinelReady, tt.status.Ready)
			}
			if tt.status.Ready && snapshot.SentinelSDKVersion != tt.status.SDKVersion {
				t.Fatalf("sentinel_sdk_version=%q", snapshot.SentinelSDKVersion)
			}
		})
	}
}

func TestSourceReadsLiveStatusAndReturnsIndependentPoolNames(t *testing.T) {
	pool, err := fingerprint.ParsePool("chrome144,chrome150")
	if err != nil {
		t.Fatal(err)
	}
	provider := &mutableSentinelStatus{status: sentinel.Status{Reason: sentinel.StatusReasonRequirementsFailed}}
	source := NewSource(pool, provider)

	first := source.Snapshot()
	if first.ProtocolReady || first.ReadyReason != sentinel.StatusReasonRequirementsFailed {
		t.Fatalf("first Snapshot()=%#v", first)
	}
	first.FingerprintPool[0] = "mutated"
	provider.set(sentinel.Status{Ready: true, SDKVersion: "lastGoodA1"})
	second := source.Snapshot()
	if !second.ProtocolReady || second.ReadyReason != "" || second.SentinelSDKVersion != "lastGoodA1" {
		t.Fatalf("second Snapshot()=%#v", second)
	}
	if !slices.Equal(second.FingerprintPool, []string{"chrome144", "chrome150"}) {
		t.Fatalf("pool=%v", second.FingerprintPool)
	}

	provider.set(sentinel.Status{Ready: true, SDKVersion: "lastGoodA1"})
	third := source.Snapshot()
	if !third.ProtocolReady {
		t.Fatalf("validated last-good did not retain readiness: %#v", third)
	}
}

func TestSourceHandlesNilSentinelStatusSource(t *testing.T) {
	pool, err := fingerprint.ParsePool(fingerprint.DefaultPool)
	if err != nil {
		t.Fatal(err)
	}
	snapshot := NewSource(pool, nil).Snapshot()
	if snapshot.ProtocolReady || snapshot.SentinelReady || snapshot.ReadyReason != sentinel.StatusReasonNotChecked {
		t.Fatalf("Snapshot()=%#v", snapshot)
	}
}

type mutableSentinelStatus struct {
	mu     sync.RWMutex
	status sentinel.Status
}

func (s *mutableSentinelStatus) Status() sentinel.Status {
	s.mu.RLock()
	defer s.mu.RUnlock()
	return s.status
}

func (s *mutableSentinelStatus) set(status sentinel.Status) {
	s.mu.Lock()
	s.status = status
	s.mu.Unlock()
}
