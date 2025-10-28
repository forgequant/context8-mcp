package config

import (
	"fmt"
	"time"

	"github.com/caarlos0/env/v11"
)

// Config holds the MCP service configuration.
type Config struct {
	// Server
	Port      int `env:"MCP_PORT" envDefault:"8080"`
	TimeoutMS int `env:"TIMEOUT_MS" envDefault:"150"`

	// Redis
	RedisURL      string `env:"REDIS_URL" envDefault:"redis://localhost:6379"`
	RedisPassword string `env:"REDIS_PASSWORD"`

	// Observability
	LogLevel       string `env:"LOG_LEVEL" envDefault:"info"`
	PrometheusPort int    `env:"PROMETHEUS_PORT" envDefault:"9092"`
}

// Timeout returns the timeout as a time.Duration.
func (c *Config) Timeout() time.Duration {
	return time.Duration(c.TimeoutMS) * time.Millisecond
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

	return cfg, nil
}

// Validate validates the configuration.
func (c *Config) Validate() error {
	if c.Port < 1 || c.Port > 65535 {
		return fmt.Errorf("invalid port: %d", c.Port)
	}

	if c.TimeoutMS < 1 {
		return fmt.Errorf("timeout must be at least 1ms, got %dms", c.TimeoutMS)
	}

	validLogLevels := map[string]bool{"debug": true, "info": true, "warn": true, "error": true}
	if !validLogLevels[c.LogLevel] {
		return fmt.Errorf("invalid log level: %s", c.LogLevel)
	}

	return nil
}
