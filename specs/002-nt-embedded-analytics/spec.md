# Feature Specification: Embedded Market Analytics in NautilusTrader

**Feature Branch**: `002-nt-embedded-analytics`
**Created**: 2025-10-28
**Status**: Draft
**Input**: User description: "Встроить расчёты MarketReport в NautilusTrader с горизонтальным шардированием, writer-lease и публикацией в Redis KV"

## Overview

This feature consolidates real-time market analysis calculations directly into the NautilusTrader producer service, eliminating the separate analytics service. The system will compute all market metrics (spread, depth, flow, liquidity features, anomalies) within the data ingestion layer and publish complete market reports directly to Redis key-value store. Multiple producer instances will coordinate through distributed membership management, consistent hashing for symbol assignment, and writer leases to ensure exactly-once semantics for report generation.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - LLM Receives Fresh Market Data (Priority: P1)

An AI trading system queries the MCP server for current market conditions and receives a comprehensive report with data freshness under 1 second, enabling real-time decision making.

**Why this priority**: This is the core value proposition - delivering fresh, accurate market data to LLM consumers. Without this, the system fails its primary purpose.

**Independent Test**: Deploy single producer instance tracking BTCUSDT. Query MCP endpoint and verify report contains all required fields with data_age_ms ≤ 1000ms. This validates the complete fast-path calculation cycle.

**Acceptance Scenarios**:

1. **Given** system is tracking BTCUSDT with active market data, **When** LLM queries `/get_report?symbol=BTCUSDT`, **Then** receives report with spread_bps, depth metrics, flow metrics, and data_age_ms ≤ 1000
2. **Given** no recent market activity for 2+ seconds, **When** LLM queries report, **Then** receives report with ingestion status "degraded" and data_age_ms > 1000
3. **Given** system just started and symbol not yet tracked, **When** LLM queries unknown symbol, **Then** receives 404 error with clear message

---

### User Story 2 - Horizontal Scaling Across Symbols (Priority: P2)

Operations team deploys multiple producer instances to handle 30+ trading pairs, with each symbol automatically assigned to exactly one producer that maintains write exclusivity.

**Why this priority**: Enables production scalability beyond MVP's 2-symbol limit. Required before onboarding more trading pairs.

**Independent Test**: Deploy 3 producer instances with 15 symbols configured. Verify each symbol assigned to exactly one instance via metrics endpoint. Kill one instance and verify reassignment completes within 2 seconds with no duplicate writes.

**Acceptance Scenarios**:

1. **Given** 3 producer instances running with 15 configured symbols, **When** system reaches steady state, **Then** each instance shows 4-5 assigned symbols in metrics with no overlaps
2. **Given** steady-state operation, **When** instance-2 crashes, **Then** instance-1 and instance-3 detect failure within heartbeat window and acquire orphaned symbols within 2 seconds
3. **Given** instance recovering from crash, **When** it rejoins cluster, **Then** participates in next rebalance cycle without causing duplicate writers for any symbol

---

### User Story 3 - Compute-Intensive Analytics (Priority: P3)

System calculates volume profile, liquidity walls/vacuums, and anomaly detection patterns over longer time windows, enriching reports with deeper market microstructure insights.

**Why this priority**: Provides advanced analytics that differentiate the product but aren't required for basic market data delivery. Can be enabled after fast-path metrics are stable.

**Independent Test**: Enable slow-cycle calculations with NT_SLOW_PERIOD_MS=2000. Verify volume profile (POC/VAH/VAL) appears in reports every 2-5 seconds with 30-minute trade history. Validate liquidity wall detection triggers when order book shows large concentrated orders.

**Acceptance Scenarios**:

1. **Given** 30 minutes of trade history accumulated, **When** slow cycle executes, **Then** report includes volume profile with valid POC, VAH, VAL where VAL ≤ POC ≤ VAH
2. **Given** order book shows bid at $64,000 with quantity 3x above P95 threshold, **When** liquidity analyzer runs, **Then** report includes liquidity wall detection with correct severity classification
3. **Given** insufficient data (< 10 trades or < 20 price observations), **When** slow cycle executes, **Then** report omits optional fields cleanly without errors

---

### User Story 4 - Operational Observability (Priority: P3)

Site reliability engineers monitor system health through Prometheus metrics and alerts, quickly identifying data staleness, rebalancing issues, or write conflicts.

**Why this priority**: Critical for production operations but not required for initial functionality validation. Enables proactive issue detection.

**Independent Test**: Deploy with metrics enabled on port 9101. Trigger failure scenarios (network partition, instance crash, intentional write conflict) and verify corresponding metrics increment and alerts fire within SLO windows.

**Acceptance Scenarios**:

1. **Given** system operating normally, **When** SRE queries Prometheus /metrics endpoint, **Then** sees nt_symbols_assigned, nt_data_age_ms, and nt_report_publish_rate with valid values
2. **Given** data_age_ms P95 exceeds 1000ms for 5+ minutes, **When** alert evaluator runs, **Then** Prometheus alert "MarketDataStale" fires with symbol and node context
3. **Given** two instances attempt concurrent writes (lease conflict), **When** Redis rejects second writer, **Then** nt_lease_conflicts_total counter increments and both instances log error

---

### Edge Cases

- **Rapid instance flapping**: Producer crashes and restarts repeatedly within lease TTL window. System must use fencing tokens to prevent stale writers from corrupting reports after lease expiration.
- **Network partition**: Instance loses connectivity to Redis but continues calculating. Writer lease expires; other instances acquire symbols. Original instance must detect partition and stop publishing before connectivity restores.
- **Symbol configuration mismatch**: Instance-1 configured with SYMBOLS=BTCUSDT,ETHUSDT while instance-2 has SYMBOLS=ETHUSDT,BNBUSDT. Overlapping symbol (ETHUSDT) must resolve to single writer via HRW+lease; non-overlapping symbols assigned normally.
- **WebSocket burst after reconnect**: Exchange reconnection floods system with 1000+ queued events. Fast-cycle calculations must throttle/skip ticks when lag exceeds period to maintain data freshness SLO.
- **Empty order book during low liquidity**: Bid or ask side empty for illiquid pair. System must handle gracefully - omit metrics requiring both sides, mark ingestion status as "degraded".
- **Report payload growth**: As more metrics added (e.g., order flow imbalance, maker-taker ratios), JSON payload approaches Redis value size limits (~512KB typical). System must support splitting heavy sections to separate keys.

## Requirements *(mandatory)*

### Functional Requirements

#### Core Calculations (Fast Cycle: 100-250ms)

- **FR-001**: System MUST calculate spread metrics (spread_bps, mid_price, micro_price) on every order book update within fast cycle period
- **FR-002**: System MUST compute depth metrics (sum of top 20 bid/ask levels, imbalance ratio) on every order book snapshot
- **FR-003**: System MUST track trade flow (orders_per_sec over 10s window, net_flow over 30s window) updated continuously as trades arrive
- **FR-004**: System MUST calculate health score combining freshness, spread quality, depth adequacy, and anomaly presence
- **FR-005**: System MUST publish complete report to Redis KV at fast cycle frequency (4-10 Hz) with all L1/L2/flow/health fields populated

#### Advanced Analytics (Slow Cycle: 1-5s)

- **FR-006**: System MUST calculate volume profile (POC, VAH, VAL) over rolling 30-minute trade window when sufficient data available (≥10 trades)
- **FR-007**: System MUST detect liquidity walls by identifying order levels exceeding P95 quantity threshold × 1.5 multiplier, classified by severity
- **FR-008**: System MUST detect liquidity vacuums by finding 3+ consecutive price levels below P10 quantity threshold
- **FR-009**: System MUST detect anomaly patterns: spoofing (high cancel rate on far orders), iceberg orders (stable visible depth across fills), flash crash risk (widening spread + thin book + negative flow acceleration)
- **FR-010**: System MUST merge slow-cycle analytics into existing fast-cycle report without overwriting fast-path fields

#### Distributed Coordination

- **FR-011**: Each producer instance MUST register its presence in Redis with heartbeat key `nt:node:{id}` containing JSON metadata, refreshed every 1 second with jitter (±100ms), expiring after 5 seconds
- **FR-012**: System MUST discover live cluster members by scanning `nt:node:*` keys and filtering those not expired, with ZSET `nt:nodes_seen` as backup tracking
- **FR-013**: System MUST assign symbols to nodes using Highest Random Weight (HRW) consistent hashing with node ID and symbol as inputs to hash function (xxhash or blake2b)
- **FR-014**: Symbol assignment MUST implement hysteresis to prevent flapping: sticky percentage (2% weight bonus for current owner) and minimum hold time (1500-2500ms before allowing reassignment)
- **FR-015**: Producer MUST acquire writer lease before publishing symbol reports using Redis key `report:writer:{symbol}` with SET NX PX operation
- **FR-016**: Lease holder MUST renew lease periodically (every lease_ttl / 2) using conditional PEXPIRE only if still owner
- **FR-017**: System MUST use fencing tokens (monotonic counter `report:writer:token:{symbol}`) incremented on each lease acquisition and included in every published report
- **FR-018**: Producer losing lease (renewal fails) MUST immediately stop publishing for that symbol and unsubscribe from market data
- **FR-019**: On symbol acquisition, producer MUST: (1) acquire lease, (2) subscribe to exchange data feeds, (3) begin calculations, (4) publish first report - in that order
- **FR-020**: On symbol drop, producer MUST: (1) stop publishing, (2) release lease, (3) unsubscribe from data feeds with graceful cleanup - in that order

#### State Management

- **FR-021**: System MUST maintain per-symbol state including: L2 order book (price→quantity map + sorted top-N), best bid/ask, last trade, event timestamps
- **FR-022**: System MUST buffer recent events in ring buffers: 10-second window for flow rate, 30-second window for net flow, 30-minute window for volume profile trades
- **FR-023**: System MUST track quantity statistics in rolling windows for percentile calculations (P95 for walls, P10 for vacuums) with max 10,000 observations retained
- **FR-024**: System MUST update `last_event_ts` on every market data callback to track data freshness for each symbol independently

#### Publishing & Schema

- **FR-025**: System MUST publish reports to Redis key `report:{symbol}` using SET command with KEEPTTL option to preserve existing TTL
- **FR-026**: Report JSON MUST include schema metadata: `schemaVersion` (string "1.0"), `writer` object with `nodeId` and `writerToken`, `updatedAt` (milliseconds since epoch)
- **FR-027**: Report MUST include all existing MCP schema fields: symbol, venue, last_price, change_24h_pct, high_24h, low_24h, volume_24h, best_bid, best_ask, spread_bps, mid_price, micro_price, depth, flow, liquidity, anomalies, health, ingestion status
- **FR-028**: System MUST round numeric fields consistently: spread_bps to 4 decimals, prices/micro_price/mid_price to 8 decimals
- **FR-029**: System MUST set report TTL on initial publish (configurable, default 300 seconds) and use KEEPTTL on subsequent updates
- **FR-030**: System MUST support splitting large reports: store heavy sections (e.g., full depth, trade history) in `report:{symbol}:heavy` and include reference in main report

#### Configuration & Feature Flags

- **FR-031**: System MUST support feature flags: `NT_ENABLE_KV_REPORTS` (enable embedded analytics), `NT_ENABLE_STREAMS` (optionally publish raw events to Redis Streams for compatibility)
- **FR-032**: System MUST allow configuration of cycle periods: `NT_REPORT_PERIOD_MS` (fast cycle, default 250ms), `NT_SLOW_PERIOD_MS` (slow cycle, default 2000ms)
- **FR-033**: System MUST allow configuration of lease parameters: `NT_LEASE_TTL_MS` (default 2000ms), `NT_MIN_HOLD_MS` (hysteresis, default 2000ms), `NT_HRW_STICKY_PCT` (default 0.02)
- **FR-034**: System MUST support explicit node ID via `NT_NODE_ID` environment variable or generate stable ID from hostname+PID if not provided

#### Observability

- **FR-035**: System MUST expose Prometheus metrics endpoint on configurable port (`NT_METRICS_PORT`, default 9101) with all required metrics
- **FR-036**: System MUST emit metrics: `nt_node_heartbeat` (gauge, 1 when healthy), `nt_symbols_assigned` (gauge, count), `nt_calc_latency_ms` (histogram by metric type), `nt_report_publish_rate` (counter by symbol), `nt_data_age_ms` (histogram by symbol)
- **FR-037**: System MUST emit coordination metrics: `nt_lease_conflicts_total` (counter), `nt_hrw_rebalances_total` (counter), `nt_ws_resubscribe_total` (counter by reason)
- **FR-038**: System MUST log structured JSON events for key state transitions: symbol assignment change, lease acquisition/loss, rebalancing triggers, calculation errors
- **FR-039**: System MUST provide Prometheus alerting rules for: data_age_ms P95 > 1000ms for 5+ minutes, lease conflict rate spike, excessive rebalancing frequency

### Key Entities

- **MarketReport**: Complete market analysis snapshot for a symbol, containing L1/L2 metrics, flow statistics, liquidity features, anomalies, health score, schema metadata, and writer attribution
- **NodeMembership**: Cluster participant metadata including unique node ID, hostname, process ID, startup timestamp, health status, metrics endpoint URL
- **WriterLease**: Exclusive write permission for a symbol-node pair, with expiration timestamp, lease token (fencing), and renewal status
- **SymbolState**: Per-symbol calculation context including order book (L2 depth), recent trade buffer, event statistics, percentile trackers, and last update timestamp
- **VolumeProfile**: Price distribution analysis over time window with Point of Control (peak volume price), Value Area High/Low (70% volume boundaries)
- **LiquidityFeature**: Order book anomaly detection including walls (large concentrated orders), vacuums (thin liquidity regions), with price ranges and severity levels
- **AnomalyPattern**: Suspicious market behavior detection including spoofing (high cancel rate), iceberg orders (hidden depth), flash crash risk (multiple negative signals)

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 95th percentile of data_age_ms across all tracked symbols remains ≤ 1000ms during normal operation
- **SC-002**: Upon node failure, orphaned symbols reassigned to healthy nodes and resume publishing within 2 seconds (lease_ttl + heartbeat_interval)
- **SC-003**: System supports linear scalability: adding nodes increases total symbol capacity proportionally without degrading per-symbol latency
- **SC-004**: Zero occurrences of duplicate writers: at any given time, each symbol has exactly one active publisher validated via writer tokens in reports
- **SC-005**: Fast-cycle metrics (L1/L2/flow) publish at 4-10 Hz (250-100ms period) achieving 90%+ on-time delivery
- **SC-006**: Slow-cycle metrics (volume profile, liquidity, anomalies) update at 0.2-1 Hz (5000-1000ms period) completing within period 95% of time
- **SC-007**: System handles symbol rebalancing (node join/leave) with <100ms total downtime per affected symbol measured from last good report to first new report
- **SC-008**: Prometheus metrics endpoint responds within 50ms and exposes all required metrics with correct labels and values
- **SC-009**: MCP server compatibility maintained: all report fields match existing schema, no breaking changes, existing LLM clients continue functioning
- **SC-010**: Memory usage per symbol remains under 5MB for standard configuration (20-level order book, 30min trade history, 10K percentile samples)

## Dependencies & Assumptions *(mandatory)*

### Dependencies

- Redis 7.x cluster available with sufficient memory for membership keys, report cache, and lease management
- NautilusTrader framework with Binance adapter configured and operational
- Binance exchange WebSocket connections with sufficient rate limits for configured symbols
- Python 3.11+ runtime with required libraries: redis-py, numpy for calculations, prometheus-client for metrics
- Network connectivity between all producer instances and Redis with latency <10ms p99
- Docker or equivalent container runtime for deployment orchestration

### Assumptions

- Redis operates in standalone or cluster mode with strong consistency guarantees for SET NX operations
- System clock synchronization across all nodes (NTP or equivalent) within ±100ms
- Binance WebSocket streams deliver trade ticks and order book updates with sub-100ms latency under normal conditions
- Single Redis instance can handle 100+ SET operations per second for report publishing across all symbols/nodes
- Order book depth of 20 levels sufficient for liquidity analysis (walls/vacuums detection)
- 30-minute rolling window sufficient for volume profile meaningful analysis
- Report TTL of 300 seconds (5 minutes) acceptable for cache expiration and storage management
- Symbol configuration static or changes infrequently (no hot-reloading required)
- Leap second handling and timezone considerations managed by underlying libraries (datetime, timestamp serialization)
- Fencing token wraparound (at 2^63) not reached within system lifetime or handled gracefully
- Report JSON payload typically under 100KB; heavy sections split only when approaching 256KB threshold

## Out of Scope

- Multi-region deployment with geo-distributed Redis clusters
- Dynamic symbol configuration reload without restart
- Historical report storage or time-series database integration
- Real-time streaming of reports to consumers (WebSocket/SSE)
- Authentication/authorization for metrics endpoint
- TLS/encryption for Redis connections
- Custom hash functions beyond xxhash/blake2b
- Automatic node capacity planning or autoscaling triggers
- Integration with external service discovery (Consul, etcd)
- Report compression (gzip, snappy) before Redis storage
- Differential updates / delta encoding for reports
- Support for exchanges beyond Binance
- Order book reconstruction from deltas (assumes snapshots available)
- Tick-by-tick event replay or reprocessing
- Machine learning model inference for predictions

## Non-Functional Requirements

### Performance

- **NFR-001**: Fast-cycle calculations (L1/L2/flow) complete within 20ms p99 to support 250ms publish period with headroom
- **NFR-002**: Slow-cycle calculations (volume profile, liquidity, anomalies) complete within 500ms p99 to support 2000ms period with headroom
- **NFR-003**: HRW symbol assignment calculation for 100 symbols across 10 nodes completes within 100ms
- **NFR-004**: Lease acquisition/renewal Redis operations complete within 5ms p99
- **NFR-005**: Report serialization to JSON and Redis SET operation combined complete within 10ms p99

### Reliability

- **NFR-006**: System detects node failures within one heartbeat interval (1 second) with 99%+ reliability
- **NFR-007**: Lease conflicts (multiple nodes attempting to write same symbol) occur <0.1% of time during steady state
- **NFR-008**: Rebalancing triggered by membership changes stabilizes within 5 seconds (2x lease TTL)
- **NFR-009**: Symbol reassignment after node failure succeeds on first attempt 95%+ of time; remaining cases resolve within 3 attempts
- **NFR-010**: System tolerates temporary Redis unavailability (10-30 seconds) by buffering reports in memory and republishing on reconnection

### Observability

- **NFR-011**: All metrics update within 1 second of corresponding event occurrence
- **NFR-012**: Metrics cardinality remains manageable: <1000 unique label combinations across all metrics
- **NFR-013**: Structured logs include trace context (node_id, symbol, timestamp) for correlation across distributed instances
- **NFR-014**: Alerting rules fire within 1 minute of threshold breach with <1% false positive rate
- **NFR-015**: Metrics endpoint scraping by Prometheus completes within collection interval (15s typical)

### Scalability

- **NFR-016**: Single producer instance handles 10-15 symbols concurrently on standard hardware (4 CPU cores, 8GB RAM)
- **NFR-017**: System scales horizontally to 100+ symbols by adding proportional nodes (7-10 nodes for 100 symbols)
- **NFR-018**: Redis membership overhead grows sub-linearly: 10 nodes generate <100 ops/sec for heartbeats + discovery
- **NFR-019**: CPU utilization per symbol remains under 10% of single core for fast-cycle calculations
- **NFR-020**: Network bandwidth per symbol averages 50KB/sec for market data ingestion + report publishing

## Testing Strategy

### Unit Testing

- Test calculation functions (spread, depth, flow, liquidity, anomalies) with synthetic order book and trade data
- Verify HRW consistent hashing properties: same input produces same assignment, minimal reassignment on membership change
- Test lease acquisition/renewal/release Lua scripts with Redis mock
- Validate report JSON serialization matches schema, required fields present, numeric rounding correct
- Test ring buffer implementations for event windowing (10s, 30s, 30min)
- Verify percentile calculations (P95, P10) with known input distributions

### Integration Testing

- Deploy single producer instance with real Binance testnet connection, verify report publication to local Redis
- Test symbol acquisition flow: start producer, observe lease acquisition, subscription to exchange, first report published
- Test symbol release flow: stop producer gracefully, observe unsubscribe, lease release, reports stop
- Verify fast-cycle and slow-cycle timing: measure actual publish rates, calculation latencies under load
- Test Redis connection failure recovery: kill Redis, buffer reports, reconnect, resume publishing

### System Testing (Multi-Node)

- Deploy 3 producer instances with 15 symbols total, verify HRW assignment distributes evenly, no overlaps
- Kill one instance, measure time to reassignment (target <2s), verify no duplicate writers via tokens
- Restart killed instance, verify it rejoins cluster, participates in rebalancing without conflicts
- Introduce network partition between one node and Redis, verify lease expiration and reassignment
- Trigger rapid instance flapping (crash/restart every 3 seconds for 60 seconds), verify system stabilizes without data loss

### Performance Testing

- Benchmark calculation latencies: run fast-cycle on single symbol for 10,000 iterations, measure p50/p95/p99
- Benchmark slow-cycle with max data: 30min of dense trades (1000 trades/min), full order book (20 levels × 100 updates/min)
- Load test Redis: simulate 10 instances × 10 symbols publishing at 10 Hz, measure SET latency and memory growth
- Scalability test: incrementally add symbols to single instance, identify CPU/memory limits where latency degrades

### Chaos Testing

- Chaos monkey: randomly kill instances every 30-120 seconds for 30 minutes, verify <2s recovery every time
- Network partition: introduce 5-second partition between node and Redis, verify graceful reconnection
- Clock skew: introduce +2 second clock offset on one node, verify heartbeat/lease logic tolerates
- Redis failover: switch Redis primary/replica mid-operation (if cluster mode), verify report publishing resumes
- Exchange reconnection storm: simulate Binance disconnect/reconnect with 1000-event burst, verify throttling works

### Compatibility Testing

- Run new embedded-analytics producer in parallel with existing Go analytics service for 1-2 weeks
- Compare reports from both systems for same symbols: verify field parity, numeric differences within rounding tolerance
- Send traffic to both MCP endpoints (old pointing to Go, new pointing to NT), compare response times and content
- Deploy with NT_ENABLE_STREAMS=true, verify raw events still published to Redis Streams for backward compatibility
- Gradually migrate symbols from Go to NT, validate no disruption to LLM consumers

## Risks & Mitigations

### Risk 1: Rebalancing Flapping (High)

**Description**: Membership changes trigger symbol reassignments, but if HRW assignments are unstable or lease acquisitions race, symbols may bounce between nodes rapidly, causing data gaps.

**Mitigation**:
- Implement hysteresis with sticky percentage (2% weight bonus) for current owner to bias toward stability
- Enforce minimum hold time (1500-2500ms) before allowing reassignment even if HRW suggests change
- Use fencing tokens to invalidate stale writers after lease expiration
- Test with chaos scenarios: kill/restart nodes every 3s for 5 minutes, verify flapping <1% of reassignments

### Risk 2: CPU/Memory Exhaustion (Medium)

**Description**: As symbol count increases, per-symbol calculation overhead accumulates. With slow-cycle analytics (volume profile over 30min, percentile tracking with 10K samples), memory footprint and CPU usage may exceed single-instance capacity.

**Mitigation**:
- Separate fast-cycle and slow-cycle into independent execution loops with different frequencies
- Use ring buffers with fixed size for windowed data (discard oldest when full)
- Store aggregates/histograms instead of raw events where possible (e.g., bucketed trade volumes vs. all trades)
- For slow-cycle only: offload to ProcessPoolExecutor to parallelize across CPU cores
- Profile memory usage per symbol and enforce 10-15 symbol hard limit per instance

### Risk 3: Binance WebSocket Rate Limits (Medium)

**Description**: Binance limits WebSocket connections per IP and streams per connection. With 100+ symbols, may require multiple connections. Aggressive subscribing/unsubscribing during rebalancing could trigger rate limits or bans.

**Mitigation**:
- Batch symbol subscriptions: subscribe to multiple streams in single WebSocket connection (Binance supports 1024 streams/connection)
- Implement graceful unsubscribe with delay (100-500ms) before closing streams to avoid rapid churn
- Use separate WebSocket clients for different symbol groups if hitting connection limits
- Add exponential backoff retry logic for subscription failures
- Monitor `nt_ws_resubscribe_total{reason}` metric to detect rate limiting patterns

### Risk 4: Redis Single Point of Failure (High)

**Description**: Redis stores membership, leases, and reports. If Redis becomes unavailable, entire system halts - no coordination, no publishing, no data delivery to LLMs.

**Mitigation**:
- Deploy Redis in cluster or sentinel mode for automatic failover (out of initial scope but recommended for production)
- Implement connection retry logic with exponential backoff (max 30s between attempts)
- Buffer calculated reports in memory (ring buffer, max 100 reports per symbol) during Redis downtime
- On reconnection, republish buffered reports to minimize data gap
- Emit `nt_redis_connection_status` metric and alert on disconnect >10 seconds

### Risk 5: Calculation Parity with Go Implementation (Medium)

**Description**: Existing Go analytics service has precise calculation logic (e.g., percentile interpolation, volume profile binning). Python reimplementation may have subtle differences in rounding, tie-breaking, or edge case handling, causing report discrepancies.

**Mitigation**:
- Extract test fixtures from Go unit tests: known order book states + expected outputs
- Run Python implementation against same fixtures, assert numeric outputs within tolerance (e.g., ±0.0001 for prices)
- Deploy side-by-side for 1-2 weeks: publish reports from both, compare in real-time, log differences
- Define acceptable tolerances per metric (e.g., spread_bps within 0.0001, volume profile POC within 1 tick)
- Fix discrepancies in Python or update tolerance thresholds if both are valid

## Open Questions

_None - all major design decisions documented above. Implementation details (exact Lua script syntax, specific percentile algorithm choice) left to planning phase._
