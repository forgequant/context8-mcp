package metrics

import (
	"fmt"
)

// DepthLevel represents a single price level in the order book.
type DepthLevel struct {
	Price float64 `json:"price"`
	Qty   float64 `json:"qty"`
}

// DepthMetrics contains calculated order book depth metrics.
type DepthMetrics struct {
	Bids        []DepthLevel `json:"bids"`          // Top N bid levels
	Asks        []DepthLevel `json:"asks"`          // Top N ask levels
	TotalBidQty float64      `json:"total_bid_qty"` // Sum of all bid quantities
	TotalAskQty float64      `json:"total_ask_qty"` // Sum of all ask quantities
	Imbalance   float64      `json:"imbalance"`     // Order book imbalance [-1, 1]
	BestBid     DepthLevel   `json:"best_bid"`      // Best bid price and qty
	BestAsk     DepthLevel   `json:"best_ask"`      // Best ask price and qty
}

// CalculateDepth computes order book depth metrics.
//
// Implements constitution principle 6 (Report Contract and Calculation Rules):
// - Top N levels from order book (FR-009)
// - Total bid/ask quantities
// - Order book imbalance: (ΣQ_bid − ΣQ_ask) / (ΣQ_bid + ΣQ_ask) (FR-010)
//
// Args:
//   - bids: Bid levels sorted descending by price [[price, qty], ...]
//   - asks: Ask levels sorted ascending by price [[price, qty], ...]
//   - topN: Number of levels to include (20 for MVP per FR-009)
func CalculateDepth(bids, asks [][2]float64, topN int) (*DepthMetrics, error) {
	if len(bids) == 0 || len(asks) == 0 {
		return nil, fmt.Errorf("empty order book: bids=%d asks=%d", len(bids), len(asks))
	}

	if topN <= 0 {
		return nil, fmt.Errorf("topN must be positive, got %d", topN)
	}

	// Extract top N levels
	topBids := extractTopLevels(bids, topN)
	topAsks := extractTopLevels(asks, topN)

	// Best bid/ask
	bestBid := DepthLevel{Price: topBids[0].Price, Qty: topBids[0].Qty}
	bestAsk := DepthLevel{Price: topAsks[0].Price, Qty: topAsks[0].Qty}

	// Validate book is not crossed
	if bestBid.Price >= bestAsk.Price {
		return nil, fmt.Errorf("crossed book: best_bid=%f >= best_ask=%f", bestBid.Price, bestAsk.Price)
	}

	// Calculate total quantities across all levels (not just top N)
	totalBidQty := sumQuantities(bids)
	totalAskQty := sumQuantities(asks)

	// Calculate imbalance (FR-010)
	// imbalance = (ΣQ_bid − ΣQ_ask) / (ΣQ_bid + ΣQ_ask)
	// Range: [-1, 1] where positive means more buy pressure
	imbalance := (totalBidQty - totalAskQty) / (totalBidQty + totalAskQty)

	return &DepthMetrics{
		Bids:        topBids,
		Asks:        topAsks,
		TotalBidQty: roundToDecimal(totalBidQty, 8),
		TotalAskQty: roundToDecimal(totalAskQty, 8),
		Imbalance:   roundToDecimal(imbalance, 6),
		BestBid:     bestBid,
		BestAsk:     bestAsk,
	}, nil
}

// extractTopLevels extracts top N levels from order book side.
func extractTopLevels(levels [][2]float64, topN int) []DepthLevel {
	n := topN
	if n > len(levels) {
		n = len(levels)
	}

	result := make([]DepthLevel, n)
	for i := 0; i < n; i++ {
		result[i] = DepthLevel{
			Price: roundToDecimal(levels[i][0], 8),
			Qty:   roundToDecimal(levels[i][1], 8),
		}
	}

	return result
}

// sumQuantities calculates the total quantity across all levels.
func sumQuantities(levels [][2]float64) float64 {
	total := 0.0
	for _, level := range levels {
		total += level[1] // qty is second element
	}
	return total
}

// DepthInvariant validates depth metrics invariants.
// Per constitution principle 9 (Quality and Testing).
func DepthInvariant(d *DepthMetrics) error {
	// Invariant 1: Imbalance must be in [-1, 1]
	if d.Imbalance < -1.0 || d.Imbalance > 1.0 {
		return fmt.Errorf("imbalance %f not in range [-1, 1]", d.Imbalance)
	}

	// Invariant 2: Total quantities must be positive
	if d.TotalBidQty <= 0 || d.TotalAskQty <= 0 {
		return fmt.Errorf("total quantities must be positive: bid=%f ask=%f", d.TotalBidQty, d.TotalAskQty)
	}

	// Invariant 3: Best bid < best ask
	if d.BestBid.Price >= d.BestAsk.Price {
		return fmt.Errorf("crossed book: best_bid=%f >= best_ask=%f", d.BestBid.Price, d.BestAsk.Price)
	}

	// Invariant 4: Bids sorted descending, asks sorted ascending
	if err := validateBidSorting(d.Bids); err != nil {
		return err
	}
	if err := validateAskSorting(d.Asks); err != nil {
		return err
	}

	return nil
}

// validateBidSorting checks that bids are sorted descending by price.
func validateBidSorting(bids []DepthLevel) error {
	for i := 1; i < len(bids); i++ {
		if bids[i].Price > bids[i-1].Price {
			return fmt.Errorf("bids not sorted descending: bid[%d].price=%f > bid[%d].price=%f",
				i, bids[i].Price, i-1, bids[i-1].Price)
		}
	}
	return nil
}

// validateAskSorting checks that asks are sorted ascending by price.
func validateAskSorting(asks []DepthLevel) error {
	for i := 1; i < len(asks); i++ {
		if asks[i].Price < asks[i-1].Price {
			return fmt.Errorf("asks not sorted ascending: ask[%d].price=%f < ask[%d].price=%f",
				i, asks[i].Price, i-1, asks[i-1].Price)
		}
	}
	return nil
}

// CalculateImbalance is a standalone function to calculate imbalance.
// Useful when you only need imbalance without full depth metrics.
func CalculateImbalance(totalBidQty, totalAskQty float64) (float64, error) {
	if totalBidQty < 0 || totalAskQty < 0 {
		return 0, fmt.Errorf("negative quantities: bid=%f ask=%f", totalBidQty, totalAskQty)
	}

	if totalBidQty == 0 && totalAskQty == 0 {
		return 0, fmt.Errorf("both quantities are zero")
	}

	return (totalBidQty - totalAskQty) / (totalBidQty + totalAskQty), nil
}
