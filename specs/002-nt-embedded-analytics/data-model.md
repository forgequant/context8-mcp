# Data Model: Embedded Market Analytics

**Feature**: 002-nt-embedded-analytics
**Date**: 2025-10-28
**Purpose**: Define all entities, validation rules, and state transitions for distributed market analytics

---

## Entity 1: NodeMembership

### Purpose
Track active producer instances in Redis cluster for distributed coordination and symbol assignment.

### Fields

| Field | Type | Required | Description | Validation |
|-------|------|----------|-------------|------------|
| `node_id` | string | Yes | Unique identifier for producer instance | Non-empty, alphanumeric + hyphen/underscore |
| `hostname` | string | Yes | Server hostname for debugging | Non-empty |
| `pid` | int | Yes | Process ID on host | Positive integer |
| `started_at` | datetime | Yes | Node startup timestamp (UTC) | ISO8601 format, not future |
| `metrics_url` | string | Yes | Prometheus endpoint URL | Valid HTTP URL format |
| `last_heartbeat` | datetime | Yes | Last heartbeat timestamp (UTC) | ISO8601 format, within last 5 seconds |

### Storage

**Redis Key Pattern**: `nt:node:{node_id}`

**Value Format**: JSON
```json
{
  "node_id": "nt-prod-01",
  "hostname": "ip-10-0-1-42",
  "pid": 1234,
  "started_at": "2025-10-28T10:00:00Z",
  "metrics_url": "http://10.0.1.42:9101/metrics",
  "last_heartbeat": "2025-10-28T10:05:23Z"
}
```

**TTL**: 5 seconds (auto-expire if heartbeat stops)

### Operations

1. **Heartbeat (Create/Update)**
   - Command: `SET nt:node:{node_id} <json> EX 5`
   - Frequency: Every 1 second with jitter (±100ms to avoid thundering herd)
   - Side effect: `ZADD nt:nodes_seen <unix_ts> {node_id}` (backup tracking)

2. **Discovery (Read)**
   - Command: `SCAN 0 MATCH nt:node:* COUNT 100`
   - Frequency: Every rebalancing cycle (~1-5 seconds)
   - Filter: Parse JSON, check `last_heartbeat` within 5 seconds of current time

3. **Cleanup (Delete)**
   - Automatic: Redis expires key after 5 seconds without heartbeat
   - Manual: `DEL nt:node:{node_id}` on graceful shutdown

### Invariants

- `node_id` must be globally unique across all running instances
- `last_heartbeat` must be updated at least every 2 seconds to avoid expiration
- Backup ZSET `nt:nodes_seen` should be pruned (remove entries older than 10 seconds) on each heartbeat

### State Transitions

```
[Node Starts] → CREATE membership → [Active]
[Active] → UPDATE heartbeat (every 1s) → [Active]
[Active] → MISS 2 heartbeats → [Expired] (auto-delete by Redis)
[Active] → Graceful shutdown → DELETE membership → [Terminated]
```

---

## Entity 2: WriterLease

### Purpose
Exclusive write permission for symbol with fencing tokens to prevent split-brain scenarios and stale writer corruption.

### Fields

| Field | Type | Required | Description | Validation |
|-------|------|----------|-------------|------------|
| `symbol` | string | Yes | Trading pair (e.g., "BTCUSDT") | Uppercase, valid symbol format |
| `node_id` | string | Yes | Current lease holder | Must match active node ID |
| `acquired_at` | datetime | Yes | Lease acquisition timestamp (UTC) | ISO8601, not future |
| `expires_at` | datetime | Yes | Lease expiration timestamp (UTC) | acquired_at + ttl_ms |
| `token` | int | Yes | Monotonic fencing token | Positive, incrementing |

### Storage

**Redis Keys**:
1. `report:writer:{symbol}` - Lease ownership
   - Value: `node_id` (string)
   - Expiry: `PX ttl_ms` (milliseconds)

2. `report:writer:token:{symbol}` - Fencing token counter
   - Value: `int` (monotonically incrementing)
   - No expiry (persists across leases)

### Operations

1. **Acquire Lease**
   - Lua Script: `acquire_lease.lua`
   - Logic:
     ```lua
     local acquired = redis.call("SET", KEYS[1], ARGV[1], "PX", ARGV[2], "NX")
     if acquired then
         local token = redis.call("INCR", KEYS[2])
         return token
     else
         return nil
     end
     ```
   - Returns: `token` (int) if successful, `nil` if already held by another node

2. **Renew Lease**
   - Lua Script: `renew_lease.lua`
   - Frequency: Every `ttl_ms / 2` (e.g., every 1000ms for 2000ms TTL)
   - Logic: Conditional `PEXPIRE` only if current owner
   - Returns: `1` if renewed, `0` if ownership lost

3. **Release Lease**
   - Lua Script: `release_lease.lua`
   - Trigger: Symbol drop or graceful shutdown
   - Logic: Conditional `DEL` only if current owner
   - Returns: `1` if released, `0` if not owner

4. **Check Ownership**
   - Command: `GET report:writer:{symbol}`
   - Returns: `node_id` of current owner or `nil` if no lease

### Invariants

- At most one node holds write lease for a symbol at any time (enforced by Redis `SET NX`)
- Fencing token is strictly monotonically increasing (never decreases)
- Lease expiration must exceed max expected renewal interval + clock skew tolerance (recommended: ttl ≥ 2 × renewal_interval)
- Node losing lease (renewal fails) MUST immediately stop publishing for that symbol

### State Transitions

```
[Symbol Assigned] → ACQUIRE lease → [Active Writer]
[Active Writer] → RENEW lease (every ttl/2) → [Active Writer]
[Active Writer] → RENEW fails (lost ownership) → [Idle]
[Active Writer] → RELEASE lease → [Idle]
[Active Writer] → TTL expires (missed renewals) → [Expired] → another node ACQUIRE
```

### Fencing Token Usage

Every published report MUST include current token:
```json
{
  "writer": {
    "nodeId": "nt-prod-01",
    "writerToken": 42
  }
}
```

**Validation**: Consumer (MCP server) can detect stale reports by comparing tokens:
- If `writerToken` decreases → stale writer detected, ignore report
- If `writerToken` increases → new writer took over, accept report

---

## Entity 3: SymbolState

### Purpose
Per-symbol mutable state for real-time calculations, including order book, trade history, and statistical trackers.

### Fields

| Field | Type | Description | Max Size |
|-------|------|-------------|----------|
| `symbol` | string | Trading pair identifier | - |
| `order_book` | OrderBookL2 | Price→quantity maps + sorted top-N | 20 levels bid + 20 ask |
| `last_trade` | TradeTick | Most recent trade | Single object |
| `best_bid` | PriceQty | Best bid price and quantity | Single object |
| `best_ask` | PriceQty | Best ask price and quantity | Single object |
| `trade_buffer_10s` | RingBuffer[TradeTick] | For orders_per_sec calculation | ~1000 trades (high-frequency symbols) |
| `trade_buffer_30s` | RingBuffer[TradeTick] | For net_flow calculation | ~3000 trades |
| `trade_buffer_30min` | RingBuffer[TradeTick] | For volume profile | ~20,000 trades (30 min × ~10 trades/sec) |
| `quantity_history` | RingBuffer[float] | For P95/P10 percentiles | 10,000 samples |
| `last_event_ts` | datetime | Last market data event timestamp | Single timestamp |

### Sub-Structures

**OrderBookL2**:
```python
@dataclass
class OrderBookL2:
    bids: dict[float, float]  # price → quantity
    asks: dict[float, float]  # price → quantity
    top_bids: list[tuple[float, float]]  # Sorted descending by price (top 20)
    top_asks: list[tuple[float, float]]  # Sorted ascending by price (top 20)

    def update_bid(self, price: float, qty: float):
        if qty == 0:
            self.bids.pop(price, None)
        else:
            self.bids[price] = qty
        self._recompute_top()

    def _recompute_top(self):
        self.top_bids = sorted(self.bids.items(), reverse=True)[:20]
        self.top_asks = sorted(self.asks.items())[:20]
```

**TradeTick**:
```python
@dataclass
class TradeTick:
    timestamp: datetime  # UTC
    price: float
    volume: float  # Base currency quantity
    aggressor_side: str  # "BUY" or "SELL"
```

**PriceQty**:
```python
@dataclass
class PriceQty:
    price: float
    qty: float
```

**RingBuffer[T]**:
```python
from collections import deque

class RingBuffer:
    def __init__(self, max_size: int):
        self.buffer = deque(maxlen=max_size)  # Auto-discards oldest

    def append(self, item):
        self.buffer.append(item)

    def filter_by_time(self, cutoff: datetime) -> list:
        """Return items newer than cutoff."""
        return [item for item in self.buffer if item.timestamp > cutoff]

    def __len__(self):
        return len(self.buffer)
```

### Lifecycle

**Creation**: When symbol assigned to node (HRW + lease acquired)
```python
def on_symbol_acquired(symbol: str):
    self.symbol_states[symbol] = SymbolState(
        symbol=symbol,
        order_book=OrderBookL2(),
        trade_buffer_10s=RingBuffer(1000),
        trade_buffer_30s=RingBuffer(3000),
        trade_buffer_30min=RingBuffer(20000),
        quantity_history=RingBuffer(10000),
        last_event_ts=datetime.utcnow()
    )
```

**Updates**: On every market data callback (order book delta, trade tick)
```python
def on_order_book_delta(delta):
    state = self.symbol_states[delta.symbol]
    state.order_book.update_bid(delta.price, delta.qty)
    state.quantity_history.append(delta.qty)
    state.last_event_ts = delta.timestamp

def on_trade_tick(trade):
    state = self.symbol_states[trade.symbol]
    state.last_trade = trade
    state.trade_buffer_10s.append(trade)
    state.trade_buffer_30s.append(trade)
    state.trade_buffer_30min.append(trade)
    state.last_event_ts = trade.timestamp
```

**Destruction**: When symbol dropped (lease lost or node shutdown)
```python
def on_symbol_dropped(symbol: str):
    del self.symbol_states[symbol]
```

### Invariants

- Order book: `best_bid.price < best_ask.price` (no crossed book)
- Ring buffers never exceed `max_size` (auto-discard oldest)
- `quantity_history` only stores positive non-zero quantities
- `last_event_ts` monotonically increases (within reasonable clock skew tolerance)

### Memory Estimation

Per symbol:
- OrderBookL2: ~8 KB (20 bids + 20 asks × ~200 bytes per entry)
- Trade buffers: ~1 MB (20,000 trades × ~50 bytes)
- Quantity history: ~80 KB (10,000 floats × 8 bytes)
- **Total**: ~1.1 MB per symbol

For 15 symbols: ~16 MB (acceptable)

---

## Entity 4: MarketReport (Extended)

### Purpose
Complete market snapshot for LLM consumption with distributed coordination metadata.

### New Fields (v1.1)

| Field | Type | Required | Description | Validation |
|-------|------|----------|-------------|------------|
| `schemaVersion` | string | Yes | Report schema version | Must be "1.1" |
| `writer.nodeId` | string | Yes | Producer that generated report | Non-empty, matches active node |
| `writer.writerToken` | int | Yes | Fencing token from lease | Positive, monotonically increasing |
| `updatedAt` | int64 | Yes | Report timestamp (ms since epoch) | Positive, not future |

### Existing Fields (v1.0 - Unchanged)

*(From Constitution Principle 6)*

**Identification**: `symbol`, `venue`, `generated_at`, `data_age_ms`, `ingestion.status`

**24h Statistics**: `last_price`, `change_24h_pct`, `high_24h`, `low_24h`, `volume_24h`

**L1/Spread**: `best_bid`, `best_ask`, `spread_bps`, `mid_price`, `micro_price`

**Depth**: `depth.bids[]`, `depth.asks[]`, `depth.total_bid_qty`, `depth.total_ask_qty`, `depth.imbalance`

**Flow**: `flow.orders_per_sec`, `flow.net_flow`

**Liquidity**: `liquidity.walls[]`, `liquidity.vacuums[]`, `liquidity.volume_profile`

**Anomalies**: `anomalies[]`

**Health**: `health.score`, `health.components[]`

### Full Schema Example

```json
{
  "schemaVersion": "1.1",
  "writer": {
    "nodeId": "nt-prod-01",
    "writerToken": 42
  },
  "updatedAt": 1730112345678,

  "symbol": "BTCUSDT",
  "venue": "BINANCE",
  "generated_at": "2025-10-28T10:05:45.678Z",
  "data_age_ms": 234,

  "ingestion": {
    "status": "ok",
    "last_update": "2025-10-28T10:05:45.444Z"
  },

  "last_price": 64105.50,
  "change_24h_pct": 2.34,
  "high_24h": 65000.00,
  "low_24h": 62500.00,
  "volume_24h": 45000.25,

  "best_bid": {"price": 64100.00, "qty": 2.5},
  "best_ask": {"price": 64110.00, "qty": 1.2},
  "spread_bps": 1.5608,
  "mid_price": 64105.00,
  "micro_price": 64106.7568,

  "depth": {
    "bids": [
      {"price": 64100.00, "qty": 2.5},
      {"price": 64095.00, "qty": 1.8}
    ],
    "asks": [
      {"price": 64110.00, "qty": 1.2},
      {"price": 64115.00, "qty": 3.0}
    ],
    "total_bid_qty": 42.5,
    "total_ask_qty": 38.2,
    "imbalance": 0.0533
  },

  "flow": {
    "orders_per_sec": 4.7,
    "net_flow": -0.1
  },

  "liquidity": {
    "walls": [
      {
        "side": "bid",
        "price": 64000.00,
        "qty": 25.0,
        "severity": "medium"
      }
    ],
    "vacuums": [
      {
        "from": 64105.00,
        "to": 64115.00,
        "severity": "low"
      }
    ],
    "volume_profile": {
      "POC": 64107.50,
      "VAH": 64120.00,
      "VAL": 63995.00,
      "window_sec": 1800,
      "trade_count": 1523
    }
  },

  "anomalies": [
    {
      "type": "spoofing",
      "severity": "medium",
      "note": "Large bid at $63,500 with 80% cancel rate"
    }
  ],

  "health": {
    "score": 85,
    "components": [
      {"metric": "spread", "score": 90},
      {"metric": "depth", "score": 85},
      {"metric": "freshness", "score": 95},
      {"metric": "anomalies", "score": 70}
    ]
  }
}
```

### Storage

**Redis Key**: `report:{symbol}`
**Value**: JSON (above schema)
**TTL**: 300 seconds (5 minutes, configurable)

**Update Strategy**: `SET report:{symbol} <json> KEEPTTL` (preserves existing TTL on updates)

**Splitting for Large Payloads**: If JSON > 256KB, split heavy sections:
- Main report: Fast-cycle fields + references
- Heavy report: `report:{symbol}:heavy` with full depth, trade history, etc.

### Invariants

- `schemaVersion` must be "1.1" for this feature
- `writer.writerToken` must never decrease (stale writer detection)
- `data_age_ms` = `(updatedAt - ingestion.last_update)` must be ≤ 1000ms for "ok" status
- Volume profile: `VAL ≤ POC ≤ VAH` (if present)
- Imbalance: `-1.0 ≤ imbalance ≤ 1.0`
- Spread: `spread_bps ≥ 0`, `best_bid.price < best_ask.price`

---

## Entity 5-8: Supporting Data Structures

### Entity 5: VolumeProfile

```python
@dataclass
class VolumeProfile:
    POC: float  # Point of Control - price with max volume
    VAH: float  # Value Area High - upper 70% boundary
    VAL: float  # Value Area Low - lower 70% boundary
    window_sec: int  # Window size (e.g., 1800 for 30 min)
    trade_count: int  # Number of trades in calculation

    def validate(self):
        assert self.VAL <= self.POC <= self.VAH, "Volume profile invariant violated"
        assert self.trade_count >= 10, "Insufficient trades for valid profile"
```

### Entity 6: LiquidityWall

```python
@dataclass
class LiquidityWall:
    side: str  # "bid" or "ask"
    price: float
    qty: float
    severity: str  # "low" | "medium" | "high"

    def validate(self):
        assert self.side in ("bid", "ask")
        assert self.severity in ("low", "medium", "high")
        assert self.qty > 0
```

### Entity 7: LiquidityVacuum

```python
@dataclass
class LiquidityVacuum:
    from_price: float  # Start of vacuum
    to_price: float  # End of vacuum
    severity: str  # "low" | "medium" | "high"

    def validate(self):
        assert self.from_price < self.to_price, "Vacuum price range invalid"
        assert self.severity in ("low", "medium", "high")
```

### Entity 8: Anomaly

```python
@dataclass
class Anomaly:
    type: str  # "spoofing" | "iceberg" | "flash_crash_risk"
    severity: str  # "low" | "medium" | "high"
    note: str  # Human-readable description

    def validate(self):
        assert self.type in ("spoofing", "iceberg", "flash_crash_risk")
        assert self.severity in ("low", "medium", "high")
        assert len(self.note) > 0, "Anomaly note must be non-empty"
```

---

## Relationships

```
NodeMembership ──(discovers)──> NodeMembership[]  (cluster members)
       │
       │ (acquires)
       ↓
WriterLease ──(grants write to)──> Symbol
       │
       │ (token included in)
       ↓
MarketReport
       ↑
       │ (generated from)
       │
SymbolState ──(contains)──> OrderBookL2, TradeTick[], RingBuffer[]
       │
       │ (produces)
       ↓
VolumeProfile, LiquidityWall[], LiquidityVacuum[], Anomaly[]
```

---

## State Machine: Symbol Assignment Lifecycle

```
                    ┌──────────────┐
                    │   IDLE       │  (No assignment)
                    └──────┬───────┘
                           │ HRW assigns symbol to node
                           ↓
                    ┌──────────────┐
                    │ ACQUIRING    │  (Lease acquisition in progress)
                    └──────┬───────┘
                           │ Success
                           ↓
    ┌───────────────┬──────────────┬────────────────┐
    │               │              │                │
    │ Renew fails   │ ACTIVE       │  Grace period  │
    │               │              │                │
    └───────────────┴──────┬───────┴────────────────┘
                           │ (Publishing reports)
                           │
      ┌────────────────────┼────────────────────┐
      │ Lease lost         │ Lease expires      │ Graceful stop
      ↓                    ↓                    ↓
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ RELEASING    │    │ EXPIRED      │    │ STOPPING     │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       └───────────────────┴───────────────────┘
                           │
                           ↓
                    ┌──────────────┐
                    │   IDLE       │
                    └──────────────┘
```

**State Actions**:
- **ACQUIRING**: Execute `acquire_lease.lua`, subscribe to exchange data
- **ACTIVE**: Renew lease every ttl/2, publish reports via fast/slow cycles
- **RELEASING**: Stop publishing, execute `release_lease.lua`, unsubscribe
- **EXPIRED**: Emergency cleanup, unsubscribe immediately (lease already gone)
- **STOPPING**: Graceful shutdown sequence (release → unsubscribe → cleanup)

---

## Validation Rules Summary

| Entity | Key Invariants |
|--------|----------------|
| NodeMembership | Unique node_id, heartbeat every 1-2s, max 5s without update |
| WriterLease | At most one owner per symbol, token monotonic, renew < ttl/2 |
| SymbolState | No crossed book (bid < ask), ring buffers bounded, last_event_ts monotonic |
| MarketReport | Schema v1.1, token never decreases, data_age ≤ 1000ms for "ok" status |
| VolumeProfile | VAL ≤ POC ≤ VAH, min 10 trades |
| LiquidityWall | qty > 0, severity valid |
| LiquidityVacuum | from < to, severity valid |
| Anomaly | type/severity valid, note non-empty |

---

## Performance Characteristics

| Entity | Memory (per instance) | Update Frequency | Critical Path |
|--------|----------------------|------------------|---------------|
| NodeMembership | ~500 bytes | 1/sec | No (background) |
| WriterLease | ~100 bytes | 2/sec (renewal) | Yes (blocks publishing) |
| SymbolState | ~1.1 MB | 10-100/sec | Yes (hot path) |
| MarketReport | ~50-100 KB | 4-10/sec | Yes (hot path) |
| VolumeProfile | ~500 bytes | 0.5-1/sec | No (slow cycle) |

**Total Memory** (15 symbols): ~20 MB state + ~5 MB reports = **25 MB** (acceptable for single instance)

---

**Next Steps**: Proceed to contracts/report-schema-v1.1.json (JSON Schema specification)
