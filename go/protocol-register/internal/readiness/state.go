package readiness

import (
	"strings"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/sentinel"
)

const (
	ReasonFingerprintPoolInvalid = "fingerprint_pool_invalid"
	ReasonSentinelUnavailable    = "sentinel_unavailable"
)

type Snapshot struct {
	ProtocolReady      bool     `json:"protocol_ready"`
	FingerprintPool    []string `json:"fingerprint_pool"`
	SentinelReady      bool     `json:"sentinel_ready"`
	SentinelSDKVersion string   `json:"sentinel_sdk_version"`
	ReadyReason        string   `json:"ready_reason"`
}

type SentinelStatusSource interface {
	Status() sentinel.Status
}

type Source struct {
	poolNames []string
	sentinel  SentinelStatusSource
}

func NewSource(pool fingerprint.Pool, sentinelSource SentinelStatusSource) *Source {
	return &Source{
		poolNames: append([]string(nil), pool.Names()...),
		sentinel:  sentinelSource,
	}
}

func (s *Source) Snapshot() Snapshot {
	if s == nil {
		return Snapshot{
			FingerprintPool: []string{},
			ReadyReason:     ReasonFingerprintPoolInvalid,
		}
	}
	status := sentinel.Status{Reason: sentinel.StatusReasonNotChecked}
	if s.sentinel != nil {
		status = s.sentinel.Status()
	}
	sdkVersion := strings.TrimSpace(status.SDKVersion)
	sentinelReady := status.Ready && sdkVersion != ""
	snapshot := Snapshot{
		FingerprintPool:    append([]string{}, s.poolNames...),
		SentinelReady:      sentinelReady,
		SentinelSDKVersion: sdkVersion,
	}
	if len(s.poolNames) == 0 {
		snapshot.ReadyReason = ReasonFingerprintPoolInvalid
		return snapshot
	}
	if !sentinelReady {
		snapshot.SentinelSDKVersion = ""
		snapshot.ReadyReason = SanitizeReason(status.Reason)
		if snapshot.ReadyReason == "" {
			snapshot.ReadyReason = ReasonSentinelUnavailable
		}
		return snapshot
	}
	snapshot.ProtocolReady = true
	return snapshot
}

func SanitizeReason(reason string) string {
	switch strings.TrimSpace(reason) {
	case "":
		return ""
	case ReasonFingerprintPoolInvalid:
		return ReasonFingerprintPoolInvalid
	case ReasonSentinelUnavailable:
		return ReasonSentinelUnavailable
	case sentinel.StatusReasonNotChecked:
		return sentinel.StatusReasonNotChecked
	case sentinel.StatusReasonSDKResolutionFailed:
		return sentinel.StatusReasonSDKResolutionFailed
	case sentinel.StatusReasonSDKCompileFailed:
		return sentinel.StatusReasonSDKCompileFailed
	case sentinel.StatusReasonRequirementsFailed:
		return sentinel.StatusReasonRequirementsFailed
	default:
		return ReasonSentinelUnavailable
	}
}
