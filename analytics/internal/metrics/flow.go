package metrics

import (
	"sync"
	"time"
)

// FlowTracker tracks market activity metrics over time windows.
// Phase 6 - US6: Flow metrics implementation (T097, T098, T099).
type FlowTracker struct {
	mu sync.RWMutex

	// Rolling window for orders_per_sec calculation (last 10 seconds)
	eventWindow []timestampedEvent

	// Rolling window for net_flow calculation (last 30 seconds)
	tradeWindow []timestampedTrade
}

// timestampedEvent represents an event occurrence for rate calculation.
type timestampedEvent struct {
	timestamp time.Time
}

// timestampedTrade represents a trade with aggressor side for flow calculation.
type timestampedTrade struct {
	timestamp time.Time
	volume    float64
	isBuy     bool // true if aggressive buy, false if aggressive sell
}

// NewFlowTracker creates a new flow tracker.
func NewFlowTracker() *FlowTracker {
	return &FlowTracker{
		eventWindow: make([]timestampedEvent, 0, 1000),
		tradeWindow: make([]timestampedTrade, 0, 1000),
	}
}

// RecordEvent records a market event (any event type) for rate calculation.
// Used for orders_per_sec calculation over last 10 seconds (FR-014, T097).
func (ft *FlowTracker) RecordEvent(ts time.Time) {
	ft.mu.Lock()
	defer ft.mu.Unlock()

	ft.eventWindow = append(ft.eventWindow, timestampedEvent{timestamp: ts})
	ft.pruneEventWindow(ts)
}

// RecordTrade records a trade with aggressor side for net flow calculation.
// Used for net_flow calculation over last 30 seconds (FR-015, T098).
func (ft *FlowTracker) RecordTrade(ts time.Time, volume float64, isBuy bool) {
	ft.mu.Lock()
	defer ft.mu.Unlock()

	ft.tradeWindow = append(ft.tradeWindow, timestampedTrade{
		timestamp: ts,
		volume:    volume,
		isBuy:     isBuy,
	})
	ft.pruneTradeWindow(ts)
}

// pruneEventWindow removes events older than 10 seconds.
func (ft *FlowTracker) pruneEventWindow(now time.Time) {
	cutoff := now.Add(-10 * time.Second)

	// Find first index to keep
	keepIdx := 0
	for keepIdx < len(ft.eventWindow) && ft.eventWindow[keepIdx].timestamp.Before(cutoff) {
		keepIdx++
	}

	// Remove old events
	if keepIdx > 0 {
		ft.eventWindow = ft.eventWindow[keepIdx:]
	}
}

// pruneTradeWindow removes trades older than 30 seconds.
func (ft *FlowTracker) pruneTradeWindow(now time.Time) {
	cutoff := now.Add(-30 * time.Second)

	// Find first index to keep
	keepIdx := 0
	for keepIdx < len(ft.tradeWindow) && ft.tradeWindow[keepIdx].timestamp.Before(cutoff) {
		keepIdx++
	}

	// Remove old trades
	if keepIdx > 0 {
		ft.tradeWindow = ft.tradeWindow[keepIdx:]
	}
}

// CalculateOrdersPerSec calculates the event rate over the last 10 seconds (FR-014, T097).
// Returns the average number of events per second.
func (ft *FlowTracker) CalculateOrdersPerSec(now time.Time) float64 {
	ft.mu.RLock()
	defer ft.mu.RUnlock()

	// Prune old data (const operation on read-only copy)
	cutoff := now.Add(-10 * time.Second)

	// Count events in window
	count := 0
	for _, event := range ft.eventWindow {
		if !event.timestamp.Before(cutoff) {
			count++
		}
	}

	// Calculate rate over 10 seconds
	if count == 0 {
		return 0.0
	}

	// Average over 10 second window
	return float64(count) / 10.0
}

// CalculateNetFlow calculates net buying/selling pressure over last 30 seconds (FR-015, T098).
// Returns: aggressive buy volume - aggressive sell volume.
// Positive = net buying pressure, Negative = net selling pressure.
func (ft *FlowTracker) CalculateNetFlow(now time.Time) float64 {
	ft.mu.RLock()
	defer ft.mu.RUnlock()

	cutoff := now.Add(-30 * time.Second)

	var buyVolume, sellVolume float64

	for _, trade := range ft.tradeWindow {
		if !trade.timestamp.Before(cutoff) {
			if trade.isBuy {
				buyVolume += trade.volume
			} else {
				sellVolume += trade.volume
			}
		}
	}

	return buyVolume - sellVolume
}

// GetMetrics returns both flow metrics at once (T100).
func (ft *FlowTracker) GetMetrics(now time.Time) FlowMetrics {
	return FlowMetrics{
		OrdersPerSec: ft.CalculateOrdersPerSec(now),
		NetFlow:      ft.CalculateNetFlow(now),
	}
}

// FlowMetrics contains calculated flow metrics.
type FlowMetrics struct {
	OrdersPerSec float64
	NetFlow      float64
}
