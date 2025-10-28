package metrics

import (
	"fmt"
	"math"
	"time"

	"analytics/internal/models"
)

// AnomalyConfig contains configuration for anomaly detection.
type AnomalyConfig struct {
	// Spoofing detection
	SpoofingDistanceMultiplier  float64 // How far from mid price (in spread units)
	SpoofingCancelRateThreshold float64 // Cancel rate to trigger detection (0.7 = 70%)
	SpoofingMinOrderSize        float64 // Minimum order size to track

	// Iceberg detection
	IcebergMinFills       int     // Minimum number of fills at same price
	IcebergDepthStability float64 // Max allowed depth change (0.1 = 10%)

	// Flash crash risk detection
	SpreadWideningMultiplier  float64 // Spread increase multiplier to trigger alert
	ThinBookVacuumThreshold   int     // Number of vacuums indicating thin book
	FlowAccelerationThreshold float64 // Net flow acceleration threshold
}

// DefaultAnomalyConfig returns default configuration.
func DefaultAnomalyConfig() *AnomalyConfig {
	return &AnomalyConfig{
		SpoofingDistanceMultiplier:  3.0,
		SpoofingCancelRateThreshold: 0.7,
		SpoofingMinOrderSize:        0,
		IcebergMinFills:             5,
		IcebergDepthStability:       0.1,
		SpreadWideningMultiplier:    2.0,
		ThinBookVacuumThreshold:     3,
		FlowAccelerationThreshold:   -1000.0, // Negative flow acceleration
	}
}

// AnomalyDetector maintains state for anomaly detection.
type AnomalyDetector struct {
	config *AnomalyConfig

	// Spoofing detection state
	trackedOrders       map[string]*trackedOrder
	orderHistory        []orderEvent
	maxOrderHistorySize int

	// Iceberg detection state
	fillHistory        []fillEvent
	maxFillHistorySize int

	// Flash crash detection state
	spreadHistory  []spreadRecord
	flowHistory    []float64
	maxHistorySize int
}

type trackedOrder struct {
	price       float64
	qty         float64
	side        string
	firstSeen   time.Time
	lastSeen    time.Time
	cancelCount int
	updateCount int
}

type orderEvent struct {
	timestamp int64
	price     float64
	qty       float64
	eventType string // "add", "update", "cancel"
	side      string
}

type fillEvent struct {
	timestamp  int64
	price      float64
	volume     float64
	visibleQty float64
}

type spreadRecord struct {
	timestamp int64
	spreadBps float64
}

// NewAnomalyDetector creates a new anomaly detector.
func NewAnomalyDetector(config *AnomalyConfig) *AnomalyDetector {
	if config == nil {
		config = DefaultAnomalyConfig()
	}
	return &AnomalyDetector{
		config:              config,
		trackedOrders:       make(map[string]*trackedOrder),
		orderHistory:        make([]orderEvent, 0, 1000),
		fillHistory:         make([]fillEvent, 0, 1000),
		spreadHistory:       make([]spreadRecord, 0, 1000),
		flowHistory:         make([]float64, 0, 1000),
		maxOrderHistorySize: 1000,
		maxFillHistorySize:  1000,
		maxHistorySize:      1000,
	}
}

// UpdateOrderBook tracks order book changes for spoofing detection.
// T121: Implement large order tracking
func (ad *AnomalyDetector) UpdateOrderBook(timestamp int64, bids, asks []models.PriceQty, midPrice float64) {
	// Track large orders far from mid price
	spreadSize := math.Abs(asks[0].Price - bids[0].Price)
	distanceThreshold := spreadSize * ad.config.SpoofingDistanceMultiplier

	// Track bid orders
	for _, level := range bids {
		distance := midPrice - level.Price
		if distance > distanceThreshold {
			key := makeOrderKey(level.Price, "bid")
			if existing, found := ad.trackedOrders[key]; found {
				existing.lastSeen = time.Now()
				existing.updateCount++
			} else {
				ad.trackedOrders[key] = &trackedOrder{
					price:       level.Price,
					qty:         level.Qty,
					side:        "bid",
					firstSeen:   time.Now(),
					lastSeen:    time.Now(),
					updateCount: 1,
				}
			}
		}
	}

	// Track ask orders
	for _, level := range asks {
		distance := level.Price - midPrice
		if distance > distanceThreshold {
			key := makeOrderKey(level.Price, "ask")
			if existing, found := ad.trackedOrders[key]; found {
				existing.lastSeen = time.Now()
				existing.updateCount++
			} else {
				ad.trackedOrders[key] = &trackedOrder{
					price:       level.Price,
					qty:         level.Qty,
					side:        "ask",
					firstSeen:   time.Now(),
					lastSeen:    time.Now(),
					updateCount: 1,
				}
			}
		}
	}

	// Clean up old tracked orders (older than 30 seconds)
	ad.cleanupTrackedOrders(30 * time.Second)
}

// RecordOrderCancellation tracks cancellations for spoofing detection.
// T122: Implement cancellation rate tracking
func (ad *AnomalyDetector) RecordOrderCancellation(timestamp int64, price float64, side string) {
	key := makeOrderKey(price, side)
	if order, found := ad.trackedOrders[key]; found {
		order.cancelCount++
	}

	ad.orderHistory = append(ad.orderHistory, orderEvent{
		timestamp: timestamp,
		price:     price,
		eventType: "cancel",
		side:      side,
	})

	if len(ad.orderHistory) > ad.maxOrderHistorySize {
		ad.orderHistory = ad.orderHistory[len(ad.orderHistory)-ad.maxOrderHistorySize:]
	}
}

// RecordTradeFill tracks fills for iceberg detection.
// T126: Implement partial fill tracking
func (ad *AnomalyDetector) RecordTradeFill(timestamp int64, price, volume, visibleQty float64) {
	ad.fillHistory = append(ad.fillHistory, fillEvent{
		timestamp:  timestamp,
		price:      price,
		volume:     volume,
		visibleQty: visibleQty,
	})

	if len(ad.fillHistory) > ad.maxFillHistorySize {
		ad.fillHistory = ad.fillHistory[len(ad.fillHistory)-ad.maxFillHistorySize:]
	}
}

// UpdateSpreadHistory tracks spread for flash crash detection.
func (ad *AnomalyDetector) UpdateSpreadHistory(timestamp int64, spreadBps float64) {
	ad.spreadHistory = append(ad.spreadHistory, spreadRecord{
		timestamp: timestamp,
		spreadBps: spreadBps,
	})

	if len(ad.spreadHistory) > ad.maxHistorySize {
		ad.spreadHistory = ad.spreadHistory[len(ad.spreadHistory)-ad.maxHistorySize:]
	}
}

// UpdateFlowHistory tracks net flow for flash crash detection.
func (ad *AnomalyDetector) UpdateFlowHistory(netFlow float64) {
	ad.flowHistory = append(ad.flowHistory, netFlow)

	if len(ad.flowHistory) > ad.maxHistorySize {
		ad.flowHistory = ad.flowHistory[len(ad.flowHistory)-ad.maxHistorySize:]
	}
}

// DetectSpoofing identifies potential spoofing patterns.
// T123: Implement spoofing pattern detection per FR-016
func (ad *AnomalyDetector) DetectSpoofing() []models.Anomaly {
	anomalies := []models.Anomaly{}

	for _, order := range ad.trackedOrders {
		if order.updateCount == 0 {
			continue
		}

		// Calculate cancel rate
		totalEvents := order.updateCount + order.cancelCount
		cancelRate := float64(order.cancelCount) / float64(totalEvents)

		// Check if meets spoofing criteria
		if cancelRate >= ad.config.SpoofingCancelRateThreshold {
			severity := classifySpoofingSeverity(cancelRate, order.cancelCount) // T124
			anomalies = append(anomalies, models.Anomaly{
				Type:     "spoofing",
				Severity: severity,
				Note: fmt.Sprintf("Large %s order at %.2f with %.0f%% cancel rate (%d cancels)",
					order.side, order.price, cancelRate*100, order.cancelCount),
			})
		}
	}

	return anomalies
}

// classifySpoofingSeverity determines spoofing severity.
// T124: Implement severity classification for spoofing
func classifySpoofingSeverity(cancelRate float64, cancelCount int) string {
	if cancelRate >= 0.9 && cancelCount >= 5 {
		return "high"
	} else if cancelRate >= 0.8 && cancelCount >= 3 {
		return "medium"
	}
	return "low"
}

// DetectIcebergOrders identifies potential iceberg order patterns.
// T128: Implement iceberg pattern detection per FR-017
func (ad *AnomalyDetector) DetectIcebergOrders(currentTime int64) []models.Anomaly {
	anomalies := []models.Anomaly{}

	if len(ad.fillHistory) < ad.config.IcebergMinFills {
		return anomalies
	}

	// Group fills by price
	fillsByPrice := make(map[float64][]fillEvent)
	windowStart := currentTime - 300 // 5 minute window

	for _, fill := range ad.fillHistory {
		if fill.timestamp >= windowStart {
			fillsByPrice[fill.price] = append(fillsByPrice[fill.price], fill)
		}
	}

	// Check for iceberg pattern at each price
	for price, fills := range fillsByPrice {
		if len(fills) >= ad.config.IcebergMinFills {
			// T127: Check visible depth stability
			if isDepthStable(fills, ad.config.IcebergDepthStability) {
				anomalies = append(anomalies, models.Anomaly{
					Type:     "iceberg",
					Severity: "medium",
					Note: fmt.Sprintf("Iceberg order detected at %.2f (%d fills with stable visible depth)",
						price, len(fills)),
				})
			}
		}
	}

	return anomalies
}

// isDepthStable checks if visible quantity remains stable across fills.
// T127: Implement visible depth stability monitoring
func isDepthStable(fills []fillEvent, stabilityThreshold float64) bool {
	if len(fills) < 2 {
		return false
	}

	avgQty := 0.0
	for _, fill := range fills {
		avgQty += fill.visibleQty
	}
	avgQty /= float64(len(fills))

	// Check if all fills have similar visible quantity
	for _, fill := range fills {
		deviation := math.Abs(fill.visibleQty-avgQty) / avgQty
		if deviation > stabilityThreshold {
			return false
		}
	}

	return true
}

// DetectFlashCrashRisk identifies conditions indicating flash crash risk.
// T133: Implement flash crash risk pattern detection per FR-018
func (ad *AnomalyDetector) DetectFlashCrashRisk(
	currentSpreadBps float64,
	vacuums []models.LiquidityVacuum,
	currentNetFlow float64,
) []models.Anomaly {
	anomalies := []models.Anomaly{}

	// T130: Check spread widening
	spreadWidening := ad.isSpreadWidening(currentSpreadBps)

	// T131: Check book thinness (number of vacuums)
	thinBook := len(vacuums) >= ad.config.ThinBookVacuumThreshold

	// T132: Check flow acceleration (negative flow getting more negative)
	negativeFlowAccel := ad.isNegativeFlowAccelerating()

	// Combine signals
	signalCount := 0
	if spreadWidening {
		signalCount++
	}
	if thinBook {
		signalCount++
	}
	if negativeFlowAccel {
		signalCount++
	}

	if signalCount >= 2 {
		// At least 2 of 3 signals present
		severity := classifyFlashCrashSeverity(signalCount, vacuums) // T134
		anomalies = append(anomalies, models.Anomaly{
			Type:     "flash_crash_risk",
			Severity: severity,
			Note: fmt.Sprintf("Flash crash risk: widening=%v thin=%v flow=%v",
				spreadWidening, thinBook, negativeFlowAccel),
		})
	}

	return anomalies
}

// isSpreadWidening checks if spread is increasing significantly.
// T130: Implement spread widening detection
func (ad *AnomalyDetector) isSpreadWidening(currentSpreadBps float64) bool {
	if len(ad.spreadHistory) < 10 {
		return false
	}

	// Calculate average spread from recent history
	recentCount := 10
	avgSpread := 0.0
	for i := len(ad.spreadHistory) - recentCount; i < len(ad.spreadHistory); i++ {
		if i >= 0 {
			avgSpread += ad.spreadHistory[i].spreadBps
		}
	}
	avgSpread /= float64(recentCount)

	// Check if current spread is significantly wider
	return currentSpreadBps > avgSpread*ad.config.SpreadWideningMultiplier
}

// isNegativeFlowAccelerating checks if negative flow is accelerating.
// T132: Implement flow velocity tracking
func (ad *AnomalyDetector) isNegativeFlowAccelerating() bool {
	if len(ad.flowHistory) < 5 {
		return false
	}

	// Calculate flow acceleration (change in flow rate)
	recentFlows := ad.flowHistory[len(ad.flowHistory)-5:]

	// Check if flow is consistently negative and getting more negative
	allNegative := true
	acceleration := 0.0

	for i := 1; i < len(recentFlows); i++ {
		if recentFlows[i] >= 0 {
			allNegative = false
		}
		acceleration += recentFlows[i] - recentFlows[i-1]
	}

	return allNegative && acceleration < ad.config.FlowAccelerationThreshold
}

// classifyFlashCrashSeverity determines flash crash risk severity.
// T134: Implement severity classification for flash crash risk
func classifyFlashCrashSeverity(signalCount int, vacuums []models.LiquidityVacuum) string {
	// Count high severity vacuums
	highSeverityVacuums := 0
	for _, v := range vacuums {
		if v.Severity == "high" {
			highSeverityVacuums++
		}
	}

	if signalCount == 3 || highSeverityVacuums >= 3 {
		return "high"
	} else if signalCount == 2 || highSeverityVacuums >= 2 {
		return "medium"
	}
	return "low"
}

// DetectAnomalies performs complete anomaly detection.
// T136: Integrate anomaly detection (spoofing, iceberg, flash crash)
func (ad *AnomalyDetector) DetectAnomalies(
	currentTime int64,
	currentSpreadBps float64,
	vacuums []models.LiquidityVacuum,
	currentNetFlow float64,
) []models.Anomaly {
	anomalies := []models.Anomaly{}

	// Detect spoofing
	spoofingAnomalies := ad.DetectSpoofing()
	anomalies = append(anomalies, spoofingAnomalies...)

	// Detect iceberg orders
	icebergAnomalies := ad.DetectIcebergOrders(currentTime)
	anomalies = append(anomalies, icebergAnomalies...)

	// Detect flash crash risk
	flashCrashAnomalies := ad.DetectFlashCrashRisk(currentSpreadBps, vacuums, currentNetFlow)
	anomalies = append(anomalies, flashCrashAnomalies...)

	return anomalies
}

// cleanupTrackedOrders removes orders that haven't been seen recently.
func (ad *AnomalyDetector) cleanupTrackedOrders(maxAge time.Duration) {
	now := time.Now()
	for key, order := range ad.trackedOrders {
		if now.Sub(order.lastSeen) > maxAge {
			delete(ad.trackedOrders, key)
		}
	}
}

// makeOrderKey creates a unique key for tracking orders.
func makeOrderKey(price float64, side string) string {
	return fmt.Sprintf("%s_%.8f", side, price)
}
