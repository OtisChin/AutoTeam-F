package config

import (
	"encoding/json"
	"os"
)

// Config contains the two proxies used by the standalone PayPal link helper.
type Config struct {
	ProxyJP string `json:"proxy_jp"`
	ProxyUS string `json:"proxy_us"`
}

// Load reads a JSON proxy configuration from path.
func Load(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var cfg Config
	if err := json.Unmarshal(data, &cfg); err != nil {
		return nil, err
	}
	return &cfg, nil
}
