package aggregator

import (
	"context"
	"fmt"
	"log/slog"
	"sync"
	"time"

	"analytics/internal/instrumentation"
	"analytics/internal/metrics"
	"analytics/internal/models"
)

// ReportPublisher publishes generated reports (typically to Redis cache).
type ReportPublisher interface {
	Publish(ctx context.Context, symbol string, report *models.MarketReport) error
}

// Aggregator maintains market state and generates reports.
//
// Implements constitution principle 6 (Report Contract) with all required fields.
type Aggregator struct {
	mu            sync.RWMutex
	symbolState   map[string]*SymbolState
	publisher     ReportPublisher
	logger        *slog.Logger
	reportVersion string
	cacheTTL      time.Duration
	metrics       *instrumentation.Metrics
}

// SymbolState tracks the latest market state for a single symbol.
type SymbolState struct {
	Symbol string
	Venue  string

	// Latest data from events
	LastPrice    float64
	High24h      float64
	Low24h       float64
	Volume24h    float64
	Change24hPct float64

	// Latest order book
	Bids [][2]float64 // [[price, qty], ...] sorted descending
	Asks [][2]float64 // [[price, qty], ...] sorted ascending

	// Timestamps
	LastEventTime  time.Time
	LastReportTime time.Time

	// Ingestion status state machine (Phase 5 - US5)
	IngestionStatus          string    // "ok", "degraded", "down"
	IngestionStatusChangedAt time.Time // When current status was entered
	DegradedSince            time.Time // When data first became stale (>1s), used for ok->degraded transition

	// Flow tracking (Phase 6 - US6)
	FlowTracker *metrics.FlowTracker

	// Liquidity analysis (Phase 7 - US4)
	LiquidityAnalyzer *metrics.LiquidityAnalyzer

	// Anomaly detection (Phase 8 - US3)
	AnomalyDetector *metrics.AnomalyDetector
}

// New creates a new aggregator.
func New(publisher ReportPublisher, logger *slog.Logger, cacheTTL time.Duration, metrics *instrumentation.Metrics) *Aggregator {
	return &Aggregator{
		symbolState:   make(map[string]*SymbolState),
		publisher:     publisher,
		logger:        logger.With("component", "aggregator"),
		reportVersion: "1.0.0", // Per constitution principle 12 (semantic versioning)
		cacheTTL:      cacheTTL,
		metrics:       metrics,
	}
}

// ProcessEvent processes a market event and generates/publishes a report if needed.
func (a *Aggregator) ProcessEvent(ctx context.Context, envelope *models.MarketEventEnvelope) error {
	// Record event processing
	if a.metrics != nil {
		a.metrics.RecordEventProcessed()

		// Record stream lag
		now := time.Now()
		lagMs := now.Sub(envelope.TsEvent).Milliseconds()
		a.metrics.RecordStreamLag(float64(lagMs))
	}

	a.mu.Lock()
	defer a.mu.Unlock()

	symbol := envelope.Symbol

	// Get or create symbol state
	state, exists := a.symbolState[symbol]
	if !exists {
		now := time.Now()
		state = &SymbolState{
			Symbol:                   symbol,
			Venue:                    envelope.Venue,
			Bids:                     make([][2]float64, 0),
			Asks:                     make([][2]float64, 0),
			IngestionStatus:          "ok",
			IngestionStatusChangedAt: now,
			FlowTracker:              metrics.NewFlowTracker(),          // Phase 6 - T100
			LiquidityAnalyzer:        metrics.NewLiquidityAnalyzer(nil), // Phase 7 - T118
			AnomalyDetector:          metrics.NewAnomalyDetector(nil),   // Phase 8 - T136
		}
		a.symbolState[symbol] = state
	}

	// Record event for flow metrics (Phase 6 - T100)
	if state.FlowTracker != nil {
		state.FlowTracker.RecordEvent(envelope.TsEvent)
	}

	// Update state based on event type
	switch envelope.Type {
	case "trade_tick":
		a.processTradeTick(state, envelope)
	case "ticker_24h":
		a.processTicker24h(state, envelope)
	case "order_book_depth":
		a.processOrderBookDepth(state, envelope)
	case "order_book_deltas":
		a.processOrderBookDeltas(state, envelope)
	default:
		a.logger.Warn("unknown_event_type", "type", envelope.Type, "symbol", symbol)
	}

	state.LastEventTime = envelope.TsEvent

	// Generate and publish report
	// For MVP, generate report on every order book update
	if envelope.Type == "order_book_depth" || envelope.Type == "ticker_24h" {
		return a.generateAndPublishReport(ctx, state)
	}

	return nil
}

// processTradeTick updates state from a trade tick event.
func (a *Aggregator) processTradeTick(state *SymbolState, envelope *models.MarketEventEnvelope) {
	payload, ok := envelope.Payload.(map[string]interface{})
	if !ok {
		a.logger.Error("invalid_trade_tick_payload", "symbol", state.Symbol)
		return
	}

	var price, qty float64
	var isBuy bool

	if priceStr, ok := payload["price"].(string); ok {
		fmt.Sscanf(priceStr, "%f", &price)
		state.LastPrice = price
	}

	// Extract trade details for flow tracking (Phase 6 - T100)
	if qtyStr, ok := payload["size"].(string); ok {
		fmt.Sscanf(qtyStr, "%f", &qty)
	}

	// Determine aggressor side
	// In NautilusTrader, aggressor_side can be "BUY" or "SELL" (from trade tick)
	if aggressorSide, ok := payload["aggressor_side"].(string); ok {
		isBuy = (aggressorSide == "BUY" || aggressorSide == "BUYER")
	}

	// Record trade for flow metrics (Phase 6 - T100)
	if state.FlowTracker != nil && qty > 0 {
		state.FlowTracker.RecordTrade(envelope.TsEvent, qty, isBuy)
	}

	// Update liquidity analyzer with trade data for volume profile (Phase 7 - T118)
	if state.LiquidityAnalyzer != nil && price > 0 && qty > 0 {
		state.LiquidityAnalyzer.UpdateTrades(envelope.TsEvent.UnixMilli(), price, qty)
	}

	// Record trade fill for iceberg detection (Phase 8 - T136)
	if state.AnomalyDetector != nil && price > 0 && qty > 0 {
		// Estimate visible quantity from best bid/ask if available
		visibleQty := qty // Default to trade qty
		if len(state.Bids) > 0 && len(state.Asks) > 0 {
			if isBuy && len(state.Asks) > 0 {
				visibleQty = state.Asks[0][1]
			} else if !isBuy && len(state.Bids) > 0 {
				visibleQty = state.Bids[0][1]
			}
		}
		state.AnomalyDetector.RecordTradeFill(envelope.TsEvent.UnixMilli(), price, qty, visibleQty)
	}
}

// processTicker24h updates 24h statistics from ticker event.
func (a *Aggregator) processTicker24h(state *SymbolState, envelope *models.MarketEventEnvelope) {
	payload, ok := envelope.Payload.(map[string]interface{})
	if !ok {
		a.logger.Error("invalid_ticker_payload", "symbol", state.Symbol)
		return
	}

	// Extract best bid/ask from ticker (comes as arrays [price, qty] from producer)
	if bestBidRaw, ok := payload["best_bid"].([]interface{}); ok && len(bestBidRaw) >= 2 {
		bidPrice, _ := bestBidRaw[0].(float64)
		bidQty, _ := bestBidRaw[1].(float64)
		if bidPrice > 0 && bidQty > 0 {
			state.Bids = [][2]float64{{bidPrice, bidQty}}
		}
	}

	if bestAskRaw, ok := payload["best_ask"].([]interface{}); ok && len(bestAskRaw) >= 2 {
		askPrice, _ := bestAskRaw[0].(float64)
		askQty, _ := bestAskRaw[1].(float64)
		if askPrice > 0 && askQty > 0 {
			state.Asks = [][2]float64{{askPrice, askQty}}
		}
	}
}

// processOrderBookDepth updates order book from depth snapshot.
func (a *Aggregator) processOrderBookDepth(state *SymbolState, envelope *models.MarketEventEnvelope) {
	payload, ok := envelope.Payload.(map[string]interface{})
	if !ok {
		a.logger.Error("invalid_depth_payload", "symbol", state.Symbol)
		return
	}

	// Extract bids
	if bidsRaw, ok := payload["bids"].([]interface{}); ok {
		bids := make([][2]float64, 0, len(bidsRaw))
		quantities := make([]float64, 0, len(bidsRaw))
		for _, bidRaw := range bidsRaw {
			bidMap, ok := bidRaw.(map[string]interface{})
			if !ok {
				continue
			}
			var price, qty float64
			if priceStr, ok := bidMap["price"].(string); ok {
				fmt.Sscanf(priceStr, "%f", &price)
			}
			if qtyStr, ok := bidMap["size"].(string); ok {
				fmt.Sscanf(qtyStr, "%f", &qty)
			}
			bids = append(bids, [2]float64{price, qty})
			quantities = append(quantities, qty)
		}
		state.Bids = bids

		// Update liquidity analyzer with bid quantities (Phase 7 - T118)
		if state.LiquidityAnalyzer != nil && len(quantities) > 0 {
			state.LiquidityAnalyzer.UpdateQuantities(quantities)
		}
	}

	// Extract asks
	if asksRaw, ok := payload["asks"].([]interface{}); ok {
		asks := make([][2]float64, 0, len(asksRaw))
		quantities := make([]float64, 0, len(asksRaw))
		for _, askRaw := range asksRaw {
			askMap, ok := askRaw.(map[string]interface{})
			if !ok {
				continue
			}
			var price, qty float64
			if priceStr, ok := askMap["price"].(string); ok {
				fmt.Sscanf(priceStr, "%f", &price)
			}
			if qtyStr, ok := askMap["size"].(string); ok {
				fmt.Sscanf(qtyStr, "%f", &qty)
			}
			asks = append(asks, [2]float64{price, qty})
			quantities = append(quantities, qty)
		}
		state.Asks = asks

		// Update liquidity analyzer with ask quantities (Phase 7 - T118)
		if state.LiquidityAnalyzer != nil && len(quantities) > 0 {
			state.LiquidityAnalyzer.UpdateQuantities(quantities)
		}
	}

	// Update anomaly detector with order book (Phase 8 - T136)
	if state.AnomalyDetector != nil && len(state.Bids) > 0 && len(state.Asks) > 0 {
		bids := convertToModels(state.Bids)
		asks := convertToModels(state.Asks)
		midPrice := (state.Bids[0][0] + state.Asks[0][0]) / 2.0
		state.AnomalyDetector.UpdateOrderBook(envelope.TsEvent.UnixMilli(), bids, asks, midPrice)
	}
}

// processOrderBookDeltas updates order book from deltas (simplified MVP version).
func (a *Aggregator) processOrderBookDeltas(state *SymbolState, envelope *models.MarketEventEnvelope) {
	// For MVP, skip delta processing and rely on periodic depth snapshots
	// Full delta application will be implemented in later phases
	a.logger.Debug("order_book_deltas_skipped", "symbol", state.Symbol)
}

// updateIngestionStatus implements the state machine for ingestion health (Phase 5 - US5).
// State transitions:
// - ok -> degraded: when data_age_ms > 1000 for >2 seconds (T090)
// - degraded -> down: when data_age_ms > 5000 (T091)
// - degraded/down -> ok: when fresh data received (data_age_ms <= 1000) (T092)
func (a *Aggregator) updateIngestionStatus(state *SymbolState, dataAgeMs int64, now time.Time) {
	fresh := dataAgeMs <= 1000
	currentStatus := state.IngestionStatus

	switch currentStatus {
	case "ok":
		if !fresh {
			// Data became stale, start tracking degradation time
			if state.DegradedSince.IsZero() {
				state.DegradedSince = now
			}

			// Transition to degraded after 2 seconds of staleness (T090)
			if now.Sub(state.DegradedSince) > 2*time.Second {
				state.IngestionStatus = "degraded"
				state.IngestionStatusChangedAt = now
				a.logger.Warn("ingestion_status_transition",
					"symbol", state.Symbol,
					"from", "ok",
					"to", "degraded",
					"data_age_ms", dataAgeMs,
				)
			}
		} else {
			// Fresh data, reset degradation tracking
			state.DegradedSince = time.Time{}
		}

	case "degraded":
		// Transition to down if data age exceeds 5 seconds (T091)
		if dataAgeMs > 5000 {
			state.IngestionStatus = "down"
			state.IngestionStatusChangedAt = now
			a.logger.Error("ingestion_status_transition",
				"symbol", state.Symbol,
				"from", "degraded",
				"to", "down",
				"data_age_ms", dataAgeMs,
			)
		} else if fresh {
			// Recovery: fresh data received (T092)
			state.IngestionStatus = "ok"
			state.IngestionStatusChangedAt = now
			state.DegradedSince = time.Time{}
			a.logger.Info("ingestion_status_transition",
				"symbol", state.Symbol,
				"from", "degraded",
				"to", "ok",
				"data_age_ms", dataAgeMs,
			)
		}

	case "down":
		// Recovery: fresh data received (T092)
		if fresh {
			state.IngestionStatus = "ok"
			state.IngestionStatusChangedAt = now
			state.DegradedSince = time.Time{}
			a.logger.Info("ingestion_status_transition",
				"symbol", state.Symbol,
				"from", "down",
				"to", "ok",
				"data_age_ms", dataAgeMs,
			)
		}
	}
}

// generateAndPublishReport creates a market report and publishes it.
func (a *Aggregator) generateAndPublishReport(ctx context.Context, state *SymbolState) error {
	startTime := time.Now()
	now := startTime

	// Calculate data age (FR-020)
	dataAgeMs := now.Sub(state.LastEventTime).Milliseconds()

	// Update ingestion status using state machine (Phase 5 - T089, T090, T091, T092)
	a.updateIngestionStatus(state, dataAgeMs, now)

	fresh := dataAgeMs <= 1000

	// Build report
	report := &models.MarketReport{
		Symbol:        state.Symbol,
		Venue:         state.Venue,
		GeneratedAt:   now,
		DataAgeMs:     dataAgeMs,
		ReportVersion: a.reportVersion,
		Ingestion: models.IngestionStatus{
			Status: state.IngestionStatus, // Use state machine status
			Fresh:  fresh,
		},
		LastPrice:    state.LastPrice,
		Change24hPct: state.Change24hPct,
		High24h:      state.High24h,
		Low24h:       state.Low24h,
		Volume24h:    state.Volume24h,
		Anomalies:    []models.Anomaly{}, // Empty for MVP
	}

	// Calculate spread metrics if we have best bid/ask
	if len(state.Bids) > 0 && len(state.Asks) > 0 {
		bestBid := state.Bids[0]
		bestAsk := state.Asks[0]

		report.BestBid = models.PriceQty{Price: bestBid[0], Qty: bestBid[1]}
		report.BestAsk = models.PriceQty{Price: bestAsk[0], Qty: bestAsk[1]}

		spreadMetrics, err := metrics.CalculateSpread(bestBid[0], bestBid[1], bestAsk[0], bestAsk[1])
		if err != nil {
			a.logger.Error("spread_calculation_failed", "symbol", state.Symbol, "error", err)
		} else {
			report.SpreadBps = spreadMetrics.SpreadBps
			report.MidPrice = spreadMetrics.MidPrice
			report.MicroPrice = spreadMetrics.MicroPrice
		}

		// Calculate depth metrics
		depthMetrics, err := metrics.CalculateDepth(state.Bids, state.Asks, 20)
		if err != nil {
			a.logger.Error("depth_calculation_failed", "symbol", state.Symbol, "error", err)
		} else {
			// Convert to report format
			top20Bid := make([]models.PriceQty, len(depthMetrics.Bids))
			for i, level := range depthMetrics.Bids {
				top20Bid[i] = models.PriceQty{Price: level.Price, Qty: level.Qty}
			}
			top20Ask := make([]models.PriceQty, len(depthMetrics.Asks))
			for i, level := range depthMetrics.Asks {
				top20Ask[i] = models.PriceQty{Price: level.Price, Qty: level.Qty}
			}

			report.Depth = models.DepthMetrics{
				Top20Bid:  top20Bid,
				Top20Ask:  top20Ask,
				SumBid:    depthMetrics.TotalBidQty,
				SumAsk:    depthMetrics.TotalAskQty,
				Imbalance: depthMetrics.Imbalance,
			}
		}
	}

	// Calculate flow metrics (Phase 6 - T100)
	if state.FlowTracker != nil {
		flowMetrics := state.FlowTracker.GetMetrics(now)
		report.Flow = models.FlowMetrics{
			OrdersPerSec: flowMetrics.OrdersPerSec,
			NetFlow:      flowMetrics.NetFlow,
		}

		// Update anomaly detector with flow history (Phase 8 - T136)
		if state.AnomalyDetector != nil {
			state.AnomalyDetector.UpdateFlowHistory(flowMetrics.NetFlow)
		}
	}

	// Calculate liquidity analysis (Phase 7 - T118, T119, T120)
	if state.LiquidityAnalyzer != nil && len(state.Bids) > 0 && len(state.Asks) > 0 {
		bids := convertToModels(state.Bids)
		asks := convertToModels(state.Asks)
		midPrice := report.MidPrice
		if midPrice == 0 {
			midPrice = (state.Bids[0][0] + state.Asks[0][0]) / 2.0
		}

		liquidityAnalysis, err := state.LiquidityAnalyzer.AnalyzeLiquidity(
			bids, asks, midPrice, now.UnixMilli(),
		)
		if err != nil {
			a.logger.Warn("liquidity_analysis_failed", "symbol", state.Symbol, "error", err)
		} else {
			report.Liquidity = liquidityAnalysis
		}

		// Update anomaly detector with spread history (Phase 8 - T136)
		if state.AnomalyDetector != nil {
			state.AnomalyDetector.UpdateSpreadHistory(now.UnixMilli(), report.SpreadBps)
		}

		// Detect anomalies (Phase 8 - T136, T137, T138)
		if state.AnomalyDetector != nil && report.Liquidity != nil {
			anomalies := state.AnomalyDetector.DetectAnomalies(
				now.UnixMilli(),
				report.SpreadBps,
				report.Liquidity.Vacuums,
				report.Flow.NetFlow,
			)
			report.Anomalies = anomalies
		}
	}

	// MVP: Simple health score based on freshness and spread
	healthScore := 100
	if !fresh {
		healthScore -= 20
	}
	if report.SpreadBps > 10 {
		healthScore -= 10
	}

	report.Health = models.HealthScore{
		Score: healthScore,
		Components: models.HealthComponents{
			Freshness: float64(healthScore),
		},
	}

	// Publish report
	if err := a.publisher.Publish(ctx, state.Symbol, report); err != nil {
		// Record error metric (T094)
		if a.metrics != nil {
			a.metrics.RecordError("aggregator", "publish_failed")
		}
		return fmt.Errorf("publish failed: %w", err)
	}

	state.LastReportTime = now

	// Record metrics (T093, T094)
	if a.metrics != nil {
		a.metrics.RecordReportAge(dataAgeMs)
		calcLatency := time.Since(startTime).Milliseconds()
		a.metrics.RecordCalcLatency(float64(calcLatency))
	}

	a.logger.Info("report_generated",
		"symbol", state.Symbol,
		"data_age_ms", dataAgeMs,
		"fresh", fresh,
		"status", state.IngestionStatus, // Use state machine status
		"spread_bps", report.SpreadBps,
		"imbalance", report.Depth.Imbalance,
	)

	return nil
}

// convertToModels converts [][2]float64 to []models.PriceQty.
func convertToModels(levels [][2]float64) []models.PriceQty {
	result := make([]models.PriceQty, len(levels))
	for i, level := range levels {
		result[i] = models.PriceQty{
			Price: level[0],
			Qty:   level[1],
		}
	}
	return result
}
