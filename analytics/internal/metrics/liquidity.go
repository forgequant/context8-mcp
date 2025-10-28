package metrics

import (
	"fmt"
	"math"
	"sort"

	"analytics/internal/models"
)

// LiquidityConfig contains configuration for liquidity analysis.
type LiquidityConfig struct {
	WallThresholdMultiplier float64 // Default: 1.5 (P95 × 1.5)
	VacuumPercentile        float64 // Default: 10 (P10)
	MinWallQty              float64 // Absolute minimum for wall detection
	VolumeBinWidth          int     // Number of ticks per bin for volume profile
	VolumeWindowSec         int     // Time window in seconds (default: 1800 = 30 min)
}

// DefaultLiquidityConfig returns default configuration.
func DefaultLiquidityConfig() *LiquidityConfig {
	return &LiquidityConfig{
		WallThresholdMultiplier: 1.5,
		VacuumPercentile:        10,
		MinWallQty:              0, // Will be calculated from median if not set
		VolumeBinWidth:          5,
		VolumeWindowSec:         1800, // 30 minutes
	}
}

// LiquidityAnalyzer maintains state for liquidity analysis.
type LiquidityAnalyzer struct {
	config         *LiquidityConfig
	qtyHistory     []float64 // Rolling window of quantities for percentile calculation
	tradeHistory   []tradeRecord
	maxHistorySize int
}

type tradeRecord struct {
	timestamp int64
	price     float64
	volume    float64
}

// NewLiquidityAnalyzer creates a new liquidity analyzer.
func NewLiquidityAnalyzer(config *LiquidityConfig) *LiquidityAnalyzer {
	if config == nil {
		config = DefaultLiquidityConfig()
	}
	return &LiquidityAnalyzer{
		config:         config,
		qtyHistory:     make([]float64, 0, 1000),
		tradeHistory:   make([]tradeRecord, 0, 10000),
		maxHistorySize: 10000,
	}
}

// UpdateQuantities updates the rolling window of quantities for percentile calculation.
// Call this with order book level quantities.
func (la *LiquidityAnalyzer) UpdateQuantities(quantities []float64) {
	la.qtyHistory = append(la.qtyHistory, quantities...)

	// Keep only recent data
	if len(la.qtyHistory) > la.maxHistorySize {
		la.qtyHistory = la.qtyHistory[len(la.qtyHistory)-la.maxHistorySize:]
	}
}

// UpdateTrades updates the rolling window of trades for volume profile.
func (la *LiquidityAnalyzer) UpdateTrades(timestamp int64, price, volume float64) {
	la.tradeHistory = append(la.tradeHistory, tradeRecord{
		timestamp: timestamp,
		price:     price,
		volume:    volume,
	})

	// Keep only recent data
	if len(la.tradeHistory) > la.maxHistorySize {
		la.tradeHistory = la.tradeHistory[len(la.tradeHistory)-la.maxHistorySize:]
	}
}

// DetectWalls identifies large concentrated orders (liquidity walls).
// Implements FR-011: qty >= max(P95 * 1.5, configurable_minimum)
func (la *LiquidityAnalyzer) DetectWalls(bids, asks []models.PriceQty) []models.LiquidityWall {
	if len(la.qtyHistory) < 20 {
		// Not enough data for reliable percentile calculation
		return []models.LiquidityWall{}
	}

	// Calculate P95 threshold (T103)
	p95 := calculatePercentile(la.qtyHistory, 95)
	threshold := p95 * la.config.WallThresholdMultiplier

	if la.config.MinWallQty > 0 {
		threshold = math.Max(threshold, la.config.MinWallQty)
	}

	walls := []models.LiquidityWall{}

	// Detect bid walls (T104)
	for _, level := range bids {
		if level.Qty >= threshold {
			wall := models.LiquidityWall{
				Price:    level.Price,
				Qty:      level.Qty,
				Side:     "bid",
				Severity: classifyWallSeverity(level.Qty, threshold), // T105
			}
			walls = append(walls, wall)
		}
	}

	// Detect ask walls
	for _, level := range asks {
		if level.Qty >= threshold {
			wall := models.LiquidityWall{
				Price:    level.Price,
				Qty:      level.Qty,
				Side:     "ask",
				Severity: classifyWallSeverity(level.Qty, threshold), // T105
			}
			walls = append(walls, wall)
		}
	}

	return walls
}

// classifyWallSeverity determines the severity based on multiples of threshold.
// T105: Implement severity classification for walls
func classifyWallSeverity(qty, threshold float64) string {
	ratio := qty / threshold
	if ratio >= 3.0 {
		return "high"
	} else if ratio >= 2.0 {
		return "medium"
	}
	return "low"
}

// DetectVacuums identifies thin liquidity regions.
// Implements FR-012: depth < P10 over several ticks
func (la *LiquidityAnalyzer) DetectVacuums(bids, asks []models.PriceQty, midPrice float64) []models.LiquidityVacuum {
	if len(la.qtyHistory) < 20 {
		return []models.LiquidityVacuum{}
	}

	// Calculate P10 threshold (T107)
	p10 := calculatePercentile(la.qtyHistory, 10)

	vacuums := []models.LiquidityVacuum{}

	// Check bid side for thin regions (T108)
	bidVacuums := detectVacuumsOnSide(bids, p10, "bid")

	// Check ask side for thin regions
	askVacuums := detectVacuumsOnSide(asks, p10, "ask")

	// Merge adjacent vacuum regions (T109)
	vacuums = append(vacuums, mergeAdjacentVacuums(bidVacuums)...)
	vacuums = append(vacuums, mergeAdjacentVacuums(askVacuums)...)

	return vacuums
}

// detectVacuumsOnSide identifies thin regions on one side of the book.
func detectVacuumsOnSide(levels []models.PriceQty, threshold float64, side string) []models.LiquidityVacuum {
	vacuums := []models.LiquidityVacuum{}

	var vacuumStart, vacuumEnd float64
	inVacuum := false
	consecutiveThin := 0

	for _, level := range levels {
		if level.Qty < threshold {
			consecutiveThin++
			if !inVacuum && consecutiveThin >= 3 {
				// Start a new vacuum (need at least 3 consecutive thin levels)
				inVacuum = true
				vacuumStart = level.Price
			}
			vacuumEnd = level.Price
		} else {
			if inVacuum {
				// End the vacuum
				vacuum := models.LiquidityVacuum{
					From:     math.Min(vacuumStart, vacuumEnd),
					To:       math.Max(vacuumStart, vacuumEnd),
					Severity: classifyVacuumSeverity(consecutiveThin), // T110
				}
				vacuums = append(vacuums, vacuum)
				inVacuum = false
			}
			consecutiveThin = 0
		}
	}

	// Handle vacuum extending to the end
	if inVacuum {
		vacuum := models.LiquidityVacuum{
			From:     math.Min(vacuumStart, vacuumEnd),
			To:       math.Max(vacuumStart, vacuumEnd),
			Severity: classifyVacuumSeverity(consecutiveThin),
		}
		vacuums = append(vacuums, vacuum)
	}

	return vacuums
}

// classifyVacuumSeverity determines severity based on the number of consecutive thin levels.
// T110: Implement severity classification for vacuums
func classifyVacuumSeverity(consecutiveThinLevels int) string {
	if consecutiveThinLevels >= 10 {
		return "high"
	} else if consecutiveThinLevels >= 6 {
		return "medium"
	}
	return "low"
}

// mergeAdjacentVacuums combines adjacent vacuum regions.
// T109: Implement adjacent vacuum region merging
func mergeAdjacentVacuums(vacuums []models.LiquidityVacuum) []models.LiquidityVacuum {
	if len(vacuums) <= 1 {
		return vacuums
	}

	// Sort by From price
	sort.Slice(vacuums, func(i, j int) bool {
		return vacuums[i].From < vacuums[j].From
	})

	merged := []models.LiquidityVacuum{vacuums[0]}

	for i := 1; i < len(vacuums); i++ {
		current := vacuums[i]
		last := &merged[len(merged)-1]

		// Check if current vacuum is adjacent to the last one
		if current.From <= last.To {
			// Merge them
			last.To = math.Max(last.To, current.To)
			// Take the more severe classification
			if severityRank(current.Severity) > severityRank(last.Severity) {
				last.Severity = current.Severity
			}
		} else {
			merged = append(merged, current)
		}
	}

	return merged
}

// severityRank returns a numeric rank for severity comparison.
func severityRank(severity string) int {
	switch severity {
	case "high":
		return 3
	case "medium":
		return 2
	case "low":
		return 1
	default:
		return 0
	}
}

// CalculateVolumeProfile computes volume distribution across price levels.
// Implements FR-013: 30-minute rolling window with POC, VAH, VAL
func (la *LiquidityAnalyzer) CalculateVolumeProfile(currentTime int64) (models.VolumeProfile, error) {
	// Filter trades within the time window (T113)
	windowStart := currentTime - int64(la.config.VolumeWindowSec)
	recentTrades := []tradeRecord{}

	for _, trade := range la.tradeHistory {
		if trade.timestamp >= windowStart {
			recentTrades = append(recentTrades, trade)
		}
	}

	if len(recentTrades) < 10 {
		return models.VolumeProfile{}, fmt.Errorf("insufficient trade data for volume profile (got %d trades)", len(recentTrades))
	}

	// Bin trades by price (T112)
	volumeBins := make(map[float64]float64)

	// Find price range
	minPrice, maxPrice := recentTrades[0].price, recentTrades[0].price
	for _, trade := range recentTrades {
		if trade.price < minPrice {
			minPrice = trade.price
		}
		if trade.price > maxPrice {
			maxPrice = trade.price
		}
	}

	// Calculate bin size based on price range and tick size
	tickSize := (maxPrice - minPrice) / 200 // Approximate tick size
	binSize := tickSize * float64(la.config.VolumeBinWidth)

	if binSize <= 0 {
		binSize = (maxPrice - minPrice) / 50 // Fallback
	}

	// Aggregate volume into bins
	for _, trade := range recentTrades {
		binKey := math.Floor(trade.price/binSize) * binSize
		volumeBins[binKey] += trade.volume
	}

	// Find POC (Point of Control) - bin with maximum volume (T114)
	var poc float64
	var maxVolume float64

	for price, volume := range volumeBins {
		if volume > maxVolume {
			maxVolume = volume
			poc = price
		}
	}

	// Calculate VAH and VAL (70% of volume around POC) (T115)
	totalVolume := 0.0
	for _, volume := range volumeBins {
		totalVolume += volume
	}

	targetVolume := totalVolume * 0.70

	// Sort bins by price
	type binEntry struct {
		price  float64
		volume float64
	}
	sortedBins := make([]binEntry, 0, len(volumeBins))
	for price, volume := range volumeBins {
		sortedBins = append(sortedBins, binEntry{price, volume})
	}
	sort.Slice(sortedBins, func(i, j int) bool {
		return sortedBins[i].price < sortedBins[j].price
	})

	// Find POC index
	pocIndex := 0
	for i, bin := range sortedBins {
		if bin.price == poc {
			pocIndex = i
			break
		}
	}

	// Expand from POC to cover 70% of volume
	accumulatedVolume := sortedBins[pocIndex].volume
	lowIndex, highIndex := pocIndex, pocIndex

	for accumulatedVolume < targetVolume && (lowIndex > 0 || highIndex < len(sortedBins)-1) {
		// Decide whether to expand low or high
		expandLow := lowIndex > 0
		expandHigh := highIndex < len(sortedBins)-1

		if expandLow && expandHigh {
			// Choose the side with more volume
			if sortedBins[lowIndex-1].volume > sortedBins[highIndex+1].volume {
				lowIndex--
				accumulatedVolume += sortedBins[lowIndex].volume
			} else {
				highIndex++
				accumulatedVolume += sortedBins[highIndex].volume
			}
		} else if expandLow {
			lowIndex--
			accumulatedVolume += sortedBins[lowIndex].volume
		} else if expandHigh {
			highIndex++
			accumulatedVolume += sortedBins[highIndex].volume
		}
	}

	val := sortedBins[lowIndex].price
	vah := sortedBins[highIndex].price

	// Validate invariants (T116)
	if val > poc || poc > vah {
		return models.VolumeProfile{}, fmt.Errorf("volume profile invariant violated: val=%f poc=%f vah=%f", val, poc, vah)
	}

	return models.VolumeProfile{
		POC: roundToDecimal(poc, 8),
		VAH: roundToDecimal(vah, 8),
		VAL: roundToDecimal(val, 8),
	}, nil
}

// AnalyzeLiquidity performs complete liquidity analysis.
func (la *LiquidityAnalyzer) AnalyzeLiquidity(
	bids, asks []models.PriceQty,
	midPrice float64,
	currentTime int64,
) (*models.LiquidityAnalysis, error) {

	// Detect walls
	walls := la.DetectWalls(bids, asks)

	// Detect vacuums
	vacuums := la.DetectVacuums(bids, asks, midPrice)

	// Calculate volume profile
	profile, err := la.CalculateVolumeProfile(currentTime)
	if err != nil {
		// Volume profile is optional, use empty struct if calculation fails
		profile = models.VolumeProfile{}
	}

	return &models.LiquidityAnalysis{
		Walls:   walls,
		Vacuums: vacuums,
		Profile: profile,
	}, nil
}

// calculatePercentile computes the Nth percentile of a slice of float64 values.
func calculatePercentile(data []float64, percentile float64) float64 {
	if len(data) == 0 {
		return 0
	}

	// Create a copy and sort it
	sorted := make([]float64, len(data))
	copy(sorted, data)
	sort.Float64s(sorted)

	// Calculate percentile position
	pos := (percentile / 100.0) * float64(len(sorted)-1)
	lower := int(math.Floor(pos))
	upper := int(math.Ceil(pos))

	if lower == upper {
		return sorted[lower]
	}

	// Linear interpolation
	weight := pos - float64(lower)
	return sorted[lower]*(1-weight) + sorted[upper]*weight
}
