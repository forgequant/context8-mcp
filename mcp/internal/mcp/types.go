package mcp

import "encoding/json"

// Tool represents an MCP tool definition per MCP specification
type Tool struct {
	Name        string                 `json:"name"`
	Description string                 `json:"description"`
	InputSchema map[string]interface{} `json:"inputSchema"`
}

// TextContent represents MCP text content response
type TextContent struct {
	Type string `json:"type"` // Always "text" for MCP
	Text string `json:"text"`
}

// JSONRPCRequest represents a JSON-RPC 2.0 request
type JSONRPCRequest struct {
	JSONRPC string          `json:"jsonrpc"` // Always "2.0"
	ID      interface{}     `json:"id"`      // Can be string or number
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params,omitempty"`
}

// JSONRPCResponse represents a JSON-RPC 2.0 response
type JSONRPCResponse struct {
	JSONRPC string      `json:"jsonrpc"` // Always "2.0"
	ID      interface{} `json:"id"`      // Matches request ID
	Result  interface{} `json:"result,omitempty"`
	Error   *RPCError   `json:"error,omitempty"`
}

// RPCError represents a JSON-RPC 2.0 error object
type RPCError struct {
	Code    int         `json:"code"`
	Message string      `json:"message"`
	Data    interface{} `json:"data,omitempty"`
}

// Error implements the error interface for RPCError
func (e *RPCError) Error() string {
	return e.Message
}

// Standard JSON-RPC error codes
const (
	ParseError     = -32700 // Invalid JSON
	InvalidRequest = -32600 // Invalid Request object
	MethodNotFound = -32601 // Method does not exist
	InvalidParams  = -32602 // Invalid method parameters
	InternalError  = -32603 // Internal JSON-RPC error
	ServerError    = -32000 // Server error (generic)
)

// MCP-specific error codes
const (
	SymbolNotFound    = -32001 // Symbol not found in cache
	DataUnavailable   = -32002 // Redis unavailable
	ValidationFailed  = -32003 // Parameter validation failed
	TimeoutExceeded   = -32004 // Request timeout
)

// CallToolParams represents parameters for call_tool method
type CallToolParams struct {
	Name      string                 `json:"name"`
	Arguments map[string]interface{} `json:"arguments,omitempty"`
}

// ListToolsResult represents the result of list_tools method
type ListToolsResult struct {
	Tools []Tool `json:"tools"`
}

// CallToolResult represents the result of call_tool method
type CallToolResult struct {
	Content []TextContent `json:"content"`
}
