# Quickstart: Embedded Market Analytics Deployment

**Feature**: 002-nt-embedded-analytics
**Date**: 2025-10-28
**Purpose**: Local deployment guide for testing embedded analytics with horizontal scaling

---

## Prerequisites

### System Requirements
- Docker Engine 24+ and Docker Compose 2.x
- 8GB RAM minimum (16GB recommended for multi-instance)
- 4 CPU cores minimum
- 20GB disk space

### Optional
- Binance API key (for production data; not required for testnet)
- jq (JSON processor for command-line testing)

### Verify Installation
```bash
docker --version  # Should be 24+
docker compose version  # Should be 2.x
jq --version  # Optional but recommended
```

---

## Configuration

### Step 1: Copy Environment Template
```bash
cp .env.example .env
```

### Step 2: Configure Embedded Analytics
Edit `.env`:
```bash
# Enable embedded analytics (NEW)
NT_ENABLE_KV_REPORTS=true

# Disable Redis Streams publishing (optional, for performance)
NT_ENABLE_STREAMS=false

# Symbols to track
SYMBOLS=BTCUSDT,ETHUSDT

# Embedded analytics configuration
NT_REPORT_PERIOD_MS=250      # Fast cycle: L1/L2/flow (4 Hz)
NT_SLOW_PERIOD_MS=2000       # Slow cycle: volume profile, anomalies (0.5 Hz)
NT_LEASE_TTL_MS=2000         # Writer lease TTL
NT_NODE_ID=nt-local-01       # Unique node identifier

# Coordination settings
NT_HRW_STICKY_PCT=0.02       # Hysteresis: 2% sticky bonus
NT_MIN_HOLD_MS=2000          # Min hold time before reassignment

# Metrics
NT_METRICS_PORT=9101         # Prometheus endpoint

# Redis
REDIS_URL=redis://redis:6379
REDIS_PASSWORD=

# Binance (optional - leave empty for testnet)
BINANCE_API_KEY=
BINANCE_API_SECRET=
```

---

## Deployment Scenarios

### Scenario 1: Single Instance (MVP)

**Use Case**: Testing embedded analytics with 2-5 symbols, single producer.

#### Start Services
```bash
docker compose up -d redis producer mcp prometheus
```

#### Wait for Startup (20 seconds)
```bash
sleep 20
docker compose ps
```

Expected output:
```
NAME                   STATUS    PORTS
context8_redis         Up        6379/tcp
context8_producer      Up        9101/tcp (metrics)
context8_mcp           Up        8080/tcp (API)
context8_prometheus    Up        9090/tcp
```

#### Verify Producer Metrics
```bash
curl -s http://localhost:9101/metrics | grep nt_node_heartbeat
# Should show: nt_node_heartbeat{node="nt-local-01"} 1

curl -s http://localhost:9101/metrics | grep nt_symbols_assigned
# Should show: nt_symbols_assigned{node="nt-local-01"} 2
```

#### Query Market Report
```bash
curl -s http://localhost:8080/get_report?symbol=BTCUSDT | jq
```

Expected response structure:
```json
{
  "schemaVersion": "1.1",
  "writer": {
    "nodeId": "nt-local-01",
    "writerToken": 1
  },
  "updatedAt": 1730112345678,
  "symbol": "BTCUSDT",
  "venue": "BINANCE",
  "data_age_ms": 234,
  "ingestion": {"status": "ok"},
  "last_price": 64105.50,
  ...
}
```

#### Verify Data Freshness
```bash
curl -s http://localhost:8080/get_report?symbol=BTCUSDT | jq '.data_age_ms'
# Should be < 1000 (target: ≤ 1000ms for "ok" status)
```

#### Check Health Score
```bash
curl -s http://localhost:8080/get_report?symbol=BTCUSDT | jq '.health.score'
# Should be 70-95 (composite score)
```

#### Monitor Logs
```bash
docker compose logs -f producer | grep "event_processed\|report_published"
```

---

### Scenario 2: Multi-Instance Deployment (Horizontal Scaling)

**Use Case**: Testing symbol assignment, failover, and writer leases with 15 symbols across 3 producers.

#### Update Configuration
Edit `.env`:
```bash
SYMBOLS=BTCUSDT,ETHUSDT,BNBUSDT,ADAUSDT,XRPUSDT,DOGEUSDT,SOLUSDT,MATICUSDT,DOTUSDT,LTCUSDT,AVAXUSDT,LINKUSDT,UNIUSDT,ATOMUSDT,APTUSDT
```

#### Create Multi-Instance Compose Override
Create `docker-compose.override.yml`:
```yaml
services:
  producer-1:
    build: ./producer
    environment:
      - NT_NODE_ID=nt-prod-01
      - NT_METRICS_PORT=9101
      - SYMBOLS=${SYMBOLS}
    ports:
      - "9101:9101"
    depends_on:
      - redis

  producer-2:
    build: ./producer
    environment:
      - NT_NODE_ID=nt-prod-02
      - NT_METRICS_PORT=9102
      - SYMBOLS=${SYMBOLS}
    ports:
      - "9102:9102"
    depends_on:
      - redis

  producer-3:
    build: ./producer
    environment:
      - NT_NODE_ID=nt-prod-03
      - NT_METRICS_PORT=9103
      - SYMBOLS=${SYMBOLS}
    ports:
      - "9103:9103"
    depends_on:
      - redis
```

#### Start Multi-Instance Cluster
```bash
docker compose up -d redis producer-1 producer-2 producer-3 mcp prometheus
sleep 30  # Wait for startup + assignment
```

#### Verify Symbol Distribution
```bash
# Check producer-1 assignments
curl -s http://localhost:9101/metrics | grep nt_symbols_assigned
# Expected: nt_symbols_assigned{node="nt-prod-01"} 5

# Check producer-2 assignments
curl -s http://localhost:9102/metrics | grep nt_symbols_assigned
# Expected: nt_symbols_assigned{node="nt-prod-02"} 5

# Check producer-3 assignments
curl -s http://localhost:9103/metrics | grep nt_symbols_assigned
# Expected: nt_symbols_assigned{node="nt-prod-03"} 5
```

#### Verify Lease Ownership (via Redis CLI)
```bash
docker compose exec redis redis-cli KEYS "report:writer:*"
# Should show 15 keys (one per symbol)

docker compose exec redis redis-cli GET "report:writer:BTCUSDT"
# Shows which node holds lease, e.g., "nt-prod-01"
```

#### Test Failover (Kill Producer-2)
```bash
# Kill producer-2
docker compose stop producer-2

# Wait for lease expiration + reassignment
sleep 3

# Verify symbols redistributed
curl -s http://localhost:9101/metrics | grep nt_symbols_assigned
# Expected: nt_symbols_assigned{node="nt-prod-01"} 7-8 (acquired orphaned symbols)

curl -s http://localhost:9103/metrics | grep nt_symbols_assigned
# Expected: nt_symbols_assigned{node="nt-prod-03"} 7-8
```

#### Verify No Duplicate Writers
```bash
# Check writer tokens for a symbol
curl -s http://localhost:8080/get_report?symbol=ETHUSDT | jq '.writer'

# Wait 5 seconds and check again
sleep 5
curl -s http://localhost:8080/get_report?symbol=ETHUSDT | jq '.writer'

# writerToken should be same or increased (never decreased)
# nodeId might change (from nt-prod-02 to nt-prod-01/03 after failover)
```

#### Check Rebalancing Metrics
```bash
curl -s http://localhost:9101/metrics | grep nt_hrw_rebalances_total
# Should increment after producer-2 stopped

curl -s http://localhost:9101/metrics | grep nt_lease_conflicts_total
# Should be 0 or very low (indicates no split-brain)
```

#### Restore Producer-2
```bash
docker compose start producer-2
sleep 5

# Verify producer-2 rejoins cluster
curl -s http://localhost:9102/metrics | grep nt_node_heartbeat
# Should show: nt_node_heartbeat{node="nt-prod-02"} 1

# Symbols will gradually rebalance back (with hysteresis delay)
```

---

### Scenario 3: Parallel Testing (Old Go Analytics + New NT Analytics)

**Use Case**: Validate calculation parity between Go analytics service and embedded NT analytics.

#### Enable Parallel Profile
Edit `docker-compose.override.yml`:
```yaml
services:
  producer:
    environment:
      - NT_ENABLE_KV_REPORTS=true
      - NT_ENABLE_STREAMS=true  # Keep streams for Go analytics
    profiles:
      - parallel-test

  analytics:
    # Existing Go analytics service
    environment:
      - REPORT_KEY_SUFFIX=:go  # Publish to report:{symbol}:go
    profiles:
      - parallel-test
```

#### Start Parallel Test
```bash
docker compose --profile parallel-test up -d
sleep 30
```

#### Compare Reports
```bash
# Get report from NT analytics
curl -s http://localhost:8080/get_report?symbol=BTCUSDT > /tmp/report_nt.json

# Get report from Go analytics (via different key or endpoint)
docker compose exec redis redis-cli GET "report:BTCUSDT:go" > /tmp/report_go.json

# Compare (ignoring writer metadata and timestamps)
diff <(jq 'del(.writer, .updatedAt, .generated_at, .data_age_ms)' /tmp/report_nt.json) \
     <(jq 'del(.writer, .updatedAt, .generated_at, .data_age_ms)' /tmp/report_go.json)
```

Expected: Small differences in floating-point rounding (spread_bps, micro_price) within tolerance (±0.0001).

---

## Troubleshooting

### Issue 1: Lease Conflicts (High `nt_lease_conflicts_total`)

**Symptoms**: Multiple producers attempting to write same symbol, writerToken fluctuating.

**Diagnosis**:
```bash
curl -s http://localhost:9101/metrics | grep nt_lease_conflicts_total
# If > 10 in first minute, investigate
```

**Likely Causes**:
- Clock skew between Docker containers (>100ms)
- Lease TTL too short (< 2x renewal interval)
- Network latency to Redis >50ms

**Fix**:
```bash
# Increase lease TTL
export NT_LEASE_TTL_MS=3000  # 3 seconds instead of 2
docker compose restart producer-1 producer-2 producer-3
```

---

### Issue 2: Heartbeat Failures

**Symptoms**: Producer losing all symbol assignments, `nt_node_heartbeat` drops to 0.

**Diagnosis**:
```bash
docker compose logs producer | grep "heartbeat_failed\|redis_connection_error"
```

**Likely Causes**:
- Redis connection lost
- Producer process hanging (GIL contention, blocking operation)

**Fix**:
```bash
# Check Redis connectivity
docker compose exec producer ping -c 3 redis

# Restart producer
docker compose restart producer
```

---

### Issue 3: Slow Cycle Lagging

**Symptoms**: Volume profile, liquidity features not updating, or updating slowly.

**Diagnosis**:
```bash
curl -s http://localhost:9101/metrics | grep 'nt_calc_latency_ms.*slow'
# Check p99 latency bucket
```

**Likely Causes**:
- Insufficient trades for volume profile (< 10 trades in 30 min window)
- Slow-cycle calculations exceeding period (500ms > 2000ms budget)

**Fix**:
```bash
# Increase slow cycle period
export NT_SLOW_PERIOD_MS=5000  # 5 seconds instead of 2
docker compose restart producer
```

---

### Issue 4: Report Missing Fields

**Symptoms**: MCP returns report without `liquidity.volume_profile` or other optional fields.

**Expected**: This is normal if insufficient data (e.g., < 10 trades in 30 min window).

**Diagnosis**:
```bash
curl -s http://localhost:8080/get_report?symbol=BTCUSDT | jq '.liquidity.volume_profile // "MISSING"'
```

**Fix**: Wait for more trade data to accumulate (may take 30 minutes for volume profile).

---

### Issue 5: Data Age Exceeds SLO (`data_age_ms > 1000`)

**Symptoms**: Ingestion status "degraded", reports stale.

**Diagnosis**:
```bash
curl -s http://localhost:8080/get_report?symbol=BTCUSDT | jq '.data_age_ms, .ingestion.status'
```

**Likely Causes**:
- Binance WebSocket disconnected
- Fast-cycle calculations taking too long (>250ms period)

**Fix**:
```bash
# Check WebSocket connection
docker compose logs producer | grep "websocket.*connected\|websocket.*error"

# Reduce symbol count per instance (if overloaded)
# Or increase fast cycle period
export NT_REPORT_PERIOD_MS=500  # Slower cadence
```

---

## Metrics Dashboard

### Prometheus Queries

Access Prometheus UI: `http://localhost:9090`

**Data Freshness (P95)**:
```promql
histogram_quantile(0.95, rate(nt_data_age_ms_bucket[5m]))
```
Target: < 1000ms

**Calculation Latency by Metric**:
```promql
histogram_quantile(0.99, rate(nt_calc_latency_ms_bucket[5m])) by (metric)
```
Target: fast-cycle < 20ms, slow-cycle < 500ms

**Symbol Assignment per Node**:
```promql
nt_symbols_assigned
```

**Lease Conflicts Rate**:
```promql
rate(nt_lease_conflicts_total[5m])
```
Target: < 0.1/min (near-zero)

**Rebalancing Frequency**:
```promql
rate(nt_hrw_rebalances_total[10m])
```
Should spike after node join/leave, then stabilize

---

## Cleanup

### Stop All Services
```bash
docker compose down
```

### Remove Volumes (Reset Redis Data)
```bash
docker compose down -v
```

### Remove Images (Full Cleanup)
```bash
docker compose down --rmi all -v
```

---

## Next Steps

1. **Run Chaos Tests**: See `producer/tests/system/test_chaos.py` for automated failover testing
2. **Tune Hysteresis**: Adjust `NT_HRW_STICKY_PCT` and `NT_MIN_HOLD_MS` based on rebalancing frequency
3. **Scale to 30+ Symbols**: Update `SYMBOLS` list, deploy 3-4 producer instances
4. **Monitor Production**: Set up Grafana dashboards using Prometheus queries above
5. **Parallel Test**: Run side-by-side with Go analytics for 1-2 weeks before migration

---

## Common Commands Cheat Sheet

```bash
# Check node heartbeat
curl -s http://localhost:9101/metrics | grep nt_node_heartbeat

# Check symbol assignments
curl -s http://localhost:9101/metrics | grep nt_symbols_assigned

# Get report
curl -s http://localhost:8080/get_report?symbol=BTCUSDT | jq .

# Check data freshness
curl -s http://localhost:8080/get_report?symbol=BTCUSDT | jq '.data_age_ms'

# View producer logs
docker compose logs -f producer | grep "report_published\|lease_acquired"

# Check Redis lease keys
docker compose exec redis redis-cli KEYS "report:writer:*"
docker compose exec redis redis-cli GET "report:writer:BTCUSDT"

# Monitor rebalancing
watch -n 1 'curl -s http://localhost:9101/metrics | grep nt_hrw_rebalances_total'

# Force failover test
docker compose stop producer-2 && sleep 3 && docker compose start producer-2
```

---

**For issues not covered here, check**: `docs/runbooks/troubleshooting.md` or open GitHub issue.
