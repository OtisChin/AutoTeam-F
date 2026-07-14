package config

import (
	"os"
	"path/filepath"
	"reflect"
	"testing"
)

func TestConfigContainsOnlyPayPalProxyFields(t *testing.T) {
	typ := reflect.TypeOf(Config{})
	want := []struct {
		name string
		tag  string
	}{
		{name: "ProxyJP", tag: "proxy_jp"},
		{name: "ProxyUS", tag: "proxy_us"},
	}

	if typ.NumField() != len(want) {
		t.Fatalf("Config field count = %d, want %d", typ.NumField(), len(want))
	}
	for i, fieldWant := range want {
		field := typ.Field(i)
		if field.Name != fieldWant.name || field.Tag.Get("json") != fieldWant.tag {
			t.Fatalf("field %d = (%s, %q), want (%s, %q)", i, field.Name, field.Tag.Get("json"), fieldWant.name, fieldWant.tag)
		}
	}
}

func TestLoadReadsProxyPair(t *testing.T) {
	path := filepath.Join(t.TempDir(), "config.json")
	if err := os.WriteFile(path, []byte(`{"proxy_jp":"socks5://jp.example:1080","proxy_us":"socks5://us.example:1080"}`), 0o600); err != nil {
		t.Fatal(err)
	}

	cfg, err := Load(path)
	if err != nil {
		t.Fatal(err)
	}
	if cfg.ProxyJP != "socks5://jp.example:1080" || cfg.ProxyUS != "socks5://us.example:1080" {
		t.Fatalf("Load() = %#v", cfg)
	}
}

func TestLoadReportsMissingConfig(t *testing.T) {
	_, err := Load(filepath.Join(t.TempDir(), "missing.json"))
	if err == nil {
		t.Fatal("Load() error = nil, want missing-file error")
	}
}
