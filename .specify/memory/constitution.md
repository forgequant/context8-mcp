<!--
Sync Impact Report:
===================
Version change: [unversioned] → 1.1.0
Constitution type: Minor amendment
Ratification date: 2025-10-28
Last amended: 2025-10-28

Modified principles:
  - Principle 10: "Library First" → "Reference-First Development" (expanded with mandatory .refs/ consultation)
  - Principle 12: Added .refs/ directory to documentation structure
Added sections:
  - Core Principles (0-13): Mission, Scope, Architecture, Data & Integrations, Report Rules,
    Reliability & Performance, Security & Compliance, Quality & Testing, Reference-First Development,
    Observability, Workflow & Repository, MCP Contract
  - Governance: Amendment and versioning rules
New artifacts:
  - .refs/INDEX.yaml: Mandatory reference repository catalog

Templates requiring updates:
  ✅ .specify/templates/plan-template.md - Constitution Check section needs updating
  ✅ .specify/templates/spec-template.md - Aligned with requirements structure
  ✅ .specify/templates/tasks-template.md - Aligned with testing discipline

Follow-up TODOs: None

Principle summary:
  - EDA-layered architecture with NautilusTrader → Redis Streams → Go analytics → Redis cache → MCP
  - JSON-based messaging with idempotent event handlers
  - Binance-only MVP with single symbol reports
  - Sub-second SLO for data freshness and report generation
  - Read-only MCP interface with no side effects
  - Comprehensive microstructure reporting (L1, depth, flows, anomalies)
-->

# Context8-MCP Constitution

## Core Principles

### 0. Mission and Boundaries

**Mission**: Deliver fresh market snapshots (currently crypto markets) to LLMs from a local pipeline: collection → bus → analytics → cache → MCP.

**MVP Scope**: Single exchange (Binance Spot/Futures), limited symbol set, one-symbol-per-JSON report format.

**Hard Out-of-Scope**: Trading actions (order execution), personal data storage, runtime ML model training, secrets committed to repository.

**Rationale**: Focus on read-only market intelligence delivery; defer complex trading logic and user-specific operations to future phases or separate systems.

---

### 1. Layered EDA Architecture (NON-NEGOTIABLE)

**Architecture**: Event-Driven Architecture with distinct layers:
- **Ingestion**: NautilusTrader collects market data from Binance
- **Message Bus**: Redis Streams (local deployment)
- **Analytics**: Go services consume events, compute metrics
- **Cache**: Redis stores computed reports
- **API**: MCP read-only interface serves cached reports

**Consumer Groups**: MUST use Redis consumer groups; consumers MUST acknowledge processing (XACK).

**Stream Topology**: Single stream key for MVP (e.g., `nt:binance`); no wildcard keys.

**Rationale**: Layered separation enables independent scaling, testing, and replacement of components. Consumer groups ensure at-least-once delivery with acknowledgment-based fault tolerance.

---

### 2. Message Bus Contract (NON-NEGOTIABLE)

**Transport**: Redis Streams (local), minimum Redis ≥ 6.2 for streams support.

**Message Format**:
- Content-Type: `application/json`
- Field naming: `snake_case`
- Mandatory fields: `symbol`, `venue`, `type`, `ts_event`, `payload`

**Event Types** (MVP-allowed):
- `trade_tick`: Individual trade events
- `order_book_depth`: Full order book snapshots
- `order_book_deltas`: Incremental order book updates
- `ticker_24h`: 24-hour rolling statistics

**NautilusTrader Integration**: Market events published from NautilusTrader MessageBus to external Redis Streams using JSON serialization for cross-language interoperability.

**Rationale**: JSON over Redis Streams provides language-agnostic, durable, replay-capable event log with minimal operational overhead for local deployment.

---

### 3. Idempotency and Time Handling (NON-NEGOTIABLE)

**Idempotency**: All event handlers MUST be idempotent; repeated delivery or reprocessing MUST NOT change final state beyond acceptable staleness.

**Timestamp Standard**: All timestamps in UTC (RFC3339 format); inputs converted to UTC at layer boundaries.

**Rationale**: Idempotency ensures safe retries and replay. UTC standardization eliminates timezone ambiguity in multi-source event correlation.

---

### 4. Technology Stack (NON-NEGOTIABLE)

**Backend Services**: Go ≥ 1.24 for analytics and aggregation services.

**Data Ingestion**: NautilusTrader (current stable release) with Binance integration (WebSocket + REST).

**Python Environment**: Locked via `poetry.lock` or `requirements.txt` for NautilusTrader dependencies.

**Subscription Frequency**: Maximum available (Binance Spot ~100ms updates; Futures no throttling).

**Rationale**: Go provides performance and concurrency for high-frequency event processing; NautilusTrader offers battle-tested exchange integrations; locked Python deps ensure reproducibility.

---

### 5. Data Integration and Schema

**Data Source**: NautilusTrader + Binance integration delivering:
- Trades (tick-by-tick)
- Order books (full depth and deltas)
- 24h ticker statistics

**Stream Key Convention**: `nt:binance` (single key for MVP).

**Report Cache Keys**: `report:{symbol}` (JSON value), `report:index` (generation timestamp index).

**Cache TTL**: 2–5 minutes (configurable per deployment characteristics).

**Verified Sources**: Official Binance data streams via NautilusTrader integration for book/trades/tickers; Redis Streams ≥ 6.2 for external message bus.

**Rationale**: Single-key stream simplifies MVP consumer logic; short TTL balances freshness with cache efficiency; official sources ensure data integrity.

---

### 6. Report Contract and Calculation Rules (NON-NEGOTIABLE)

**Report Semantics**: Snapshot at generation time + data quality/freshness metadata.

**Mandatory Report Fields** (MVP):

**Identification**:
- `symbol`, `generated_at`, `data_age_ms`, `venue`, `ingestion.status`

**24h Statistics**:
- `last_price`, `change_24h_pct`, `high_24h`, `low_24h`, `volume_24h`

**L1/Spread**:
- `best_bid.price`, `best_bid.qty`, `best_ask.price`, `best_ask.qty`
- `spread_bps` (basis points), `mid_price`
- `micro_price = (ask × bid_qty + bid × ask_qty) / (bid_qty + ask_qty)`

**Depth** (top 20 levels):
- `bids[]`, `asks[]` (price, quantity pairs)
- `total_bid_qty`, `total_ask_qty`
- `imbalance = (ΣQ_bid − ΣQ_ask) / (ΣQ_bid + ΣQ_ask)`

**Liquidity**:
- `walls[]` (anomalously large levels): `{side, price, qty, severity}`
- `vacuums[]` (thin ranges): `{range, depth, severity}`
- `volume_profile`: `{POC, VAH, VAL}` (Point of Control, Value Area High/Low) over rolling window

**Flows**:
- `orders_per_sec`, `net_flow` (aggressive buy volume − sell volume)

**Anomalies**:
- `anomalies[]`: `{type ∈ {spoofing, iceberg, flash_crash_risk}, severity ∈ {low, medium, high}, recommendation}`

**Health**:
- `health.score` (0–100), `health.components[]` (per-metric contributions)

**Calculation Determinism**: All formulas MUST be documented in `/docs/metrics.md`; formula changes trigger minor version bump of `report_version`.

**Rationale**: Comprehensive microstructure metrics enable LLM to assess market quality, liquidity, and risks. Deterministic formulas ensure reproducibility and auditability.

---

### 7. Reliability, Performance, and SLO (NON-NEGOTIABLE)

**SLO: Data Freshness**: `data_age_ms ≤ 1000` for `ingestion.status = "healthy"`.

**SLO: Report Generation**: ≤ 250 ms on warm cache at ≥ 100 events/sec ingestion rate.

**Degradation Handling**: When data source degrades → return last cached report with `ingestion.status = "degraded"` and `fresh = false`.

**Back-Pressure Strategy**: Under overload → coalesce (skip) intermediate order book frames; MUST NOT violate idempotency.

**Rationale**: Sub-second freshness ensures actionable market intel for LLM queries. Graceful degradation maintains service availability during transient issues.

---

### 8. Security and Compliance (NON-NEGOTIABLE)

**Secrets Management**: API keys and tokens stored ONLY in `.env` files or vault; MUST NOT commit to repository.

**Access Control**: MCP server is read-only; no external calls except Redis cache reads.

**Licensing/ToS Compliance**: Adhere to Binance API Terms of Service; raw market data MUST NOT be redistributed outside local environment.

**Rationale**: Read-only design minimizes attack surface; secrets management prevents credential leaks; ToS compliance avoids legal and access termination risks.

---

### 9. Quality and Testing (NON-NEGOTIABLE)

**Mandatory Checks**:
- `go vet`, `golangci-lint` for Go code
- Unit tests for all calculation logic
- Property-based tests for metric formulas (e.g., imbalance bounds, micro-price sanity)
- MCP contract tests (schema validation, timeout compliance)

**Schema Fixation**: JSON schemas (OpenAPI/JSON Schema) for:
- Message bus events (`.specify/schemas/events/`)
- Report output (`.specify/schemas/report.json`)

**Schema Evolution**: Any schema change MUST go through review and include migration path (if breaking).

**Calculation Documentation**: `/docs/metrics.md` MUST define all formulas, rolling windows, and edge case handling.

**Rationale**: Automated checks catch regressions early. Fixed schemas enable contract testing. Property-based tests validate invariants (e.g., imbalance ∈ [−1, 1]).

---

### 10. Reference-First Development (NON-NEGOTIABLE)

**Principle**: ALWAYS consult `.refs/INDEX.yaml` before implementing integrations, using libraries, or writing integration code.

**Mandatory Consultation Workflow**:

1. **IDENTIFY** relevant category in `.refs/INDEX.yaml` for the task at hand
2. **READ** key files from applicable reference repositories
3. **EXTRACT** working patterns, error handling, and best practices from examples
4. **ADAPT** patterns to context8-mcp architecture (document deviations in code comments)
5. **IMPLEMENT** using proven patterns from references

**Reference Index**: `.refs/INDEX.yaml` catalogs all reference repositories by category:
- Exchange Integrations (Binance API clients, WebSocket patterns)
- Redis Streams & Cache (go-redis, consumer groups, XACK patterns)
- Message Brokers (NATS, Kafka alternatives for pattern reference)
- MCP Integration (mcp-go, server implementations)
- Market Data Processing (NautilusTrader, microprice, spoofing detection)

**Enforcement**:
- Code reviews MUST verify reference consultation
- PRs MUST document which reference repositories were consulted
- Deviations from reference patterns MUST be justified in code comments

**Library Selection Criteria** (after consulting references):
- **Maturity**: Active maintenance, stable release history, production usage
- **License Compatibility**: MIT, Apache 2.0, BSD (permissive licenses preferred)
- **Dependencies**: Minimal transitive dependencies; no conflicting versions
- **Performance**: Acceptable overhead for the use case (benchmark if critical path)

**Prohibited Custom Implementations**: Do NOT reinvent:
- JSON parsing/serialization
- HTTP clients/servers (use standard library or established frameworks)
- Cryptographic primitives
- Time/date manipulation (use standard library time packages)
- Connection pooling, retry logic (use proven libraries)
- Exchange API clients (use go-binance or binance-connector-go patterns)
- Redis Streams consumers (use go-redis patterns)

**Allowed Custom Code**:
- Core domain logic (market microstructure calculations, anomaly detection algorithms)
- Thin adapters/wrappers for library integration
- Performance-critical hot paths where profiling justifies optimization

**Examples**:
```
Task: Implement Redis Streams consumer with consumer group
→ Consult .refs/INDEX.yaml → "Redis Streams & Cache" category
→ Read go-redis/stream_commands.go and examples
→ Extract XREADGROUP + XACK pattern
→ Implement with acknowledgment as shown in examples

Task: Subscribe to Binance order book WebSocket
→ Consult .refs/INDEX.yaml → "Exchange Integrations" category
→ Read go-binance/v2/websocket_service.go
→ Review nautilus_trader Binance adapter for reconnection logic
→ Implement with error handling from examples
```

**Rationale**: Reference repositories contain battle-tested code, edge case handling, and proven integration patterns. Consulting them eliminates common bugs (missed XACK, wrong WebSocket reconnection, misunderstood API contracts) and accelerates development. Combined with library-first approach, this ensures robust, maintainable implementations.

---

### 11. Observability (NON-NEGOTIABLE)

**Structured Logging**: JSON logs with mandatory fields:
- `component` (e.g., `analytics`, `cache`, `mcp`)
- `symbol`
- `lag_ms` (event processing delay)
- `stream_id` (Redis stream message ID for traceability)

**Log Levels**: `error`, `warn`, `info`, `debug` (configurable per component).

**Rationale**: Structured logs enable log aggregation, filtering, and correlation across distributed components. Lag tracking reveals performance bottlenecks.

---

### 12. Workflow and Repository (NON-NEGOTIABLE)

**Branching**: `main` + `feature/*`; PRs required for merges to `main`.

**CI Pipeline**: Tests + lint + container builds on every PR.

**Report Versioning**: Semantic versioning (`MAJOR.MINOR.PATCH`) in `report_version` field:
- **MAJOR**: Breaking schema or calculation changes
- **MINOR**: New fields, new anomaly types, formula enhancements
- **PATCH**: Bug fixes, performance improvements (no semantic change)

**Documentation Structure**:
- `/docs/metrics.md`: Calculation formulas and windows
- `/docs/schemas/*.json`: JSON schemas for events and reports
- `/docs/runbooks/*.md`: Operational procedures (restart, scaling, debugging)
- `/.refs/`: Reference repositories with code examples and implementation patterns for resolving ambiguities

**Reference Repository Usage**: When encountering unclear implementation patterns, integration approaches, or architectural questions, consult `.refs/` directory containing reference repositories with working examples.

**Rationale**: Semantic versioning communicates compatibility; documentation in repo ensures version control and discoverability. Reference repositories provide concrete, tested examples that clarify abstract patterns and reduce implementation uncertainty.

---

### 13. MCP Contract (Read-Only) (NON-NEGOTIABLE)

**Method Signature**: `get_report(symbol: string) -> ReportJSON | null`

**Guarantees**:
- Response sourced from Redis cache (no computation triggered)
- Timeout ≤ 150 ms
- Missing symbol → HTTP 404 or `null` with `symbol_not_indexed` explanation

**No Side Effects**: MCP MUST NOT initiate report recalculations, new subscriptions, or writes.

**Rationale**: Read-only contract prevents MCP layer from inducing load or side effects. Timeout ensures bounded latency for LLM tool calls.

---

## Governance

**Amendment Process**:
1. Propose changes via RFC in `/rfcs/` with justification (performance data, incident postmortems, or user requirements).
2. Review and approval required (at minimum: maintainer consensus or designated approver).
3. Increment `CONSTITUTION_VERSION` per semantic versioning rules.
4. Update `LAST_AMENDED_DATE` to amendment approval date.
5. Sync dependent templates (plan, spec, tasks) and command files.

**Versioning Policy**:
- **MAJOR**: Removal or redefinition of core principles (e.g., changing message bus technology).
- **MINOR**: Addition of new principles or material expansion of guidance.
- **PATCH**: Clarifications, typo fixes, non-semantic refinements.

**Compliance Review**:
- All PRs MUST verify constitution compliance before merge.
- Complexity or principle deviations MUST be explicitly justified in "Complexity Tracking" section of `plan.md`.
- Constitution violations without justification → PR rejected.

**Constitution Supremacy**: This document supersedes all other project practices, guidelines, and conventions. In case of conflict, constitution rules prevail.

**Version**: 1.1.0 | **Ratified**: 2025-10-28 | **Last Amended**: 2025-10-28
