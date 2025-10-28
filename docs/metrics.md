# Metrics Calculation Reference

**Feature**: Real-Time Crypto Market Analysis MCP Server
**Last Updated**: 2025-10-28
**Status**: Foundation - formulas to be fully documented during implementation

## Overview

This document provides the precise calculation formulas, time windows, edge cases, and examples for all market metrics computed by the analytics service. All formulas are implemented in `analytics/internal/metrics/`.

---

## Price Metrics (FR-006 to FR-008)

### Spread in Basis Points (FR-006)

**Formula**: `spread_bps = (best_ask - best_bid) / best_bid × 10000`

**Implementation**: `analytics/internal/metrics/spread.go`

**Inputs**:
- `best_bid`: Best bid price from order book
- `best_ask`: Best ask price from order book

**Output**: Float64, non-negative

**Edge Cases**:
- Crossed book (bid >= ask): Invalid state, reject event
- Zero bid: Invalid, reject event
- Very tight spread (<0.01 bps): Valid, indicates high liquidity

**Example**:
```
best_bid = $64,100
best_ask = $64,110
spread_bps = (64110 - 64100) / 64100 × 10000 = 1.56 bps
```

---

### Mid Price (FR-007)

**Formula**: `mid_price = (best_bid + best_ask) / 2`

**Implementation**: `analytics/internal/metrics/spread.go`

**Edge Cases**: None (always valid if bid and ask are valid)

---

### Micro Price (FR-008)

**Formula**: `micro_price = (best_ask × bid_qty + best_bid × ask_qty) / (bid_qty + ask_qty)`

**Implementation**: `analytics/internal/metrics/spread.go`

**Invariant**: `best_bid ≤ micro_price ≤ best_ask`

**Edge Cases**:
- Zero quantities: Fall back to mid price
- Imbalanced book (e.g., bid_qty >> ask_qty): Micro price closer to best_ask

**Example**:
```
best_bid = $64,100, bid_qty = 2.5 BTC
best_ask = $64,110, ask_qty = 1.2 BTC
micro_price = (64110 × 2.5 + 64100 × 1.2) / (2.5 + 1.2) = $64,106.76
```

---

## Depth Metrics (FR-009 to FR-010)

### Order Book Depth (FR-009)

**Description**: Sum of quantities at top 20 levels

**Implementation**: `analytics/internal/metrics/depth.go`

**Formulas**:
- `sum_bid = Σ(qty) for top 20 bid levels`
- `sum_ask = Σ(qty) for top 20 ask levels`

---

### Imbalance (FR-010)

**Formula**: `imbalance = (sum_bid - sum_ask) / (sum_bid + sum_ask)`

**Range**: [-1, 1]
- +1 = all bids, no asks
- 0 = balanced
- -1 = all asks, no bids

**Edge Cases**:
- Empty book (sum_bid + sum_ask = 0): Set imbalance = 0
- Very thin book: Valid, but may be noisy

---

## Liquidity Features (FR-011 to FR-013)

### Liquidity Walls (FR-011)

**Detection Criteria**: `qty >= max(P95 × 1.5, configurable_minimum)`

**Implementation**: `analytics/internal/metrics/liquidity.go` (Phase 7 - T103-T106)

**Algorithm**:
1. **Percentile Calculation (T103)**:
   - Maintain rolling window of order book quantities from recent snapshots
   - Calculate P95 (95th percentile) using linear interpolation
   - Window size: Up to 10,000 recent quantity observations

2. **Threshold Determination (T104)**:
   - Wall threshold = P95 × 1.5 (configurable multiplier)
   - Optional absolute minimum can override calculated threshold

3. **Wall Detection**:
   - Check each bid/ask level against threshold
   - If `level.qty >= threshold`, classify as wall

4. **Severity Classification (T105)**:
   - **High**: qty ≥ 3.0 × threshold
   - **Medium**: qty ≥ 2.0 × threshold
   - **Low**: qty ≥ 1.0 × threshold

**Edge Cases**:
- Insufficient data (<20 observations): Skip detection, return empty array
- No walls detected: Return empty array
- Multiple walls on same side: Report all independently

**Example**:
```
Order book quantities observed: [0.5, 1.2, 2.1, ..., 15.3] BTC
P95 = 12.5 BTC
Threshold = 12.5 × 1.5 = 18.75 BTC

Bid at $64,000 with 25 BTC → Wall detected (severity: medium)
Ask at $65,000 with 50 BTC → Wall detected (severity: high)
```

**Configuration**:
- `WallThresholdMultiplier`: Default 1.5, adjustable via config
- `MinWallQty`: Optional absolute minimum

**Documentation**: T106 - Wall detection algorithm and thresholds documented

---

### Liquidity Vacuums (FR-012)

**Detection Criteria**: Depth over several consecutive ticks < P10 threshold

**Implementation**: `analytics/internal/metrics/liquidity.go` (Phase 7 - T107-T111)

**Algorithm**:
1. **P10 Calculation (T107)**:
   - Calculate 10th percentile of rolling quantity window
   - Identifies thin liquidity threshold

2. **Thin Level Detection (T108)**:
   - Scan order book levels sequentially
   - Mark levels where `qty < P10`
   - Require ≥3 consecutive thin levels to start a vacuum

3. **Vacuum Region Formation**:
   - Track `from` (start price) and `to` (end price) of thin region
   - Continue expanding while levels remain thin
   - End vacuum when normal liquidity encountered

4. **Adjacent Vacuum Merging (T109)**:
   - Sort vacuums by price
   - Merge overlapping or adjacent regions
   - Take more severe classification when merging

5. **Severity Classification (T110)**:
   - **High**: ≥10 consecutive thin levels
   - **Medium**: 6-9 consecutive thin levels
   - **Low**: 3-5 consecutive thin levels

**Edge Cases**:
- Insufficient data: Skip detection
- Vacuum extending to end of book: Capture as-is
- Single thin level: Ignored (need ≥3 consecutive)

**Example**:
```
P10 = 0.8 BTC

Order book:
$64,100: 2.5 BTC (normal)
$64,105: 0.5 BTC (thin)
$64,110: 0.3 BTC (thin)
$64,115: 0.4 BTC (thin)
$64,120: 3.0 BTC (normal)

Vacuum detected: from=$64,105 to=$64,115 (severity: low)
```

**Documentation**: T111 - Vacuum detection algorithm and merging rules documented

---

### Volume Profile (FR-013)

**Components**:
- **POC** (Point of Control): Price bin with maximum volume
- **VAH/VAL**: Value Area High/Low - boundaries covering 70% of volume around POC

**Window**: Rolling 30 minutes (default)

**Invariant**: `VAL ≤ POC ≤ VAH`

**Implementation**: `analytics/internal/metrics/liquidity.go` (Phase 7 - T112-T117)

**Algorithm**:
1. **Trade Filtering (T113)**:
   - Filter trades within time window (current_time - 30 minutes)
   - Store trades with (timestamp, price, volume)
   - Maximum history size: 10,000 trades

2. **Price Binning (T112)**:
   - Calculate bin size: `bin_size = tick_size × bin_width`
   - Default bin_width = 5 ticks
   - Bin each trade: `bin_key = floor(price / bin_size) × bin_size`
   - Aggregate volume into bins

3. **POC Calculation (T114)**:
   - Find bin with maximum total volume
   - POC = price of that bin

4. **VAH/VAL Calculation (T115)**:
   - Calculate total volume across all bins
   - Target = 70% of total volume
   - Start from POC bin, accumulate volume
   - Expand outward (alternating low/high) until target reached
   - VAL = lowest price in value area
   - VAH = highest price in value area

5. **Invariant Validation (T116)**:
   - Verify `VAL ≤ POC ≤ VAH`
   - Reject result if invariant violated

**Edge Cases**:
- Insufficient trades (<10): Return error, profile omitted from report
- Single price bin: VAL = POC = VAH (valid but unusual)
- No trades in window: Error

**Example**:
```
30-minute window: 500 trades
Bin width: 5 ticks ($5)

Volume distribution:
$64,000-$64,005: 15 BTC
$64,005-$64,010: 45 BTC ← POC
$64,010-$64,015: 30 BTC
...

Total volume: 200 BTC
70% target: 140 BTC

Value area: $63,995 to $64,020
VAL = $63,995
POC = $64,007.50
VAH = $64,020
```

**Configuration**:
- `VolumeWindowSec`: Default 1800 (30 minutes)
- `VolumeBinWidth`: Default 5 ticks

**Interpretation**:
- POC: Price with most trading activity (support/resistance)
- VAH/VAL: Range where 70% of volume occurred
- Price outside value area: Potential mean reversion

**Documentation**: T117 - Volume profile calculation and bin width tuning documented

---

## Flow Metrics (FR-014 to FR-015)

### Orders Per Second (FR-014)

**Formula**: `orders_per_sec = count(events in last 10 seconds) / 10`

**Implementation**: `analytics/internal/metrics/flow.go` (Phase 6 - T097)

**Window**: 10 seconds (rolling)

**Description**: Measures market activity intensity by counting all market events (trades, order book updates, tickers) in the last 10 seconds and averaging over the window.

**Rolling Window Implementation**:
- Events are timestamped and stored in a deque
- On each calculation, events older than 10 seconds are pruned
- Count remaining events and divide by 10 to get rate

**Edge Cases**:
- No events in window: Returns 0.0
- Burst of events: Accurately captures short-term spikes in activity
- Window boundary: Events exactly at 10s boundary are excluded

**Example**:
```
Events in last 10 seconds: 47 events
orders_per_sec = 47 / 10 = 4.7 events/sec
```

**Interpretation**:
- < 1: Low activity, possibly illiquid
- 1-10: Normal activity for major pairs
- > 10: High activity, volatile or liquid market
- > 50: Very high activity, possible news event

---

### Net Flow (FR-015)

**Formula**: `net_flow = Σ(aggressive_buy_volume) - Σ(aggressive_sell_volume)` over last 30 seconds

**Implementation**: `analytics/internal/metrics/flow.go` (Phase 6 - T098)

**Window**: 30 seconds (rolling)

**Description**: Measures directional trading pressure by tracking the net difference between aggressive buy and sell volumes.

**Aggressive Side Determination**:
- **Aggressive Buy**: Trade that takes liquidity from the ask side (market buy order)
  - Detected from `aggressor_side = "BUY"` or `"BUYER"` in trade tick payload
- **Aggressive Sell**: Trade that takes liquidity from the bid side (market sell order)
  - Detected from `aggressor_side = "SELL"` or `"SELLER"` in trade tick payload

**Rolling Window Implementation**:
- Trades are timestamped and stored with (volume, isBuy) in a deque
- On each calculation, trades older than 30 seconds are pruned
- Sum buy volumes and sell volumes separately, return difference

**Output**:
- Float64 (can be positive, negative, or zero)
- Units: Base currency (e.g., BTC for BTCUSDT)

**Interpretation**:
- **Positive net_flow**: Net buying pressure
  - Market participants are aggressively buying
  - Price may be supported or rising
- **Negative net_flow**: Net selling pressure
  - Market participants are aggressively selling
  - Price may be under pressure or falling
- **Zero or near-zero**: Balanced flow
  - Equal buying and selling pressure
  - Consolidation or range-bound market

**Edge Cases**:
- No trades in window: Returns 0.0
- One-sided market: Large positive or negative values
- Equal buy/sell: Returns near 0.0

**Example**:
```
Trades in last 30 seconds:
- 2.5 BTC aggressive buy at $64,100
- 1.2 BTC aggressive buy at $64,105
- 3.0 BTC aggressive sell at $64,095
- 0.8 BTC aggressive sell at $64,090

net_flow = (2.5 + 1.2) - (3.0 + 0.8) = 3.7 - 3.8 = -0.1 BTC

Interpretation: Slightly negative, indicating marginally more selling pressure
```

**Correlation with Price**:
- Strong positive net_flow often precedes or accompanies price increases
- Strong negative net_flow often precedes or accompanies price decreases
- Divergence (price up, net_flow down) may signal weakness or reversal

---

## Anomaly Detection (FR-016 to FR-018)

### Spoofing (FR-016)

**Pattern**: Large orders far from mid price with high cancellation rate

**Implementation**: `analytics/internal/metrics/anomalies.go` (Phase 8 - T121-T125)

**Algorithm**:
1. **Large Order Tracking (T121)**:
   - Track orders where `distance_from_mid > spread × 3.0` (configurable)
   - Maintain state: price, qty, side, first_seen, update_count, cancel_count
   - Auto-cleanup orders not seen for >30 seconds

2. **Cancellation Rate Tracking (T122)**:
   - Record each cancellation event
   - Calculate: `cancel_rate = cancel_count / (update_count + cancel_count)`

3. **Spoofing Detection (T123)**:
   - Trigger when `cancel_rate >= 0.7` (70% cancellations)
   - Only consider tracked large orders
   - Report as spoofing anomaly

4. **Severity Classification (T124)**:
   - **High**: cancel_rate ≥ 90% AND cancel_count ≥ 5
   - **Medium**: cancel_rate ≥ 80% AND cancel_count ≥ 3
   - **Low**: cancel_rate ≥ 70%

**Edge Cases**:
- No tracked orders: No spoofing detected
- Order updated but never cancelled: Not spoofing
- Legitimate cancellations: May trigger false positives (acceptable trade-off)

**Example**:
```
Large bid at $63,000 (far below mid $64,100):
- Added, updated, cancelled (repeat 5 times in 30 seconds)
- cancel_rate = 5/10 = 50% → Not spoofing (below 70%)

Large bid at $63,500:
- Added, updated, cancelled (repeat 8 times, only 2 updates remain)
- cancel_rate = 8/10 = 80% → Spoofing detected (medium severity)
```

**Configuration**:
- `SpoofingDistanceMultiplier`: Default 3.0 (3× spread distance)
- `SpoofingCancelRateThreshold`: Default 0.7 (70%)
- `SpoofingMinOrderSize`: Optional minimum to consider

**Documentation**: T125 - Spoofing detection algorithm and thresholds documented

---

### Iceberg Orders (FR-017)

**Pattern**: Series of partial fills at same price with stable visible depth

**Implementation**: `analytics/internal/metrics/anomalies.go` (Phase 8 - T126-T129)

**Algorithm**:
1. **Fill Tracking (T126)**:
   - Record each trade fill: (timestamp, price, volume, visible_qty)
   - Visible qty estimated from best bid/ask at time of trade
   - Rolling window: 5 minutes

2. **Depth Stability Monitoring (T127)**:
   - Group fills by price level
   - For each price, check if visible_qty remains stable (±10%)
   - Stable depth indicates hidden liquidity being replenished

3. **Iceberg Detection (T128)**:
   - Require ≥5 fills at same price (configurable)
   - Verify visible depth stability across fills
   - Report as iceberg anomaly

**Severity**: Fixed at "medium" (icebergs are informational, not manipulative)

**Edge Cases**:
- Insufficient fills (<5): No detection
- High volatility: Visible depth may fluctuate legitimately
- Multiple icebergs: Each reported independently

**Example**:
```
Fills at $64,100:
Fill 1: 1.0 BTC trade, visible depth: 2.5 BTC
Fill 2: 0.8 BTC trade, visible depth: 2.4 BTC
Fill 3: 1.2 BTC trade, visible depth: 2.6 BTC
Fill 4: 0.9 BTC trade, visible depth: 2.5 BTC
Fill 5: 1.1 BTC trade, visible depth: 2.5 BTC

Visible depth stable within 10% → Iceberg detected
Total executed: 5.0 BTC, but only ~2.5 BTC ever visible
```

**Configuration**:
- `IcebergMinFills`: Default 5 fills
- `IcebergDepthStability`: Default 0.1 (10% variation allowed)

**Documentation**: T129 - Iceberg detection algorithm and pattern matching documented

---

### Flash Crash Risk (FR-018)

**Pattern**: Widening spread + thin book + negative accelerating flow

**Implementation**: `analytics/internal/metrics/anomalies.go` (Phase 8 - T130-T135)

**Algorithm**:

1. **Spread Widening Detection (T130)**:
   - Track spread_bps history (last 10+ observations)
   - Calculate recent average spread
   - Trigger if `current_spread > avg_spread × 2.0` (configurable)

2. **Thin Book Detection (T131)**:
   - Count liquidity vacuums in current report
   - Trigger if `vacuum_count >= 3` (configurable)
   - Higher weight for high-severity vacuums

3. **Flow Acceleration Tracking (T132)**:
   - Maintain net_flow history (last 5+ observations)
   - Calculate flow acceleration: `Σ(flow[i] - flow[i-1])`
   - Trigger if flow is consistently negative AND accelerating downward
   - Threshold: `acceleration < -1000` (configurable)

4. **Signal Combination (T133)**:
   - Require ≥2 of 3 signals to trigger flash crash risk
   - All 3 signals = highest severity

5. **Severity Classification (T134)**:
   - **High**: All 3 signals OR ≥3 high-severity vacuums
   - **Medium**: 2 signals OR ≥2 high-severity vacuums
   - **Low**: 2 signals with low-severity vacuums

**Edge Cases**:
- Insufficient history: No detection
- Normal volatility: May trigger false positives during legitimate moves
- Post-crash: Signal persists until conditions normalize

**Example**:
```
Normal conditions:
- Spread: 1.5 bps (avg: 1.4 bps) → No widening
- Vacuums: 1 → Not thin
- Net flow: +50, -20, +30 → Not accelerating

Flash crash risk conditions:
- Spread: 8.5 bps (avg: 2.0 bps) → Widening (8.5 > 4.0) ✓
- Vacuums: 4 (2 high severity) → Thin book ✓
- Net flow: -200, -350, -550, -800 → Negative accelerating ✓

All 3 signals → Flash crash risk (high severity)
```

**Configuration**:
- `SpreadWideningMultiplier`: Default 2.0
- `ThinBookVacuumThreshold`: Default 3 vacuums
- `FlowAccelerationThreshold`: Default -1000

**Interpretation**:
- **High severity**: Immediate risk, market may gap down
- **Medium severity**: Elevated risk, monitor closely
- **Low severity**: Early warning, conditions deteriorating

**Documentation**: T135 - Flash crash risk detection algorithm and signal weighting documented

---

## Health Score (FR-019)

**Formula**: Weighted sum of normalized components

**Weights**:
- Spread: 20%
- Depth: 25%
- Balance: 15%
- Flow: 15%
- Anomalies: 15%
- Freshness: 10%

**Range**: [0, 100] integer

**TODO**: Document normalization functions for each component

---

## Time Windows Configuration

| Metric | Default Window | Configurable | Env Var |
|--------|---------------|--------------|---------|
| Flow rate | 10 seconds | Yes | `FLOW_WINDOW_SEC` |
| Net flow | 30 seconds | Yes | `FLOW_WINDOW_SEC` |
| Volume profile | 30 minutes | Yes | `REPORT_WINDOW_SEC` |
| Wall detection | Rolling P95 | Yes | Implementation-specific |

---

## Testing Strategy

### Unit Tests
- Test each formula with known inputs
- Verify invariants (e.g., imbalance ∈ [-1, 1])
- Test edge cases (empty book, crossed book, zero quantities)

### Property-Based Tests
- Use `gopter` for formula invariant validation
- Generate random valid order books
- Verify mathematical properties hold

**TODO**: Implement property tests for all formulas

---

**Status**: This document will be completed during Phase 3-9 implementation as each metric is built.
