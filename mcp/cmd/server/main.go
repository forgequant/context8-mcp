package main

import (
	"context"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"

	"mcp/internal/cache"
	"mcp/internal/config"
	"mcp/internal/handlers"
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

	logger.Info("mcp_service_starting",
		"port", cfg.Port,
		"timeout_ms", cfg.TimeoutMS,
		"redis_url", cfg.RedisURL,
	)

	// Initialize Redis cache reader
	cacheReader, err := cache.New(cfg.RedisURL, cfg.RedisPassword, logger)
	if err != nil {
		logger.Error("failed to create cache reader", "error", err)
		os.Exit(1)
	}
	defer cacheReader.Close()

	logger.Info("cache_reader_initialized")

	// Create handlers
	getReportHandler := handlers.NewGetReportHandler(cacheReader, logger)

	// Create router
	r := chi.NewRouter()

	// Add middleware per constitution principle 13 (MCP Contract)
	r.Use(middleware.Recoverer)
	r.Use(handlers.LoggingMiddleware(logger))
	r.Use(handlers.TimeoutMiddleware(cfg.Timeout(), logger))

	// Health check endpoint (for docker healthcheck)
	r.Get("/health", handlers.HealthCheckHandler(logger))

	// MCP endpoint per constitution principle 13
	// GET /get_report?symbol=BTCUSDT
	r.Get("/get_report", getReportHandler.ServeHTTP)

	// Start HTTP server
	srv := &http.Server{
		Addr:         fmt.Sprintf(":%d", cfg.Port),
		Handler:      r,
		ReadTimeout:  10 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	// Start server in goroutine
	go func() {
		logger.Info("mcp_server_listening", "port", cfg.Port, "status", "healthy")
		if err := srv.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("server_error", "error", err)
			os.Exit(1)
		}
	}()

	// Wait for interrupt signal
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
	sig := <-sigChan

	// Graceful shutdown
	logger.Info("shutdown_signal_received", "signal", sig.String())
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := srv.Shutdown(ctx); err != nil {
		logger.Error("server_shutdown_error", "error", err)
	}

	logger.Info("mcp_service_stopped")
}
