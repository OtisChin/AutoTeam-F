### Task 3: Go HTTP Client and Mail OTP Polling

**Files:**
- Create: `go/protocol-register/internal/httpclient/client.go`
- Create: `go/protocol-register/internal/mailbridge/client.go`
- Create: `go/protocol-register/internal/mailbridge/otp.go`
- Create: `go/protocol-register/internal/mailbridge/otp_test.go`

**Interfaces:**
- Produces: `httpclient.New(proxyURL string, timeout time.Duration) (*http.Client, error)`.
- Produces: `mailbridge.ExtractOTP(payload []byte) string`.
- Produces: `mailbridge.Client.WaitForOTP(ctx context.Context, receiveCodeURL string) (string, error)`.

- [ ] **Step 1: Write failing OTP tests**

Create `go/protocol-register/internal/mailbridge/otp_test.go`:

```go
package mailbridge_test

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
	"autoteam-f/protocol-register/internal/mailbridge"
)

func TestExtractOTPFromJSONAndHTML(t *testing.T) {
	for _, input := range [][]byte{
		[]byte(`{"ok":true,"code":"013555"}`),
		[]byte(`{"mail":{"content":"Use 246810 to continue"}}`),
		[]byte(`<html>Your OpenAI verification code is <b>135790</b></html>`),
	} {
		if got := mailbridge.ExtractOTP(input); got == "" {
			t.Fatalf("missing code from %s", input)
		}
	}
}

func TestWaitForOTPPollsUntilCode(t *testing.T) {
	calls := 0
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls++
		if calls < 2 {
			w.WriteHeader(http.StatusNotFound)
			_, _ = w.Write([]byte(`{"ok":false}`))
			return
		}
		_, _ = w.Write([]byte(`{"code":"112233"}`))
	}))
	defer srv.Close()
	client := mailbridge.NewClient(srv.Client(), 10*time.Millisecond)
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	code, err := client.WaitForOTP(ctx, srv.URL)
	if err != nil || code != "112233" {
		t.Fatalf("code=%q err=%v", code, err)
	}
}
```

- [ ] **Step 2: Run tests to verify failure**

Run:

```powershell
cd go/protocol-register
go test ./internal/mailbridge -run Test -v
```

Expected: FAIL because package implementation is missing.

- [ ] **Step 3: Implement HTTP client and mailbridge**

Create `go/protocol-register/internal/httpclient/client.go`:

```go
package httpclient

import (
	"net/http"
	"net/http/cookiejar"
	"net/url"
	"time"
)

func New(proxyURL string, timeout time.Duration) (*http.Client, error) {
	transport := http.DefaultTransport.(*http.Transport).Clone()
	if proxyURL != "" {
		parsed, err := url.Parse(proxyURL)
		if err != nil {
			return nil, err
		}
		transport.Proxy = http.ProxyURL(parsed)
	}
	jar, _ := cookiejar.New(nil)
	if timeout <= 0 {
		timeout = 190 * time.Second
	}
	return &http.Client{Transport: transport, Jar: jar, Timeout: timeout}, nil
}
```

Create `go/protocol-register/internal/mailbridge/otp.go`:

```go
package mailbridge

import (
	"encoding/json"
	"regexp"
)

var otpPattern = regexp.MustCompile(`\b\d{6}\b`)

func ExtractOTP(payload []byte) string {
	var data any
	if json.Unmarshal(payload, &data) == nil {
		if code := findCode(data); code != "" {
			return code
		}
	}
	return otpPattern.FindString(string(payload))
}

func findCode(value any) string {
	switch typed := value.(type) {
	case map[string]any:
		for _, key := range []string{"code", "otp", "verification_code", "verificationCode"} {
			if raw, ok := typed[key].(string); ok {
				if code := otpPattern.FindString(raw); code != "" {
					return code
				}
			}
		}
		for _, raw := range typed {
			if code := findCode(raw); code != "" {
				return code
			}
		}
	case []any:
		for _, raw := range typed {
			if code := findCode(raw); code != "" {
				return code
			}
		}
	case string:
		return otpPattern.FindString(typed)
	}
	return ""
}
```

Create `go/protocol-register/internal/mailbridge/client.go`:

```go
package mailbridge

import (
	"context"
	"fmt"
	"io"
	"net/http"
	"time"
)

type Client struct {
	httpClient   *http.Client
	pollInterval time.Duration
}

func NewClient(httpClient *http.Client, pollInterval time.Duration) *Client {
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	if pollInterval <= 0 {
		pollInterval = 3 * time.Second
	}
	return &Client{httpClient: httpClient, pollInterval: pollInterval}
}

func (c *Client) WaitForOTP(ctx context.Context, receiveCodeURL string) (string, error) {
	if receiveCodeURL == "" {
		return "", fmt.Errorf("receive_code_url is empty")
	}
	ticker := time.NewTicker(c.pollInterval)
	defer ticker.Stop()
	for {
		code, err := c.fetchOnce(ctx, receiveCodeURL)
		if err == nil && code != "" {
			return code, nil
		}
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-ticker.C:
		}
	}
}

func (c *Client) fetchOnce(ctx context.Context, url string) (string, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return "", err
	}
	req.Header.Set("Accept", "application/json,text/html,*/*")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return "", err
	}
	if code := ExtractOTP(body); code != "" {
		return code, nil
	}
	return "", fmt.Errorf("no otp in response status=%d", resp.StatusCode)
}
```

- [ ] **Step 4: Run tests and commit**

Run:

```powershell
cd go/protocol-register
go test ./...
cd ..\..
git add go/protocol-register/internal/httpclient go/protocol-register/internal/mailbridge
git commit -m "feat(protocol): add Go mail OTP polling"
```

Expected: Go tests PASS and commit succeeds.

---

