# Implementation Plan: Embedded Market Analytics in NautilusTrader

**Branch**: `002-nt-embedded-analytics` | **Date**: 2025-10-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/002-nt-embedded-analytics/spec.md`

## Summary

This feature fundamentally restructures the system architecture by consolidating market analytics calculations (spread, depth, flow, liquidity features, anomalies) directly into the NautilusTrader producer service, replacing the separate Go analytics layer. Multiple producer instances will coordinate through Redis-based distributed membership, HRW consistent hashing for symbol assignment, and writer leases with fencing tokens to ensure exactly-once report generation semantics. Reports publish directly to Redis KV at 4-10 Hz (fast cycle) with advanced analytics enrichment at 0.2-1 Hz (slow cycle).

**Architectural Impact**: This represents a significant deviation from Constitution Principle 1 (Layered EDA) by collapsing Ingestion + Analytics layers into a single component.

## Technical Context

**Language/Version**: Python 3.11+ (NautilusTrader requirement), Go 1.24+ (MCP server unchanged)
**Primary Dependencies**:
- NautilusTrader (current stable) with Binance adapter
- redis-py 5.x for distributed coordination and KV operations
- numpy 1.24+ for percentile calculations and array operations
- prometheus-client 0.19+ for metrics exposition
- xxhash 3.x or hashlib (blake2b) for HRW consistent hashing

**Storage**: Redis 7.x (KV for reports + membership, optionally Streams for raw events if NT_ENABLE_STREAMS=true)
**Testing**: pytest 7.x with pytest-asyncio for async tests, property-based testing via Hypothesis
**Target Platform**: Docker containers on Linux (Ubuntu 22.04 base), single/multi-instance deployment
**Project Type**: Distributed event-processing system with horizontal scalability
**Performance Goals**:
- Fast-cycle calculations complete within 20ms p99 (L1/L2/flow/health)
- Slow-cycle calculations complete within 500ms p99 (volume profile, liquidity, anomalies)
- Report publish rate 4-10 Hz per symbol (250-100ms period)
- Symbol reassignment (failover) completes within 2 seconds (lease_ttl + heartbeat_interval)

**Constraints**:
- Data freshness: P95 data_age_ms ≤ 1000ms across all symbols
- Single producer instance capacity: 10-15 symbols max (CPU/memory bound)
- Redis SET operation latency: <10ms p99 for report publishing
- Binance WebSocket rate limits: 300 connections/IP, 1024 streams/connection
- Report JSON payload: <100KB typical, <256KB hard limit (split to heavy keys if exceeded)

**Scale/Scope**:
- MVP: 2-5 symbols, single instance
- Growth: 10-30 symbols, 2-3 instances with sharding
- Production: 100+ symbols, 7-10 instances with automatic rebalancing

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Architecture Compliance (Principle 1) ⚠️ **MAJOR DEVIATION**
- [ ] **VIOLATED**: Feature collapses Ingestion → Analytics layers into single NautilusTrader component
- [ ] **VIOLATED**: Removes Redis Streams as primary event transport (becomes optional)
- [ ] **VIOLATED**: Analytics calculations no longer in separate Go service

**Justification (see Complexity Tracking)**:
- Reduces latency by 100-150ms (eliminates serialize → stream → deserialize path)
- Simplifies deployment (one less service to orchestrate)
- Enables code reuse for backtesting (same Python calculations in production and research)
- Maintains separation of concerns via MCP read-only layer (still separate)

### Message Bus Contract (Principle 2) ⚠️ **CONDITIONAL COMPLIANCE**
- [x] Events published to Redis Streams are JSON with `snake_case` (if NT_ENABLE_STREAMS=true)
- [x] Mandatory fields present in stream events when feature flag enabled
- [ ] **MODIFIED**: Primary data path bypasses Redis Streams (calculations consume Nautilus internals directly)

**Justification**: Raw event streaming becomes optional for backward compatibility. Internal calculations operate on NautilusTrader's native data structures (OrderBook objects, Trade ticks) for performance.

### Idempotency & Time (Principle 3) ✅ **COMPLIANT**
- [x] Report generation is idempotent (recalculating with same inputs produces same output within rounding tolerance)
- [x] All timestamps in UTC, converted at Binance adapter boundary
- [x] Fencing tokens prevent stale writers from corrupting reports after lease expiration

### Technology Stack (Principle 4) ⚠️ **PARTIAL DEVIATION**
- [ ] **VIOLATED**: Analytics logic now in Python 3.11+ (not Go ≥ 1.24)
- [x] MCP server remains Go 1.24+ (read-only API layer unchanged)
- [x] Python dependencies locked via `pyproject.toml` + `uv.lock` (using uv instead of poetry)

**Justification**: Python chosen for:
- Nautilus Trader framework native language (access to internal order book state, indicators)
- NumPy/SciPy ecosystem for percentile/statistical calculations
- Code reuse with backtesting/research (same metrics in production and notebooks)
- Acceptable performance for 10-15 symbols per instance (CPU not bottleneck until 50+ symbols)

### Report Contract (Principle 6) ✅ **COMPLIANT**
- [x] Report includes all mandatory fields (identification, 24h stats, L1/spread, depth, liquidity, flows, anomalies, health)
- [x] Adds schema metadata: `schemaVersion`, `writer {nodeId, writerToken}`, `updatedAt`
- [x] Calculation formulas will be documented in `/docs/metrics.md` (porting from existing Go implementation)
- [x] `report_version` follows semantic versioning (currently "1.0")

### SLO Compliance (Principle 7) ✅ **COMPLIANT WITH ENHANCEMENTS**
- [x] Fast-cycle design supports `data_age_ms ≤ 1000` (250ms publish period with 20ms calc latency)
- [x] Report generation ≤ 250ms (direct calculation + Redis SET, no stream overhead)
- [x] Graceful degradation: ingestion status transitions (ok → degraded → down) based on data staleness

### Security (Principle 8) ✅ **COMPLIANT**
- [x] Binance API keys in `.env` only (NautilusTrader already handles this correctly)
- [x] MCP endpoints unchanged (read-only, cache-sourced)
- [x] Binance ToS compliance maintained (no redistribution, same data sources)

### Quality & Testing (Principle 9) ✅ **COMPLIANT**
- [x] Unit tests for calculation functions (spread, depth, flow, liquidity, anomalies)
- [x] Property-based tests planned (Hypothesis framework) for metric invariants
- [x] MCP contract tests unchanged (existing test suite continues to validate schema/timeout)
- [x] JSON schemas preserved (report schema extended with writer metadata)

### Reference-First Development (Principle 10) ✅ **COMPLIANT**
- [x] Will consult `.refs/nautilus_trader/` for NautilusTrader Strategy patterns, order book access
- [x] Will consult `.refs/go-redis/` for Lua scripts (lease acquisition, heartbeat patterns) even though implementing in Python
- [x] Will consult `.refs/spoof.io/` for market microstructure algorithms (spoofing detection, volume profile)
- [x] Deviations documented (e.g., Python redis-py vs go-redis, but same Redis commands)

### Observability (Principle 11) ✅ **COMPLIANT**
- [x] Structured JSON logging with mandatory fields: `component`, `symbol`, `lag_ms`, `node_id`
- [x] Prometheus metrics endpoint on configurable port (NT_METRICS_PORT=9101)
- [x] New metrics added: `nt_node_heartbeat`, `nt_symbols_assigned`, `nt_lease_conflicts_total`, `nt_hrw_rebalances_total`

### MCP Contract (Principle 13) ✅ **UNCHANGED**
- [x] MCP method signature unchanged: `get_report(symbol: string) -> ReportJSON | null`
- [x] Response still sourced from Redis cache (producer writes, MCP reads)
- [x] Timeout ≤ 150 ms enforced (no changes to MCP service)

---

**Constitution Gate Status**: ⚠️ **CONDITIONAL PASS WITH JUSTIFICATIONS**

Three major deviations require explicit justification and documentation:
1. **Architecture layer collapse** (Ingestion + Analytics merged)
2. **Technology shift** (Analytics from Go to Python)
3. **Optional event streaming** (Redis Streams no longer primary transport)

All deviations justified by latency reduction, operational simplicity, and code reuse goals. MCP contract and data quality guarantees preserved. Proceed to Phase 0 with architectural amendment documented.

## Project Structure

### Documentation (this feature)

```text
specs/002-nt-embedded-analytics/
├── plan.md              # This file (/speckit.plan output)
├── research.md          # Phase 0: HRW algorithm, Lua scripts, percentile methods
├── data-model.md        # Phase 1: SymbolState, NodeMembership, WriterLease entities
├── quickstart.md        # Phase 1: Local deployment with 2 symbols, failover demo
├── contracts/           # Phase 1: Report schema v1.1 (adds writer metadata)
│   └── report-schema-v1.1.json
├── checklists/          # Generated by other commands
└── tasks.md             # Phase 2: /speckit.tasks output (NOT created here)
```

### Source Code (repository root)

**Current Structure** (before this feature):
```text
producer/                 # Python: NautilusTrader ingestion
├── src/
│   ├── main.py           # Entry point, TradingNode setup
│   ├── config.py         # Environment config
│   ├── redis_publisher.py  # Publishes to Redis Streams
│   └── simple_producer.py  # Binance WebSocket producer
├── tests/
└── pyproject.toml

analytics/                # Go: Event processing, metric calculation
├── internal/
│   ├── consumer/
│   ├── metrics/          # spread.go, depth.go, flow.go, liquidity.go, anomalies.go
│   ├── aggregator/
│   └── models/
└── cmd/server/

mcp/                      # Go: Read-only API
├── internal/
│   ├── handlers/
│   └── cache/
└── cmd/server/
```

**Modified Structure** (this feature):
```text
producer/                 # Python: EXPANDED with analytics
├── src/
│   ├── main.py           # MODIFIED: Adds AnalyticsStrategy, coordinator
│   ├── config.py         # EXPANDED: New env vars (NT_ENABLE_KV_REPORTS, NT_LEASE_TTL_MS, etc.)
│   ├── redis_publisher.py  # MODIFIED: Optionally publishes to Streams (NT_ENABLE_STREAMS flag)
│   │
│   ├── coordinator/      # NEW: Distributed membership & symbol assignment
│   │   ├── membership.py     # Heartbeat, node discovery (SCAN nt:node:*)
│   │   ├── hrw_sharding.py   # HRW consistent hashing with hysteresis
│   │   ├── lease_manager.py  # Writer lease acquisition/renewal/release
│   │   └── assignment.py     # Symbol→node assignment controller
│   │
│   ├── calculators/      # NEW: Market analytics (ported from Go)
│   │   ├── spread.py         # spread_bps, mid_price, micro_price
│   │   ├── depth.py          # imbalance, sum_bid/ask
│   │   ├── flow.py           # orders_per_sec, net_flow (rolling windows)
│   │   ├── liquidity.py      # walls, vacuums, volume profile
│   │   ├── anomalies.py      # spoofing, iceberg, flash crash risk
│   │   └── health.py         # composite health score
│   │
│   ├── state/            # NEW: Per-symbol calculation state
│   │   ├── symbol_state.py   # Order book, trade buffers, percentile trackers
│   │   └── ring_buffer.py    # Fixed-size circular buffer for windowed data
│   │
│   ├── reporters/        # NEW: Report generation & publishing
│   │   ├── fast_cycle.py     # L1/L2/flow/health every 100-250ms
│   │   ├── slow_cycle.py     # Volume profile, liquidity, anomalies every 1-5s
│   │   └── redis_cache.py    # SET report:{symbol} with KEEPTTL
│   │
│   └── metrics/          # NEW: Prometheus metrics
│       └── prometheus.py     # Metrics exposition on :9101
│
├── lua/                  # NEW: Redis Lua scripts
│   ├── acquire_lease.lua     # SET NX PX + INCR token
│   ├── renew_lease.lua       # Conditional PEXPIRE
│   └── release_lease.lua     # Conditional DEL
│
├── tests/
│   ├── unit/             # Calculation logic, HRW properties
│   ├── integration/      # Single-instance w/ real Binance testnet
│   └── system/           # Multi-instance coordination, failover
│
└── pyproject.toml        # UPDATED: Add redis, numpy, prometheus-client, xxhash

analytics/                # DEPRECATED (kept for parallel testing)
└── [existing structure]  # Will run side-by-side for 1-2 weeks, then removed

mcp/                      # UNCHANGED
└── [existing structure]  # Continues reading from Redis report:{symbol}
```

**Structure Decision**:
Expand `producer/` with new coordinator, calculators, state, reporters, and metrics modules. This maintains separation of concerns within the monolithic service:
- `coordinator/`: Distributed system logic (membership, sharding, leases)
- `calculators/`: Pure calculation functions (testable, reusable)
- `state/`: Per-symbol mutable state management
- `reporters/`: Publication orchestration (cycles, Redis writes)

Analytics Go service kept temporarily for parallel testing, then removed after parity validated.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| **Architecture: Ingestion + Analytics merged** | 1. Latency reduction: Eliminates 100-150ms serialize→stream→deserialize overhead, critical for <1000ms data_age_ms SLO. 2. Operational simplicity: One less service to deploy/monitor/troubleshoot. 3. Code reuse: Same Python calculations in production, backtesting, and research notebooks. | **Rejected: Keep Go analytics separate** - Adds latency that violates freshness SLO. Go/Python impedance mismatch forces duplication of calculation logic for backtesting. Operational overhead of managing separate service not justified for 2-30 symbol scale. |
| **Technology: Analytics in Python vs Go** | 1. Nautilus Trader integration: Direct access to order book objects, trade ticks, without serialization. 2. Scientific ecosystem: NumPy for percentile calculations, SciPy for statistical tests, Hypothesis for property testing. 3. Development velocity: Quants/researchers can modify metrics without learning Go. | **Rejected: Rewrite Nautilus in Go** - Massive effort, loses battle-tested Binance adapter. **Rejected: Keep calculations in Go, call from Python** - IPC overhead negates latency benefits, adds complexity. |
| **Optional Redis Streams** | 1. Performance: Direct calculation on Nautilus events faster than publishing→consuming cycle. 2. Backward compatibility: Feature flag (NT_ENABLE_STREAMS) allows gradual migration, parallel testing with existing Go analytics. | **Rejected: Always publish to Streams** - Adds unnecessary latency and Redis load when analytics runs in same process. **Rejected: Remove Streams entirely** - Breaks parallel testing and rollback safety during migration. |
| **Distributed coordination complexity** | 1. Horizontal scalability: Required for 100+ symbols (single instance maxes out at 10-15 symbols). 2. High availability: <2s failover ensures continuous data delivery during node crashes/restarts. 3. Exactly-once semantics: Fencing tokens prevent duplicate/stale writers from corrupting reports. | **Rejected: Single instance only** - Cannot scale beyond 15 symbols, single point of failure. **Rejected: Load balancer without coordination** - Risk of duplicate writes, no failover mechanism. **Rejected: External coordinator (Consul/etcd)** - Adds operational dependency, overkill for Redis-based system. |

---

## Phase 0: Research & Decision Making

**Prerequisites**: None (first phase)
**Outcome**: `research.md` with all technical unknowns resolved

### Research Tasks

1. **HRW Consistent Hashing Implementation**
   - **Unknown**: Best Python library for HRW (Rendezvous hashing) with hysteresis support
   - **Research**: Compare xxhash vs hashlib.blake2b for hash function performance and collision properties
   - **Reference**: Check `.refs/` for any distributed hashing examples
   - **Output**: Decision on hash library + hysteresis algorithm (sticky weight calculation)

2. **Redis Lua Scripts for Lease Management**
   - **Unknown**: Optimal Lua script structure for acquire/renew/release operations
   - **Research**: redis-py `Script` class usage, script caching, error handling patterns
   - **Reference**: `.refs/go-redis/` for Lua script examples (port patterns to Python)
   - **Output**: Lua script templates with fencing token increment, conditional operations

3. **Percentile Calculation Methods**
   - **Unknown**: NumPy percentile vs manual interpolation for P95/P10 in rolling windows
   - **Research**: Benchmark `np.percentile` with interpolation='linear' vs custom implementation
   - **Reference**: `.refs/spoof.io/` may have statistical calculations
   - **Output**: Decision on percentile method + expected performance characteristics

4. **Volume Profile Binning Strategy**
   - **Unknown**: Optimal bin width calculation for 30-minute rolling window
   - **Research**: Market microstructure literature (point-and-figure charts, Market Profile®)
   - **Reference**: `.refs/spoof.io/ppo/` or `.refs/nautilus_trader/` examples
   - **Output**: Bin size formula (e.g., based on ATR, tick size, or fixed percentage)

5. **NautilusTrader Strategy Lifecycle**
   - **Unknown**: Correct hooks for fast-cycle (100-250ms) and slow-cycle (1-5s) execution
   - **Research**: NautilusTrader `Strategy` class: `on_start`, `on_stop`, timer APIs, async support
   - **Reference**: `.refs/nautilus_trader/examples/` sandbox strategies
   - **Output**: Timer-based callback pattern + recommended timer library (asyncio.Timer?)

6. **Prometheus Metrics in Python**
   - **Unknown**: Best practices for prometheus-client in long-running async process
   - **Research**: Metrics registry patterns, histogram bucket configuration, async exposition
   - **Reference**: Search `.refs/` for Prometheus examples
   - **Output**: Metrics setup pattern + recommended bucket boundaries for latency histograms

7. **Redis Connection Pooling**
   - **Unknown**: redis-py connection pool sizing for heartbeat + lease + report publishing
   - **Research**: ConnectionPool parameters (max_connections, timeouts), pipeline usage
   - **Reference**: `.refs/go-redis/` patterns (port concepts to redis-py)
   - **Output**: Connection pool configuration + retry/backoff strategy

8. **Chaos Testing Approaches**
   - **Unknown**: Tools for simulating network partitions, clock skew, Redis failover in test environment
   - **Research**: Pytest fixtures for chaos scenarios, Docker network manipulation
   - **Reference**: General distributed systems testing patterns
   - **Output**: Test harness design for chaos scenarios (flapping, partitions, clock skew)

### Research Deliverables

Create `research.md` with structured decisions:
- **Decision**: What was chosen (library, algorithm, pattern)
- **Rationale**: Why this choice (performance, simplicity, reference alignment)
- **Alternatives Considered**: What else was evaluated and why rejected
- **Implementation Guidance**: Key code snippets or patterns to follow

---

## Phase 1: Design & Contracts

**Prerequisites**: `research.md` complete, all NEEDS CLARIFICATION resolved
**Outcome**: `data-model.md`, `contracts/`, `quickstart.md`, updated agent context

### Data Model (`data-model.md`)

Extract entities from spec + research decisions:

1. **NodeMembership**
   - Purpose: Track active producer instances in Redis
   - Fields:
     - `node_id`: string (unique identifier, from NT_NODE_ID or generated)
     - `hostname`: string (for debugging)
     - `pid`: int (process ID)
     - `started_at`: datetime (UTC, node boot time)
     - `metrics_url`: string (Prometheus endpoint URL)
     - `last_heartbeat`: datetime (UTC, updated every ~1s)
   - Redis Key: `nt:node:{node_id}`
   - Expiration: 5 seconds (auto-expire if heartbeat stops)
   - Operations: SET with EX on heartbeat, SCAN for discovery, ZADD to backup ZSET

2. **WriterLease**
   - Purpose: Exclusive write permission for symbol with fencing
   - Fields:
     - `symbol`: string (trading pair, e.g., "BTCUSDT")
     - `node_id`: string (current lease holder)
     - `acquired_at`: datetime (UTC, lease grant time)
     - `expires_at`: datetime (UTC, calculated from TTL)
     - `token`: int (monotonic fencing token, from `report:writer:token:{symbol}`)
   - Redis Keys:
     - `report:writer:{symbol}`: Lease holder (value: node_id, PX: ttl_ms)
     - `report:writer:token:{symbol}`: Fencing token counter (incremented on each acquisition)
   - Operations: SET NX PX (acquire), PEXPIRE (renew), DEL (release), INCR (token bump)

3. **SymbolState**
   - Purpose: Per-symbol mutable state for calculations
   - Fields:
     - `symbol`: string
     - `order_book`: OrderBookL2 (price→qty maps for bids/asks + sorted top-N)
     - `last_trade`: TradeTick (most recent trade)
     - `best_bid`: PriceQty
     - `best_ask`: PriceQty
     - `trade_buffer_10s`: RingBuffer[TradeTick] (for orders_per_sec)
     - `trade_buffer_30s`: RingBuffer[TradeTick] (for net_flow)
     - `trade_buffer_30min`: RingBuffer[TradeTick] (for volume profile)
     - `quantity_history`: RingBuffer[float] (10K samples for P95/P10)
     - `last_event_ts`: datetime (UTC, for data_age_ms calculation)
   - Lifecycle: Created on symbol acquisition, destroyed on symbol drop
   - Validation: Order book invariant (best_bid < best_ask), quantity_history bounded size

4. **MarketReport** (extended from existing schema)
   - Purpose: Complete market snapshot for LLM consumption
   - New Top-Level Fields (this feature):
     - `schemaVersion`: string (e.g., "1.1" - adds writer metadata)
     - `writer`: object
       - `nodeId`: string (producer that generated report)
       - `writerToken`: int (fencing token from lease)
     - `updatedAt`: int64 (milliseconds since epoch, UTC)
   - Existing Fields (unchanged): symbol, venue, generated_at, data_age_ms, ingestion, last_price, change_24h_pct, high_24h, low_24h, volume_24h, best_bid, best_ask, spread_bps, mid_price, micro_price, depth, flow, liquidity, anomalies, health
   - Redis Key: `report:{symbol}`
   - TTL: 300 seconds (5 minutes, configurable)
   - Validation: All mandatory fields present, invariants hold (VAL ≤ POC ≤ VAH if volume profile present)

5. **VolumeProfile**
   - Purpose: Price distribution analysis over time window
   - Fields:
     - `POC`: float (Point of Control - price with max volume)
     - `VAH`: float (Value Area High - upper 70% volume boundary)
     - `VAL`: float (Value Area Low - lower 70% volume boundary)
     - `window_sec`: int (trade history window used, e.g., 1800 for 30min)
     - `trade_count`: int (number of trades in window)
   - Invariant: VAL ≤ POC ≤ VAH (enforced in calculation, omit field if insufficient data)

6. **LiquidityWall**
   - Purpose: Large concentrated order detection
   - Fields:
     - `side`: enum ("bid" | "ask")
     - `price`: float (level price)
     - `qty`: float (order quantity)
     - `severity`: enum ("low" | "medium" | "high")
   - Threshold: qty >= P95 × 1.5 (configurable multiplier)
   - Severity: Based on multiple of threshold (≥3.0=high, ≥2.0=medium, ≥1.0=low)

7. **LiquidityVacuum**
   - Purpose: Thin liquidity region detection
   - Fields:
     - `from`: float (start price of vacuum)
     - `to`: float (end price of vacuum)
     - `severity`: enum ("low" | "medium" | "high")
   - Detection: 3+ consecutive levels < P10 threshold
   - Severity: Based on consecutive thin levels (≥10=high, ≥6=medium, ≥3=low)

8. **Anomaly**
   - Purpose: Suspicious market behavior alert
   - Fields:
     - `type`: enum ("spoofing" | "iceberg" | "flash_crash_risk")
     - `severity`: enum ("low" | "medium" | "high")
     - `note`: string (human-readable description with key metrics)
   - Detection Criteria:
     - Spoofing: Cancel rate ≥ 70% on large far-from-mid orders
     - Iceberg: ≥5 fills at same price with stable visible depth (±10%)
     - Flash crash risk: ≥2 of 3 signals (spread widening, thin book, negative flow acceleration)

### API Contracts (`contracts/`)

**File**: `contracts/report-schema-v1.1.json` (extends existing v1.0)

Additions to existing schema:
```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "MarketReport v1.1",
  "description": "Extended with writer metadata for distributed coordination",
  "type": "object",
  "required": ["schemaVersion", "writer", "updatedAt", "symbol", "venue", ...existing fields...],
  "properties": {
    "schemaVersion": {"type": "string", "enum": ["1.1"]},
    "writer": {
      "type": "object",
      "required": ["nodeId", "writerToken"],
      "properties": {
        "nodeId": {"type": "string", "minLength": 1},
        "writerToken": {"type": "integer", "minimum": 1}
      }
    },
    "updatedAt": {"type": "integer", "minimum": 0},
    ...existing properties unchanged...
  }
}
```

**No other contract changes**: MCP API signature unchanged (`get_report(symbol) -> JSON`), Redis Streams event schema unchanged (if NT_ENABLE_STREAMS=true).

### Quickstart Guide (`quickstart.md`)

Title: **Local Deployment with Embedded Analytics**

Sections:
1. **Prerequisites**: Docker, 8GB RAM, Binance API key (optional for testnet)
2. **Configuration**: Copy `.env.example` to `.env`, set NT_ENABLE_KV_REPORTS=true, NT_ENABLE_STREAMS=false
3. **Single Instance Deployment**:
   ```bash
   docker compose up -d redis producer mcp prometheus
   # Wait 20s for startup
   curl http://localhost:8080/get_report?symbol=BTCUSDT | jq
   # Verify schemaVersion=1.1, writer metadata present
   ```
4. **Multi-Instance Deployment** (failover demo):
   ```bash
   docker compose up -d redis producer-1 producer-2 producer-3 mcp
   # Configure 15 symbols across 3 instances
   # Check metrics: curl http://localhost:9101/metrics | grep nt_symbols_assigned
   # Kill producer-2: docker compose stop producer-2
   # Verify reassignment <2s: watch metrics, no data gap in reports
   ```
5. **Parallel Testing** (old Go analytics + new NT analytics):
   ```bash
   docker compose --profile parallel-test up -d
   # Runs both analytics services, publishes to report:{symbol}:go and report:{symbol}:nt
   # Compare: diff <(curl .../report:BTCUSDT:go) <(curl .../report:BTCUSDT:nt)
   ```
6. **Troubleshooting**: Common issues (lease conflicts, heartbeat failures, slow cycles lagging)

### Agent Context Update

Run update script:
```bash
bash .specify/scripts/bash/update-agent-context.sh claude
```

This will add to `.claude/CLAUDE.md`:
- NautilusTrader Strategy patterns for timer-based callbacks
- redis-py Lua script execution examples
- HRW consistent hashing implementation notes
- Distributed coordination best practices (lease management, fencing tokens)

**Manual additions preserved**: Existing project-specific guidance between markers will not be overwritten.

---

## Phase 2: Tasks Breakdown *(Not part of /speckit.plan)*

**This section is intentionally empty. Run `/speckit.tasks` to generate `tasks.md`.**

The tasks command will create dependency-ordered implementation tasks from:
- This plan's data model and contracts
- Constitution compliance checklist
- Feature spec's functional requirements (FR-001 to FR-039)
- Testing strategy (unit → integration → system → chaos)

---

## Open Questions

1. **Fencing Token Wraparound**: At what threshold should we handle writerToken approaching max int64 (2^63-1)? Proposal: Log warning at 2^62, implement reset mechanism at 2^63-1000.

2. **Hysteresis Tuning**: Sticky percentage (default 2%) and min hold time (default 2000ms) may need tuning based on real-world rebalancing patterns. Should we expose these as first-class config or keep as constants?

3. **Slow Cycle Execution**: If slow-cycle calculations consistently exceed period (500ms > 2000ms target), should we: (a) skip cycles to catch up, (b) run in ProcessPoolExecutor, (c) disable slow cycle entirely? Propose default (a) with config flag for (b).

4. **Report Splitting Threshold**: When report JSON exceeds 256KB, split to `report:{symbol}:heavy`. Should this be automatic or require explicit config? Propose automatic with logged warning.

5. **Backward Compatibility**: How long to maintain NT_ENABLE_STREAMS=true mode? Propose: 2 releases (6 months) then deprecate, remove after 4 releases (1 year).

---

**Next Steps**: Execute Phase 0 research tasks to resolve unknowns, then proceed to Phase 1 design artifacts.
