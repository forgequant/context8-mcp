package metrics

import (
	"fmt"
	"math"
)

// SpreadMetrics contains calculated spread-related metrics.
type SpreadMetrics struct {
	SpreadBps  float64 `json:"spread_bps"`  // Spread in basis points
	MidPrice   float64 `json:"mid_price"`   // Mid price (bid + ask) / 2
	MicroPrice float64 `json:"micro_price"` // Volume-weighted mid price
}

// CalculateSpread computes spread metrics from best bid and ask.
//
// Implements constitution principle 6 (Report Contract and Calculation Rules):
// - spread_bps: (ask - bid) / bid * 10000 (FR-006)
// - mid_price: (bid + ask) / 2 (FR-007)
// - micro_price: (ask × bid_qty + bid × ask_qty) / (bid_qty + ask_qty) (FR-008)
func CalculateSpread(bidPrice, bidQty, askPrice, askQty float64) (*SpreadMetrics, error) {
	// Validate inputs
	if bidPrice <= 0 || askPrice <= 0 {
		return nil, fmt.Errorf("invalid prices: bid=%f ask=%f (must be > 0)", bidPrice, askPrice)
	}

	if bidQty <= 0 || askQty <= 0 {
		return nil, fmt.Errorf("invalid quantities: bidQty=%f askQty=%f (must be > 0)", bidQty, askQty)
	}

	if askPrice <= bidPrice {
		return nil, fmt.Errorf("crossed book: bid=%f >= ask=%f", bidPrice, askPrice)
	}

	// Calculate spread in basis points (FR-006)
	// spread_bps = (ask - bid) / bid * 10000
	spreadBps := (askPrice - bidPrice) / bidPrice * 10000.0

	// Calculate mid price (FR-007)
	// mid_price = (bid + ask) / 2
	midPrice := (bidPrice + askPrice) / 2.0

	// Calculate micro price (FR-008)
	// micro_price = (ask × bid_qty + bid × ask_qty) / (bid_qty + ask_qty)
	// This gives more weight to the side with more quantity
	microPrice := (askPrice*bidQty + bidPrice*askQty) / (bidQty + askQty)

	return &SpreadMetrics{
		SpreadBps:  roundToDecimal(spreadBps, 4),
		MidPrice:   roundToDecimal(midPrice, 8),
		MicroPrice: roundToDecimal(microPrice, 8),
	}, nil
}

// roundToDecimal rounds a float64 to a specified number of decimal places.
func roundToDecimal(value float64, decimals int) float64 {
	multiplier := math.Pow(10, float64(decimals))
	return math.Round(value*multiplier) / multiplier
}

// SpreadInvariant validates spread metrics invariants.
// Useful for property-based testing per constitution principle 9 (Quality and Testing).
func SpreadInvariant(s *SpreadMetrics, bidPrice, askPrice float64) error {
	// Invariant 1: spread_bps must be positive
	if s.SpreadBps <= 0 {
		return fmt.Errorf("spread_bps must be positive, got %f", s.SpreadBps)
	}

	// Invariant 2: mid_price must be between bid and ask
	if s.MidPrice < bidPrice || s.MidPrice > askPrice {
		return fmt.Errorf("mid_price %f not in range [%f, %f]", s.MidPrice, bidPrice, askPrice)
	}

	// Invariant 3: micro_price should be close to mid_price
	// (within 10% for normal market conditions)
	diff := math.Abs(s.MicroPrice - s.MidPrice)
	threshold := s.MidPrice * 0.10
	if diff > threshold {
		return fmt.Errorf("micro_price %f too far from mid_price %f (diff=%f > threshold=%f)",
			s.MicroPrice, s.MidPrice, diff, threshold)
	}

	return nil
}
