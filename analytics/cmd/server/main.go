package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"

	"github.com/prometheus/client_golang/prometheus/promhttp"

	"analytics/internal/aggregator"
	"analytics/internal/config"
	"analytics/internal/consumer"
	"analytics/internal/instrumentation"
	"analytics/internal/models"
)

func main() {
	// Load configuration
	cfg, err := config.LoadFromEnv()
	if err != nil {
		slog.Error("failed to load configuration", "error", err)
		os.Exit(1)
	}

	// Validate configuration
	if err := cfg.Validate(); err != nil {
		slog.Error("invalid configuration", "error", err)
		os.Exit(1)
	}

	// Setup structured logging per constitution principle 11
	logLevel := slog.LevelInfo
	switch cfg.LogLevel {
	case "debug":
		logLevel = slog.LevelDebug
	case "warn":
		logLevel = slog.LevelWarn
	case "error":
		logLevel = slog.LevelError
	}

	logger := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{
		Level: logLevel,
	}))
	slog.SetDefault(logger)

	logger.Info("analytics_service_starting",
		"redis_url", cfg.RedisURL,
		"stream_key", cfg.StreamKey,
		"consumer_group", cfg.ConsumerGroup,
		"symbols", cfg.Symbols,
		"cache_ttl", cfg.CacheTTL,
	)

	// Create context with cancellation
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Initialize Redis cache publisher
	cachePublisher, err := aggregator.NewRedisPublisher(
		cfg.RedisURL,
		cfg.RedisPassword,
		cfg.CacheTTL,
		logger,
	)
	if err != nil {
		logger.Error("failed to create redis publisher", "error", err)
		os.Exit(1)
	}
	defer cachePublisher.Close()

	logger.Info("redis_publisher_initialized")

	// Initialize Prometheus metrics (Phase 5 - T093, T094)
	metrics := instrumentation.NewMetrics()
	logger.Info("metrics_initialized")

	// Start Prometheus HTTP server for metrics endpoint
	go func() {
		metricsPort := ":9091"
		http.Handle("/metrics", promhttp.Handler())
		logger.Info("metrics_server_starting", "port", metricsPort)
		if err := http.ListenAndServe(metricsPort, nil); err != nil {
			logger.Error("metrics_server_failed", "error", err)
		}
	}()

	// Initialize report aggregator
	agg := aggregator.New(cachePublisher, logger, cfg.CacheTTL, metrics)

	logger.Info("aggregator_initialized")

	// Create event handler that processes events through aggregator
	eventHandler := func(ctx context.Context, envelope *models.MarketEventEnvelope, streamID string) error {
		return agg.ProcessEvent(ctx, envelope)
	}

	// Initialize Redis Streams consumer
	consumerCfg := consumer.Config{
		RedisURL:      cfg.RedisURL,
		RedisPassword: cfg.RedisPassword,
		StreamKey:     cfg.StreamKey,
		ConsumerGroup: cfg.ConsumerGroup,
		ConsumerName:  fmt.Sprintf("analytics-%s", os.Getenv("HOSTNAME")),
		BlockTime:     0, // Use default
		BatchSize:     10,
	}

	cons, err := consumer.New(consumerCfg, eventHandler, logger)
	if err != nil {
		logger.Error("failed to create consumer", "error", err)
		os.Exit(1)
	}
	defer cons.Close()

	logger.Info("consumer_initialized",
		"consumer_group", cfg.ConsumerGroup,
		"stream_key", cfg.StreamKey,
	)

	// Setup signal handling for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start consumer in a goroutine
	errChan := make(chan error, 1)
	go func() {
		logger.Info("consumer_starting")
		if err := cons.Start(ctx); err != nil && err != context.Canceled {
			errChan <- err
		}
	}()

	logger.Info("analytics_service_running", "status", "healthy")

	// Wait for shutdown signal or error
	select {
	case sig := <-sigChan:
		logger.Info("shutdown_signal_received", "signal", sig.String())
		cancel()
	case err := <-errChan:
		logger.Error("consumer_error", "error", err)
		cancel()
	}

	logger.Info("analytics_service_stopped")
}
