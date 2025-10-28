# Research & Technology Decisions

**Feature**: Real-Time Crypto Market Analysis MCP Server
**Date**: 2025-10-28
**Status**: Complete - All decisions finalized

## Executive Summary

All technology choices have been made based on:
1. **Constitution mandates** (Go 1.24+, NautilusTrader, Redis Streams, Binance)
2. **Specification requirements** (sub-second latency, comprehensive metrics, read-only MCP)
3. **Reference-first development** (consultation with `.refs/INDEX.yaml` for proven patterns)
4. **Ecosystem maturity** (stable libraries with production usage)

**No clarifications needed** - all decisions are concrete and justified below.

---

## 1. Language & Runtime Decisions

### Decision: Go 1.24+ for Analytics and MCP Services

**Rationale**:
- **Constitution mandate** (Principle 4): Backend services MUST use Go ≥ 1.24
- **Performance**: Native concurrency model (goroutines) ideal for event processing at 100+ events/sec
- **Type safety**: Compile-time validation reduces runtime errors in critical calculation logic
- **Deployment**: Single static binary simplifies Docker images and reduces attack surface
- **Ecosystem**: Mature libraries for Redis, HTTP, metrics, testing

**Alternatives Considered**:
- Python: Rejected - constitution mandates Go for analytics; Python reserved for NT integration
- Rust: Rejected - steeper learning curve, smaller ecosystem for this use case, overkill for MVP

### Decision: Python 3.11+ for Producer Service

**Rationale**:
- **Constitution mandate** (Principle 4): NautilusTrader is Python-based
- **Integration**: Native NautilusTrader support eliminates need for FFI or subprocess spawning
- **Stability**: Python 3.11 offers performance improvements while maintaining library compatibility
- **Dependency locking**: Poetry provides deterministic builds (constitution requirement)

**Alternatives Considered**:
- Go with Python subprocess: Rejected - adds complexity, harder to debug, no clear benefit
- Python for entire stack: Rejected - constitution mandates Go for analytics

---

## 2. Core Library Selections

### 2.1 Redis Client (Go)

**Decision**: `github.com/redis/go-redis/v9`

**Rationale**:
- **Industry standard**: Most widely used Redis client for Go
- **Streams support**: Full Redis Streams API including XREADGROUP, XACK, consumer groups
- **Connection pooling**: Built-in pool management for performance
- **Type safety**: Strongly typed API reduces errors
- **Testing support**: Works with miniredis for in-memory testing

**Consulted References** (from `.refs/INDEX.yaml`):
- `go-redis` repository examples for consumer group patterns
- Redis Streams documentation for XACK idempotency patterns

**Alternatives Considered**:
- `gomodule/redigo`: Rejected - lower-level API, less type-safe, declining maintenance
- `mediocregopher/radix`: Rejected - smaller ecosystem, fewer examples

**Key Implementation Patterns** (from references):
```go
// Consumer group with XACK (pattern from go-redis examples)
streams, err := client.XReadGroup(ctx, &redis.XReadGroupArgs{
    Group:    "context8",
    Consumer: "analytics-1",
    Streams:  []string{"nt:binance", ">"},
    Count:    10,
    Block:    time.Second,
})
// Process events...
client.XAck(ctx, "nt:binance", "context8", msg.ID)
```

### 2.2 HTTP Router (Go)

**Decision**: `github.com/go-chi/chi/v5`

**Rationale**:
- **Lightweight**: Minimal overhead, fast routing (critical for 150ms MCP timeout)
- **Stdlib-compatible**: Uses standard `net/http` interfaces, easy testing
- **Middleware support**: Timeout, logging, metrics middleware built-in
- **Context-aware**: First-class support for request context (needed for timeout propagation)

**Alternatives Considered**:
- `gorilla/mux`: Rejected - heavier, slower, declining activity
- stdlib only: Rejected - boilerplate for middleware and route groups
- `gin`: Rejected - more opinionated, unnecessary features for read-only API

### 2.3 Metrics & Observability (Go)

**Decision**: `github.com/prometheus/client_golang`

**Rationale**:
- **Constitution mandate** (FR-030): Prometheus metrics required
- **Standard format**: Industry-standard exposition format
- **Built-in types**: Counter, Gauge, Histogram match our needs (lag, rate, latency)
- **Zero dependencies**: No external services needed for local dev

**Key Metrics** (as defined in plan.md):
- `context8_stream_lag_ms{symbol}` - Gauge
- `context8_events_rate{symbol, type}` - Counter → rate calculation
- `context8_calc_latency_ms{symbol, metric}` - Histogram
- `context8_mcp_request_duration_ms{method, code}` - Histogram

### 2.4 Testing Frameworks (Go)

**Decisions**:
- **Unit/Integration**: `github.com/stretchr/testify` (assertions and mocking)
- **Property-based**: `github.com/leanovate/gopter` (formula invariant testing)
- **In-memory Redis**: `github.com/alicebob/miniredis/v2` (integration tests without real Redis)
- **JSON Schema**: `github.com/xeipuuv/gojsonschema` (contract validation)

**Rationale**:
- `testify`: Most popular Go testing library, readable assertions, suite support
- `gopter`: QuickCheck-style property testing for mathematical invariants (e.g., imbalance ∈ [-1, 1])
- `miniredis`: Full Redis Streams implementation in-memory, deterministic tests, fast CI
- `gojsonschema`: Mature JSON Schema Draft 7 support, used in production systems

**Example Property Test**:
```go
properties := gopter.NewProperties(nil)
properties.Property("imbalance always in [-1, 1]", prop.ForAll(
    func(bidQty, askQty float64) bool {
        imbalance := calculateImbalance(bidQty, askQty)
        return imbalance >= -1.0 && imbalance <= 1.0
    },
    gen.Float64Range(0, 1000000),
    gen.Float64Range(0, 1000000),
))
properties.TestingRun(t)
```

### 2.5 Python Dependencies (Producer)

**Decisions**:
- **Dependency management**: Poetry (with `poetry.lock` committed)
- **NautilusTrader**: Latest stable from PyPI
- **Redis client**: `redis-py` (official Python Redis client)
- **Testing**: `pytest` + `pytest-asyncio` (NT is async-based)
- **Linting**: `ruff` (fast, comprehensive)

**Rationale**:
- Poetry: Constitution requires locked dependencies; Poetry is modern standard for Python
- `redis-py`: Official client, supports Redis Streams, async-capable
- `pytest`: De facto standard for Python testing, excellent async support
- `ruff`: Orders of magnitude faster than pylint/flake8, catches more issues

**Poetry Configuration**:
```toml
[tool.poetry.dependencies]
python = "^3.11"
nautilus_trader = "^1.200"  # Use latest stable
redis = "^5.0"
pydantic = "^2.0"  # For config validation

[tool.poetry.group.dev.dependencies]
pytest = "^7.4"
pytest-asyncio = "^0.21"
ruff = "^0.1"
```

---

## 3. NautilusTrader Integration Strategy

### Decision: Use NautilusTrader MessageBus with Redis Streams External Publishing

**Rationale**:
- **Constitution mandate** (Principle 2): NautilusTrader MUST publish to Redis Streams in JSON
- **Official support**: NautilusTrader has built-in external message bus adapters
- **Separation of concerns**: NT handles exchange complexity, we handle analytics
- **Reliability**: NT manages WebSocket reconnection, rate limiting, authentication

**Consulted References**:
- NautilusTrader documentation: external message bus configuration
- NautilusTrader Binance adapter: event types and schemas
- `.refs/` examples of NT integration patterns

**Implementation Approach**:
1. Configure NT with Binance adapter for BTCUSDT, ETHUSDT
2. Enable external streaming to Redis Streams with JSON serialization
3. Subscribe to: trades, order book depth (L2), order book deltas, 24h ticker
4. NT publishes to `nt:binance` stream key in our event envelope format

**Configuration Pattern**:
```python
# NT configuration (simplified)
data_engine_config = {
    "external_streams": {
        "enabled": True,
        "encoding": "json",
        "target": "redis",
        "redis_url": os.getenv("REDIS_URL"),
        "stream_key": "nt:binance",
        "types_filter": ["trade", "depth", "deltas", "ticker"]
    }
}
```

**Fallback for Testing**: Synthetic event generator in Go for integration tests (avoids NT dependency in tests)

---

## 4. Docker & Deployment Decisions

### 4.1 Base Images

**Decisions**:
- **Go services**: `golang:1.24-alpine` (build) → `alpine:3.19` (runtime)
- **Python producer**: `python:3.11-slim`
- **Redis**: `redis:7-alpine`

**Rationale**:
- Alpine: Minimal attack surface, small image size (~5-10MB for Go binary)
- Multi-stage builds: Separate build and runtime reduces final image size by 10x
- Official images: Security updates, proven stability

**Go Dockerfile Pattern** (from references):
```dockerfile
# Build stage
FROM golang:1.24-alpine AS builder
WORKDIR /build
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o server ./cmd/server

# Runtime stage
FROM alpine:3.19
RUN apk add --no-cache ca-certificates tzdata
COPY --from=builder /build/server /server
ENTRYPOINT ["/server"]
```

### 4.2 Docker Compose Strategy

**Decision**: Single `docker-compose.yml` with health checks and service dependencies

**Rationale**:
- **Simplicity**: One command (`docker-compose up`) starts entire stack
- **Health checks**: Ensure services start in correct order (Redis → Producer → Analytics → MCP)
- **Local development**: Matches production-like environment without k8s overhead

**Health Check Pattern**:
```yaml
services:
  redis:
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  analytics:
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:8081/health"]
```

---

## 5. Testing Strategy Refinement

### 5.1 Test Pyramid

**Unit Tests** (70%):
- Each metric calculation function in isolation
- Mock Redis client with miniredis for consumer/cache logic
- Fast feedback loop (<1 second for all unit tests)

**Integration Tests** (20%):
- Full component interactions with real-ish dependencies (miniredis)
- Producer → Streams → Consumer flow
- Analytics → Cache → MCP flow
- Contract validation (JSON schema compliance)

**E2E Tests** (10%):
- Docker Compose stack with synthetic event generator
- Validate end-to-end latency and correctness
- Slow but comprehensive (run in CI only)

### 5.2 Contract Testing Approach

**Decision**: JSON Schema validation with automated test generation

**Rationale**:
- **Constitution mandate** (Principle 9): Schema fixation required
- **Cross-language**: Go and Python both validate against same schemas
- **Automated**: Generate tests from schemas, catch drift immediately

**Test Generation Pattern**:
```go
// Auto-generated from contracts/events.json
func TestEventSchemaCompliance(t *testing.T) {
    schema := loadSchema("contracts/events.json")
    events := []Event{/* test cases */}

    for _, event := range events {
        result, err := schema.Validate(gojsonschema.NewGoLoader(event))
        assert.NoError(t, err)
        assert.True(t, result.Valid())
    }
}
```

---

## 6. Performance Optimization Strategies

### 6.1 Memory Pooling

**Decision**: Use `sync.Pool` for frequently allocated structs (order book levels, trade ticks)

**Rationale**:
- Reduce GC pressure at 100+ events/sec
- Proven pattern from Go references (high-frequency trading systems)
- Minimal code complexity, significant performance gain

### 6.2 Event Batching

**Decision**: Process events in batches of 10 from Redis Streams

**Rationale**:
- Reduce Redis round trips (network latency)
- Amortize XACK overhead across multiple events
- Balance between latency and throughput

### 6.3 Calculation Caching

**Decision**: Cache intermediate calculations within report generation cycle

**Rationale**:
- Volume profile calculation is expensive (price binning over 30-minute window)
- Mid-price used by multiple downstream calculations
- In-memory cache per report generation (no cross-report caching to ensure freshness)

---

## 7. Observability Implementation

### 7.1 Structured Logging

**Decision**: `log/slog` (Go 1.21+ standard library)

**Rationale**:
- **Standard library**: No external dependency
- **JSON output**: Constitution requires structured logs
- **Context propagation**: Integrates with `context.Context` for request tracing
- **Performance**: Zero-allocation logging for hot paths

**Log Format** (per constitution §11):
```json
{
  "time": "2025-10-28T12:00:00.123Z",
  "level": "INFO",
  "msg": "Processed order book snapshot",
  "component": "analytics",
  "symbol": "BTCUSDT",
  "lag_ms": 87,
  "stream_id": "1698499200123-0",
  "event_type": "order_book_depth"
}
```

### 7.2 Distributed Tracing (Future)

**Decision**: Defer to post-MVP; design for OpenTelemetry compatibility

**Rationale**:
- MVP is single-instance, local deployment (no distributed tracing needed yet)
- Context.Context pattern enables easy OTEL integration later
- Current logs + metrics sufficient for troubleshooting MVP issues

---

## 8. Configuration Management

### Decision: Environment variables with `envconfig` pattern

**Rationale**:
- **Constitution mandate** (FR-031): All config from env vars
- **12-factor app**: Standard pattern for configuration
- **Type safety**: Struct tags provide validation and defaults
- **Docker-friendly**: Easy to override in docker-compose or k8s

**Configuration Struct Pattern**:
```go
type Config struct {
    RedisURL        string        `env:"REDIS_URL" envDefault:"redis://localhost:6379"`
    ConsumerGroup   string        `env:"CONSUMER_GROUP" envDefault:"context8"`
    StreamKey       string        `env:"STREAM_KEY" envDefault:"nt:binance"`
    CacheTTL        time.Duration `env:"CACHE_TTL_SEC" envDefault:"300s"`
    LogLevel        string        `env:"LOG_LEVEL" envDefault:"info"`
    PrometheusPort  int           `env:"PROMETHEUS_PORT" envDefault:"9090"`
}

func LoadConfig() (*Config, error) {
    var cfg Config
    if err := envconfig.Process("", &cfg); err != nil {
        return nil, err
    }
    return &cfg, nil
}
```

---

## 9. Risk Mitigations

### 9.1 NautilusTrader Complexity

**Mitigation**:
- Incremental integration: Start with single symbol, verify data flow
- Synthetic fallback: Generate mock events for testing without NT
- Documentation: Detailed runbook for NT configuration and troubleshooting

### 9.2 Redis Streams Consumer Lag

**Mitigation**:
- Back-pressure: Skip intermediate order book frames under load (constitution §7 allows)
- Monitoring: Alert on `stream_lag_ms > 2000` for >30 seconds
- Load testing: Validate performance with miniredis + synthetic high-frequency events

### 9.3 Calculation Correctness

**Mitigation**:
- Property-based tests: Validate invariants (imbalance bounds, micro-price range)
- Unit tests: Known inputs with expected outputs (golden tests)
- Peer review: metrics.md documentation reviewed for formula accuracy
- Reference implementation: Compare against industry-standard formulas (e.g., VWAP, POC)

---

## 10. Open Questions & Future Research

**None** - All decisions finalized for MVP.

**Post-MVP Considerations** (out of scope for this plan):
1. **Multi-exchange support**: Research unified event schema across Binance, Coinbase, Kraken
2. **Horizontal scaling**: Investigate Redis Streams consumer group sharding strategies
3. **Machine learning anomalies**: Evaluate online learning models for spoofing detection
4. **Historical replay**: Design data retention and replay capabilities for backtesting

---

## 11. Reference Consultation Summary

Per constitution Principle 10 (Reference-First Development), the following references from `.refs/INDEX.yaml` were consulted:

### Consulted References:

1. **Redis Streams & Cache**:
   - `go-redis` repository: Consumer group patterns, XREADGROUP + XACK examples
   - Redis Streams documentation: Idempotency patterns, consumer group best practices

2. **Exchange Integrations**:
   - NautilusTrader documentation: External message bus configuration
   - NautilusTrader Binance adapter: Event types, schemas, WebSocket patterns

3. **MCP Integration**:
   - MCP specification: Tool definition schema, timeout requirements
   - mcp-go examples: HTTP server patterns, error handling

4. **Market Data Processing**:
   - Industry references: Micro-price formula, volume profile (POC/VAH/VAL) calculations
   - Academic papers: Spoofing detection heuristics, order book imbalance metrics

### Key Patterns Extracted:

- **XACK pattern**: Always acknowledge after successful processing, not before (prevents message loss on crash)
- **Reconnection logic**: Exponential backoff with jitter for WebSocket reconnections
- **Health checks**: Combine connectivity check + functional check (e.g., Redis PING + sample read)
- **Timeout propagation**: Use `context.WithTimeout` at HTTP layer, propagate to Redis calls

---

## 12. Decision Log

| Decision | Category | Rationale | Date |
|----------|----------|-----------|------|
| Go 1.24+ for analytics/MCP | Language | Constitution mandate, performance, type safety | 2025-10-28 |
| Python 3.11+ for producer | Language | NautilusTrader requirement, constitution mandate | 2025-10-28 |
| go-redis/v9 | Library | Industry standard, Streams support, type safety | 2025-10-28 |
| chi/v5 router | Library | Lightweight, stdlib-compatible, fast | 2025-10-28 |
| testify + gopter | Testing | Popular, property-based testing support | 2025-10-28 |
| miniredis | Testing | In-memory Redis, deterministic, fast | 2025-10-28 |
| Poetry | Python Deps | Locked dependencies, constitution requirement | 2025-10-28 |
| Alpine base images | Docker | Small size, security, official images | 2025-10-28 |
| log/slog | Logging | Standard library, structured, performant | 2025-10-28 |
| Prometheus client_golang | Metrics | Constitution mandate, standard format | 2025-10-28 |
| NT external streams | Integration | Constitution mandate, separation of concerns | 2025-10-28 |
| Docker Compose | Deployment | Simple, matches prod-like env, health checks | 2025-10-28 |

---

## 13. Next Steps

1. ✅ **Research complete** - All technology decisions finalized
2. ⏭️ **Proceed to Phase 1** - Generate data models, contracts, quickstart guide
3. 📋 **After Phase 1** - Run `/speckit.tasks` to generate implementation tasks
4. 🚀 **Implementation** - Begin with M1 (infrastructure skeleton)

---

**Research Status**: ✅ COMPLETE
**Consultation**: ✅ `.refs/INDEX.yaml` consulted per constitution
**Decisions**: ✅ All finalized with rationale
**Ready for**: Phase 1 (Data Models & Contracts)
