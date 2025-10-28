# Data Model: Real-Time Crypto Market Analysis MCP Server

**Feature**: Real-Time Crypto Market Analysis MCP Server
**Date**: 2025-10-28
**Status**: Complete

## Overview

This document defines all entities, their fields, relationships, validation rules, and state transitions for the context8-mcp system. The data model supports the event-driven architecture with JSON serialization for cross-language compatibility (Python producer, Go analytics/MCP).

---

## 1. Event Domain (Redis Streams Messages)

### 1.1 Market Event Envelope

**Purpose**: Standardized wrapper for all market events published to Redis Streams.

**Schema**:
```typescript
interface MarketEventEnvelope {
  type: "trade_tick" | "order_book_depth" | "order_book_deltas" | "ticker_24h"
  venue: "BINANCE"  // Constant for MVP
  symbol: string    // e.g., "BTCUSDT", "ETHUSDT"
  ts_event: string  // UTC RFC3339 timestamp from exchange
  payload: TradeTick | OrderBookDepth | OrderBookDeltas | Ticker24h
}
```

**Fields**:
- `type` (string, required): Event type discriminator
  - Validation: MUST be one of 4 allowed values
  - Purpose: Enable consumers to dispatch to correct handler
- `venue` (string, required): Exchange identifier
  - Validation: MUST be "BINANCE" for MVP
  - Purpose: Future multi-exchange support
- `symbol` (string, required): Trading pair identifier
  - Validation: MUST match pattern `^[A-Z]{3,10}USDT$` for MVP
  - Purpose: Filter events by symbol
- `ts_event` (string, required): Event timestamp from exchange
  - Validation: MUST be RFC3339 UTC format
  - Purpose: Calculate data age, detect out-of-order events
- `payload` (object, required): Type-specific event data
  - Validation: Shape depends on `type` field
  - Purpose: Carry actual market data

**Relationships**:
- Envelope → Payload (composition, 1:1)

**State Transitions**: None (immutable event)

**Indexes** (Redis Streams):
- Stream key: `nt:binance` (all events)
- Consumer group: `context8`

---

### 1.2 Trade Tick Payload

**Purpose**: Represents a single executed trade.

**Schema**:
```typescript
interface TradeTick {
  price: number      // Trade execution price
  qty: number        // Trade quantity (volume)
  side: "buy" | "sell"  // Aggressor side
  trade_id: string   // Unique trade identifier from exchange
}
```

**Fields**:
- `price` (float64, required): Trade price in quote currency
  - Validation: MUST be > 0
  - Precision: 8 decimal places
- `qty` (float64, required): Trade size in base currency
  - Validation: MUST be > 0
  - Precision: 8 decimal places
- `side` (string, required): Which side was the aggressor
  - Validation: MUST be "buy" or "sell"
  - Purpose: Calculate net flow (buy pressure vs sell pressure)
- `trade_id` (string, required): Exchange-provided unique ID
  - Validation: Non-empty string
  - Purpose: Deduplicate trades, debugging

**Usage**:
- Net flow calculation (FR-015)
- Volume profile binning (FR-013)
- Order rate tracking (FR-014)

---

### 1.3 Order Book Depth Payload

**Purpose**: Full snapshot of the order book top N levels.

**Schema**:
```typescript
interface OrderBookDepth {
  bids: Array<[number, number]>  // [[price, qty], ...]
  asks: Array<[number, number]>  // [[price, qty], ...]
  levels: number                  // Number of levels (20 for MVP)
}
```

**Fields**:
- `bids` (array, required): Best bid levels, sorted descending by price
  - Validation: Each element is [price > 0, qty > 0]
  - Maximum length: 20 (FR-009)
- `asks` (array, required): Best ask levels, sorted ascending by price
  - Validation: Each element is [price > 0, qty > 0]
  - Maximum length: 20 (FR-009)
- `levels` (integer, required): Snapshot depth
  - Validation: MUST be 20 for MVP
  - Purpose: Verify complete snapshot

**Usage**:
- Calculate spread (FR-006), mid price (FR-007), micro price (FR-008)
- Calculate imbalance (FR-010)
- Identify walls (FR-011) and vacuums (FR-012)

**Invariants**:
- `bids[0][0] < asks[0][0]` (best bid < best ask, no crossed book)
- `bids` sorted descending, `asks` sorted ascending

---

### 1.4 Order Book Deltas Payload

**Purpose**: Incremental updates to the order book (more efficient than full snapshots).

**Schema**:
```typescript
interface OrderBookDeltas {
  bids_upd: Array<[number, number]>  // [[price, new_qty], ...]
  asks_upd: Array<[number, number]>  // [[price, new_qty], ...]
}
```

**Fields**:
- `bids_upd` (array, required): Bid level changes
  - Validation: Each element [price > 0, qty ≥ 0]
  - qty = 0 means remove level
- `asks_upd` (array, required): Ask level changes
  - Validation: Each element [price > 0, qty ≥ 0]
  - qty = 0 means remove level

**Usage**:
- Update in-memory order book representation
- Track order rate (FR-014)

**Processing Notes**:
- Deltas applied to existing snapshot
- Idempotency: Last update wins for a given price level

---

### 1.5 24h Ticker Payload

**Purpose**: Aggregated 24-hour rolling statistics from the exchange.

**Schema**:
```typescript
interface Ticker24h {
  last_price: number
  price_change_pct: number
  high_24h: number
  low_24h: number
  volume_24h: number
  best_bid: [number, number]  // [price, qty]
  best_ask: [number, number]  // [price, qty]
}
```

**Fields**:
- `last_price` (float64, required): Most recent trade price
  - Validation: > 0
- `price_change_pct` (float64, required): 24h price change percentage
  - Validation: Any finite number (can be negative)
- `high_24h` (float64, required): Highest price in 24h window
  - Validation: >= low_24h
- `low_24h` (float64, required): Lowest price in 24h window
  - Validation: > 0
- `volume_24h` (float64, required): Total traded volume in 24h
  - Validation: >= 0
- `best_bid` (tuple, required): Top bid [price, qty]
  - Validation: price > 0, qty > 0
- `best_ask` (tuple, required): Top ask [price, qty]
  - Validation: price > 0, qty > 0

**Usage**:
- Populate report 24h statistics (FR-005)
- Fallback for best bid/ask if no recent depth snapshot

---

## 2. Report Domain (Cached Output)

### 2.1 Market Report

**Purpose**: Comprehensive market analysis snapshot served via MCP.

**Schema**:
```typescript
interface MarketReport {
  // Identification
  symbol: string
  venue: "BINANCE"
  generated_at: string  // UTC RFC3339
  data_age_ms: number
  report_version: string  // Semantic version

  // Ingestion Health
  ingestion: IngestionStatus

  // 24h Statistics
  last_price: number
  change_24h_pct: number
  high_24h: number
  low_24h: number
  volume_24h: number

  // L1 / Spread
  best_bid: PriceQty
  best_ask: PriceQty
  spread_bps: number
  mid_price: number
  micro_price: number

  // Depth (Top 20)
  depth: DepthMetrics

  // Liquidity Features
  liquidity?: LiquidityAnalysis  // Optional for MVP

  // Flow Metrics
  flow: FlowMetrics

  // Anomalies
  anomalies: Array<Anomaly>

  // Health Score
  health: HealthScore
}
```

**Cache Storage**:
- Redis key: `report:{symbol}` (e.g., `report:BTCUSDT`)
- TTL: 2-5 minutes (configurable)
- Format: JSON string

**Validation**:
- MUST validate against `contracts/report.json` schema before caching (FR-029)
- MUST include all required fields

---

### 2.2 Ingestion Status

**Purpose**: Indicate data pipeline health.

**Schema**:
```typescript
interface IngestionStatus {
  status: "ok" | "degraded" | "down"
  fresh: boolean  // true if data_age_ms <= 1000
}
```

**Fields**:
- `status` (enum, required):
  - `"ok"`: Normal operation, data flowing
  - `"degraded"`: Slow or intermittent data
  - `"down"`: No data received
  - Validation: MUST be one of three values
- `fresh` (boolean, required):
  - `true` if `data_age_ms <= 1000`
  - `false` otherwise

**State Transitions**:
```
ok → degraded: When data_age_ms > 1000ms for >2 seconds
degraded → down: When data_age_ms > 5000ms
degraded → ok: When fresh data received and data_age_ms <= 1000
down → degraded: When data received but still stale
down → ok: When fresh data received
```

**Usage**: FR-020, FR-021, User Story 5

---

### 2.3 Price-Quantity Pair

**Purpose**: Represent a single order book level.

**Schema**:
```typescript
interface PriceQty {
  price: number
  qty: number
}
```

**Validation**:
- `price` > 0
- `qty` > 0

**Usage**: Best bid/ask, wall detection

---

### 2.4 Depth Metrics

**Purpose**: Order book depth analysis.

**Schema**:
```typescript
interface DepthMetrics {
  top20_bid: Array<{p: number, q: number}>
  top20_ask: Array<{p: number, q: number}>
  sum_bid: number    // Total bid qty in top 20
  sum_ask: number    // Total ask qty in top 20
  imbalance: number  // [-1, 1] range
}
```

**Fields**:
- `top20_bid` (array, required): Top 20 bid levels
  - Length: Up to 20
  - Sorted: Descending by price
- `top20_ask` (array, required): Top 20 ask levels
  - Length: Up to 20
  - Sorted: Ascending by price
- `sum_bid` (float64, required): Sum of top 20 bid quantities
  - Validation: >= 0
- `sum_ask` (float64, required): Sum of top 20 ask quantities
  - Validation: >= 0
- `imbalance` (float64, required): Order book imbalance
  - Formula: `(sum_bid - sum_ask) / (sum_bid + sum_ask)`
  - Range: [-1, 1]
  - -1 = all asks, +1 = all bids, 0 = balanced

**Usage**: FR-009, FR-010

**Invariants**:
- `imbalance ∈ [-1, 1]`
- `sum_bid = Σ top20_bid[i].q`
- `sum_ask = Σ top20_ask[i].q`

---

### 2.5 Liquidity Analysis

**Purpose**: Advanced liquidity features (walls, vacuums, volume profile).

**Schema**:
```typescript
interface LiquidityAnalysis {
  walls: Array<LiquidityWall>
  vacuums: Array<LiquidityVacuum>
  profile: VolumeProfile
}
```

**Optional**: May be omitted in early MVP builds (Phase M3), required by M4.

---

### 2.6 Liquidity Wall

**Purpose**: Large concentrated order (potential support/resistance).

**Schema**:
```typescript
interface LiquidityWall {
  price: number
  qty: number
  side: "bid" | "ask"
  severity?: "low" | "medium" | "high"
}
```

**Detection Criteria** (FR-011):
- `qty >= max(P95 * 1.5, abs_min)`
- P95 = 95th percentile of quantities in rolling window
- abs_min = configurable (e.g., 25× median trade size)

**Usage**: LLM can identify potential price levels where large orders might halt movement

---

### 2.7 Liquidity Vacuum

**Purpose**: Thin liquidity region (high slippage risk).

**Schema**:
```typescript
interface LiquidityVacuum {
  from: number  // Start price
  to: number    // End price
  severity?: "low" | "medium" | "high"
}
```

**Detection Criteria** (FR-012):
- Depth over several ticks < threshold (P10 percentile)
- Merge adjacent thin regions

**Usage**: LLM can warn about slippage risk in these price ranges

---

### 2.8 Volume Profile

**Purpose**: Distribution of traded volume across price levels.

**Schema**:
```typescript
interface VolumeProfile {
  poc: number  // Point of Control (price with max volume)
  vah: number  // Value Area High (upper 70% volume boundary)
  val: number  // Value Area Low (lower 70% volume boundary)
}
```

**Calculation** (FR-013):
- Aggregate trade volume into price bins (width = tick × B, e.g., B=5)
- Rolling window: 30 minutes
- POC = bin with maximum volume
- VAH/VAL = boundaries covering 70% of volume around POC

**Usage**: Identify key price levels where most trading occurred

**Invariants**:
- `val <= poc <= vah`
- All values > 0

---

### 2.9 Flow Metrics

**Purpose**: Market activity intensity and directional pressure.

**Schema**:
```typescript
interface FlowMetrics {
  orders_per_sec: number  // Event rate
  net_flow: number        // Buy - sell volume
}
```

**Fields**:
- `orders_per_sec` (float64, required): Event processing rate
  - Calculation: Average events (trades + deltas) over last 10 seconds (FR-014)
  - Validation: >= 0
- `net_flow` (float64, required): Net buy/sell pressure
  - Calculation: Aggressive buy volume − sell volume over last 30 seconds (FR-015)
  - Validation: Any finite number (can be negative)
  - Positive = buying pressure, Negative = selling pressure

---

### 2.10 Anomaly

**Purpose**: Detected unusual market behavior pattern.

**Schema**:
```typescript
interface Anomaly {
  type: "spoofing" | "iceberg" | "flash_crash_risk"
  severity: "low" | "medium" | "high"
  note?: string  // Optional human-readable description
}
```

**Fields**:
- `type` (enum, required): Anomaly classification
  - `"spoofing"`: Large orders far from mid with high cancel rate (FR-016)
  - `"iceberg"`: Series of partial fills with stable visible depth (FR-017)
  - `"flash_crash_risk"`: Widening spread + thin book + negative flow (FR-018)
- `severity` (enum, required): Impact level
  - `"low"`: Informational, no immediate concern
  - `"medium"`: Worth monitoring
  - `"high"`: Significant market stress or manipulation signal
- `note` (string, optional): Additional context
  - Example: "Large bid wall at $64,000 cancelled 5 times in 30 seconds"

**Detection Logic**:
- Heuristic-based for MVP (not ML)
- Configurable thresholds per anomaly type
- Multiple anomalies can coexist in report

---

### 2.11 Health Score

**Purpose**: Overall market quality assessment.

**Schema**:
```typescript
interface HealthScore {
  score: number  // 0-100 integer
  components: {
    spread: number     // Contribution from spread tightness
    depth: number      // Contribution from depth adequacy
    balance: number    // Contribution from imbalance (lower = better)
    flow: number       // Contribution from activity level
    anomalies: number  // Penalty from detected anomalies
    freshness: number  // Contribution from data freshness
  }
}
```

**Calculation** (FR-019):
- Weighted sum of normalized components
- Weights: `{spread: 20%, depth: 25%, balance: 15%, flow: 15%, anomalies: 15%, freshness: 10%}`
- Each component normalized to [0, 100] range
- Final score: Integer in [0, 100]

**Interpretation**:
- 90-100: Excellent market quality
- 70-89: Good
- 50-69: Fair
- 30-49: Poor (caution advised)
- 0-29: Very poor (high risk)

**Usage**: LLM can provide high-level market quality assessment to users

---

## 3. Configuration Entities

### 3.1 System Configuration

**Purpose**: Runtime configuration loaded from environment variables (FR-031).

**Schema**:
```typescript
interface SystemConfig {
  // Redis
  redis_url: string
  redis_password?: string

  // Symbols
  symbols: Array<string>  // e.g., ["BTCUSDT", "ETHUSDT"]

  // Consumer
  consumer_group: string  // Default: "context8"
  stream_key: string      // Default: "nt:binance"

  // Performance Tuning
  cache_ttl_sec: number      // Default: 300 (5 minutes)
  report_window_sec: number  // Default: 1800 (30 minutes for volume profile)
  flow_window_sec: number    // Default: 30

  // Observability
  log_level: "debug" | "info" | "warn" | "error"
  prometheus_port: number  // Default: 9090

  // Thresholds (for anomaly detection)
  wall_threshold_multiplier: number  // Default: 1.5 (P95 × 1.5)
  vacuum_threshold_percentile: number  // Default: 10 (P10)
}
```

**Loading**:
- Loaded at service startup
- Validated before use
- Immutable during runtime (restart required for changes)

**Defaults**: See `research.md` configuration section

---

## 4. State Machines

### 4.1 Ingestion Status State Machine

```
┌──────┐
│  ok  │
└──┬───┘
   │ data_age > 1000ms for >2s
   ↓
┌──────────┐
│ degraded │←──┐
└──┬───────┘   │
   │           │ data received but still stale
   │           │
   ├───────────┤
   │ data_age > 5000ms
   ↓
┌──────┐
│ down │
└──┬───┘
   │ fresh data received (data_age <= 1000)
   └─→ ok
```

**Triggers**:
- `data_age_ms` calculated from `generated_at - ts_event` of most recent event
- Transitions checked on every report generation cycle

---

## 5. Data Flow Summary

```
Binance Exchange
    ↓ WebSocket/REST
NautilusTrader (Python)
    ↓ Publish JSON
Redis Streams: nt:binance
    ↓ XREADGROUP (consumer group: context8)
Go Analytics Service
    ↓ Calculate metrics
    ↓ Aggregate report
Redis KV: report:{symbol}
    ↓ GET
Go MCP Service
    ↓ HTTP JSON
LLM Client
```

**Data Transformations**:
1. **NT → Streams**: Raw exchange events → MarketEventEnvelope
2. **Streams → Analytics**: JSON events → Go structs (deserialization)
3. **Analytics → Cache**: Calculated metrics → MarketReport JSON
4. **Cache → MCP**: Cached JSON → HTTP response
5. **MCP → LLM**: HTTP JSON → LLM tool result

---

## 6. Validation Rules Summary

| Entity | Key Validation Rules |
|--------|---------------------|
| MarketEventEnvelope | type ∈ {trade_tick, order_book_depth, order_book_deltas, ticker_24h}, venue = "BINANCE", ts_event is RFC3339 UTC |
| TradeTick | price > 0, qty > 0, side ∈ {buy, sell} |
| OrderBookDepth | bids/asks length ≤ 20, all prices > 0, all qtys > 0, bids descending, asks ascending |
| OrderBookDeltas | prices > 0, qtys ≥ 0 (0 = delete) |
| Ticker24h | high_24h >= low_24h, volume_24h >= 0, all prices > 0 |
| MarketReport | data_age_ms >= 0, all required fields present, passes JSON schema validation |
| IngestionStatus | status ∈ {ok, degraded, down}, fresh = (data_age_ms <= 1000) |
| DepthMetrics | imbalance ∈ [-1, 1], sum_bid/sum_ask >= 0 |
| Anomaly | type ∈ {spoofing, iceberg, flash_crash_risk}, severity ∈ {low, medium, high} |
| HealthScore | score ∈ [0, 100], all component scores >= 0 |

---

## 7. Index & Query Patterns

### Redis Streams (nt:binance)
- **Consumer**: XREADGROUP with consumer group "context8"
- **Acknowledgment**: XACK after successful processing (idempotency via consumer group)
- **Retention**: Auto-trim messages older than 30-60 minutes (FR-035)

### Redis KV (reports)
- **Write**: `SET report:{symbol} <json> EX {ttl}`
- **Read**: `GET report:{symbol}`
- **Pattern match**: `KEYS report:*` (for debugging only, not in hot path)

---

## 8. Cross-References

| Entity | Spec References | Implementation Files |
|--------|----------------|---------------------|
| MarketEventEnvelope | FR-003 | `analytics/internal/models/events.go` |
| TradeTick | FR-002, FR-015 | `analytics/internal/models/events.go` |
| OrderBookDepth | FR-002, FR-006-FR-010 | `analytics/internal/models/events.go` |
| OrderBookDeltas | FR-002, FR-014 | `analytics/internal/models/events.go` |
| Ticker24h | FR-002, FR-005 | `analytics/internal/models/events.go` |
| MarketReport | FR-001, FR-029, SC-006 | `analytics/internal/models/report.go`, `mcp/internal/models/report.go` |
| IngestionStatus | FR-020, FR-021, User Story 5 | `analytics/internal/models/report.go` |
| DepthMetrics | FR-009, FR-010 | `analytics/internal/metrics/depth.go` |
| LiquidityWall | FR-011 | `analytics/internal/metrics/liquidity.go` |
| LiquidityVacuum | FR-012 | `analytics/internal/metrics/liquidity.go` |
| VolumeProfile | FR-013 | `analytics/internal/metrics/liquidity.go` |
| FlowMetrics | FR-014, FR-015 | `analytics/internal/metrics/flow.go` |
| Anomaly | FR-016, FR-017, FR-018 | `analytics/internal/metrics/anomalies.go` |
| HealthScore | FR-019 | `analytics/internal/metrics/health.go` |

---

**Data Model Status**: ✅ COMPLETE
**Next**: Generate JSON schemas in `contracts/` directory
