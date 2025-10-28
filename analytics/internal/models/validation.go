package models

import (
	"encoding/json"
	"fmt"
)

// ValidateReport validates a market report against business rules.
// TODO: Add JSON schema validation using gojsonschema library
func ValidateReport(report *MarketReport) error {
	if report.Symbol == "" {
		return fmt.Errorf("symbol is required")
	}

	if report.Venue == "" {
		return fmt.Errorf("venue is required")
	}

	if report.DataAgeMs < 0 {
		return fmt.Errorf("data_age_ms must be non-negative")
	}

	// Validate ingestion status
	validStatuses := map[string]bool{"ok": true, "degraded": true, "down": true}
	if !validStatuses[report.Ingestion.Status] {
		return fmt.Errorf("invalid ingestion status: %s", report.Ingestion.Status)
	}

	// Validate prices
	if report.BestBid.Price <= 0 {
		return fmt.Errorf("best_bid price must be positive")
	}
	if report.BestAsk.Price <= 0 {
		return fmt.Errorf("best_ask price must be positive")
	}
	if report.BestBid.Price >= report.BestAsk.Price {
		return fmt.Errorf("crossed order book: bid >= ask")
	}

	// Validate spread
	if report.SpreadBps < 0 {
		return fmt.Errorf("spread_bps must be non-negative")
	}

	// Validate imbalance range
	if report.Depth.Imbalance < -1.0 || report.Depth.Imbalance > 1.0 {
		return fmt.Errorf("imbalance must be in [-1, 1], got %f", report.Depth.Imbalance)
	}

	// Validate health score range
	if report.Health.Score < 0 || report.Health.Score > 100 {
		return fmt.Errorf("health score must be in [0, 100], got %d", report.Health.Score)
	}

	// Validate anomaly types
	validAnomalyTypes := map[string]bool{"spoofing": true, "iceberg": true, "flash_crash_risk": true}
	for _, anomaly := range report.Anomalies {
		if !validAnomalyTypes[anomaly.Type] {
			return fmt.Errorf("invalid anomaly type: %s", anomaly.Type)
		}
	}

	// Validate volume profile if present
	if report.Liquidity != nil {
		if report.Liquidity.Profile.VAL > report.Liquidity.Profile.POC ||
			report.Liquidity.Profile.POC > report.Liquidity.Profile.VAH {
			return fmt.Errorf("volume profile invariant violation: VAL <= POC <= VAH")
		}
	}

	return nil
}

// ValidateReportJSON validates that the report can be serialized to valid JSON.
func ValidateReportJSON(report *MarketReport) error {
	data, err := json.Marshal(report)
	if err != nil {
		return fmt.Errorf("failed to marshal report: %w", err)
	}

	// Verify it can be unmarshaled back
	var check MarketReport
	if err := json.Unmarshal(data, &check); err != nil {
		return fmt.Errorf("failed to unmarshal report: %w", err)
	}

	return nil
}
