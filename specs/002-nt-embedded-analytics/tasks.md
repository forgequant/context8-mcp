# Tasks: Embedded Market Analytics in NautilusTrader

**Feature Branch**: `002-nt-embedded-analytics`
**Input**: Design documents from `/specs/002-nt-embedded-analytics/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/report-schema-v1.1.json, quickstart.md

**Tests**: Per feature requirements, tests are NOT explicitly requested. Task generation focuses on implementation with manual validation via quickstart scenarios.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `- [ ] [ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

Based on plan.md, the project structure is:
- **producer/**: Python NautilusTrader service (EXPANDED with embedded analytics)
- **mcp/**: Go MCP server (UNCHANGED)
- **analytics/**: Go analytics service (DEPRECATED - kept for parallel testing)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, dependencies, and basic structure

- [X] T001 Update producer/pyproject.toml to add dependencies: redis-py 5.x, numpy 1.24+, prometheus-client 0.19+, xxhash 3.x
- [X] T002 [P] Create producer/lua/ directory for Redis Lua scripts (acquire_lease.lua, renew_lease.lua, release_lease.lua)
- [X] T003 [P] Create producer/src/coordinator/ directory structure (membership.py, hrw_sharding.py, lease_manager.py, assignment.py)
- [X] T004 [P] Create producer/src/calculators/ directory structure (spread.py, depth.py, flow.py, liquidity.py, anomalies.py, health.py)
- [X] T005 [P] Create producer/src/state/ directory structure (symbol_state.py, ring_buffer.py)
- [X] T006 [P] Create producer/src/reporters/ directory structure (fast_cycle.py, slow_cycle.py, redis_cache.py)
- [X] T007 [P] Create producer/src/metrics/ directory structure (prometheus.py)
- [X] T008 [P] Update producer/src/config.py to add environment variables for NT_ENABLE_KV_REPORTS, NT_REPORT_PERIOD_MS, NT_SLOW_PERIOD_MS, NT_LEASE_TTL_MS, NT_NODE_ID, NT_HRW_STICKY_PCT, NT_MIN_HOLD_MS, NT_METRICS_PORT
- [X] T009 [P] Create .gitignore entries for producer: __pycache__/, *.pyc, .venv/, dist/, *.egg-info/, .env*, *.log
- [X] T010 [P] Create .dockerignore for producer: .git/, .venv/, __pycache__/, *.pyc, .env*, *.log*, tests/

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Redis Lua Scripts (Lease Management)

- [X] T011 [P] Implement acquire_lease.lua: SET NX PX + INCR fencing token, returns token or nil
- [X] T012 [P] Implement renew_lease.lua: Conditional PEXPIRE if current owner, returns 1/0
- [X] T013 [P] Implement release_lease.lua: Conditional DEL if current owner, returns 1/0

### State Management Infrastructure

- [X] T014 [P] Implement producer/src/state/ring_buffer.py: RingBuffer class with fixed max_size, append(), filter_by_time() methods
- [X] T015 Implement producer/src/state/symbol_state.py: SymbolState class with OrderBookL2, trade buffers (10s, 30s, 30min), quantity_history, last_event_ts
- [X] T016 Add SymbolState validation methods: check_order_book_invariants (bid < ask), validate_buffers_bounded

### Coordination Infrastructure

- [X] T017 Implement producer/src/coordinator/hrw_sharding.py: hrw_hash() using hashlib.blake2b, select_node() with hysteresis (sticky_pct bonus)
- [X] T018 Implement producer/src/coordinator/membership.py: NodeMembership class with heartbeat() (SET EX 5), discover() (SCAN nt:node:*), cleanup methods
- [X] T019 Implement producer/src/coordinator/lease_manager.py: LeaseManager class loading Lua scripts, acquire()/renew()/release() methods wrapping Script execution
- [X] T020 Implement producer/src/coordinator/assignment.py: SymbolAssignmentController with HRW-based assignment, rebalancing logic, min_hold_time enforcement

### Redis Client Infrastructure

- [X] T021 Create producer/src/redis_client.py: RedisClient class with ConnectionPool (max_connections=20, socket_timeout=5, retry logic), shared pool instance

### Prometheus Metrics Infrastructure

- [X] T022 Implement producer/src/metrics/prometheus.py: PrometheusMetrics class with node_heartbeat, symbols_assigned, calc_latency, report_publish_rate, data_age, lease_conflicts, hrw_rebalances, ws_resubscribe metrics
- [X] T023 Add start_http_server(NT_METRICS_PORT) in PrometheusMetrics.__init__() for /metrics endpoint

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - LLM Receives Fresh Market Data (Priority: P1) 🎯 MVP

**Goal**: Single producer instance tracks 2-5 symbols, calculates L1/L2/flow/health metrics at 4-10 Hz, publishes reports to Redis KV with data_age_ms ≤ 1000ms

**Independent Test**: Deploy single producer instance tracking BTCUSDT. Query MCP endpoint and verify report contains all required fields with data_age_ms ≤ 1000ms (validates complete fast-path calculation cycle).

### Fast-Cycle Calculators (L1/L2/Flow/Health)

- [X] T024 [P] [US1] Implement producer/src/calculators/spread.py: calculate_spread_bps(), calculate_mid_price(), calculate_micro_price() functions using SymbolState.best_bid/best_ask
- [X] T025 [P] [US1] Implement producer/src/calculators/depth.py: calculate_depth_metrics() function computing total_bid_qty, total_ask_qty, imbalance from OrderBookL2.top_bids/top_asks
- [X] T026 [P] [US1] Implement producer/src/calculators/flow.py: calculate_orders_per_sec() over 10s window, calculate_net_flow() over 30s window using RingBuffer.filter_by_time()
- [X] T027 [US1] Implement producer/src/calculators/health.py: calculate_health_score() function combining freshness (data_age_ms), spread quality (spread_bps), depth adequacy (imbalance), anomaly presence

### Fast-Cycle Report Generation

- [X] T028 [US1] Implement producer/src/reporters/fast_cycle.py: generate_fast_report() function collecting spread, depth, flow, health into MarketReport structure with schemaVersion=1.1
- [X] T029 [US1] Add writer metadata to fast_cycle report: nodeId (from NT_NODE_ID), writerToken (from lease), updatedAt (current timestamp ms)
- [X] T030 [US1] Add data freshness calculation: data_age_ms = (updatedAt - last_event_ts), ingestion.status based on age (<1000ms=ok, 1000-2000ms=degraded, >2000ms=down)

### Redis Report Publishing

- [X] T031 [US1] Implement producer/src/reporters/redis_cache.py: publish_report() function executing Redis SET report:{symbol} <json> KEEPTTL
- [X] T032 [US1] Add publish_report() error handling: retry on connection failure (max 3 attempts with exponential backoff), log failures

### NautilusTrader Strategy Integration (Fast Cycle)

- [X] T033 [US1] Create producer/src/analytics_strategy.py: MarketAnalyticsStrategy class inheriting from nautilus_trader.trading.strategy.Strategy
- [X] T034 [US1] Implement MarketAnalyticsStrategy.on_start(): setup fast_cycle timer (NT_REPORT_PERIOD_MS, default 250ms) using self.clock.set_timer()
- [X] T035 [US1] Implement MarketAnalyticsStrategy.on_fast_cycle(event): iterate symbol_states, generate_fast_report(), publish_report(), record metrics
- [X] T036 [US1] Implement MarketAnalyticsStrategy.on_order_book_deltas(deltas): update SymbolState.order_book, update quantity_history, set last_event_ts
- [X] T037 [US1] Implement MarketAnalyticsStrategy.on_trade_tick(trade): update SymbolState.last_trade, append to trade_buffers, set last_event_ts
- [X] T038 [US1] Implement MarketAnalyticsStrategy.on_stop(): cancel timers, release leases, cleanup symbol_states

### Configuration and Entry Point

- [X] T039 [US1] Update producer/src/main.py: add conditional MarketAnalyticsStrategy initialization if NT_ENABLE_KV_REPORTS=true, pass config to strategy
- [X] T040 [US1] Update producer/src/config.py: add get_analytics_config() function returning dict with all NT_* environment variables parsed

### Metrics Recording (US1)

- [X] T041 [US1] Add metrics recording in fast_cycle: calc_latency for each calculator (spread, depth, flow, health), report_publish_rate per symbol, data_age per symbol

**Checkpoint**: User Story 1 complete - single instance publishes reports with all fast-cycle metrics, data_age_ms ≤ 1000ms

---

## Phase 4: User Story 2 - Horizontal Scaling Across Symbols (Priority: P2)

**Goal**: Multiple producer instances (3+) coordinate via Redis membership, HRW consistent hashing assigns each symbol to exactly one instance, writer leases enforce exclusivity, failover <2 seconds

**Independent Test**: Deploy 3 producer instances with 15 symbols configured. Verify each symbol assigned to exactly one instance via metrics endpoint. Kill one instance and verify reassignment completes within 2 seconds with no duplicate writes.

### Membership and Heartbeat

- [ ] T042 [US2] Implement heartbeat loop in MarketAnalyticsStrategy: call membership.heartbeat() every 1 second with jitter (±100ms) in background asyncio task
- [ ] T043 [US2] Add membership.discover() call in heartbeat loop: scan nt:node:* keys, filter expired nodes (last_heartbeat > 5s ago), maintain live cluster member list

### Symbol Assignment and Rebalancing

- [ ] T044 [US2] Implement assignment.rebalance() in MarketAnalyticsStrategy: runs every 2-3 seconds, calls HRW select_node() for all configured symbols, compares to current assignments
- [ ] T045 [US2] Add rebalancing decision logic: acquire new symbols (not currently owned), release dropped symbols (no longer assigned), enforce min_hold_time before allowing reassignment
- [ ] T046 [US2] Implement on_symbol_acquired() handler: acquire lease via lease_manager, subscribe to exchange data (order book + trades), initialize SymbolState, start publishing
- [ ] T047 [US2] Implement on_symbol_dropped() handler: stop publishing, release lease via lease_manager, unsubscribe from exchange data, cleanup SymbolState

### Writer Lease Management

- [ ] T048 [US2] Implement lease renewal loop in MarketAnalyticsStrategy: for each owned symbol, call lease_manager.renew() every lease_ttl/2 (e.g., every 1000ms for 2000ms TTL)
- [ ] T049 [US2] Add lease renewal failure handling: if renew() returns 0 (lost ownership), immediately call on_symbol_dropped() to stop publishing and clean up
- [ ] T050 [US2] Add fencing token validation in publish_report(): check lease_manager.get_current_token(symbol) matches report.writer.writerToken before publishing

### Metrics Recording (US2)

- [ ] T051 [P] [US2] Add node_heartbeat.set(1) in heartbeat loop, node_heartbeat.set(0) on shutdown
- [ ] T052 [P] [US2] Add symbols_assigned.set(len(owned_symbols)) after each rebalance cycle
- [ ] T053 [P] [US2] Add lease_conflicts.inc() when publish_report() detects token mismatch (stale writer)
- [ ] T054 [P] [US2] Add hrw_rebalances.inc() when rebalance() triggers symbol reassignment
- [ ] T055 [P] [US2] Add ws_resubscribe.labels(reason=reason).inc() when WebSocket re-subscription occurs (exchange disconnect, symbol acquisition)

### Error Handling and Graceful Shutdown

- [ ] T056 [US2] Implement graceful shutdown in on_stop(): release all leases, stop heartbeat loop, unsubscribe from all symbols, cleanup Redis connections
- [ ] T057 [US2] Add signal handlers (SIGTERM, SIGINT) in main.py to trigger graceful shutdown sequence

**Checkpoint**: User Story 2 complete - multi-instance coordination working, failover <2s, no duplicate writers

---

## Phase 5: User Story 3 - Compute-Intensive Analytics (Priority: P3)

**Goal**: System calculates volume profile (POC/VAH/VAL), liquidity walls/vacuums, anomaly detection over longer windows, enriches reports every 1-5 seconds

**Independent Test**: Enable slow-cycle calculations with NT_SLOW_PERIOD_MS=2000. Verify volume profile (POC/VAH/VAL) appears in reports every 2-5 seconds with 30-minute trade history. Validate liquidity wall detection triggers when order book shows large concentrated orders.

### Volume Profile Calculator

- [ ] T058 [P] [US3] Implement producer/src/calculators/liquidity.py: calculate_volume_profile() function with tick-size based binning (default 5 ticks per bin)
- [ ] T059 [P] [US3] Add volume profile POC calculation: find bin with max volume, return center of bin as POC
- [ ] T060 [P] [US3] Add volume profile VAH/VAL calculation: expand from POC until reaching 70% total volume, return boundaries
- [ ] T061 [US3] Add volume profile validation: ensure VAL ≤ POC ≤ VAH invariant, minimum 10 trades required, return None if insufficient data

### Liquidity Features (Walls and Vacuums)

- [ ] T062 [P] [US3] Implement detect_liquidity_walls() in liquidity.py: calculate P95 quantity threshold using numpy.percentile on quantity_history
- [ ] T063 [P] [US3] Add wall detection logic: find order levels with qty >= P95 × 1.5, classify severity (≥3.0=high, ≥2.0=medium, ≥1.0=low)
- [ ] T064 [P] [US3] Implement detect_liquidity_vacuums() in liquidity.py: calculate P10 quantity threshold using numpy.percentile
- [ ] T065 [US3] Add vacuum detection logic: find 3+ consecutive levels < P10 threshold, classify severity (≥10 levels=high, ≥6=medium, ≥3=low)

### Anomaly Detection

- [ ] T066 [P] [US3] Implement producer/src/calculators/anomalies.py: detect_spoofing() function checking cancel rate ≥70% on large far-from-mid orders
- [ ] T067 [P] [US3] Implement detect_iceberg() function: ≥5 fills at same price with stable visible depth (±10%)
- [ ] T068 [P] [US3] Implement detect_flash_crash_risk() function: check ≥2 of 3 signals (spread widening, thin book, negative flow acceleration)
- [ ] T069 [US3] Add anomaly severity classification and human-readable note generation for each anomaly type

### Slow-Cycle Report Generation

- [ ] T070 [US3] Implement producer/src/reporters/slow_cycle.py: calculate_slow_metrics() function calling volume_profile, walls, vacuums, anomalies calculators
- [ ] T071 [US3] Implement enrich_report() function: merge slow-cycle metrics into existing fast-cycle report without overwriting fast fields (spread, depth, flow, health)

### NautilusTrader Strategy Integration (Slow Cycle)

- [ ] T072 [US3] Update MarketAnalyticsStrategy.on_start(): setup slow_cycle timer (NT_SLOW_PERIOD_MS, default 2000ms) using self.clock.set_timer()
- [ ] T073 [US3] Implement MarketAnalyticsStrategy.on_slow_cycle(event): iterate symbol_states, calculate_slow_metrics(), enrich_report(), record metrics
- [ ] T074 [US3] Add slow-cycle lag detection: if previous slow_cycle still running when new cycle triggers, skip cycle and log warning

### Metrics Recording (US3)

- [ ] T075 [P] [US3] Add calc_latency.labels(metric='volume_profile', cycle='slow').observe(duration_ms) in slow_cycle
- [ ] T076 [P] [US3] Add calc_latency.labels(metric='liquidity', cycle='slow').observe(duration_ms) for walls/vacuums calculation
- [ ] T077 [P] [US3] Add calc_latency.labels(metric='anomalies', cycle='slow').observe(duration_ms) for anomaly detection

**Checkpoint**: User Story 3 complete - advanced analytics (volume profile, liquidity features, anomalies) enriching reports every 1-5s

---

## Phase 6: User Story 4 - Operational Observability (Priority: P3)

**Goal**: SREs monitor system health through Prometheus metrics and alerts, quickly identifying data staleness, rebalancing issues, or write conflicts

**Independent Test**: Deploy with metrics enabled on port 9101. Trigger failure scenarios (network partition, instance crash, intentional write conflict) and verify corresponding metrics increment and alerts fire within SLO windows.

### Prometheus Alert Rules

- [ ] T078 [P] [US4] Create producer/config/prometheus-alerts.yml: MarketDataStale alert rule (data_age_ms P95 > 1000ms for 5+ minutes)
- [ ] T079 [P] [US4] Add LeaseConflictSpike alert rule (lease_conflicts_total rate spike, threshold TBD based on testing)
- [ ] T080 [P] [US4] Add ExcessiveRebalancing alert rule (hrw_rebalances_total rate > threshold for 10+ minutes)
- [ ] T081 [P] [US4] Add ProducerDown alert rule (nt_node_heartbeat == 0 for 30+ seconds)

### Structured Logging

- [ ] T082 [P] [US4] Add JSON structured logging in MarketAnalyticsStrategy: log.info() calls with mandatory fields (component, symbol, lag_ms, node_id) for all state transitions
- [ ] T083 [P] [US4] Add log events for key state transitions: symbol_assigned, symbol_dropped, lease_acquired, lease_lost, lease_renewed, lease_conflict, rebalance_triggered, calculation_error
- [ ] T084 [US4] Configure log level via environment variable (NT_LOG_LEVEL, default INFO), support DEBUG for troubleshooting

### Metrics Validation

- [ ] T085 [US4] Add metrics self-test in MarketAnalyticsStrategy.on_start(): verify all expected metrics registered, log warning if missing
- [ ] T086 [US4] Add /health endpoint (separate from /metrics) returning JSON with node_id, uptime, owned_symbols, last_heartbeat_ts

### Documentation

- [ ] T087 [P] [US4] Create docs/metrics.md: document all Prometheus metrics with descriptions, labels, example queries, alert thresholds
- [ ] T088 [P] [US4] Create docs/runbooks/troubleshooting.md: document common issues (lease conflicts, heartbeat failures, slow cycle lagging) with diagnosis and fixes per quickstart.md

**Checkpoint**: User Story 4 complete - full observability stack operational, alerts configured, runbooks documented

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories, final validation

### Parallel Testing Infrastructure (Go Analytics Compatibility)

- [ ] T089 [P] Update MarketAnalyticsStrategy to support NT_ENABLE_STREAMS flag: conditionally publish raw events to Redis Streams (for backward compatibility with existing Go analytics)
- [ ] T090 [P] Update docker-compose.yml: add parallel-test profile running both producer (NT analytics) and analytics (Go service) side-by-side

### Configuration Validation

- [ ] T091 Implement config validation in producer/src/config.py: check NT_LEASE_TTL_MS >= 2 × renewal_interval, NT_REPORT_PERIOD_MS reasonable (100-1000ms), NT_SLOW_PERIOD_MS >= 1000ms
- [ ] T092 Add environment variable validation on startup: log ERROR and exit if critical configs missing (REDIS_URL, SYMBOLS when NT_ENABLE_KV_REPORTS=true)

### Performance Optimization

- [ ] T093 [P] Profile fast-cycle latency using cProfile: ensure spread, depth, flow calculations complete within 20ms p99 target
- [ ] T094 [P] Profile slow-cycle latency: ensure volume profile + liquidity + anomalies complete within 500ms p99 target
- [ ] T095 Optimize numpy percentile calls: ensure P95/P10 calculation on 10K samples completes <1ms

### Quickstart Validation

- [ ] T096 Validate quickstart.md Scenario 1 (Single Instance): verify all commands work, report contains schemaVersion=1.1, data_age_ms < 1000
- [ ] T097 Validate quickstart.md Scenario 2 (Multi-Instance Deployment): verify 3 instances distribute 15 symbols, failover <2s, no duplicate writers
- [ ] T098 Validate quickstart.md Scenario 3 (Parallel Testing): verify both NT and Go analytics produce reports, compare outputs within tolerance

### Code Quality

- [ ] T099 [P] Run ruff check on producer/src/: fix any linting errors, ensure code style consistent
- [ ] T100 [P] Add type hints to all public functions in calculators/, coordinators/, reporters/ modules
- [ ] T101 [P] Add docstrings to all public classes and functions following Google style

### Docker Configuration

- [ ] T102 Update producer/Dockerfile: ensure all dependencies installed (redis-py, numpy, prometheus-client, xxhash), COPY lua/ scripts
- [ ] T103 Update docker-compose.yml: add producer service with NT_ENABLE_KV_REPORTS=true, expose metrics port 9101, configure SYMBOLS, depends_on redis

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - US1 (Phase 3): Can start after Foundational - No dependencies on other stories ✅ MVP TARGET
  - US2 (Phase 4): Can start after Foundational - Extends US1 with coordination
  - US3 (Phase 5): Can start after Foundational - Extends US1 with slow-cycle analytics
  - US4 (Phase 6): Can start after Foundational - Adds observability to US1/US2/US3
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Foundation only - delivers MVP (single instance, fast-cycle analytics)
- **User Story 2 (P2)**: Extends US1 - adds multi-instance coordination (membership, leases, rebalancing)
- **User Story 3 (P3)**: Extends US1 - adds slow-cycle analytics (volume profile, liquidity, anomalies)
- **User Story 4 (P3)**: Cross-cutting - adds observability to all stories (alerts, runbooks, metrics docs)

### Within Each User Story

- **US1**: Calculators → Report Generation → Strategy Integration → Entry Point
- **US2**: Membership → Assignment → Lease Management → Error Handling
- **US3**: Volume Profile → Liquidity Features → Anomalies → Slow-Cycle Integration
- **US4**: Alert Rules → Structured Logging → Metrics Docs → Runbooks

### Parallel Opportunities

- All Setup tasks (T001-T010) can run in parallel
- Foundational Lua scripts (T011-T013) can run in parallel
- Foundational state/coordination infrastructure (T014-T020) can run in parallel after Lua scripts complete
- US1 calculators (T024-T027) can run in parallel within fast-cycle implementation
- US2 metrics recording (T051-T055) can run in parallel during coordination implementation
- US3 calculators (T058-T069) can run in parallel within slow-cycle implementation
- US4 alert rules and docs (T078-T088) can run in parallel during observability implementation
- Polish tasks (T089-T103) can run in parallel after all user stories complete

---

## Parallel Example: User Story 1 (MVP)

```bash
# After Foundational phase completes, launch all US1 calculators in parallel:
Task T024: "Implement spread.py calculator"
Task T025: "Implement depth.py calculator"
Task T026: "Implement flow.py calculator"
Task T027: "Implement health.py calculator"

# Then proceed with sequential report generation and strategy integration
Task T028: "Implement fast_cycle.py report generation"
...
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T010)
2. Complete Phase 2: Foundational (T011-T023) - CRITICAL
3. Complete Phase 3: User Story 1 (T024-T041)
4. **STOP and VALIDATE**: Run quickstart.md Scenario 1, verify report quality and data_age_ms
5. Deploy/demo MVP if ready

**Estimated MVP Completion**: After ~41 tasks (Setup + Foundation + US1)

### Incremental Delivery

1. MVP (US1): Single instance with fast-cycle analytics → Deploy/Test
2. Add US2: Multi-instance coordination → Deploy/Test horizontal scaling
3. Add US3: Slow-cycle analytics → Deploy/Test advanced features
4. Add US4: Observability → Deploy/Test production readiness
5. Polish: Parallel testing, optimization, final validation

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together (T001-T023)
2. Once Foundational is done:
   - Developer A: User Story 1 (T024-T041) - MVP focus
   - Developer B: Can start User Story 2 prep (T042-T057) - but depends on US1 strategy structure
   - Developer C: Can start User Story 3 calculators (T058-T069) - but depends on US1 strategy hooks
3. US1 completes first (MVP), then US2/US3 integrate sequentially

**Recommendation**: Focus all resources on US1 MVP first, then parallelize US2/US3 after MVP validated.

---

## Notes

- **Tests**: Spec does not explicitly request unit/integration tests. Validation via quickstart.md manual scenarios.
- **[P] tasks**: Different files, no dependencies - safe to parallelize
- **[Story] labels**: Map tasks to user stories for traceability and independent delivery
- **Critical path**: Setup → Foundational → US1 (MVP) - estimated ~41 tasks
- **Validation checkpoints**: After each user story phase, validate via quickstart scenarios
- **Docker**: Tasks T102-T103 handle Docker configuration updates
- **Go analytics**: Kept for parallel testing (Phase 7, T089-T090), then deprecated

**Total Task Count**: 103 tasks
- Phase 1 (Setup): 10 tasks
- Phase 2 (Foundational): 13 tasks
- Phase 3 (US1 - MVP): 18 tasks ⭐
- Phase 4 (US2): 16 tasks
- Phase 5 (US3): 20 tasks
- Phase 6 (US4): 11 tasks
- Phase 7 (Polish): 15 tasks

**MVP Scope**: Phases 1-3 only (41 tasks) → Single instance with fast-cycle analytics
