package mcp

import (
	"context"
	"encoding/json"
	"fmt"

	"mcp/internal/cache"
)

// ToolExecutor handles execution of MCP tools
type ToolExecutor struct {
	cacheReader *cache.Reader
}

// NewToolExecutor creates a new tool executor with cache reader
func NewToolExecutor(cacheReader *cache.Reader) *ToolExecutor {
	return &ToolExecutor{
		cacheReader: cacheReader,
	}
}

// ExecuteGetReport executes the get_report tool by reading from cache
// Returns MCP CallToolResult with report as JSON text content
func (te *ToolExecutor) ExecuteGetReport(ctx context.Context, symbol string) (*CallToolResult, error) {
	// Call existing cache reader (mcp/internal/cache/reader.go)
	report, err := te.cacheReader.GetReport(ctx, symbol)
	if err != nil {
		// Check if symbol not found vs other errors
		if err.Error() == "report not found" || err.Error() == "key does not exist" {
			return nil, &RPCError{
				Code:    SymbolNotFound,
				Message: fmt.Sprintf("Symbol '%s' not found in cache", symbol),
				Data:    symbol,
			}
		}
		// Redis connection or other errors
		return nil, &RPCError{
			Code:    DataUnavailable,
			Message: "Failed to retrieve report from cache",
			Data:    err.Error(),
		}
	}

	// Marshal report to JSON for text content
	reportJSON, err := json.Marshal(report)
	if err != nil {
		return nil, &RPCError{
			Code:    InternalError,
			Message: "Failed to serialize report",
			Data:    err.Error(),
		}
	}

	// Return as MCP TextContent per MCP specification
	return &CallToolResult{
		Content: []TextContent{
			{
				Type: "text",
				Text: string(reportJSON),
			},
		},
	}, nil
}
