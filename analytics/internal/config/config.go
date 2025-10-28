package config

import (
	"fmt"
	"strings"
	"time"

	"github.com/caarlos0/env/v11"
)

// Config holds the analytics service configuration.
type Config struct {
	// Redis
	RedisURL      string `env:"REDIS_URL" envDefault:"redis://localhost:6379"`
	RedisPassword string `env:"REDIS_PASSWORD"`
	ConsumerGroup string `env:"CONSUMER_GROUP" envDefault:"context8"`
	StreamKey     string `env:"STREAM_KEY" envDefault:"nt:binance"`

	// Symbols
	Symbols []string `env:"SYMBOLS" envSeparator:"," envDefault:"BTCUSDT,ETHUSDT"`

	// Performance (parsed as seconds)
	CacheTTLSec     int `env:"CACHE_TTL_SEC" envDefault:"300"`
	ReportWindowSec int `env:"REPORT_WINDOW_SEC" envDefault:"1800"`
	FlowWindowSec   int `env:"FLOW_WINDOW_SEC" envDefault:"30"`

	// Computed durations (not from env)
	CacheTTL     time.Duration `env:"-"`
	ReportWindow time.Duration `env:"-"`
	FlowWindow   time.Duration `env:"-"`

	// Observability
	LogLevel       string `env:"LOG_LEVEL" envDefault:"info"`
	PrometheusPort int    `env:"PROMETHEUS_PORT" envDefault:"9091"`

	// Thresholds
	WallThresholdMultiplier   float64 `env:"WALL_THRESHOLD_MULTIPLIER" envDefault:"1.5"`
	VacuumThresholdPercentile int     `env:"VACUUM_THRESHOLD_PERCENTILE" envDefault:"10"`
}

// LoadFromEnv loads configuration from environment variables.
func LoadFromEnv() (*Config, error) {
	cfg := &Config{}
	opts := env.Options{
		Prefix: "",
	}

	if err := env.ParseWithOptions(cfg, opts); err != nil {
		return nil, fmt.Errorf("failed to parse environment variables: %w", err)
	}

	// Trim whitespace from symbols
	for i := range cfg.Symbols {
		cfg.Symbols[i] = strings.TrimSpace(cfg.Symbols[i])
	}

	// Convert seconds to time.Duration
	cfg.CacheTTL = time.Duration(cfg.CacheTTLSec) * time.Second
	cfg.ReportWindow = time.Duration(cfg.ReportWindowSec) * time.Second
	cfg.FlowWindow = time.Duration(cfg.FlowWindowSec) * time.Second

	return cfg, nil
}

// Validate validates the configuration.
func (c *Config) Validate() error {
	if len(c.Symbols) == 0 {
		return fmt.Errorf("at least one symbol must be configured")
	}

	for _, symbol := range c.Symbols {
		if !strings.HasSuffix(symbol, "USDT") {
			return fmt.Errorf("symbol %s must end with USDT for MVP", symbol)
		}
	}

	validLogLevels := map[string]bool{"debug": true, "info": true, "warn": true, "error": true}
	if !validLogLevels[c.LogLevel] {
		return fmt.Errorf("invalid log level: %s", c.LogLevel)
	}

	if c.CacheTTL < time.Second {
		return fmt.Errorf("cache TTL must be at least 1 second")
	}

	if c.ReportWindow < time.Second {
		return fmt.Errorf("report window must be at least 1 second")
	}

	if c.FlowWindow < time.Second {
		return fmt.Errorf("flow window must be at least 1 second")
	}

	return nil
}
