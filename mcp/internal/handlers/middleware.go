package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"github.com/google/uuid"
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

// contextKey is a custom type for context keys to avoid collisions
type contextKey string

const (
	// CorrelationIDKey is the context key for correlation IDs
	CorrelationIDKey contextKey = "correlation_id"
)

// CorrelationIDMiddleware adds a unique correlation ID to each request
// for distributed tracing. The ID can be extracted using GetCorrelationID.
//
// Implements constitution principle 11 (Observability) for request tracing.
func CorrelationIDMiddleware() func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			// Generate or extract correlation ID
			correlationID := r.Header.Get("X-Correlation-ID")
			if correlationID == "" {
				// Generate new UUID if not provided
				correlationID = uuid.New().String()
			}

			// Add to response header for client visibility
			w.Header().Set("X-Correlation-ID", correlationID)

			// Add to request context for handler access
			ctx := context.WithValue(r.Context(), CorrelationIDKey, correlationID)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// GetCorrelationID extracts the correlation ID from request context
func GetCorrelationID(ctx context.Context) string {
	if id, ok := ctx.Value(CorrelationIDKey).(string); ok {
		return id
	}
	return ""
}

// HealthCheckHandler returns a simple health check handler.
func HealthCheckHandler(logger *slog.Logger) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`{"status":"healthy"}`))
	}
}
