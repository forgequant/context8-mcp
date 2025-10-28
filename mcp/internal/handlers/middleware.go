package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"time"
)

// TimeoutMiddleware enforces a timeout on all requests.
//
// Implements constitution principle 13 (MCP Contract):
// - Timeout ≤ 150 ms per FR-023
func TimeoutMiddleware(timeout time.Duration, logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Create context with timeout
			ctx, cancel := context.WithTimeout(r.Context(), timeout)
			defer cancel()

			// Create a channel to signal completion
			done := make(chan struct{})

			// Process request in goroutine
			go func() {
				next.ServeHTTP(w, r.WithContext(ctx))
				close(done)
			}()

			// Wait for completion or timeout
			select {
			case <-done:
				// Request completed successfully
				return
			case <-ctx.Done():
				// Timeout occurred
				logger.Warn("request_timeout",
					"path", r.URL.Path,
					"timeout_ms", timeout.Milliseconds(),
					"remote_addr", r.RemoteAddr,
				)
				// Note: Response may have already been written by handler
				// This is primarily for logging and context cancellation
				return
			}
		})
	}
}

// LoggingMiddleware logs all incoming requests.
//
// Implements constitution principle 11 (Observability) with structured logging.
func LoggingMiddleware(logger *slog.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			start := time.Now()

			// Wrap response writer to capture status code
			wrapped := &responseWriter{ResponseWriter: w, statusCode: http.StatusOK}

			// Process request
			next.ServeHTTP(wrapped, r)

			// Log request completion
			duration := time.Since(start)

			logger.Info("http_request",
				"method", r.Method,
				"path", r.URL.Path,
				"query", r.URL.RawQuery,
				"status", wrapped.statusCode,
				"duration_ms", duration.Milliseconds(),
				"remote_addr", r.RemoteAddr,
			)
		})
	}
}

// responseWriter wraps http.ResponseWriter to capture the status code.
type responseWriter struct {
	http.ResponseWriter
	statusCode int
}

func (rw *responseWriter) WriteHeader(code int) {
	rw.statusCode = code
	rw.ResponseWriter.WriteHeader(code)
}

// HealthCheckHandler returns a simple health check handler.
func HealthCheckHandler(logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"healthy"}`))
	}
}
