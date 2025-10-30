package mcp

import (
	"context"
	"log/slog"
)

// LogMCPRequest logs an MCP request with structured fields
// per Constitution Principle 11 (Observability)
func LogMCPRequest(ctx context.Context, logger *slog.Logger, tool string, symbol string, correlationID string) {
	logger.InfoContext(ctx, "mcp_request",
		"component", "mcp-provider",
		"tool_name", tool,
		"symbol", symbol,
		"correlation_id", correlationID,
	)
}

// LogMCPSuccess logs successful MCP tool execution with metrics
func LogMCPSuccess(ctx context.Context, logger *slog.Logger, tool string, symbol string, correlationID string, cacheHit bool, latencyMS int64) {
	logger.InfoContext(ctx, "mcp_success",
		"component", "mcp-provider",
		"tool_name", tool,
		"symbol", symbol,
		"correlation_id", correlationID,
		"cache_hit", cacheHit,
		"latency_ms", latencyMS,
	)
}

// LogMCPError logs MCP request errors with context
func LogMCPError(ctx context.Context, logger *slog.Logger, tool string, symbol string, correlationID string, errorCode int, errorMsg string) {
	logger.ErrorContext(ctx, "mcp_error",
		"component", "mcp-provider",
		"tool_name", tool,
		"symbol", symbol,
		"correlation_id", correlationID,
		"error_code", errorCode,
		"error_message", errorMsg,
	)
}
