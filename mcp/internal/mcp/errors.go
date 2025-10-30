package mcp

import (
	"fmt"
	"net/http"
)

// FormatMCPError formats various error types into MCP-compatible JSON-RPC errors
func FormatMCPError(err error) *RPCError {
	// Check if already an RPC error
	if rpcErr, ok := err.(*RPCError); ok {
		return rpcErr
	}

	// Check for validation errors
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

	// Generic error
	return &RPCError{
		Code:    InternalError,
		Message: fmt.Sprintf("Internal error: %s", err.Error()),
	}
}

// HTTPStatusFromError maps MCP error codes to HTTP status codes
func HTTPStatusFromError(rpcErr *RPCError) int {
	if rpcErr == nil {
		return http.StatusOK
	}

	switch rpcErr.Code {
	case ParseError, InvalidRequest:
		return http.StatusBadRequest
	case MethodNotFound:
		return http.StatusNotFound
	case InvalidParams, ValidationFailed:
		return http.StatusBadRequest
	case SymbolNotFound:
		return http.StatusNotFound
	case DataUnavailable:
		return http.StatusServiceUnavailable
	case TimeoutExceeded:
		return http.StatusGatewayTimeout
	case InternalError, ServerError:
		return http.StatusInternalServerError
	default:
		return http.StatusInternalServerError
	}
}

// ErrorResponse creates a user-friendly error message with details
// Per spec requirement for actionable error messages (SC-005)
func ErrorResponse(code int, message string, details interface{}) map[string]interface{} {
	response := map[string]interface{}{
		"error":   message,
		"code":    code,
	}

	if details != nil {
		response["details"] = details
	}

	// Add suggestions for common errors
	switch code {
	case SymbolNotFound:
		response["suggestion"] = "Verify symbol format (e.g., BTCUSDT) and ensure it's tracked by the system"
	case DataUnavailable:
		response["suggestion"] = "Data source is temporarily unavailable. Please retry in a few moments"
	case TimeoutExceeded:
		response["suggestion"] = "Request took too long. Try again or contact support if problem persists"
	case ValidationFailed:
		response["suggestion"] = "Check parameter format and try again"
	}

	return response
}
