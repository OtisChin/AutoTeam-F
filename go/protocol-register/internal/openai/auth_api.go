package openai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
)

type Client struct {
	HTTP           *http.Client
	BaseURL        string
	ChatGPTBaseURL string
}

func NewClient(httpClient *http.Client, baseURL, chatGPTBaseURL string) *Client {
	if baseURL == "" {
		baseURL = "https://auth.openai.com"
	}
	if chatGPTBaseURL == "" {
		chatGPTBaseURL = "https://chatgpt.com"
	}
	return &Client{HTTP: httpClient, BaseURL: baseURL, ChatGPTBaseURL: chatGPTBaseURL}
}

func (c *Client) GetCSRF(ctx context.Context) (string, error) {
	var out struct {
		CSRFToken string `json:"csrfToken"`
	}
	if err := c.doJSON(ctx, http.MethodGet, c.ChatGPTBaseURL+"/api/auth/csrf", nil, &out); err != nil {
		return "", err
	}
	if out.CSRFToken == "" {
		return "", fmt.Errorf("csrf token missing")
	}
	return out.CSRFToken, nil
}

func (c *Client) SigninOpenAI(ctx context.Context, csrf string) error {
	var out struct {
		URL string `json:"url"`
	}
	err := c.doJSON(ctx, http.MethodPost, c.ChatGPTBaseURL+"/api/auth/signin/openai", map[string]any{"csrfToken": csrf, "callbackUrl": c.ChatGPTBaseURL + "/", "json": "true"}, &out)
	if err != nil {
		return err
	}
	if out.URL == "" {
		return fmt.Errorf("auth url missing")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, out.URL, nil)
	if err != nil {
		return err
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("oauth signin request failed: HTTP %d", resp.StatusCode)
	}
	return nil
}

func (c *Client) AuthorizeContinue(ctx context.Context, email string) (string, error) {
	var out struct {
		Page struct {
			Type string `json:"type"`
		} `json:"page"`
	}
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/authorize/continue", map[string]any{"username": map[string]any{"value": email, "kind": "email"}, "screen_hint": "signup"}, &out)
	return out.Page.Type, err
}

func (c *Client) RegisterPassword(ctx context.Context, email, password string) error {
	return c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/user/register", map[string]any{"password": password, "username": email}, nil)
}

func (c *Client) SendEmailOTP(ctx context.Context) error {
	return c.doJSON(ctx, http.MethodGet, c.BaseURL+"/api/accounts/email-otp/send", nil, nil)
}

func (c *Client) VerifyEmailOTP(ctx context.Context, code string) (string, error) {
	var out struct {
		ContinueURL string `json:"continue_url"`
	}
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/email-otp/verify", map[string]any{"code": code}, &out)
	return out.ContinueURL, err
}

func (c *Client) CreateAccount(ctx context.Context) error {
	return c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/profile", map[string]any{"name": "Alex Chen", "age": 33}, nil)
}

func (c *Client) GetAuthSession(ctx context.Context) (map[string]any, error) {
	var out map[string]any
	err := c.doJSON(ctx, http.MethodGet, c.ChatGPTBaseURL+"/api/auth/session", nil, &out)
	return out, err
}

func (c *Client) doJSON(ctx context.Context, method, url string, payload any, out any) error {
	var body io.Reader
	if payload != nil {
		raw, _ := json.Marshal(payload)
		body = bytes.NewReader(raw)
	}
	req, err := http.NewRequestWithContext(ctx, method, url, body)
	if err != nil {
		return err
	}
	for key, values := range CommonHeaders(c.ChatGPTBaseURL + "/") {
		for _, value := range values {
			req.Header.Add(key, value)
		}
	}
	if payload != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("%s %s: HTTP %d", method, req.URL.Path, resp.StatusCode)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(resp.Body).Decode(out)
}
