# Feature Specification: Real-Time Crypto Market Analysis MCP Server

**Feature Branch**: `001-market-report-mcp`
**Created**: 2025-10-28
**Status**: Draft
**Input**: User description: "context8 — MVP for real-time crypto market analytics with MCP interface"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - LLM Queries Market State (Priority: P1)

An LLM assistant needs to answer user questions about current crypto market conditions for BTCUSDT or ETHUSDT on Binance, such as "What's the current spread?" or "Is there unusual trading activity?" The assistant calls the MCP server to get a structured market report and uses it to provide accurate, real-time answers.

**Why this priority**: This is the core value proposition - enabling LLMs to access fresh, structured market data for informed decision-making. Without this, the entire system has no purpose.

**Independent Test**: Can be fully tested by invoking the MCP `get_report` method for a symbol and verifying that a valid, fresh JSON report is returned within acceptable time limits. This delivers immediate value as a read-only data source.

**Acceptance Scenarios**:

1. **Given** the market data pipeline is running, **When** an LLM calls `get_report("BTCUSDT")`, **Then** it receives a JSON report with current price, spread, depth, and health metrics within 150ms
2. **Given** fresh market data is flowing, **When** the report is generated, **Then** the `data_age_ms` field shows data freshness ≤1000ms and `ingestion.fresh` is true
3. **Given** normal market conditions, **When** an LLM requests a report, **Then** the report includes all required fields: prices, spreads, order book depth, liquidity indicators, flow metrics, and health score
4. **Given** the LLM needs to understand data quality, **When** reviewing the report, **Then** the `ingestion.status` field indicates whether data ingestion is operating normally ("ok"), degraded, or down

---

### User Story 2 - Engineer Deploys System Locally (Priority: P1)

A developer or trader wants to run the market analysis system on their local machine to start collecting and analyzing Binance market data. They execute a single command to start all components and verify the system is working.

**Why this priority**: Without a working deployment, no one can use the system. This is foundational infrastructure that must work before any value can be delivered.

**Independent Test**: Can be fully tested by running `docker-compose up`, waiting 10-20 seconds, and verifying that all containers are healthy and that calling `get_report("BTCUSDT")` returns a valid report with `fresh=true`.

**Acceptance Scenarios**:

1. **Given** Docker and Docker Compose are installed, **When** an engineer runs `docker-compose up`, **Then** all containers (Redis, NT Producer, Go Analytics, Go MCP) start successfully
2. **Given** all containers are running, **When** 10-20 seconds have elapsed, **Then** calling `get_report("BTCUSDT")` returns a valid report with `fresh=true`
3. **Given** the system is running normally, **When** configuration needs to be changed, **Then** all secrets and settings can be modified via environment variables in `.env` file
4. **Given** the system has been running, **When** an engineer checks container logs, **Then** they can see clear evidence of data flowing through the pipeline (trades, order book updates, report generations)

---

### User Story 3 - Trader Monitors Market Anomalies (Priority: P2)

A crypto trader wants to detect unusual market behavior (spoofing, iceberg orders, flash crash risks) automatically. They query the market report periodically and receive alerts when anomalies are detected with severity levels.

**Why this priority**: This provides advanced intelligence beyond basic price data, helping users identify market manipulation and risks. It's valuable but not essential for basic operation.

**Independent Test**: Can be fully tested by generating synthetic market data that simulates spoofing patterns (large orders far from mid, rapid cancellations) and verifying that the report's `anomalies` array contains appropriate entries with correct severity levels.

**Acceptance Scenarios**:

1. **Given** large limit orders appear far from the mid price and are rapidly cancelled, **When** a report is generated, **Then** the `anomalies` array includes a "spoofing" entry with severity "medium" or "high"
2. **Given** a series of similar partial fills occur at one price level while visible depth remains constant, **When** a report is generated, **Then** the `anomalies` array includes an "iceberg" detection
3. **Given** the spread is widening, the order book is thin (many vacuums), and net flow is increasingly negative, **When** a report is generated, **Then** the `anomalies` array includes a "flash_crash_risk" warning
4. **Given** normal market conditions with no unusual patterns, **When** a report is generated, **Then** the `anomalies` array is empty or contains only "low" severity items

---

### User Story 4 - LLM Analyzes Liquidity Conditions (Priority: P2)

An LLM needs to advise a user about optimal trade execution. It queries the market report to understand liquidity depth, identify large buy/sell walls, find thin areas (vacuums) in the order book, and assess volume profile to recommend execution strategies.

**Why this priority**: This enables sophisticated trading advice based on market microstructure. It's valuable for serious traders but not essential for basic market monitoring.

**Independent Test**: Can be fully tested by setting up test order books with known large orders (walls) and thin regions (vacuums), then verifying that the report's `liquidity` section correctly identifies these features with accurate price levels and quantities.

**Acceptance Scenarios**:

1. **Given** unusually large orders exist at specific price levels, **When** a report is generated, **Then** the `liquidity.walls` array identifies these with accurate price and quantity values
2. **Given** there are price ranges with very low depth, **When** a report is generated, **Then** the `liquidity.vacuums` array identifies these thin regions with "from" and "to" price boundaries
3. **Given** trading activity over the past 30 minutes, **When** a report is generated, **Then** the `liquidity.profile` includes POC (point of control), VAH (value area high), and VAL (value area low) derived from volume distribution
4. **Given** an order book with balanced depth, **When** a report is generated, **Then** the `depth.imbalance` value is close to zero; given an imbalanced book, the value approaches +1 (bid-heavy) or -1 (ask-heavy)

---

### User Story 5 - System Diagnoses Data Quality Issues (Priority: P3)

An engineer or automated monitoring system needs to understand if the data pipeline is healthy. When the data producer stops or slows down, the system detects this and reports degraded status, allowing operators to troubleshoot.

**Why this priority**: This supports operational reliability and debugging. It's important for production use but not blocking for initial development and testing with stable data.

**Independent Test**: Can be fully tested by stopping the NT Producer container and verifying that subsequent reports show `ingestion.status` transitioning from "ok" to "degraded" or "down", `fresh` becoming false, and `data_age_ms` increasing over time.

**Acceptance Scenarios**:

1. **Given** the NT Producer is running normally, **When** market data is flowing, **Then** reports show `ingestion.status: "ok"` and `fresh: true`
2. **Given** the NT Producer stops sending data, **When** sufficient time has passed (>1 second), **Then** new reports show `ingestion.status: "degraded"` or `"down"` and `fresh: false`
3. **Given** data ingestion has stopped, **When** reports are generated over time, **Then** the `data_age_ms` field increases, reflecting how stale the cached data has become
4. **Given** degraded data quality, **When** an LLM queries for a report, **Then** it receives the report with clear indicators of staleness, allowing it to warn users or decline to answer

---

### User Story 6 - System Tracks Market Flow and Velocity (Priority: P3)

A quantitative analyst wants to understand market activity intensity and directional flow. They query reports to see order book update rates (orders per second) and net buying/selling pressure (net flow) over recent time windows.

**Why this priority**: This provides additional context for market dynamics. It's useful for advanced analysis but not essential for basic price and depth monitoring.

**Independent Test**: Can be fully tested by generating synthetic market data with known trade and order book update frequencies, then verifying that `flow.orders_per_sec` accurately reflects the event rate and `flow.net_flow` correctly sums aggressive buy volume minus aggressive sell volume.

**Acceptance Scenarios**:

1. **Given** a known rate of trade and order book events (e.g., 100 events in 10 seconds), **When** a report is generated, **Then** `flow.orders_per_sec` reflects approximately 10 events/second
2. **Given** aggressive buy orders dominate over a 30-second window, **When** a report is generated, **Then** `flow.net_flow` is positive, indicating net buying pressure
3. **Given** aggressive sell orders dominate over a 30-second window, **When** a report is generated, **Then** `flow.net_flow` is negative, indicating net selling pressure
4. **Given** balanced buying and selling activity, **When** a report is generated, **Then** `flow.net_flow` is close to zero

---

### Edge Cases

- **What happens when a requested symbol has never been indexed?** The MCP server returns an error indicating `symbol_not_indexed` (404/null response), allowing the LLM to inform the user that the symbol is not tracked.
- **How does the system handle Redis becoming unavailable?** The MCP server returns a `backend_unavailable` error, and the LLM can inform the user of a temporary service outage.
- **What if market data arrives out of order or with duplicates?** The analytics component must handle idempotent processing and tolerate duplicate events via consumer group acknowledgment (`XACK`), ensuring consistent report generation.
- **What happens during extreme market volatility (e.g., flash crash)?** The system detects rapidly widening spreads, thin order books, and negative net flow, reporting a "flash_crash_risk" anomaly with high severity to warn users.
- **What if the order book snapshot is incomplete or corrupted?** The analytics component validates incoming data, skips invalid entries, and continues processing; if data quality is too poor, `ingestion.status` transitions to "degraded".
- **How does the system handle symbols that are temporarily delisted or suspended by Binance?** The NT Producer stops receiving data for that symbol; reports for affected symbols will show increasing `data_age_ms` and `fresh: false`, signaling staleness.
- **What if the analytics component lags behind the data stream?** Consumer group lag metrics (via Prometheus `stream_lag_ms`) alert operators; reports may show slightly increased `data_age_ms` but remain valid as long as lag is within acceptable bounds.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide an MCP method `get_report(symbol: string)` that returns a JSON report for the specified crypto pair (initially BTCUSDT and ETHUSDT)
- **FR-002**: System MUST ingest real-time market data from Binance Spot market, including trade ticks, order book depth snapshots, order book deltas, and 24-hour ticker data
- **FR-003**: System MUST publish ingested market events to Redis Streams with JSON encoding, using a standardized message envelope with fields: `type`, `venue`, `symbol`, `ts_event`, and `payload`
- **FR-004**: System MUST consume market events from Redis Streams using a consumer group (named "context8") to enable reliable, distributed processing with acknowledgment
- **FR-005**: System MUST calculate and include in reports: last price, 24h price change percentage, 24h high/low, 24h volume, best bid/ask with quantities
- **FR-006**: System MUST calculate spread in basis points: `(ask - bid) / bid * 10000`
- **FR-007**: System MUST calculate mid price: `(bid + ask) / 2`
- **FR-008**: System MUST calculate micro price (volume-weighted): `(ask * bidQty + bid * askQty) / (bidQty + askQty)`
- **FR-009**: System MUST maintain top 20 levels of bid and ask depth from the order book, including price and quantity for each level
- **FR-010**: System MUST calculate order book imbalance: `(sum_bid - sum_ask) / (sum_bid + sum_ask)` where sums are over top 20 levels
- **FR-011**: System MUST identify "walls" (large concentrated orders) when level quantity exceeds `max(P95 * 1.5, configurable_minimum)` where P95 is the 95th percentile of quantities in a rolling window
- **FR-012**: System MUST identify "vacuums" (thin liquidity regions) where depth over several ticks falls below a threshold (P10 percentile) and merge adjacent thin regions
- **FR-013**: System MUST calculate volume profile over a 30-minute rolling window, aggregating trade volume into price bins and identifying POC (price with maximum volume), VAH, and VAL (boundaries covering 70% of volume around POC)
- **FR-014**: System MUST calculate order flow rate: average number of events (trades + order book deltas) over the last 10 seconds
- **FR-015**: System MUST calculate net flow: volume of aggressive buys minus aggressive sells over the last 30 seconds
- **FR-016**: System MUST detect spoofing patterns: large limit orders far from mid price with high cancellation rates, generating severity-rated anomaly entries
- **FR-017**: System MUST detect iceberg order patterns: series of similar partial fills at one price with stable visible depth
- **FR-018**: System MUST detect flash crash risk: widening spread + thin order book (many vacuums) + negative net flow with increasing velocity
- **FR-019**: System MUST calculate a health score (0-100) as a weighted sum of normalized components: spread (20%), depth (25%), balance (15%), flow (15%), anomalies (15%), freshness (10%)
- **FR-020**: System MUST track data freshness with `data_age_ms` (milliseconds since last data update) and `fresh` boolean flag (true if data_age_ms ≤ 1000ms)
- **FR-021**: System MUST track ingestion status with values: "ok" (normal operation), "degraded" (slow or intermittent data), "down" (no data)
- **FR-022**: System MUST store generated reports in Redis key-value store with key pattern `report:{symbol}`
- **FR-023**: System MUST respond to MCP `get_report` requests within 150ms timeout
- **FR-024**: System MUST return `symbol_not_indexed` error when requesting a report for an untracked symbol
- **FR-025**: System MUST return `backend_unavailable` error when Redis is unreachable
- **FR-026**: System MUST be read-only via the MCP interface (no mutations allowed)
- **FR-027**: System MUST use UTC timestamps in RFC3339 format for all time fields
- **FR-028**: System MUST validate all Redis Streams messages against the defined JSON schema (envelope structure)
- **FR-029**: System MUST validate all generated reports against the report JSON schema before storing
- **FR-030**: System MUST expose Prometheus metrics including: `stream_lag_ms`, `events_rate`, `calc_latency_ms`, `report_age_ms`, `errors_total`
- **FR-031**: System MUST load all configuration (Redis connection, time windows, thresholds) from environment variables
- **FR-032**: System MUST store all secrets (Redis password, API keys) in `.env` file, not in code or version control
- **FR-033**: System MUST process events idempotently to tolerate duplicate event delivery from Redis Streams
- **FR-034**: System MUST deploy all components (Redis, NT Producer, Go Analytics, Go MCP) via Docker Compose for local execution
- **FR-035**: System MUST auto-trim Redis Streams data older than 30-60 minutes to prevent unbounded growth

### Key Entities *(include if feature involves data)*

- **Market Event**: A time-stamped occurrence from the exchange (trade, order book change, ticker update) with a type, venue, symbol, event timestamp, and type-specific payload
- **Trade Tick**: A completed trade with price, quantity, side (buy/sell), and trade identifier
- **Order Book Depth**: A snapshot of the top N levels (default 20) of bids and asks, each level having price and quantity
- **Order Book Delta**: An incremental update to the order book, containing arrays of bid and ask price-quantity pairs that changed
- **24h Ticker**: Aggregated statistics for the past 24 hours including last price, price change percentage, high, low, volume, and best bid/ask
- **Market Report**: A comprehensive, point-in-time analysis of a symbol containing prices, spreads, depth, liquidity features (walls, vacuums, volume profile), flow metrics, anomalies, health score, and data quality indicators
- **Anomaly**: A detected pattern of unusual market behavior (spoofing, iceberg, flash crash risk) with a type, severity level (low/medium/high), and optional descriptive note
- **Liquidity Wall**: A large order at a specific price level identified when quantity exceeds dynamic thresholds based on recent distribution
- **Liquidity Vacuum**: A price range where order book depth is unusually thin, representing potential slippage risk
- **Volume Profile**: A distribution of traded volume across price levels over a time window, including POC (point of control - price with most volume), VAH (value area high), and VAL (value area low)
- **Health Components**: Individual scores for different market quality aspects (spread tightness, depth adequacy, balance, flow activity, anomaly presence, data freshness) that combine into an overall health score
- **Ingestion Status**: An indicator of the data pipeline health ("ok", "degraded", "down") based on data arrival rates and staleness

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: LLM clients receive market reports for tracked symbols within 150ms response time in 99% of requests
- **SC-002**: Market reports reflect data freshness of 1 second or less (`data_age_ms ≤ 1000`) when the data pipeline is operating normally (`ingestion.status = "ok"`)
- **SC-003**: The analytics component generates reports with calculation latency ≤ 250ms on a "warm" cache under load of 100+ events per second
- **SC-004**: The system successfully starts all components via `docker-compose up` and produces valid reports within 10-20 seconds of startup
- **SC-005**: When the data producer is stopped, reports correctly transition to showing `ingestion.status = "degraded"` or `"down"`, `fresh = false`, and increasing `data_age_ms` within 2 seconds
- **SC-006**: All generated reports pass JSON schema validation against the defined report schema with 100% compliance
- **SC-007**: The system detects and reports spoofing patterns with appropriate severity when synthetic spoofing data is injected (validated via integration tests)
- **SC-008**: The system correctly identifies large order walls and liquidity vacuums when test order books with known features are processed (validated via unit tests)
- **SC-009**: The MCP interface returns correct error responses (`symbol_not_indexed`, `backend_unavailable`) when tested against failure scenarios
- **SC-010**: The system exposes Prometheus metrics that accurately reflect stream lag, event processing rate, calculation latency, report age, and error counts
- **SC-011**: Engineers can configure all operational parameters (time windows, thresholds, Redis connection) via environment variables without code changes
- **SC-012**: The consumer group processes events idempotently, with duplicate events not causing incorrect metric calculations (validated via property tests with repeated events)

## Assumptions

- **Assumption 1**: Binance Spot market data is accessible via public WebSocket and REST APIs without requiring special permissions or paid subscriptions
- **Assumption 2**: NautilusTrader library supports Binance Spot integration and can publish events to Redis Streams in JSON format
- **Assumption 3**: The local development environment has sufficient resources (CPU, memory, network) to run Redis, Python data producer, and Go services simultaneously
- **Assumption 4**: Redis Streams provides sufficient throughput and reliability for the expected event rate (hundreds of events per second per symbol)
- **Assumption 5**: Initial deployment targets local development environment; cloud deployment and scaling considerations are out of scope for MVP
- **Assumption 6**: Go is an acceptable implementation language for the analytics and MCP components (based on project preferences for performance and deployment simplicity)
- **Assumption 7**: Python with NautilusTrader is an acceptable implementation for the data ingestion component
- **Assumption 8**: The MCP protocol supports JSON request/response for tool calls, allowing the `get_report` method to return structured data
- **Assumption 9**: Two symbols (BTCUSDT, ETHUSDT) are sufficient for MVP validation; multi-symbol scaling is a post-MVP concern
- **Assumption 10**: Standard Prometheus metrics format is acceptable for observability; no custom monitoring infrastructure required
- **Assumption 11**: Docker and Docker Compose are available on all target deployment environments
- **Assumption 12**: Time windows (30m for volume profile, 10s for order rate, 30s for net flow) are reasonable defaults and can be tuned later based on empirical data

## Dependencies

- **External Dependency 1**: Binance public APIs must remain available and accessible; changes to API schemas or rate limits could impact data ingestion
- **External Dependency 2**: NautilusTrader library must support the required Binance integration and Redis Streams publishing capabilities
- **External Dependency 3**: Redis server (version 7+) must be available with Streams and key-value storage functionality
- **External Dependency 4**: MCP protocol specification and compatible client libraries must support JSON-based tool definitions and responses
- **External Dependency 5**: Docker and Docker Compose must be installed on deployment targets
- **Internal Dependency 1**: The NT Producer must publish events in the agreed JSON envelope format to Redis Streams before the analytics component can function
- **Internal Dependency 2**: The analytics component must generate and store valid reports in Redis before the MCP server can serve them
- **Internal Dependency 3**: JSON schemas for both stream messages and reports must be defined and validated before integration testing can proceed

## Out of Scope

- Support for exchanges other than Binance (Coinbase, Kraken, etc.) - future enhancement
- Support for futures, options, or margin markets - focusing on Spot only for MVP
- Historical data replay or backtesting capabilities - real-time operation only
- User authentication, authorization, or multi-tenancy - single-user local deployment assumed
- Persistent storage of historical reports beyond current cached values - ephemeral reports only
- Advanced anomaly detection using machine learning models - MVP uses heuristic-based detection
- Alerting or notification systems for detected anomalies - reporting only, no push notifications
- WebSocket or streaming report APIs - pull-based MCP interface only
- High availability, failover, or disaster recovery configurations - single-instance deployment
- Performance optimization for > 10 symbols - MVP targets 2 symbols
- Customizable formulas or pluggable metric calculations - fixed calculation logic in MVP
- Report retention policies or report history querying - only current report available
- Integration with trading execution systems - read-only market analysis, no order placement
- Custom dashboards or visualization UIs - data access via MCP only, presentation left to LLM/client
