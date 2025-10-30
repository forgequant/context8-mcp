package mcp

import (
	"encoding/json"
	"fmt"
	"net/http"
)

// SSEWriter wraps http.ResponseWriter with SSE event sending capability
type SSEWriter struct {
	w http.ResponseWriter
}

// NewSSEWriter creates a new SSE writer from http.ResponseWriter
// Uses http.ResponseController to access Flusher even through middleware wrappers (Go 1.20+)
func NewSSEWriter(w http.ResponseWriter) (*SSEWriter, error) {
	// Set SSE headers per MCP specification
	w.Header().Set("Content-Type", "text/event-stream")
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Connection", "keep-alive")
	w.Header().Set("Access-Control-Allow-Origin", "*") // Allow ChatGPT access
	w.Header().Set("X-Accel-Buffering", "no")          // Disable nginx buffering

	return &SSEWriter{w: w}, nil
}

// SendEvent sends a JSON-RPC response as an SSE event
// Uses http.ResponseController to flush data through middleware
func (s *SSEWriter) SendEvent(data interface{}) error {
	jsonData, err := json.Marshal(data)
	if err != nil {
		return fmt.Errorf("failed to marshal SSE data: %w", err)
	}

	// SSE format: "data: {json}\n\n"
	if _, err := fmt.Fprintf(s.w, "data: %s\n\n", jsonData); err != nil {
		return fmt.Errorf("failed to write SSE event: %w", err)
	}

	// Use http.ResponseController to flush (works through middleware in Go 1.20+)
	if err := http.NewResponseController(s.w).Flush(); err != nil {
		return fmt.Errorf("failed to flush SSE event: %w", err)
	}

	return nil
}

// SendError sends a JSON-RPC error as an SSE event
func (s *SSEWriter) SendError(id interface{}, code int, message string, data interface{}) error {
	response := JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error: &RPCError{
			Code:    code,
			Message: message,
			Data:    data,
		},
	}
	return s.SendEvent(response)
}

// SendResult sends a JSON-RPC success result as an SSE event
func (s *SSEWriter) SendResult(id interface{}, result interface{}) error {
	response := JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Result:  result,
	}
	return s.SendEvent(response)
}
