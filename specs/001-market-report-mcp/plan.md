# Implementation Plan: Real-Time Crypto Market Analysis MCP Server

**Branch**: `001-market-report-mcp` | **Date**: 2025-10-28 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-market-report-mcp/spec.md`

## Summary

Build a real-time crypto market analysis system that provides LLMs with comprehensive, sub-second fresh market reports via MCP interface. The system ingests Binance Spot market data through NautilusTrader, publishes events to Redis Streams, processes them through Go analytics services to calculate microstructure metrics (prices, spreads, depth, liquidity features, flows, anomalies), caches reports in Redis, and serves them via a read-only MCP server.

**Core Value**: Enable LLMs to answer market state questions with fresh data (≤1 second staleness), detect market manipulation patterns (spoofing, icebergs, flash crash risks), and provide sophisticated trading intelligence based on order book microstructure.

**Technical Approach**: Event-driven architecture with five layers: (1) NautilusTrader Python producer → (2) Redis Streams message bus → (3) Go analytics consumer → (4) Redis cache → (5) Go MCP server. All components deployable via Docker Compose for local development.

## Technical Context

**Language/Version**:
- Go 1.24+ (analytics and MCP services)
- Python 3.11+ (NautilusTrader data ingestion)

**Primary Dependencies**:
- **NautilusTrader** (current stable): Exchange integration and market data ingestion
- **go-redis/redis/v9**: Redis Streams consumer groups and KV cache
- **gorilla/mux** or **chi**: HTTP routing for MCP server
- **prometheus/client_golang**: Metrics instrumentation
- **testify**: Testing framework with assertions
- **miniredis**: In-memory Redis for integration tests

**Storage**:
- Redis 7+ (Streams for message bus, KV for report cache)
- No persistent storage required (ephemeral reports only)

**Testing**:
- Go: `go test` with `testify` assertions and `miniredis` for integration tests
- Python: `pytest` for NT producer contract tests
- Property-based: `gopter` for formula invariant testing
- Contract: JSON Schema validation for events and reports

**Target Platform**:
- Linux server (primary) with Docker Compose
- macOS/Windows via Docker Desktop (development)

**Project Type**:
- Distributed system with multiple services (single repository)
- Components: `producer/` (Python), `analytics/` (Go), `mcp/` (Go), `docker-compose.yml`

**Performance Goals**:
- Data freshness: ≤1 second (`data_age_ms ≤ 1000`)
- Report generation: ≤250ms at 100+ events/sec
- MCP response time: ≤150ms (99th percentile)
- Event processing rate: Handle 100+ events/sec per symbol without lag

**Constraints**:
- Response time: MCP `get_report()` must respond within 150ms timeout
- Memory: Analytics service should handle 2 symbols with <500MB RSS
- Latency: Sub-second end-to-end from exchange event to cached report
- Deployment: All components start successfully within 20 seconds via `docker-compose up`

**Scale/Scope**:
- **MVP**: 2 symbols (BTCUSDT, ETHUSDT), 1 exchange (Binance Spot)
- **Event Rate**: ~100-200 events/sec per symbol (trades + order book updates)
- **Concurrency**: Single instance of each service (no multi-tenancy or horizontal scaling)
- **Report Size**: ~5-10 KB JSON per symbol
- **Cache TTL**: 2-5 minutes (configurable)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Architecture Compliance (Principle 1)
- [x] Feature follows layered EDA: Ingestion → Message Bus → Analytics → Cache → MCP
  - **Status**: PASS - Five distinct layers with clear separation of concerns
  - **Evidence**: NT Producer (ingestion) → Redis Streams (bus) → Go Analytics (computation) → Redis KV (cache) → Go MCP (API)
- [x] Uses Redis Streams with consumer groups and XACK acknowledgment
  - **Status**: PASS - Analytics service uses consumer group named "context8" with XACK after processing
  - **Evidence**: Spec FR-004 mandates consumer group with acknowledgment
- [x] Respects single stream key topology (`nt:binance` for MVP)
  - **Status**: PASS - Single stream key for all Binance events
  - **Evidence**: Constitution §5 specifies `nt:binance` key; spec uses this convention

### Message Bus Contract (Principle 2)
- [x] All events use JSON format with `snake_case` fields
  - **Status**: PASS - JSON encoding with snake_case field naming
  - **Evidence**: Spec shows event envelope with `ts_event`, `order_book_depth`, etc.
- [x] Mandatory fields present: `symbol`, `venue`, `type`, `ts_event`, `payload`
  - **Status**: PASS - All events include these fields
  - **Evidence**: Spec FR-003 defines envelope structure with all mandatory fields
- [x] Event types limited to MVP-allowed: `trade_tick`, `order_book_depth|deltas`, `ticker_24h`
  - **Status**: PASS - Only these four event types used
  - **Evidence**: Spec defines exactly these event types in data contracts section

### Idempotency & Time (Principle 3)
- [x] All event handlers are idempotent (safe for replay/retry)
  - **Status**: PASS - Design ensures idempotent processing
  - **Evidence**: Spec FR-033 mandates idempotent event processing; last-write-wins for cache updates
- [x] All timestamps in UTC (RFC3339), converted at layer boundaries
  - **Status**: PASS - UTC timestamps throughout
  - **Evidence**: Spec FR-027 requires UTC RFC3339 format for all time fields

### Technology Stack (Principle 4)
- [x] Analytics/backend services implemented in Go ≥ 1.24
  - **Status**: PASS - Go 1.24+ for analytics and MCP services
  - **Evidence**: Technical Context specifies Go 1.24+
- [x] Python dependencies locked in `poetry.lock` or `requirements.txt`
  - **Status**: PASS - NautilusTrader dependencies will be locked
  - **Evidence**: Spec Assumption 7 mentions Python with locked dependencies

### Report Contract (Principle 6)
- [x] Report includes all mandatory fields: identification, 24h stats, L1/spread, depth, liquidity, flows, anomalies, health
  - **Status**: PASS - Comprehensive report structure with all required sections
  - **Evidence**: Spec provides complete JSON schema with all mandatory fields (FR-005 through FR-021)
- [x] All calculation formulas documented in `/docs/metrics.md`
  - **Status**: PASS - Formulas will be documented (task for Phase 1)
  - **Evidence**: Spec includes precise formulas for spread_bps, micro_price, imbalance, etc. (FR-006 through FR-019)
- [x] `report_version` follows semantic versioning
  - **Status**: PASS - Report includes version field
  - **Evidence**: JSON schema includes `report_version` field; constitution defines versioning rules

### SLO Compliance (Principle 7)
- [x] Feature supports `data_age_ms ≤ 1000` for healthy status
  - **Status**: PASS - Data freshness tracking built into report
  - **Evidence**: Spec FR-020 defines `data_age_ms` calculation and 1000ms threshold; SC-002 validates this SLO
- [x] Report generation design targets ≤ 250 ms on warm cache
  - **Status**: PASS - Performance goal explicitly stated
  - **Evidence**: Spec SC-003 defines 250ms generation target at 100+ events/sec
- [x] Graceful degradation implemented for data source failures
  - **Status**: PASS - Degradation handling specified
  - **Evidence**: Spec FR-021 defines ingestion status transitions; User Story 5 validates degradation behavior

### Security (Principle 8)
- [x] No secrets in code or repository (use `.env` or vault)
  - **Status**: PASS - Secrets management defined
  - **Evidence**: Spec FR-032 mandates secrets in `.env` file only
- [x] MCP endpoints remain read-only (no side effects)
  - **Status**: PASS - Read-only MCP interface
  - **Evidence**: Spec FR-026 enforces read-only constraint; FR-023 sources data from cache only
- [x] Complies with Binance API Terms of Service
  - **Status**: PASS - Compliance noted
  - **Evidence**: Spec Assumption 1 acknowledges public API usage; Out of Scope clarifies no data redistribution

### Quality & Testing (Principle 9)
- [x] Unit tests for all calculation logic
  - **Status**: PASS - Testing requirements defined
  - **Evidence**: Spec SC-008 validates unit tests for formulas; testing section specifies unit tests
- [x] Property-based tests for metric formulas
  - **Status**: PASS - Property testing planned
  - **Evidence**: Spec testing section mentions property tests for formula stability; SC-012 validates idempotency via property tests
- [x] MCP contract tests (schema + timeout validation)
  - **Status**: PASS - Contract testing defined
  - **Evidence**: Spec testing section specifies MCP tests with timeout validation; SC-009 validates error responses
- [x] JSON schemas defined for events and reports
  - **Status**: PASS - Schemas will be created in Phase 1
  - **Evidence**: Spec FR-028 and FR-029 mandate schema validation; complete JSON schema provided for reports

### Reference-First Development (Principle 10)
- [x] `.refs/INDEX.yaml` consulted for relevant integrations/libraries
  - **Status**: PASS - Reference repositories cataloged
  - **Evidence**: `.refs/INDEX.yaml` exists with categorized reference repositories
- [x] Reference repository patterns used (e.g., go-redis for streams, go-binance for WebSocket)
  - **Status**: PASS - Research phase will consult references
  - **Evidence**: Spec Assumption 7 mentions reference consultation; research.md will document patterns used
- [x] Deviations from reference patterns documented in code comments
  - **Status**: PASS - Documentation practice established
  - **Evidence**: Code review process includes pattern verification
- [x] PRs document which reference repositories were consulted
  - **Status**: PASS - PR template includes reference documentation
  - **Evidence**: Workflow includes reference tracking in implementation

### Observability (Principle 11)
- [x] Structured JSON logging with: `component`, `symbol`, `lag_ms`, `stream_id`
  - **Status**: PASS - Logging requirements defined
  - **Evidence**: Constitution §11 mandates these fields; spec FR-030 requires Prometheus metrics including lag tracking

### MCP Contract (Principle 13)
- [x] MCP method signature: `get_report(symbol: string) -> ReportJSON | null`
  - **Status**: PASS - Method signature matches specification
  - **Evidence**: Spec FR-001 defines exact method signature
- [x] Response sourced from cache only (no computation triggered)
  - **Status**: PASS - Read-only cache access
  - **Evidence**: Spec FR-023 and FR-026 enforce cache-only reads with no side effects
- [x] Timeout ≤ 150 ms enforced
  - **Status**: PASS - Timeout constraint specified
  - **Evidence**: Spec FR-023 defines 150ms timeout; SC-001 validates 99% compliance

**Constitution Compliance Summary**: ✅ **ALL CHECKS PASS** - No violations. Feature fully complies with constitution principles.

## Project Structure

### Documentation (this feature)

```text
specs/001-market-report-mcp/
├── plan.md              # This file (/speckit.plan output)
├── research.md          # Phase 0: Technology decisions and patterns
├── data-model.md        # Phase 1: Entity definitions and state machines
├── quickstart.md        # Phase 1: Deployment and local development guide
├── contracts/           # Phase 1: API schemas and message formats
│   ├── events.json      # Redis Streams event schema (envelope + payloads)
│   ├── report.json      # Market report output schema
│   └── mcp.json         # MCP tool definition schema
├── checklists/
│   └── requirements.md  # Spec quality validation (from /speckit.specify)
└── tasks.md             # Phase 2: Detailed implementation tasks (/speckit.tasks - NOT created by /speckit.plan)
```

### Source Code (repository root)

```text
context8-mcp/
├── producer/                      # Python: NautilusTrader data ingestion
│   ├── src/
│   │   ├── main.py                # Entry point: configure NT and start ingestion
│   │   ├── config.py              # Configuration from env vars
│   │   ├── binance_adapter.py    # Binance integration (if needed beyond NT)
│   │   └── redis_publisher.py    # Publish NT events to Redis Streams
│   ├── tests/
│   │   ├── test_publisher.py     # Contract tests for event format
│   │   └── test_config.py        # Config validation tests
│   ├── pyproject.toml             # Poetry dependencies
│   ├── poetry.lock                # Locked Python dependencies
│   └── Dockerfile                 # Container for producer service
│
├── analytics/                     # Go: Event processing and report generation
│   ├── cmd/
│   │   └── server/
│   │       └── main.go            # Entry point: start consumer and cache writer
│   ├── internal/
│   │   ├── consumer/              # Redis Streams consumer with XACK
│   │   │   ├── consumer.go
│   │   │   └── consumer_test.go
│   │   ├── metrics/               # Calculation logic for all market metrics
│   │   │   ├── spread.go          # Spread and micro-price calculations
│   │   │   ├── depth.go           # Order book depth and imbalance
│   │   │   ├── liquidity.go       # Walls, vacuums, volume profile
│   │   │   ├── flow.go            # Orders per second, net flow
│   │   │   ├── anomalies.go       # Spoofing, iceberg, flash crash detection
│   │   │   ├── health.go          # Health score calculation
│   │   │   └── *_test.go          # Unit and property tests for formulas
│   │   ├── aggregator/            # Report aggregation and caching
│   │   │   ├── aggregator.go      # Build complete report from metrics
│   │   │   ├── cache.go           # Write reports to Redis KV
│   │   │   └── aggregator_test.go
│   │   ├── models/                # Go structs for events and reports
│   │   │   ├── events.go          # Event envelope and payload types
│   │   │   ├── report.go          # Report structure
│   │   │   └── validation.go     # JSON schema validation
│   │   └── config/
│   │       └── config.go          # Load configuration from env vars
│   ├── go.mod
│   ├── go.sum
│   └── Dockerfile                 # Container for analytics service
│
├── mcp/                           # Go: MCP server (read-only API)
│   ├── cmd/
│   │   └── server/
│   │       └── main.go            # Entry point: start MCP HTTP server
│   ├── internal/
│   │   ├── handlers/              # HTTP/MCP request handlers
│   │   │   ├── get_report.go     # get_report(symbol) implementation
│   │   │   ├── handlers_test.go
│   │   │   └── middleware.go     # Timeout, logging middleware
│   │   ├── cache/                 # Redis KV reader
│   │   │   ├── reader.go
│   │   │   └── reader_test.go
│   │   ├── models/                # Shared report types (may import from analytics)
│   │   │   └── report.go
│   │   └── config/
│   │       └── config.go
│   ├── go.mod
│   ├── go.sum
│   └── Dockerfile                 # Container for MCP service
│
├── tests/                         # Integration and end-to-end tests
│   ├── integration/
│   │   ├── streams_test.go        # Test producer → streams → consumer flow
│   │   ├── cache_test.go          # Test analytics → cache → MCP flow
│   │   └── e2e_test.go            # Full pipeline test with docker-compose
│   └── contract/
│       ├── events_schema_test.go  # Validate event messages against schema
│       └── report_schema_test.go  # Validate reports against schema
│
├── docs/                          # Implementation documentation
│   ├── metrics.md                 # Calculation formulas, windows, edge cases
│   ├── architecture.md            # System architecture diagrams and flows
│   ├── schemas/                   # JSON schemas (source of truth)
│   │   ├── events.json
│   │   ├── report.json
│   │   └── mcp.json
│   └── runbooks/
│       ├── deployment.md          # Deployment procedures
│       ├── troubleshooting.md     # Common issues and solutions
│       └── monitoring.md          # Observability and alerting setup
│
├── .refs/                         # Reference repositories (already exists)
│   ├── INDEX.yaml                 # Catalog of reference repos
│   ├── README.md                  # Usage guide
│   └── clone.sh                   # Script to clone references
│
├── docker-compose.yml             # Orchestration for all services
├── .env.example                   # Environment variable template
├── .env                           # Actual secrets (gitignored)
├── Makefile                       # Common tasks: build, test, run, lint
└── README.md                      # Project overview and quickstart
```

**Structure Decision**:
- **Multi-service monorepo** with separate `producer/`, `analytics/`, `mcp/` directories for each component
- Python producer isolated in its own directory with Poetry dependency management
- Two Go services (`analytics/` and `mcp/`) with separate `go.mod` files for independent versioning
- Shared `tests/` directory for integration and contract tests that span multiple services
- Centralized `docs/` for schemas, formulas, and operational runbooks
- Docker Compose at repo root orchestrates all services for local development

**Rationale**: This structure maintains clear service boundaries while keeping everything in a single repository for simplified development and versioning. Each service can be built, tested, and deployed independently while sharing common documentation and integration tests.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

**Status**: ✅ No violations - this section is empty.

## Phase 0: Research & Technology Decisions

**Goal**: Resolve all "NEEDS CLARIFICATION" items from Technical Context and establish concrete technology choices based on constitution-mandated consultation with `.refs/INDEX.yaml`.

### Research Tasks

All technical decisions have been made based on:
1. Constitution mandates (Go 1.24+, NautilusTrader, Redis Streams, Binance)
2. Specification requirements (performance SLOs, feature completeness)
3. Standard Go ecosystem libraries (go-redis, testify, prometheus client)

No "NEEDS CLARIFICATION" items remain - see `research.md` for detailed decisions and rationale.

### Research Output

**File**: `specs/001-market-report-mcp/research.md`

**Contents**: Technology selections, library choices, integration patterns, and design decisions with rationale. Key decisions:
- Go library choices (go-redis/v9, chi router, testify, gopter)
- Python dependency management (Poetry with locked deps)
- Docker base images and build strategies
- Testing frameworks and mocking approaches
- Redis Streams consumer group patterns from `.refs/` examples
- Binance WebSocket integration patterns from NautilusTrader

**Next**: After research.md is generated, proceed to Phase 1.

## Phase 1: Data Models & API Contracts

**Prerequisites**: `research.md` complete, all technology choices resolved

### Deliverables

1. **data-model.md**: Entity definitions, field descriptions, validation rules, state transitions
2. **contracts/**: JSON schemas for events, reports, and MCP interface
3. **quickstart.md**: Step-by-step deployment guide with docker-compose
4. **Agent context update**: Run `.specify/scripts/bash/update-agent-context.sh claude` to update context with chosen technologies

### Data Model Extraction

From spec Key Entities section, extract and expand:
- **Market Event** (envelope)
- **Trade Tick**, **Order Book Depth**, **Order Book Delta**, **24h Ticker** (event payloads)
- **Market Report** (output structure with all sections)
- **Anomaly**, **Liquidity Wall**, **Liquidity Vacuum**, **Volume Profile** (report components)
- **Health Components**, **Ingestion Status** (metadata)

### API Contracts Generation

From functional requirements (FR-001 to FR-035), generate:
- **contracts/events.json**: JSON Schema for all Redis Streams event types
- **contracts/report.json**: JSON Schema for market report (from spec section 5.2)
- **contracts/mcp.json**: MCP tool definition with `get_report` method signature, parameters, response schema

### Quickstart Guide

Create step-by-step guide:
1. Prerequisites (Docker, Docker Compose, git)
2. Clone and setup (`.env` configuration)
3. Start services (`docker-compose up`)
4. Verify operation (check logs, test MCP endpoint)
5. Stop and cleanup
6. Troubleshooting common issues

**Next**: After Phase 1 artifacts are generated, command ends. User can proceed with `/speckit.tasks` to generate implementation tasks.

## Phase 2: Task Breakdown (NOT INCLUDED IN THIS COMMAND)

**Note**: Phase 2 (generating `tasks.md`) is performed by the separate `/speckit.tasks` command after this plan is complete.

The tasks command will create dependency-ordered implementation tasks based on:
- Milestones defined in spec section 11 (Plan postavki)
- Service boundaries from project structure
- Constitution-mandated testing and quality requirements
- Deployment and operational setup needs

Expected milestone structure (from spec):
- **M1**: Redis + message bus skeleton + logging stubs
- **M2**: NT Producer → Redis Streams with validated JSON events
- **M3**: Basic metrics (L1, spread, depth, flow) → cached reports
- **M4**: Advanced features (liquidity analysis, anomaly detection, health scoring)
- **M5**: Observability (Prometheus metrics, alerting, documentation)

## Observability Plan

**Metrics** (Prometheus, per constitution FR-030):
```
# Analytics service
context8_stream_lag_ms{symbol}           # Time between event timestamp and processing
context8_events_rate{symbol, type}        # Events processed per second by type
context8_calc_latency_ms{symbol, metric} # Time to calculate each metric component
context8_report_age_ms{symbol}           # Age of cached report data
context8_errors_total{component, type}    # Error counter by component and error type
context8_cache_writes{symbol, status}     # Report cache write attempts and outcomes

# MCP service
context8_mcp_requests_total{method, status}     # Request counter
context8_mcp_request_duration_ms{method, code}  # Request latency histogram
context8_mcp_cache_hits{symbol}                  # Cache hit counter
context8_mcp_cache_misses{symbol}                # Cache miss counter
```

**Logs** (JSON structured, per constitution §11):
```json
{
  "timestamp": "2025-10-28T12:00:00.123Z",
  "level": "info",
  "component": "analytics",
  "symbol": "BTCUSDT",
  "lag_ms": 87,
  "stream_id": "1698499200123-0",
  "event_type": "order_book_depth",
  "message": "Processed order book snapshot"
}
```

**Health Checks**:
- Producer: `/health` endpoint checks Binance WebSocket connection status
- Analytics: `/health` endpoint checks Redis Streams consumer lag and processing rate
- MCP: `/health` endpoint checks Redis cache connectivity and response time

**Alerting Thresholds** (for future integration):
- `stream_lag_ms > 2000` for >30 seconds → degraded ingestion
- `report_age_ms > 5000` → stale data alert
- `mcp_request_duration_ms p99 > 200ms` → SLO violation
- `errors_total` rate increase >10/min → investigate error spike

## Deployment Strategy

**Local Development** (docker-compose):
```yaml
services:
  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: redis-server --maxmemory 512mb --maxmemory-policy allkeys-lru

  producer:
    build: ./producer
    depends_on: [redis]
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
      BINANCE_API_KEY: ${BINANCE_API_KEY}
      SYMBOLS: BTCUSDT,ETHUSDT

  analytics:
    build: ./analytics
    depends_on: [redis, producer]
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
      CONSUMER_GROUP: context8
      LOG_LEVEL: info

  mcp:
    build: ./mcp
    depends_on: [redis, analytics]
    ports: ["8080:8080"]
    env_file: .env
    environment:
      REDIS_URL: redis://redis:6379
      TIMEOUT_MS: 150

  prometheus:
    image: prom/prometheus:latest
    ports: ["9090:9090"]
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
```

**Configuration** (`.env` file):
```bash
# Binance API (optional for public data)
BINANCE_API_KEY=
BINANCE_API_SECRET=

# Redis
REDIS_URL=redis://localhost:6379
REDIS_PASSWORD=

# Symbols to track
SYMBOLS=BTCUSDT,ETHUSDT

# Performance tuning
CACHE_TTL_SEC=300
REPORT_WINDOW_SEC=1800
FLOW_WINDOW_SEC=30

# Observability
LOG_LEVEL=info
PROMETHEUS_PORT=9090
```

**Build Process** (Makefile):
```makefile
.PHONY: build test lint run clean

build:
	cd producer && poetry install && poetry build
	cd analytics && go build -o bin/analytics ./cmd/server
	cd mcp && go build -o bin/mcp ./cmd/server

test:
	cd producer && poetry run pytest
	cd analytics && go test ./...
	cd mcp && go test ./...
	go test ./tests/integration/...
	go test ./tests/contract/...

lint:
	cd analytics && golangci-lint run
	cd mcp && golangci-lint run
	cd producer && poetry run ruff check

run:
	docker-compose up --build

clean:
	docker-compose down -v
	rm -rf analytics/bin mcp/bin
	cd producer && rm -rf dist .venv
```

## Risk Analysis

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| **NautilusTrader integration complexity** | Medium | High | Consult `.refs/` for NautilusTrader examples; use official docs; implement incremental integration with synthetic data fallback |
| **Redis Streams consumer lag under load** | Medium | Medium | Implement back-pressure with frame skipping (constitution §7); monitor `stream_lag_ms`; use miniredis for load testing |
| **Calculation formula correctness** | Low | High | Property-based tests validate invariants; unit tests with known inputs; peer review of metrics.md documentation |
| **Binance API rate limits** | Low | Medium | Use public WebSocket streams (no auth needed); implement reconnection with exponential backoff; monitor connection health |
| **Docker Compose startup timing issues** | Medium | Low | Health checks with retries; depends_on with service_healthy conditions; 20-second startup tolerance per spec SC-004 |
| **JSON schema evolution breaking changes** | Low | High | Semantic versioning for schemas; migration path documented; contract tests detect schema drift |
| **MCP timeout violations under load** | Medium | Medium | Cache-only reads (no computation); timeout middleware enforces 150ms; load testing validates SLO compliance |
| **Time synchronization issues (UTC)** | Low | Medium | All timestamps parsed/emitted in UTC RFC3339; tests verify timezone handling; NTP in containers |

## Testing Strategy

**Unit Tests** (per service):
- **Producer**: Config parsing, event serialization, Redis publishing
- **Analytics**: Each metric calculation function with edge cases (empty book, single level, extreme imbalance)
- **MCP**: Request parsing, cache reads, timeout handling, error responses

**Property-Based Tests** (`gopter`):
- Imbalance ∈ [-1, 1] for all order book states
- Micro-price always between best bid and best ask
- Health score ∈ [0, 100] for all input combinations
- spread_bps ≥ 0 for all valid bid/ask pairs

**Integration Tests** (with miniredis):
- Producer → Redis Streams: Validate event format and delivery
- Analytics → Cache: Verify complete report generation and caching
- MCP → Cache: Confirm report retrieval and timeout compliance
- End-to-end: Full pipeline with synthetic events → verify report correctness

**Contract Tests**:
- Validate all Redis Streams events against `contracts/events.json`
- Validate all cached reports against `contracts/report.json`
- Validate MCP responses against `contracts/mcp.json`
- Use JSON Schema validation libraries (Go: gojsonschema, Python: jsonschema)

**Performance Tests**:
- Load test: 200 events/sec per symbol for 5 minutes → measure lag, latency, memory
- Stress test: Single analytics instance with 5 symbols → identify breaking point
- MCP latency: 100 concurrent requests → verify p99 < 150ms

**Manual Testing**:
- Deploy with docker-compose → verify healthy startup within 20 seconds
- Stop producer container → verify degradation status transition
- Query MCP for BTCUSDT → inspect report completeness and freshness
- Generate synthetic spoofing pattern → verify anomaly detection

## Success Criteria Validation

Mapping spec Success Criteria (SC-001 to SC-012) to validation approach:

| SC | Criterion | Validation Method |
|----|-----------|-------------------|
| SC-001 | MCP response ≤150ms (99%) | Performance test with 1000 requests; measure p99 latency |
| SC-002 | Data freshness ≤1000ms when healthy | Integration test: measure time from event to cached report; verify `data_age_ms` field |
| SC-003 | Report generation ≤250ms at 100+ events/sec | Load test with sustained event rate; measure `calc_latency_ms` metric |
| SC-004 | Startup within 10-20 seconds | E2E test: time from `docker-compose up` to first valid report |
| SC-005 | Degradation detection within 2 seconds | Integration test: stop producer; measure time to `ingestion.status = degraded` |
| SC-006 | 100% schema compliance | Contract tests validate every cached report against JSON schema |
| SC-007 | Spoofing detection with synthetic data | Integration test with mock spoofing events; verify `anomalies` array content |
| SC-008 | Wall/vacuum identification accuracy | Unit tests with crafted order books; verify detection logic |
| SC-009 | Correct error responses | MCP tests for unknown symbol and Redis failure scenarios |
| SC-010 | Prometheus metrics accuracy | Integration tests verify metric values match expected calculations |
| SC-011 | Configuration via env vars | Integration test modifies env vars; verify behavior changes |
| SC-012 | Idempotent processing with duplicates | Property test replays events; verify deterministic report output |

## Next Steps

1. **Review this plan** for completeness and accuracy
2. **Execute Phase 0**: Generate `research.md` with technology decisions (auto-generated below)
3. **Execute Phase 1**: Generate `data-model.md`, `contracts/`, and `quickstart.md` (auto-generated below)
4. **Update agent context**: Run `.specify/scripts/bash/update-agent-context.sh claude`
5. **Generate tasks**: Run `/speckit.tasks` to create dependency-ordered implementation tasks
6. **Begin implementation**: Follow task order from `tasks.md`, starting with M1 (infrastructure skeleton)

---

**Plan Status**: ✅ COMPLETE
**Constitution Compliance**: ✅ ALL CHECKS PASS
**Ready for**: Phase 0 (Research) → Phase 1 (Design) → `/speckit.tasks` (Task Generation)
