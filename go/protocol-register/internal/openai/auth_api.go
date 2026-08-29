package openai

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

type Client struct {
	HTTP           *http.Client
	BaseURL        string
	ChatGPTBaseURL string
	UserAgent      string
}

func NewClient(httpClient *http.Client, baseURL, chatGPTBaseURL, userAgent string) *Client {
	if baseURL == "" {
		baseURL = "https://auth.openai.com"
	}
	if chatGPTBaseURL == "" {
		chatGPTBaseURL = "https://chatgpt.com"
	}
	if userAgent == "" {
		userAgent = defaultTransportUserAgent
	}
	return &Client{
		HTTP:           httpClient,
		BaseURL:        strings.TrimRight(baseURL, "/"),
		ChatGPTBaseURL: strings.TrimRight(chatGPTBaseURL, "/"),
		UserAgent:      userAgent,
	}
}

func (c *Client) GetCSRF(ctx context.Context) (string, error) {
	var out struct {
		CSRFToken string `json:"csrfToken"`
	}
	if err := c.doJSON(ctx, http.MethodGet, c.ChatGPTBaseURL+"/api/auth/csrf", nil, &out, c.chatGPTAPIHeaders()); err != nil {
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
	form := url.Values{}
	form.Set("csrfToken", csrf)
	form.Set("callbackUrl", c.ChatGPTBaseURL+"/")
	form.Set("json", "true")
	err := c.doForm(ctx, http.MethodPost, c.ChatGPTBaseURL+"/api/auth/signin/openai", form, &out, c.chatGPTAPIHeaders())
	if err != nil {
		return err
	}
	if out.URL == "" {
		return fmt.Errorf("auth url missing")
	}
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, out.URL, nil)
	if err != nil {
		return fmt.Errorf("build oauth signin request")
	}
	for key, values := range NavigationHeaders(c.ChatGPTBaseURL+"/auth/login", c.UserAgent) {
		for _, value := range values {
			req.Header.Add(key, value)
		}
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("oauth signin request failed")
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
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/authorize/continue", map[string]any{"username": map[string]any{"value": email, "kind": "email"}, "screen_hint": "signup"}, &out, c.authAPIHeaders())
	return out.Page.Type, err
}

func (c *Client) RegisterPassword(ctx context.Context, email, password string) error {
	return c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/user/register", map[string]any{"password": password, "username": email}, nil, c.authAPIHeaders())
}

func (c *Client) SendEmailOTP(ctx context.Context) error {
	return c.doJSON(ctx, http.MethodGet, c.BaseURL+"/api/accounts/email-otp/send", nil, nil, c.authAPIHeaders())
}

func (c *Client) VerifyEmailOTP(ctx context.Context, code string) (string, error) {
	var out struct {
		ContinueURL string `json:"continue_url"`
	}
	err := c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/email-otp/verify", map[string]any{"code": code}, &out, c.authAPIHeaders())
	return out.ContinueURL, err
}

func (c *Client) CreateAccount(ctx context.Context) error {
	return c.doJSON(ctx, http.MethodPost, c.BaseURL+"/api/accounts/profile", map[string]any{"name": "Alex Chen", "age": 33}, nil, c.authAPIHeaders())
}

func (c *Client) GetAuthSession(ctx context.Context) (map[string]any, error) {
	var out map[string]any
	err := c.doJSON(ctx, http.MethodGet, c.ChatGPTBaseURL+"/api/auth/session", nil, &out, c.chatGPTAPIHeaders())
	return out, err
}

func (c *Client) doJSON(ctx context.Context, method, targetURL string, payload any, out any, headers http.Header) error {
	var body io.Reader
	if payload != nil {
		raw, err := json.Marshal(payload)
		if err != nil {
			return fmt.Errorf("encode JSON request: %w", err)
		}
		body = bytes.NewReader(raw)
	}
	headers = headers.Clone()
	if payload != nil {
		headers.Set("Content-Type", "application/json")
	}
	return c.do(ctx, method, targetURL, body, out, headers)
}

func (c *Client) doForm(ctx context.Context, method, targetURL string, form url.Values, out any, headers http.Header) error {
	headers = headers.Clone()
	headers.Set("Content-Type", "application/x-www-form-urlencoded")
	return c.do(ctx, method, targetURL, strings.NewReader(form.Encode()), out, headers)
}

func (c *Client) do(ctx context.Context, method, targetURL string, body io.Reader, out any, headers http.Header) error {
	req, err := http.NewRequestWithContext(ctx, method, targetURL, body)
	if err != nil {
		return fmt.Errorf("build %s request", method)
	}
	for key, values := range headers {
		for _, value := range values {
			req.Header.Add(key, value)
		}
	}
	resp, err := c.HTTP.Do(req)
	if err != nil {
		return fmt.Errorf("%s request failed", method)
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		return fmt.Errorf("%s %s: HTTP %d", method, req.URL.Path, resp.StatusCode)
	}
	if out == nil {
		return nil
	}
	return json.NewDecoder(io.LimitReader(resp.Body, 1<<20)).Decode(out)
}

func (c *Client) chatGPTAPIHeaders() http.Header {
	return APIHeaders(baseOrigin(c.ChatGPTBaseURL), c.ChatGPTBaseURL+"/auth/login", c.UserAgent)
}

func (c *Client) authAPIHeaders() http.Header {
	return APIHeaders(baseOrigin(c.BaseURL), c.BaseURL+"/", c.UserAgent)
}

func baseOrigin(raw string) string {
	parsed, err := url.Parse(raw)
	if err != nil || parsed.Scheme == "" || parsed.Host == "" {
		return strings.TrimRight(raw, "/")
	}
	return parsed.Scheme + "://" + parsed.Host
}
