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

type WaitOptions struct {
	IssuedAfterUnix int64
	ExcludeCodes    map[string]bool
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
	return c.WaitForOTPWithOptions(ctx, receiveCodeURL, WaitOptions{})
}

func (c *Client) WaitForOTPWithOptions(ctx context.Context, receiveCodeURL string, opts WaitOptions) (string, error) {
	if receiveCodeURL == "" {
		return "", fmt.Errorf("receive_code_url is empty")
	}
	ticker := time.NewTicker(c.pollInterval)
	defer ticker.Stop()
	for {
		code, err := c.fetchOnce(ctx, receiveCodeURL, opts)
		if err == nil && code != "" && !opts.ExcludeCodes[code] {
			return code, nil
		}
		select {
		case <-ctx.Done():
			return "", ctx.Err()
		case <-ticker.C:
		}
	}
}

func (c *Client) fetchOnce(ctx context.Context, receiveCodeURL string, opts WaitOptions) (string, error) {
	body, status, err := c.fetch(ctx, receiveCodeURL)
	if err != nil {
		return "", err
	}
	if code := ExtractOTPWithOptions(body, opts); code != "" {
		return code, nil
	}
	// Listing pages may only carry mail metadata; the OTP lives in per-message
	// detail links (e.g. icloudyang.com). Follow the newest few and parse those.
	detailURLs := DetailURLs(receiveCodeURL, body)
	for index, detailURL := range detailURLs {
		if index >= detailFetchLimit {
			break
		}
		detailBody, _, err := c.fetch(ctx, detailURL)
		if err != nil {
			continue
		}
		if code := ExtractOTPFromDetail(detailBody, opts); code != "" {
			return code, nil
		}
	}
	return "", fmt.Errorf("no otp in response status=%d", status)
}

const detailFetchLimit = 8

func (c *Client) fetch(ctx context.Context, url string) ([]byte, int, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, 0, err
	}
	req.Header.Set("Accept", "application/json,text/html,*/*")
	resp, err := c.httpClient.Do(req)
	if err != nil {
		return nil, 0, err
	}
	defer resp.Body.Close()
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1<<20))
	if err != nil {
		return nil, resp.StatusCode, err
	}
	return body, resp.StatusCode, nil
}
