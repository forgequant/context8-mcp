package handlers

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"mcp/internal/cache"
	"mcp/internal/mcp"
)

// MCPInvokeHandler handles MCP call_tool JSON-RPC requests via SSE transport
type MCPInvokeHandler struct {
	invoker *mcp.ToolInvoker
	logger  *slog.Logger
}

// NewMCPInvokeHandler creates a new MCP tool invocation handler
func NewMCPInvokeHandler(cacheReader *cache.Reader, logger *slog.Logger) (*MCPInvokeHandler, error) {
	executor := mcp.NewToolExecutor(cacheReader)
	invoker, err := mcp.NewToolInvoker(executor)
	if err != nil {
		return nil, err
	}

	return &MCPInvokeHandler{
		invoker: invoker,
		logger:  logger,
	}, nil
}

// ServeHTTP handles POST /mcp/sse requests with SSE transport
// Implements T013, T018, T019, T020
func (h *MCPInvokeHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	start := time.Now()

	// Only accept POST requests
	if r.Method != http.MethodPost {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	// Get correlation ID from context (T009)
	correlationID := GetCorrelationID(r.Context())

	// Create SSE writer for MCP protocol (T005)
	// Uses http.ResponseController to work through middleware
	sseWriter, err := mcp.NewSSEWriter(w)
	if err != nil {
		h.logger.Error("sse_init_failed", "error", err, "correlation_id", correlationID)
		http.Error(w, "SSE initialization failed", http.StatusInternalServerError)
		return
	}

	// Parse JSON-RPC request (T008)
	req, err := mcp.ParseJSONRPCRequest(r.Body)
	if err != nil {
		if rpcErr, ok := err.(*mcp.RPCError); ok {
			sseWriter.SendError(nil, rpcErr.Code, rpcErr.Message, rpcErr.Data)
			return
		}
		sseWriter.SendError(nil, mcp.ParseError, "Invalid request", err.Error())
		return
	}

	// Validate method is call_tool
	if req.Method != "call_tool" && req.Method != "tools/call" {
		sseWriter.SendError(req.ID, mcp.MethodNotFound, "Unknown method (expected 'call_tool')", req.Method)
		return
	}

	// Parse call_tool parameters
	toolParams, err := mcp.ParseCallToolParams(req.Params)
	if err != nil {
		if rpcErr, ok := err.(*mcp.RPCError); ok {
			sseWriter.SendError(req.ID, rpcErr.Code, rpcErr.Message, rpcErr.Data)
			return
		}
		sseWriter.SendError(req.ID, mcp.InvalidParams, "Invalid parameters", err.Error())
		return
	}

	// Extract symbol for logging
	symbol := ""
	if toolParams.Arguments != nil {
		if sym, ok := toolParams.Arguments["symbol"].(string); ok {
			symbol = sym
		}
	}

	// Log MCP request (T014)
	mcp.LogMCPRequest(r.Context(), h.logger, toolParams.Name, symbol, correlationID)

	// Enforce 500ms timeout per spec requirement SC-001 (T019)
	ctx, cancel := context.WithTimeout(r.Context(), 500*time.Millisecond)
	defer cancel()

	// Execute tool invocation with timeout
	done := make(chan struct{})
	var result *mcp.CallToolResult
	var invokeErr error

	go func() {
		result, invokeErr = h.invoker.InvokeTool(ctx, toolParams.Name, toolParams.Arguments)
		close(done)
	}()

	select {
	case <-done:
		// Tool execution completed
		latencyMS := time.Since(start).Milliseconds()

		if invokeErr != nil {
			// Handle tool execution error (T017)
			rpcErr := mcp.FormatMCPError(invokeErr)

			// Log error (T020)
			mcp.LogMCPError(ctx, h.logger, toolParams.Name, symbol, correlationID, rpcErr.Code, rpcErr.Message)

			// Send error response via SSE
			sseWriter.SendError(req.ID, rpcErr.Code, rpcErr.Message, rpcErr.Data)
			return
		}

		// Success - determine cache hit status (T020)
		cacheHit := latencyMS < 50 // Cache hits typically < 50ms

		// Log success with metrics (T014, T020)
		mcp.LogMCPSuccess(ctx, h.logger, toolParams.Name, symbol, correlationID, cacheHit, latencyMS)

		// Send successful result via SSE (T005)
		sseWriter.SendResult(req.ID, result)

	case <-ctx.Done():
		// Timeout exceeded (T019)
		latencyMS := time.Since(start).Milliseconds()

		// Log timeout error (T020)
		mcp.LogMCPError(ctx, h.logger, toolParams.Name, symbol, correlationID, mcp.TimeoutExceeded, "Request timeout")

		// Send timeout error via SSE
		sseWriter.SendError(req.ID, mcp.TimeoutExceeded, "Request timeout (exceeded 500ms)", map[string]interface{}{
			"timeout_ms":  500,
			"elapsed_ms": latencyMS,
		})
	}
}
