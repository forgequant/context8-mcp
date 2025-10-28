# System Architecture

**Feature**: Real-Time Crypto Market Analysis MCP Server
**Last Updated**: 2025-10-28

## Overview

context8-mcp is an event-driven system that processes real-time cryptocurrency market data from Binance and serves comprehensive market analysis reports via MCP interface. The system prioritizes sub-second latency, data freshness, and observability.

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Binance Exchange                         │
│                    (WebSocket Spot Market)                      │
└─────────────────┬───────────────────────────────────────────────┘
                  │ Market data (trades, order book, 24h stats)
                  ↓
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 1: Data Ingestion (Producer)                 │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  NautilusTrader Python Service                           │   │
│  │  - Subscribe to BTCUSDT, ETHUSDT                         │   │
│  │  - Normalize events → MarketEventEnvelope                │   │
│  │  - JSON serialization (snake_case)                       │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────────┘
                  │ Publish JSON events
                  ↓
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 2: Message Bus (Redis Streams)               │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Stream Key: nt:binance                                  │   │
│  │  Consumer Group: context8                                │   │
│  │  Retention: Auto-trim >30-60 minutes                     │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────────┘
                  │ XREADGROUP + XACK
                  ↓
┌─────────────────────────────────────────────────────────────────┐
│          LAYER 3: Analytics Service (Go)                        │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Consumer → Metrics → Aggregator → Cache Writer         │   │
│  │                                                          │   │
│  │  Metrics Calculations:                                   │   │
│  │  - Spread, mid-price, micro-price                       │   │
│  │  - Depth, imbalance                                     │   │
│  │  - Liquidity walls, vacuums, volume profile            │   │
│  │  - Flow rate, net flow                                  │   │
│  │  - Anomaly detection (spoofing, iceberg, flash crash)  │   │
│  │  - Health scoring                                        │   │
│  │                                                          │   │
│  │  Report Aggregation:                                     │   │
│  │  - Combine all metrics → MarketReport                   │   │
│  │  - Validate against JSON schema                         │   │
│  │  - Calculate data_age_ms, ingestion status             │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────────┘
                  │ Write JSON reports
                  ↓
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 4: Cache (Redis KV)                          │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  Key Pattern: report:{symbol}                           │   │
│  │  Example: report:BTCUSDT → JSON MarketReport           │   │
│  │  TTL: 2-5 minutes (configurable)                        │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────────┘
                  │ GET report:{symbol}
                  ↓
┌─────────────────────────────────────────────────────────────────┐
│              LAYER 5: MCP Server (Go)                           │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  HTTP API (chi router)                                   │   │
│  │  - GET /get_report?symbol=BTCUSDT                       │   │
│  │  - Timeout: 150ms middleware                            │   │
│  │  - Cache-only reads (no computation)                    │   │
│  │  - Read-only interface (no side effects)                │   │
│  └──────────────────────────────────────────────────────────┘   │
└─────────────────┬───────────────────────────────────────────────┘
                  │ HTTP JSON response
                  ↓
┌─────────────────────────────────────────────────────────────────┐
│                        LLM Clients                              │
│              (Claude, GPT-4, etc. via MCP)                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### 1. Ingestion Flow
```
Binance WS → NT Adapter → MarketEventEnvelope → Redis XADD(nt:binance)
```

**Frequency**: 100-200 events/sec per symbol

**Events**:
- `trade_tick`: Individual trades
- `order_book_depth`: Full L2 snapshot (top 20)
- `order_book_deltas`: Incremental updates
- `ticker_24h`: Rolling 24h statistics

---

### 2. Processing Flow
```
Redis XREADGROUP → Deserialize → Calculate Metrics → Aggregate Report → Validate → Cache Write
```

**Target Latency**: <250ms from event to cached report

**Processing Steps**:
1. Consumer polls streams with consumer group "context8"
2. Deserialize JSON → Go structs
3. Calculate all metrics in parallel (where possible)
4. Aggregate into single MarketReport
5. Validate against schema and business rules
6. Write to cache with TTL

---

### 3. Serving Flow
```
MCP Request → Redis GET → JSON Response (within 150ms)
```

**SLO**: 99% of requests < 150ms

**Endpoint**: `GET /get_report?symbol=BTCUSDT`

**Error Responses**:
- 404: Symbol not indexed
- 500: Redis unavailable
- 503: Service starting up

---

## Service Responsibilities

### Producer Service (Python)
- **Technology**: Python 3.11 + NautilusTrader + Poetry
- **Responsibilities**:
  - Connect to Binance WebSocket streams
  - Subscribe to configured symbols
  - Normalize events into MarketEventEnvelope format
  - Publish to Redis Streams with XADD
  - Expose health check endpoint
- **Configuration**: Via environment variables
- **Observability**: Structured JSON logging

---

### Analytics Service (Go)
- **Technology**: Go 1.24 + go-redis + Prometheus client
- **Responsibilities**:
  - Consume events from Redis Streams (consumer group)
  - Calculate all market metrics
  - Aggregate reports with health scoring
  - Validate reports against schemas
  - Write to cache with atomic updates
  - Track ingestion status (ok/degraded/down)
  - Expose Prometheus metrics
- **Concurrency**: Goroutines for parallel metric calculation
- **Error Handling**: Idempotent processing, graceful degradation

---

### MCP Service (Go)
- **Technology**: Go 1.24 + chi router + go-redis
- **Responsibilities**:
  - Serve HTTP API for MCP clients
  - Read reports from cache (no computation)
  - Enforce 150ms timeout
  - Handle errors gracefully
  - Expose Prometheus metrics and health checks
- **Constraints**: Read-only, stateless, cache-only

---

## Deployment

### Local Development (Docker Compose)
```yaml
services:
  redis:       # Message bus + cache
  producer:    # Python NT service
  analytics:   # Go processing
  mcp:         # Go API (port 8080)
  prometheus:  # Metrics (port 9090)
```

**Startup Time**: Target <20 seconds to first valid report

**Health Checks**: All services have `/health` endpoints

---

## Observability

### Metrics (Prometheus)

**Analytics**:
- `context8_stream_lag_ms{symbol}`: Event processing lag
- `context8_events_rate{symbol, type}`: Events/sec by type
- `context8_calc_latency_ms{symbol, metric}`: Calculation time
- `context8_report_age_ms{symbol}`: Data staleness
- `context8_errors_total{component, type}`: Error counts

**MCP**:
- `context8_mcp_requests_total{method, status}`: Request counts
- `context8_mcp_request_duration_ms{method}`: Request latency (histogram)
- `context8_mcp_cache_hits{symbol}`: Cache hit rate
- `context8_mcp_cache_misses{symbol}`: Cache miss rate

### Logging (Structured JSON)

**Required Fields** (constitution §11):
- `timestamp`: ISO8601 UTC
- `level`: debug/info/warn/error
- `component`: service name
- `symbol`: trading pair
- `lag_ms`: processing latency
- `stream_id`: Redis Streams message ID

---

## Scalability Considerations

**Current Scope (MVP)**:
- 2 symbols (BTCUSDT, ETHUSDT)
- 1 exchange (Binance Spot)
- Single instance per service
- Local deployment only

**Future Scaling**:
- Horizontal scaling: Multiple analytics consumers in same consumer group
- Multi-exchange: Separate streams per venue
- Symbol sharding: Route symbols to dedicated consumers
- Geographic distribution: Edge caches closer to LLM clients

---

## Security

- **Secrets Management**: All secrets in `.env`, never committed
- **Read-Only API**: MCP server has no write capabilities
- **Input Validation**: All events validated against schemas
- **Rate Limiting**: Future consideration for public API
- **Network Isolation**: Docker Compose network for service communication

---

## Error Handling & Resilience

### Producer
- Reconnect to Binance on disconnect (exponential backoff)
- Skip malformed events, log and continue
- Health check reports WebSocket status

### Analytics
- XACK only after successful processing (at-least-once delivery)
- Idempotent processing (replay-safe)
- Graceful degradation: Report ingestion status changes
- Redis reconnection with retry logic

### MCP
- Timeout enforcement via middleware
- Graceful error responses (JSON)
- Redis failure → 500 error, don't crash
- Health check verifies Redis connectivity

---

**Status**: Foundation complete. Detailed component documentation to be added during implementation.
