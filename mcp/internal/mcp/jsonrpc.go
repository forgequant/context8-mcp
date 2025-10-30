package mcp

import (
	"encoding/json"
	"fmt"
	"io"
)

// ParseJSONRPCRequest parses a JSON-RPC 2.0 request from a reader
// Returns error for invalid JSON or malformed JSON-RPC requests
func ParseJSONRPCRequest(r io.Reader) (*JSONRPCRequest, error) {
	var req JSONRPCRequest
	if err := json.NewDecoder(r).Decode(&req); err != nil {
		return nil, &RPCError{
			Code:    ParseError,
			Message: "Invalid JSON",
			Data:    err.Error(),
		}
	}

	// Validate JSON-RPC 2.0 format
	if req.JSONRPC != "2.0" {
		return nil, &RPCError{
			Code:    InvalidRequest,
			Message: "Invalid JSON-RPC version (must be '2.0')",
			Data:    req.JSONRPC,
		}
	}

	if req.Method == "" {
		return nil, &RPCError{
			Code:    InvalidRequest,
			Message: "Missing 'method' field",
		}
	}

	return &req, nil
}

// ParseCallToolParams extracts call_tool parameters from JSON-RPC params
func ParseCallToolParams(params json.RawMessage) (*CallToolParams, error) {
	if len(params) == 0 {
		return nil, &RPCError{
			Code:    InvalidParams,
			Message: "Missing parameters for call_tool",
		}
	}

	var toolParams CallToolParams
	if err := json.Unmarshal(params, &toolParams); err != nil {
		return nil, &RPCError{
			Code:    InvalidParams,
			Message: "Invalid call_tool parameters",
			Data:    err.Error(),
		}
	}

	if toolParams.Name == "" {
		return nil, &RPCError{
			Code:    InvalidParams,
			Message: "Missing 'name' field in call_tool parameters",
		}
	}

	return &toolParams, nil
}

// NewJSONRPCError creates a JSON-RPC error response
func NewJSONRPCError(id interface{}, code int, message string, data interface{}) *JSONRPCResponse {
	return &JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Error: &RPCError{
			Code:    code,
			Message: message,
			Data:    data,
		},
	}
}

// NewJSONRPCResult creates a JSON-RPC success response
func NewJSONRPCResult(id interface{}, result interface{}) *JSONRPCResponse {
	return &JSONRPCResponse{
		JSONRPC: "2.0",
		ID:      id,
		Result:  result,
	}
}

// ErrorFromValidation converts a validation error to RPC error
func ErrorFromValidation(err error) *RPCError {
	if ve, ok := err.(*ValidationError); ok {
		return &RPCError{
			Code:    ValidationFailed,
			Message: "Parameter validation failed",
			Data: map[string]interface{}{
				"field":   ve.Field,
				"message": ve.Message,
			},
		}
	}
	return &RPCError{
		Code:    ValidationFailed,
		Message: fmt.Sprintf("Validation failed: %s", err.Error()),
	}
}
