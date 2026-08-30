package sentinel

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"

	"autoteam-f/protocol-register/internal/fingerprint"
	"autoteam-f/protocol-register/internal/openai"
)

var (
	ErrInvalidChallengeInput    = errors.New("invalid Sentinel challenge input")
	ErrInvalidChallengeResponse = errors.New("invalid Sentinel challenge response")
)

const maxChallengeBytes int64 = 1024 * 1024

type challengeRequest struct {
	P    string `json:"p"`
	ID   string `json:"id"`
	Flow string `json:"flow"`
}

type challengeResult struct {
	Payload map[string]any
	Token   string
}

type challengeTransport struct {
	requestURL string
	frameURL   string
	timeout    time.Duration
}

func newChallengeTransport(cfg Config) (challengeTransport, error) {
	normalized, err := normalizeConfig(cfg)
	if err != nil {
		return challengeTransport{}, err
	}
	return challengeTransport{
		requestURL: normalized.RequestURL,
		frameURL:   normalized.FrameURL,
		timeout:    normalized.HTTPTimeout,
	}, nil
}

func (t challengeTransport) Fetch(
	ctx context.Context,
	client *http.Client,
	profile fingerprint.Profile,
	sdk SDK,
	deviceID string,
	flow string,
	requestP string,
) (challengeResult, error) {
	if ctx == nil {
		return challengeResult{}, ErrInvalidChallengeInput
	}
	if err := ctx.Err(); err != nil {
		return challengeResult{}, err
	}
	if client == nil {
		return challengeResult{}, ErrNilHTTPClient
	}
	if t.requestURL != defaultRequestURL || t.frameURL != defaultFrameURL || t.timeout <= 0 {
		return challengeResult{}, ErrInvalidChallengeInput
	}
	normalizedSDK, err := normalizeSDK(sdk)
	if err != nil || !validChallengeProfile(profile) {
		return challengeResult{}, ErrInvalidChallengeInput
	}
	deviceID = strings.TrimSpace(deviceID)
	flow = strings.TrimSpace(flow)
	requestP = strings.TrimSpace(requestP)
	if deviceID == "" || flow == "" || requestP == "" ||
		len(deviceID) > maxRuntimeOutputBytes || len(flow) > maxRuntimeOutputBytes || len(requestP) > maxRuntimeOutputBytes {
		return challengeResult{}, ErrInvalidChallengeInput
	}

	body, err := json.Marshal(challengeRequest{P: requestP, ID: deviceID, Flow: flow})
	if err != nil || len(body) > maxRuntimeInputBytes {
		return challengeResult{}, ErrInvalidChallengeInput
	}
	requestContext, cancel := context.WithTimeout(ctx, t.timeout)
	defer cancel()
	request, err := http.NewRequestWithContext(requestContext, http.MethodPost, t.requestURL, bytes.NewReader(body))
	if err != nil {
		return challengeResult{}, ErrInvalidChallengeInput
	}
	request.Header = openai.APIHeaders(
		"https://sentinel.openai.com",
		t.frameURL+"?sv="+url.QueryEscape(normalizedSDK.Version),
		profile,
	)
	request.Header.Set("Accept", "*/*")
	request.Header.Set("Accept-Encoding", "gzip, deflate, br, zstd")
	request.Header.Set("Content-Type", "text/plain;charset=UTF-8")

	boundedClient := *client
	boundedClient.CheckRedirect = func(*http.Request, []*http.Request) error {
		return http.ErrUseLastResponse
	}
	response, err := boundedClient.Do(request)
	if err != nil {
		if contextErr := requestContext.Err(); contextErr != nil {
			return challengeResult{}, contextErr
		}
		if errors.Is(err, context.Canceled) {
			return challengeResult{}, context.Canceled
		}
		if errors.Is(err, context.DeadlineExceeded) {
			return challengeResult{}, context.DeadlineExceeded
		}
		return challengeResult{}, ErrHTTPTransport
	}
	if response == nil || response.Body == nil {
		return challengeResult{}, ErrInvalidChallengeResponse
	}
	defer response.Body.Close()
	if response.StatusCode != http.StatusOK {
		return challengeResult{}, fmt.Errorf("%w: %d", ErrUnexpectedHTTPStatus, response.StatusCode)
	}
	if response.ContentLength > maxChallengeBytes {
		return challengeResult{}, ErrResponseTooLarge
	}
	payloadBytes, err := io.ReadAll(io.LimitReader(response.Body, maxChallengeBytes+1))
	if err != nil {
		return challengeResult{}, ErrInvalidChallengeResponse
	}
	if int64(len(payloadBytes)) > maxChallengeBytes {
		return challengeResult{}, ErrResponseTooLarge
	}

	decoder := json.NewDecoder(bytes.NewReader(payloadBytes))
	decoder.UseNumber()
	var payload map[string]any
	if err := decoder.Decode(&payload); err != nil || payload == nil {
		return challengeResult{}, ErrInvalidChallengeResponse
	}
	if err := requireJSONEOF(decoder); err != nil {
		return challengeResult{}, ErrInvalidChallengeResponse
	}
	token, ok := payload["token"].(string)
	if !ok {
		return challengeResult{}, ErrInvalidChallengeResponse
	}
	token = strings.TrimSpace(token)
	if token == "" {
		return challengeResult{}, ErrInvalidChallengeResponse
	}
	payload["token"] = token
	return challengeResult{Payload: payload, Token: token}, nil
}

func validChallengeProfile(profile fingerprint.Profile) bool {
	return strings.TrimSpace(profile.Name) != "" &&
		profile.Major > 0 &&
		strings.TrimSpace(profile.UserAgent) != "" &&
		strings.TrimSpace(profile.SecCHUA) != "" &&
		strings.TrimSpace(profile.SecCHUAMobile) != "" &&
		strings.TrimSpace(profile.SecCHUAPlatform) != "" &&
		strings.TrimSpace(profile.AcceptLanguage) != ""
}
