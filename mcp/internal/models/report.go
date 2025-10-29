package models

import "time"

// MarketReport is the comprehensive market analysis snapshot.
// This is a duplicate of analytics/internal/models/report.go for MCP service independence.
// In production, consider using a shared models package.
type MarketReport struct {
	// Identification
	Symbol        string    `json:"symbol"`
	Venue         string    `json:"venue"`
	GeneratedAt   time.Time `json:"generated_at"`
	DataAgeMs     int64     `json:"data_age_ms"`
	ReportVersion string    `json:"schemaVersion"`

	// Ingestion Health
	Ingestion IngestionStatus `json:"ingestion"`

	// 24h Statistics
	LastPrice    float64 `json:"last_price"`
	Change24hPct float64 `json:"change_24h_pct"`
	High24h      float64 `json:"high_24h"`
	Low24h       float64 `json:"low_24h"`
	Volume24h    float64 `json:"volume_24h"`

	// L1 / Spread
	BestBid    PriceQty `json:"best_bid"`
	BestAsk    PriceQty `json:"best_ask"`
	SpreadBps  float64  `json:"spread_bps"`
	MidPrice   float64  `json:"mid_price"`
	MicroPrice float64  `json:"micro_price"`

	// Depth (Top 20)
	Depth DepthMetrics `json:"depth"`

	// Liquidity Features
	Liquidity *LiquidityAnalysis `json:"liquidity,omitempty"`

	// Flow Metrics
	Flow FlowMetrics `json:"flow"`

	// Anomalies
	Anomalies []Anomaly `json:"anomalies"`

	// Health Score
	Health HealthScore `json:"health"`
}

// IngestionStatus indicates data pipeline health.
type IngestionStatus struct {
	Status string `json:"status"`
	Fresh  bool   `json:"fresh"`
}

// PriceQty represents a price-quantity pair.
type PriceQty struct {
	Price float64 `json:"price"`
	Qty   float64 `json:"qty"`
}

// DepthMetrics contains order book depth analysis.
type DepthMetrics struct {
	Top20Bid  []PriceQty `json:"top20_bid"`
	Top20Ask  []PriceQty `json:"top20_ask"`
	SumBid    float64    `json:"sum_bid"`
	SumAsk    float64    `json:"sum_ask"`
	Imbalance float64    `json:"imbalance"`
}

// LiquidityAnalysis contains advanced liquidity features.
type LiquidityAnalysis struct {
	Walls   []LiquidityWall   `json:"walls"`
	Vacuums []LiquidityVacuum `json:"vacuums"`
	Profile VolumeProfile     `json:"profile"`
}

// LiquidityWall represents a large concentrated order.
type LiquidityWall struct {
	Price    float64 `json:"price"`
	Qty      float64 `json:"qty"`
	Side     string  `json:"side"`
	Severity string  `json:"severity,omitempty"`
}

// LiquidityVacuum represents a thin liquidity region.
type LiquidityVacuum struct {
	From     float64 `json:"from"`
	To       float64 `json:"to"`
	Severity string  `json:"severity,omitempty"`
}

// VolumeProfile represents volume distribution.
type VolumeProfile struct {
	POC float64 `json:"poc"`
	VAH float64 `json:"vah"`
	VAL float64 `json:"val"`
}

// FlowMetrics represents market activity intensity.
type FlowMetrics struct {
	OrdersPerSec float64 `json:"orders_per_sec"`
	NetFlow      float64 `json:"net_flow"`
}

// Anomaly represents detected unusual behavior.
type Anomaly struct {
	Type     string `json:"type"`
	Severity string `json:"severity"`
	Note     string `json:"note,omitempty"`
}

// HealthScore represents market quality.
type HealthScore struct {
	Score      int              `json:"score"`
	Components HealthComponents `json:"components"`
}

// HealthComponents contains individual score components.
type HealthComponents struct {
	Spread    float64 `json:"spread"`
	Depth     float64 `json:"depth"`
	Balance   float64 `json:"balance"`
	Flow      float64 `json:"flow"`
	Anomalies float64 `json:"anomalies"`
	Freshness float64 `json:"freshness"`
}

// ErrorResponse is the standard error response format.
type ErrorResponse struct {
	Error   string `json:"error"`
	Message string `json:"message"`
}
