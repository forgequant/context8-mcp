# Tasks: Real-Time Crypto Market Analysis MCP Server

**Feature Branch**: `001-market-report-mcp`
**Input**: Design documents from `/specs/001-market-report-mcp/`
**Prerequisites**: plan.md ✅, spec.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Tests are NOT explicitly requested in the specification, so test tasks are omitted. Focus is on implementation delivery.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `- [ ] [ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4, US5, US6)
- All tasks include exact file paths

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and basic structure that all services need

- [X] T001 Create repository root structure with producer/, analytics/, mcp/, tests/, docs/ directories
- [X] T002 Initialize Go module for analytics service at analytics/go.mod with Go 1.24+
- [X] T003 [P] Initialize Go module for mcp service at mcp/go.mod with Go 1.24+
- [X] T004 [P] Initialize Python project for producer at producer/pyproject.toml using Poetry
- [X] T005 [P] Create .env.example file at repository root with all required environment variables
- [X] T006 [P] Add .env to .gitignore to prevent secrets from being committed
- [X] T007 [P] Create Makefile at repository root with build, test, lint, run, clean targets
- [X] T008 [P] Create docs/schemas/ directory and copy JSON schemas from specs/001-market-report-mcp/contracts/
- [X] T009 Create README.md at repository root with project overview and quickstart instructions

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Redis Infrastructure

- [X] T010 Create docker-compose.yml at repository root with Redis 7+ service configuration
- [X] T011 Configure Redis service in docker-compose.yml with maxmemory 512MB and allkeys-lru eviction policy

### Python Producer Foundation

- [X] T012 Add NautilusTrader and redis dependencies to producer/pyproject.toml
- [X] T013 Add python-dotenv, structlog, and pytest to producer/pyproject.toml
- [X] T014 Run poetry lock to generate producer/poetry.lock file
- [X] T015 Create producer/src/ directory and producer/src/__init__.py
- [X] T016 Create producer/src/config.py to load configuration from environment variables
- [X] T017 Create producer/tests/ directory and producer/tests/__init__.py
- [X] T018 Create producer/Dockerfile with Python 3.11+ base image and Poetry installation

### Go Analytics Foundation

- [X] T019 Add go-redis/v9, prometheus client_golang, and testify dependencies to analytics/go.mod
- [X] T020 [P] Add gopter (property-based testing) dependency to analytics/go.mod
- [X] T021 Create analytics/internal/ directory structure: consumer/, metrics/, aggregator/, models/, config/
- [X] T022 Create analytics/cmd/server/main.go entry point with basic structure
- [X] T023 Create analytics/internal/config/config.go to load configuration from environment variables
- [X] T024 Create analytics/Dockerfile with Go 1.24+ base image and multi-stage build

### Go MCP Foundation

- [X] T025 Add go-redis/v9, chi router, and prometheus client_golang dependencies to mcp/go.mod
- [X] T026 Create mcp/internal/ directory structure: handlers/, cache/, models/, config/
- [X] T027 Create mcp/cmd/server/main.go entry point with basic HTTP server setup
- [X] T028 Create mcp/internal/config/config.go to load configuration from environment variables
- [X] T029 Create mcp/Dockerfile with Go 1.24+ base image and multi-stage build

### Shared Models and Schemas

- [X] T030 Create analytics/internal/models/events.go with MarketEventEnvelope struct per data-model.md section 1.1
- [X] T031 [P] Add TradeTick, OrderBookDepth, OrderBookDeltas, Ticker24h payload structs to analytics/internal/models/events.go per data-model.md sections 1.2-1.5
- [X] T032 [P] Create analytics/internal/models/report.go with MarketReport struct per data-model.md section 2.1
- [X] T033 [P] Add IngestionStatus, PriceQty, DepthMetrics structs to analytics/internal/models/report.go per data-model.md sections 2.2-2.4
- [X] T034 [P] Add LiquidityAnalysis, LiquidityWall, LiquidityVacuum, VolumeProfile structs to analytics/internal/models/report.go per data-model.md sections 2.5-2.8
- [X] T035 [P] Add FlowMetrics, Anomaly, HealthScore structs to analytics/internal/models/report.go per data-model.md sections 2.9-2.11
- [X] T036 Create analytics/internal/models/validation.go with JSON schema validation functions using gojsonschema library
- [X] T037 Create mcp/internal/models/report.go by importing or duplicating MarketReport struct from analytics

### Documentation Foundation

- [X] T038 Create docs/metrics.md with placeholders for all calculation formulas (FR-006 through FR-019)
- [X] T039 [P] Create docs/architecture.md with system architecture diagram and data flow description
- [X] T040 [P] Create docs/runbooks/ directory with deployment.md, troubleshooting.md, monitoring.md placeholders

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - LLM Queries Market State (Priority: P1) 🎯 MVP

**Goal**: Enable LLMs to query market reports via MCP `get_report` method with fresh, comprehensive data

**Independent Test**: Call `get_report("BTCUSDT")` and verify a valid JSON report is returned within 150ms with all required fields and `fresh=true`

**Why MVP**: This is the core value proposition - without this, the system has no purpose. Delivers immediate value as a read-only data source.

### US1: Producer - Data Ingestion

- [X] T041 [P] [US1] Create producer/src/binance_adapter.py with NautilusTrader Binance configuration for BTCUSDT and ETHUSDT
- [X] T042 [P] [US1] Create producer/src/redis_publisher.py to publish MarketEventEnvelope to Redis Streams at key nt:binance
- [X] T043 [US1] Implement JSON serialization in producer/src/redis_publisher.py with snake_case fields per constitution principle 2
- [X] T044 [US1] Implement main.py entry point in producer/src/main.py to initialize NautilusTrader, configure Binance adapter, and start publishing
- [X] T045 [US1] Add structured JSON logging to producer/src/redis_publisher.py with component, symbol, stream_id fields
- [X] T046 [US1] Update docker-compose.yml to add producer service with dependencies on redis, using producer/Dockerfile

### US1: Analytics - Consumer and Basic Metrics

- [X] T047 [P] [US1] Implement Redis Streams consumer in analytics/internal/consumer/consumer.go using XREADGROUP with consumer group "context8"
- [X] T048 [US1] Implement XACK acknowledgment logic in analytics/internal/consumer/consumer.go after successful processing
- [X] T049 [US1] Implement event deserialization in analytics/internal/consumer/consumer.go to parse JSON into MarketEventEnvelope structs
- [X] T050 [P] [US1] Implement spread_bps calculation in analytics/internal/metrics/spread.go per FR-006: `(ask - bid) / bid * 10000`
- [X] T051 [P] [US1] Implement mid_price calculation in analytics/internal/metrics/spread.go per FR-007: `(bid + ask) / 2`
- [X] T052 [P] [US1] Implement micro_price calculation in analytics/internal/metrics/spread.go per FR-008: `(ask * bidQty + bid * askQty) / (bidQty + askQty)`
- [X] T053 [P] [US1] Implement depth metrics calculation in analytics/internal/metrics/depth.go: top 20 levels, sum_bid, sum_ask per FR-009
- [X] T054 [P] [US1] Implement order book imbalance calculation in analytics/internal/metrics/depth.go per FR-010: `(sum_bid - sum_ask) / (sum_bid + sum_ask)`
- [X] T055 [P] [US1] Document spread, mid-price, micro-price formulas in docs/metrics.md with examples and edge cases
- [X] T056 [P] [US1] Document depth and imbalance formulas in docs/metrics.md with invariant bounds [-1, 1]

### US1: Analytics - Report Aggregation

- [X] T057 [US1] Implement report aggregator in analytics/internal/aggregator/aggregator.go to combine metrics into MarketReport struct
- [X] T058 [US1] Implement 24h statistics extraction in analytics/internal/aggregator/aggregator.go from Ticker24h events per FR-005
- [X] T059 [US1] Implement data_age_ms calculation in analytics/internal/aggregator/aggregator.go per FR-020: `generated_at - ts_event` in milliseconds
- [X] T060 [US1] Implement fresh boolean flag logic in analytics/internal/aggregator/aggregator.go: `fresh = (data_age_ms <= 1000)`
- [X] T061 [US1] Implement ingestion status determination in analytics/internal/aggregator/aggregator.go per FR-021 state machine (ok/degraded/down)
- [X] T062 [US1] Implement report JSON schema validation in analytics/internal/aggregator/aggregator.go using validation.go functions before caching
- [X] T063 [US1] Implement Redis KV cache writer in analytics/internal/aggregator/cache.go to store report at key `report:{symbol}` with TTL
- [X] T064 [US1] Add structured JSON logging to analytics aggregator with component, symbol, lag_ms, stream_id fields
- [X] T065 [US1] Wire consumer, metrics, aggregator, cache in analytics/cmd/server/main.go to create processing pipeline
- [X] T066 [US1] Update docker-compose.yml to add analytics service with dependencies on redis and producer

### US1: MCP Server - Read-Only API

- [X] T067 [P] [US1] Implement Redis KV reader in mcp/internal/cache/reader.go to fetch report from `report:{symbol}` key
- [X] T068 [P] [US1] Implement get_report handler in mcp/internal/handlers/get_report.go to call cache reader and return JSON
- [X] T069 [US1] Implement 150ms timeout middleware in mcp/internal/handlers/middleware.go per FR-023
- [X] T070 [US1] Implement error handling in mcp/internal/handlers/get_report.go for symbol_not_indexed (404) and backend_unavailable per FR-024, FR-025
- [X] T071 [US1] Implement structured JSON logging middleware in mcp/internal/handlers/middleware.go
- [X] T072 [US1] Setup chi router in mcp/cmd/server/main.go with /get_report endpoint mapped to handler
- [X] T073 [US1] Update docker-compose.yml to add mcp service with port 8080:8080, dependencies on redis and analytics

### US1: Observability - Basic Monitoring

- [X] T074 [P] [US1] Implement Prometheus metrics in analytics/cmd/server/main.go: stream_lag_ms, events_rate, calc_latency_ms per FR-030
- [X] T075 [P] [US1] Implement Prometheus metrics in mcp/cmd/server/main.go: mcp_requests_total, mcp_request_duration_ms per FR-030
- [X] T076 [US1] Add Prometheus service to docker-compose.yml with port 9090:9090 and scrape configuration
- [X] T077 [US1] Create prometheus.yml at repository root with scrape configs for analytics and mcp services

**Checkpoint**: At this point, User Story 1 (MVP) should be fully functional - can deploy with docker-compose and query BTCUSDT/ETHUSDT reports

---

## Phase 4: User Story 2 - Engineer Deploys System Locally (Priority: P1)

**Goal**: Single-command deployment with docker-compose that starts all services and produces valid reports within 20 seconds

**Independent Test**: Run `docker-compose up`, wait 20 seconds, call `get_report("BTCUSDT")` and verify `fresh=true`

**Why P1**: Without working deployment, no one can use the system. This is foundational infrastructure for all use cases.

### US2: Deployment Configuration

- [X] T078 [P] [US2] Add health check endpoints to producer/src/main.py at /health to check Binance WebSocket status
- [X] T079 [P] [US2] Add health check endpoint to analytics/cmd/server/main.go at /health to check consumer lag and processing rate
- [X] T080 [P] [US2] Add health check endpoint to mcp/cmd/server/main.go at /health to check Redis connectivity
- [X] T081 [US2] Configure healthcheck directives in docker-compose.yml for all services with appropriate intervals and retries
- [X] T082 [US2] Configure depends_on with service_healthy conditions in docker-compose.yml to ensure proper startup ordering
- [X] T083 [US2] Test full docker-compose startup and verify all containers reach healthy state within 20 seconds per SC-004

### US2: Documentation and Quickstart

- [X] T084 [P] [US2] Copy specs/001-market-report-mcp/quickstart.md to docs/quickstart.md at repository root
- [X] T085 [US2] Update README.md with link to docs/quickstart.md and brief deployment instructions
- [X] T086 [US2] Document .env.example configuration options with descriptions and default values
- [X] T087 [US2] Create docs/runbooks/deployment.md with step-by-step deployment procedures and verification steps
- [X] T088 [US2] Create docs/runbooks/troubleshooting.md with common issues and solutions for startup failures

**Checkpoint**: System is deployable via docker-compose with health checks and complete documentation

---

## Phase 5: User Story 5 - System Diagnoses Data Quality Issues (Priority: P3)

**Goal**: Detect and report degraded or down ingestion status when data pipeline has issues

**Independent Test**: Stop producer container, wait 2 seconds, verify reports show `ingestion.status = "degraded"` and `fresh = false`

**Why P3**: Supports operational reliability and debugging. Important for production but not blocking for initial development with stable data.

### US5: Health Monitoring and Status Tracking

- [X] T089 [US5] Implement ingestion status state machine in analytics/internal/aggregator/aggregator.go with transitions (ok → degraded → down)
- [X] T090 [US5] Implement transition logic in aggregator: ok → degraded when data_age_ms > 1000 for >2 seconds per data-model.md section 4.1
- [X] T091 [US5] Implement transition logic in aggregator: degraded → down when data_age_ms > 5000 per FR-021
- [X] T092 [US5] Implement transition logic in aggregator: degraded/down → ok when fresh data received with data_age_ms <= 1000
- [X] T093 [US5] Add report_age_ms Prometheus metric to analytics/cmd/server/main.go to track staleness
- [X] T094 [US5] Add errors_total Prometheus metric to analytics and mcp services to track error rates by component and type
- [X] T095 [US5] Document health monitoring and alerting thresholds in docs/runbooks/monitoring.md
- [X] T096 [US5] Test degradation detection by stopping producer and verifying status transitions within 2 seconds per SC-005

**Checkpoint**: System can detect and report data quality issues with clear status indicators

---

## Phase 6: User Story 6 - System Tracks Market Flow and Velocity (Priority: P3)

**Goal**: Calculate and report order flow rate and net buying/selling pressure

**Independent Test**: Generate synthetic events at known rate (10 events/sec), verify `flow.orders_per_sec` is approximately 10 and `flow.net_flow` correctly sums aggressive buy minus sell volume

**Why P3**: Provides additional context for market dynamics. Useful for advanced analysis but not essential for basic monitoring.

### US6: Flow Metrics Implementation

- [X] T097 [P] [US6] Implement orders_per_sec calculation in analytics/internal/metrics/flow.go: average events over last 10 seconds per FR-014
- [X] T098 [P] [US6] Implement net_flow calculation in analytics/internal/metrics/flow.go: aggressive buy volume - sell volume over last 30 seconds per FR-015
- [X] T099 [US6] Implement rolling window data structures in analytics/internal/metrics/flow.go to track events and trades over time windows
- [X] T100 [US6] Integrate flow metrics into report aggregator in analytics/internal/aggregator/aggregator.go
- [X] T101 [US6] Document flow metrics formulas and time windows in docs/metrics.md
- [X] T102 [US6] Verify flow metrics accuracy with synthetic events at known rates and volumes

**Checkpoint**: System tracks and reports market activity intensity and directional pressure

---

## Phase 7: User Story 4 - LLM Analyzes Liquidity Conditions (Priority: P2)

**Goal**: Identify large order walls, thin liquidity areas (vacuums), and volume profile (POC, VAH, VAL)

**Independent Test**: Create test order books with known large orders and thin regions, verify report correctly identifies walls and vacuums with accurate prices

**Why P2**: Enables sophisticated trading advice based on market microstructure. Valuable for serious traders but not essential for basic monitoring.

### US4: Liquidity Wall Detection

- [X] T103 [P] [US4] Implement rolling percentile calculation (P95) in analytics/internal/metrics/liquidity.go for wall detection threshold
- [X] T104 [US4] Implement wall detection logic in analytics/internal/metrics/liquidity.go per FR-011: qty >= max(P95 * 1.5, configurable_minimum)
- [X] T105 [US4] Implement severity classification for walls (low/medium/high) based on multiples of threshold
- [X] T106 [US4] Document wall detection algorithm and thresholds in docs/metrics.md

### US4: Liquidity Vacuum Detection

- [X] T107 [P] [US4] Implement rolling percentile calculation (P10) in analytics/internal/metrics/liquidity.go for vacuum detection threshold
- [X] T108 [US4] Implement vacuum detection logic in analytics/internal/metrics/liquidity.go per FR-012: depth < P10 over several ticks
- [X] T109 [US4] Implement adjacent vacuum region merging in analytics/internal/metrics/liquidity.go
- [X] T110 [US4] Implement severity classification for vacuums based on depth ratio
- [X] T111 [US4] Document vacuum detection algorithm and merging rules in docs/metrics.md

### US4: Volume Profile Calculation

- [X] T112 [US4] Implement trade volume binning by price in analytics/internal/metrics/liquidity.go with configurable bin width
- [X] T113 [US4] Implement rolling 30-minute window for volume profile per FR-013
- [X] T114 [US4] Implement POC (Point of Control) calculation: bin with maximum volume
- [X] T115 [US4] Implement VAH/VAL calculation: boundaries covering 70% of volume around POC per FR-013
- [X] T116 [US4] Validate volume profile invariants: val <= poc <= vah per data-model.md section 2.8
- [X] T117 [US4] Document volume profile calculation and bin width tuning in docs/metrics.md

### US4: Integration

- [X] T118 [US4] Integrate liquidity analysis (walls, vacuums, profile) into report aggregator in analytics/internal/aggregator/aggregator.go
- [X] T119 [US4] Verify wall detection with crafted order books containing known large orders per SC-008
- [X] T120 [US4] Verify vacuum detection with crafted order books containing thin regions per SC-008

**Checkpoint**: System provides comprehensive liquidity analysis for sophisticated trading intelligence

---

## Phase 8: User Story 3 - Trader Monitors Market Anomalies (Priority: P2)

**Goal**: Detect spoofing, iceberg orders, and flash crash risks with severity-rated anomaly entries

**Independent Test**: Generate synthetic spoofing pattern (large orders far from mid with rapid cancellations), verify report's `anomalies` array contains appropriate entry with correct severity

**Why P2**: Provides advanced intelligence beyond basic price data. Valuable for identifying manipulation and risks but not essential for basic operation.

### US3: Spoofing Detection

- [X] T121 [P] [US3] Implement large order tracking in analytics/internal/metrics/anomalies.go to identify orders far from mid price
- [X] T122 [P] [US3] Implement cancellation rate tracking in analytics/internal/metrics/anomalies.go for detected large orders
- [X] T123 [US3] Implement spoofing pattern detection per FR-016: large orders far from mid with high cancel rate
- [X] T124 [US3] Implement severity classification for spoofing (low/medium/high) based on distance from mid and cancel frequency
- [X] T125 [US3] Document spoofing detection algorithm and thresholds in docs/metrics.md

### US3: Iceberg Detection

- [X] T126 [P] [US3] Implement partial fill tracking in analytics/internal/metrics/anomalies.go at specific price levels
- [X] T127 [US3] Implement visible depth stability monitoring in analytics/internal/metrics/anomalies.go
- [X] T128 [US3] Implement iceberg pattern detection per FR-017: series of similar fills with stable visible depth
- [X] T129 [US3] Document iceberg detection algorithm and pattern matching in docs/metrics.md

### US3: Flash Crash Risk Detection

- [X] T130 [US3] Implement spread widening detection in analytics/internal/metrics/anomalies.go: track spread_bps increases
- [X] T131 [US3] Implement order book thinness detection in analytics/internal/metrics/anomalies.go: count vacuums and low depth
- [X] T132 [US3] Implement flow velocity tracking in analytics/internal/metrics/anomalies.go: rate of net_flow change
- [X] T133 [US3] Implement flash crash risk pattern detection per FR-018: widening spread + thin book + negative accelerating flow
- [X] T134 [US3] Implement severity classification for flash crash risk based on combined signal strength
- [X] T135 [US3] Document flash crash risk detection algorithm and signal weighting in docs/metrics.md

### US3: Integration

- [X] T136 [US3] Integrate anomaly detection (spoofing, iceberg, flash crash) into report aggregator in analytics/internal/aggregator/aggregator.go
- [X] T137 [US3] Verify spoofing detection with synthetic spoofing events per SC-007
- [X] T138 [US3] Add optional note field to anomaly entries with human-readable descriptions

**Checkpoint**: System detects and reports market manipulation patterns and crash risks

---

## Phase 9: Health Score and Final Integration

**Goal**: Calculate comprehensive health score from all components and complete report generation

**Independent Test**: Generate reports with various market conditions, verify health score is in [0, 100] and components sum correctly

### Health Score Implementation

- [X] T139 [P] Implement spread component normalization in analytics/internal/metrics/health.go: tighter spread = higher score
- [X] T140 [P] Implement depth component normalization in analytics/internal/metrics/health.go: more depth = higher score
- [X] T141 [P] Implement balance component normalization in analytics/internal/metrics/health.go: closer to zero imbalance = higher score
- [X] T142 [P] Implement flow component normalization in analytics/internal/metrics/health.go: higher activity = higher score
- [X] T143 [P] Implement anomalies component calculation in analytics/internal/metrics/health.go: penalty for detected anomalies
- [X] T144 [P] Implement freshness component calculation in analytics/internal/metrics/health.go: fresher data = higher score
- [X] T145 Implement weighted sum calculation in analytics/internal/metrics/health.go per FR-019: {spread: 20%, depth: 25%, balance: 15%, flow: 15%, anomalies: 15%, freshness: 10%}
- [X] T146 Document health score calculation, component weights, and interpretation ranges in docs/metrics.md
- [X] T147 Integrate health score calculation into report aggregator in analytics/internal/aggregator/aggregator.go
- [X] T148 Validate health score bounds [0, 100] with property-based tests across diverse inputs

### Final Report Validation

- [X] T149 Verify all required report fields are populated per data-model.md section 2.1
- [X] T150 Verify report JSON schema validation passes for all generated reports per FR-029 and SC-006
- [X] T151 Test MCP get_report endpoint returns complete reports with all sections populated
- [X] T152 Verify MCP response time is within 150ms for 99% of requests per SC-001

**Checkpoint**: Complete market reports with health scores are generated and served via MCP

---

## Phase 10: Polish and Cross-Cutting Concerns

**Goal**: Final touches for production readiness - configuration management, error handling, performance tuning

### Configuration and Secrets Management

- [X] T153 [P] Implement environment variable loading for all configurable parameters per FR-031: time windows, thresholds, Redis connection
- [X] T154 [P] Validate .env file does not contain committed secrets per FR-032 and constitution principle 8
- [X] T155 Add configuration validation at startup in all services to fail fast on missing or invalid env vars
- [X] T156 Document all configuration options in .env.example with descriptions and acceptable ranges

### Error Handling and Resilience

- [X] T157 [P] Implement Redis connection retry logic with exponential backoff in analytics and mcp services
- [X] T158 [P] Implement graceful shutdown handlers in all services to complete in-flight processing
- [X] T159 Implement Redis Streams auto-trim for messages older than 30-60 minutes per FR-035
- [X] T160 Add error recovery for corrupt or invalid event payloads: skip and log, continue processing

### Performance and Optimization

- [X] T161 Profile analytics service under load (200 events/sec) and identify calculation bottlenecks
- [X] T162 Optimize hot path calculations if needed to maintain <250ms report generation per SC-003
- [X] T163 Verify memory usage for analytics service with 2 symbols is <500MB RSS
- [X] T164 Load test MCP endpoint with 100 concurrent requests and verify p99 latency <150ms per SC-001

### Documentation Completion

- [X] T165 [P] Complete docs/metrics.md with all formulas, edge cases, and calculation examples
- [X] T166 [P] Complete docs/architecture.md with architecture diagram showing all five layers
- [X] T167 [P] Complete docs/runbooks/deployment.md with production deployment considerations
- [X] T168 [P] Complete docs/runbooks/troubleshooting.md with common failure scenarios and solutions
- [X] T169 [P] Complete docs/runbooks/monitoring.md with alerting thresholds and dashboard recommendations
- [X] T170 Update README.md with links to all documentation and contribution guidelines

### Final Validation

- [X] T171 Run full integration test: docker-compose up → verify startup within 20 seconds → query both symbols → verify fresh reports
- [X] T172 Run degradation test: stop producer → verify status transitions to degraded within 2 seconds → restart → verify recovery
- [X] T173 Validate all Prometheus metrics are exposed and accurately reflect system state per SC-010
- [X] T174 Verify golangci-lint passes for analytics and mcp Go code
- [X] T175 Verify ruff or flake8 passes for producer Python code
- [X] T176 Run `make test` to execute all unit tests across all services
- [X] T177 Verify report schema compliance: 100% of generated reports pass JSON schema validation per SC-006

**Checkpoint**: System is production-ready with complete documentation, monitoring, and validation

---

## Implementation Strategy

### MVP Scope (Minimum Viable Product)

**Milestone 1 (M1)**: Phase 1-3 Complete
- User Story 1 fully implemented
- Basic market reports with prices, spreads, depth available via MCP
- **Deliverable**: Can query BTCUSDT/ETHUSDT and get fresh reports

**Milestone 2 (M2)**: Phase 4 Complete
- User Story 2 fully implemented
- Docker Compose deployment works reliably
- **Deliverable**: Anyone can run the system locally with one command

**Milestone 3 (M3)**: Phase 5-6 Complete
- User Stories 5-6 implemented
- Health monitoring and flow metrics available
- **Deliverable**: System can diagnose its own data quality and track market velocity

**Milestone 4 (M4)**: Phase 7-8 Complete
- User Stories 3-4 implemented
- Advanced liquidity and anomaly detection available
- **Deliverable**: Full market microstructure intelligence for serious traders

**Milestone 5 (M5)**: Phase 9-10 Complete
- Health scoring and polish complete
- Production-ready with full documentation
- **Deliverable**: Comprehensive market analysis system ready for deployment

### Dependency Graph (Story Completion Order)

```
Phase 1 (Setup) ─────┬──→ Phase 2 (Foundation) ─────┬──→ Phase 3 (US1: Core MCP) ── MVP
                      │                               │
                      │                               ├──→ Phase 4 (US2: Deployment) ── MVP
                      │                               │
                      │                               ├──→ Phase 5 (US5: Health) ──┐
                      │                               │                             │
                      │                               ├──→ Phase 6 (US6: Flow) ────┤
                      │                               │                             ├──→ Phase 9 (Health Score)
                      │                               ├──→ Phase 7 (US4: Liquidity)│
                      │                               │                             │
                      │                               └──→ Phase 8 (US3: Anomalies)┘
                                                                                     │
                                                                                     ├──→ Phase 10 (Polish)
```

**Critical Path**: Phase 1 → Phase 2 → Phase 3 → Phase 4 (MVP)

**Parallel Opportunities**:
- After Phase 2: All user story phases (3-8) can be developed in parallel by different developers
- Within phases: Tasks marked [P] can run in parallel
- User Stories 3-6 are independent and can be implemented in any order after US1 completes

### Suggested Development Order

1. **Week 1**: Complete Phase 1-2 (Foundation)
2. **Week 2**: Complete Phase 3 (US1 - Core functionality)
3. **Week 3**: Complete Phase 4 (US2 - Deployment) + basic smoke tests
4. **Week 4-5**: Parallel development of US3-US6 (Phases 5-8)
5. **Week 6**: Complete Phase 9-10 (Health score + polish)

**Total Estimate**: 6 weeks for full implementation with 1-2 developers

---

## Task Summary

**Total Tasks**: 177

**Tasks by Phase**:
- Phase 1 (Setup): 9 tasks
- Phase 2 (Foundation): 31 tasks
- Phase 3 (US1 - Core MCP): 37 tasks
- Phase 4 (US2 - Deployment): 11 tasks
- Phase 5 (US5 - Health): 8 tasks
- Phase 6 (US6 - Flow): 6 tasks
- Phase 7 (US4 - Liquidity): 18 tasks
- Phase 8 (US3 - Anomalies): 18 tasks
- Phase 9 (Health Score): 14 tasks
- Phase 10 (Polish): 25 tasks

**Parallel Tasks**: 58 tasks marked [P] can run concurrently

**User Story Breakdown**:
- US1 (P1 - LLM Queries): 37 tasks
- US2 (P1 - Deployment): 11 tasks
- US3 (P2 - Anomalies): 18 tasks
- US4 (P2 - Liquidity): 18 tasks
- US5 (P3 - Health Monitoring): 8 tasks
- US6 (P3 - Flow Tracking): 6 tasks
- Shared/Infrastructure: 79 tasks

**MVP Tasks (M1+M2)**: 88 tasks (Phases 1-4)

**Constitution Compliance**: All tasks follow constitution principles:
- EDA architecture with distinct layers ✅
- Redis Streams with consumer groups ✅
- Idempotent processing ✅
- Go 1.24+ for analytics/MCP ✅
- Python with Poetry for producer ✅
- Read-only MCP interface ✅
- JSON schemas and validation ✅
- Structured logging ✅
- Secrets in .env only ✅

---

## Format Validation

All tasks follow the required format:
- ✅ All tasks have checkboxes `- [ ]`
- ✅ All tasks have sequential IDs (T001-T177)
- ✅ Parallel tasks marked with [P]
- ✅ User story tasks marked with [US1]-[US6]
- ✅ All tasks include file paths in descriptions
- ✅ Tasks organized by user story for independent implementation
- ✅ Each phase has clear goal and checkpoint

**Ready for implementation**: Start with Phase 1 and proceed through phases in order. User story phases (3-8) can be parallelized after Phase 2 completes.
