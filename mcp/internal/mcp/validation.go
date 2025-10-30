package mcp

import (
	"bytes"
	"encoding/json"
	"fmt"

	"github.com/santhosh-tekuri/jsonschema/v5"
)

// SchemaValidator wraps JSON Schema compilation and validation
type SchemaValidator struct {
	schema *jsonschema.Schema
}

// NewSchemaValidator creates a validator from a JSON schema definition
func NewSchemaValidator(schemaMap map[string]interface{}) (*SchemaValidator, error) {
	compiler := jsonschema.NewCompiler()
	compiler.Draft = jsonschema.Draft7 // MCP uses JSON Schema Draft 7

	// Marshal schema map to JSON
	schemaJSON, err := json.Marshal(schemaMap)
	if err != nil {
		return nil, fmt.Errorf("failed to marshal schema: %w", err)
	}

	// Add schema to compiler as JSON reader
	if err := compiler.AddResource("schema.json", bytes.NewReader(schemaJSON)); err != nil {
		return nil, fmt.Errorf("failed to add schema resource: %w", err)
	}

	// Compile schema
	schema, err := compiler.Compile("schema.json")
	if err != nil {
		return nil, fmt.Errorf("failed to compile schema: %w", err)
	}

	return &SchemaValidator{schema: schema}, nil
}

// Validate validates parameters against the compiled schema
// Returns validation error with details if validation fails
func (v *SchemaValidator) Validate(params interface{}) error {
	if err := v.schema.Validate(params); err != nil {
		// Extract validation error details for better error messages
		if ve, ok := err.(*jsonschema.ValidationError); ok {
			return &ValidationError{
				Field:   ve.InstanceLocation,
				Message: ve.Message,
				Value:   params,
			}
		}
		return fmt.Errorf("validation failed: %w", err)
	}
	return nil
}

// ValidationError represents a parameter validation error with details
type ValidationError struct {
	Field   string
	Message string
	Value   interface{}
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("validation failed for field '%s': %s", e.Field, e.Message)
}
