package mcp

// GetReportToolSchema returns the JSON Schema for get_report tool parameters
// Symbol must match pattern ^[A-Z0-9]+USDT$ (allows letters and digits)
func GetReportToolSchema() map[string]interface{} {
	return map[string]interface{}{
		"type": "object",
		"properties": map[string]interface{}{
			"symbol": map[string]interface{}{
				"type":        "string",
				"description": "Trading symbol (e.g., BTCUSDT, ETHUSDT, 1INCHUSDT, 1000SHIBUSDT)",
				"pattern":     "^[A-Z0-9]+USDT$",
			},
		},
		"required": []string{"symbol"},
	}
}

// GetReportTool returns the complete MCP Tool definition for get_report
func GetReportTool() Tool {
	return Tool{
		Name:        "get_report",
		Description: "Retrieve real-time market data report for a tracked symbol including orderbook metrics, volume profile, and flow analysis",
		InputSchema: GetReportToolSchema(),
	}
}
