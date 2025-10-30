package mcp

import (
	"context"
)

// ToolInvoker handles MCP tool invocation with parameter validation
type ToolInvoker struct {
	executor  *ToolExecutor
	validator *SchemaValidator
}

// NewToolInvoker creates a new tool invoker with validation
func NewToolInvoker(executor *ToolExecutor) (*ToolInvoker, error) {
	// Compile get_report schema for validation
	validator, err := NewSchemaValidator(GetReportToolSchema())
	if err != nil {
		return nil, err
	}

	return &ToolInvoker{
		executor:  executor,
		validator: validator,
	}, nil
}

// InvokeGetReport validates parameters and executes get_report tool
func (ti *ToolInvoker) InvokeGetReport(ctx context.Context, args map[string]interface{}) (*CallToolResult, error) {
	// Validate parameters against JSON Schema
	if err := ti.validator.Validate(args); err != nil {
		return nil, ErrorFromValidation(err)
	}

	// Extract symbol parameter
	symbol, ok := args["symbol"].(string)
	if !ok {
		return nil, &RPCError{
			Code:    InvalidParams,
			Message: "Symbol parameter must be a string",
			Data:    args,
		}
	}

	// Execute tool
	return ti.executor.ExecuteGetReport(ctx, symbol)
}

// InvokeTool dispatches to appropriate tool handler based on tool name
func (ti *ToolInvoker) InvokeTool(ctx context.Context, toolName string, args map[string]interface{}) (*CallToolResult, error) {
	switch toolName {
	case "get_report":
		return ti.InvokeGetReport(ctx, args)
	default:
		return nil, &RPCError{
			Code:    MethodNotFound,
			Message: "Unknown tool",
			Data:    toolName,
		}
	}
}
