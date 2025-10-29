# Monitoring and Alerting Guide

**Feature**: Real-Time Crypto Market Analysis MCP Server
**Last Updated**: 2025-10-29
**Status**: Phase 5 - Health Monitoring Implementation + US2 Multi-Instance Coordination

## Overview

This document describes the monitoring strategy, key metrics, alerting thresholds, and operational procedures for the context8-mcp system.

## Metrics Overview

All services expose Prometheus metrics on their designated ports:
- **Producer Service (NautilusTrader)**: `:9101/metrics` and `:9101/health`
- **Analytics Service**: `:9091/metrics`
- **MCP Service**: `:9092/metrics`
- **Prometheus**: `:9090` (aggregation and queries)

## Health Endpoint (T086)

### Producer Health Check

**Endpoint**: `http://<host>:9101/health`

**Description**: JSON endpoint providing node operational status and coordination state.

**Response Format**:
```json
{
  "status": "healthy",
  "node_id": "node-001",
  "uptime_seconds": 1234.56,
  "coordination": {
    "enabled": true,
    "owned_symbols": ["BTCUSDT", "ETHUSDT"],
    "configured_symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "ADAUSDT", "DOTUSDT"]
  }
}
```

**Response Fields**:
- `status`: Health status ("healthy" or "unhealthy")
- `node_id`: Node identifier from NT_NODE_ID
- `uptime_seconds`: Time since service started
- `coordination.enabled`: Whether multi-instance coordination is active
- `coordination.owned_symbols`: Symbols currently owned by this node (via HRW assignment and lease)
- `coordination.configured_symbols`: All symbols this node is configured to manage

**HTTP Status Codes**:
- `200 OK`: Node is healthy
- `503 Service Unavailable`: Node is unhealthy

**Use Cases**:
- Load balancer health checks
- Container orchestration readiness probes
- Monitoring system health verification
- Debugging symbol ownership in multi-instance deployments

**Example Queries**:
```bash
# Check node health
curl http://localhost:9101/health | jq

# Monitor owned symbols
watch -n 1 'curl -s http://localhost:9101/health | jq .coordination.owned_symbols'

# Multi-node cluster health check
for port in 9101 9102 9103; do
  echo "=== Node on port $port ==="
  curl -s http://localhost:$port/health | jq
done
```

### Key Metric Categories

1. **Data Pipeline Health** - Track data freshness and ingestion status
2. **Performance** - Monitor latencies and throughput
3. **Errors** - Track error rates by component and type
4. **Flow Metrics** - Market activity and directional pressure

---

## Critical Metrics and Thresholds

### 1. Data Freshness (Phase 5 - T093)

#### `context8_report_age_ms`
**Description**: Age of data in the most recent report (milliseconds)

**Thresholds**:
- **Healthy**: ≤ 1000ms (1 second)
- **Warning**: 1000-2000ms
- **Degraded**: 2000-5000ms
- **Critical**: > 5000ms

**Alert Rules**:
```yaml
# Warning: Data becoming stale
- alert: DataBecominglate
  expr: context8_report_age_ms > 1000
  for: 2s
  labels:
    severity: warning
  annotations:
    summary: "Market data is becoming stale"
    description: "Data age is {{ $value }}ms (threshold: 1000ms)"

# Critical: Data pipeline down
- alert: DataPipelineDown
  expr: context8_report_age_ms > 5000
  for: 10s
  labels:
    severity: critical
  annotations:
    summary: "Data pipeline is down or severely degraded"
    description: "Data age is {{ $value }}ms (threshold: 5000ms)"
```

**Remediation**:
1. Check if producer service is running and healthy
2. Verify Binance WebSocket connection is active
3. Check Redis connectivity
4. Review analytics service logs for processing errors

---

### 2. Stream Processing Lag

#### `context8_stream_lag_ms`
**Description**: Time between event timestamp and processing time

**Thresholds**:
- **Healthy**: < 100ms (p50), < 250ms (p99)
- **Warning**: p99 > 500ms
- **Critical**: p99 > 1000ms

**Alert Rules**:
```yaml
- alert: HighStreamLag
  expr: histogram_quantile(0.99, context8_stream_lag_ms) > 500
  for: 1m
  labels:
    severity: warning
  annotations:
    summary: "High stream processing lag"
    description: "P99 lag is {{ $value }}ms (threshold: 500ms)"
```

**Remediation**:
1. Check analytics service CPU/memory usage
2. Verify Redis performance (check SLOWLOG)
3. Review event processing rate vs capacity
4. Consider scaling analytics service

---

### 3. MCP API Response Time

#### `context8_mcp_request_duration_ms`
**Description**: Time to serve get_report requests

**Thresholds**:
- **Healthy**: < 50ms (p50), < 150ms (p99)
- **Warning**: p99 > 150ms
- **Critical**: p99 > 300ms

**Alert Rules**:
```yaml
- alert: SlowMCPResponses
  expr: histogram_quantile(0.99, context8_mcp_request_duration_ms) > 150
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "MCP API responses are slow"
    description: "P99 response time is {{ $value }}ms (threshold: 150ms)"
```

**Remediation**:
1. Check Redis cache hit rate
2. Verify Redis latency (PING command)
3. Check MCP service resource usage
4. Review network latency to Redis

---

### 4. Error Rates (Phase 5 - T094)

#### `context8_errors_total`
**Description**: Total errors by component and type

**Labels**:
- `component`: "aggregator", "consumer", "publisher", "mcp_handler"
- `error_type`: "publish_failed", "redis_connection", "invalid_payload", etc.

**Thresholds**:
- **Healthy**: < 1 error/min
- **Warning**: 1-10 errors/min
- **Critical**: > 10 errors/min or any sustained error pattern

**Alert Rules**:
```yaml
- alert: HighErrorRate
  expr: rate(context8_errors_total[5m]) > 0.1
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "High error rate detected"
    description: "{{ $labels.component }} is experiencing errors at {{ $value }} errors/sec"

- alert: PublishFailures
  expr: rate(context8_errors_total{error_type="publish_failed"}[5m]) > 0
  for: 1m
  labels:
    severity: critical
  annotations:
    summary: "Report publishing is failing"
    description: "Cannot publish reports to Redis cache"
```

**Remediation by Error Type**:
- `publish_failed`: Check Redis connectivity and disk space
- `redis_connection`: Verify Redis is running and accessible
- `invalid_payload`: Check producer data format, may need producer restart
- `calculation_error`: Review aggregator logs for invalid data states

---

### 5. Event Processing Rate

#### `context8_events_processed_total`
**Description**: Total number of market events processed

**Thresholds**:
- **Expected Rate**: 5-20 events/sec per symbol (varies by market activity)
- **Warning**: < 1 event/sec (possible producer issue)
- **Warning**: > 100 events/sec (possible data quality issue or burst)

**Alert Rules**:
```yaml
- alert: NoEventsProcessed
  expr: rate(context8_events_processed_total[1m]) == 0
  for: 30s
  labels:
    severity: critical
  annotations:
    summary: "No events being processed"
    description: "Event rate is zero - producer may be down"

- alert: EventRateSpike
  expr: rate(context8_events_processed_total[1m]) > 100
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Unusual event rate spike"
    description: "Event rate is {{ $value }} events/sec"
```

---

## Ingestion Status State Machine (Phase 5 - T089-T092)

### Status Values and Transitions

```
        data_age > 1s for >2s
    ok  ────────────────────→  degraded
     ↑                            │
     │                            │ data_age > 5s
     │                            ↓
     └──────────  fresh  ──────  down
           (data_age ≤ 1s)
```

### Status Definitions

#### `ok`
- **Condition**: `data_age_ms ≤ 1000`
- **Meaning**: Data pipeline is healthy, reports are fresh
- **Action**: Normal operation

#### `degraded`
- **Condition**: `data_age_ms > 1000` for more than 2 seconds
- **Meaning**: Data is stale but still flowing, possible network issues or processing delays
- **Action**:
  - Monitor closely
  - Check for upstream issues
  - Prepare for intervention if doesn't recover quickly

#### `down`
- **Condition**: `data_age_ms > 5000`
- **Meaning**: Data pipeline has failed, reports are severely outdated
- **Action**:
  - Immediate investigation required
  - Check producer service health
  - Verify Binance connection
  - Review all service logs

### Monitoring Status Transitions

**Query to track status changes**:
```promql
# Count status transitions in last 5 minutes
changes(context8_report_age_ms[5m]) > 0
```

**Alert on prolonged degraded state**:
```yaml
- alert: ProlongedDegradedState
  expr: context8_report_age_ms > 2000
  for: 30s
  labels:
    severity: warning
  annotations:
    summary: "Data pipeline degraded for >30 seconds"
    description: "Data age is {{ $value }}ms"
```

---

## Flow Metrics Monitoring (Phase 6)

### `orders_per_sec`
**Normal Range**: 1-20 events/sec for BTCUSDT/ETHUSDT

**Anomalies**:
- **< 0.5**: Very low activity, possible producer issue
- **> 50**: High volatility or news event

### `net_flow`
**Interpretation**:
- Large positive spikes: Strong buying pressure
- Large negative spikes: Strong selling pressure
- Oscillating around zero: Balanced market

**No specific alerts needed** - used for market analysis, not operational health

---

## NautilusTrader Producer Metrics (T087)

The NautilusTrader-based producer exposes operational metrics on `:9101/metrics` for monitoring embedded analytics and multi-instance coordination.

**Alert Rules**: Comprehensive Prometheus alert rules are defined in `producer/config/prometheus-alerts.yml` (T078-T081).

### Node Health Metrics

#### `nt_node_heartbeat`
**Type**: Gauge
**Labels**: `node` (node ID)
**Description**: Node heartbeat status indicator
**Values**:
- `1`: Node is alive and reporting
- `0`: Node is down or not reporting

**Usage**: Track node availability in multi-instance deployments

**Example Query**:
```promql
# Count alive nodes
sum(nt_node_heartbeat)

# Nodes that went down in last 5 minutes
changes(nt_node_heartbeat[5m]) < 0
```

#### `nt_symbols_assigned`
**Type**: Gauge
**Labels**: `node` (node ID)
**Description**: Number of symbols currently owned by this node
**Usage**: Monitor symbol distribution across nodes in multi-instance mode

**Alert Example**:
```yaml
- alert: ImbalancedSymbolDistribution
  expr: max(nt_symbols_assigned) - min(nt_symbols_assigned) > 2
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Uneven symbol distribution across nodes"
    description: "Max assigned: {{ $value }}, consider rebalancing"
```

### Calculation Performance Metrics

#### `nt_calc_latency_ms`
**Type**: Histogram
**Labels**:
- `metric`: Name of metric calculated (e.g., "spread", "depth", "flow")
- `cycle`: Cycle type ("fast" or "slow")

**Description**: Time taken to calculate individual metrics in milliseconds
**Buckets**: [1, 5, 10, 20, 50, 100, 200, 500, 1000, 2000]

**Thresholds**:
- **Healthy**: p99 < 50ms for fast cycle, < 200ms for slow cycle
- **Warning**: p99 > 100ms for fast cycle, > 500ms for slow cycle
- **Critical**: p99 > 250ms for fast cycle, > 1000ms for slow cycle

**Example Queries**:
```promql
# P99 calculation latency by metric
histogram_quantile(0.99, rate(nt_calc_latency_ms_bucket[5m])) by (metric, cycle)

# Average fast cycle latency
rate(nt_calc_latency_ms_sum{cycle="fast"}[5m]) / rate(nt_calc_latency_ms_count{cycle="fast"}[5m])

# Slow calculations (>100ms)
rate(nt_calc_latency_ms_bucket{le="100"}[5m])
```

**Alert Example**:
```yaml
- alert: SlowCalculations
  expr: histogram_quantile(0.99, rate(nt_calc_latency_ms_bucket{cycle="fast"}[5m])) > 100
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Fast cycle calculations are slow"
    description: "P99 latency is {{ $value }}ms (threshold: 100ms)"
```

### Publishing Metrics

#### `nt_report_publish_total`
**Type**: Counter
**Labels**: `symbol`
**Description**: Total number of reports published per symbol

**Usage**: Track report generation rate and identify stalled symbols

**Example Queries**:
```promql
# Reports per second by symbol
rate(nt_report_publish_total[1m])

# Symbols with no recent reports
rate(nt_report_publish_total[1m]) == 0
```

#### `nt_data_age_ms`
**Type**: Histogram
**Labels**: `symbol`
**Description**: Data age in milliseconds (time between data timestamp and publish time)
**Buckets**: [10, 50, 100, 250, 500, 750, 1000, 1500, 2000, 5000]

**Thresholds**:
- **Healthy**: p99 < 500ms
- **Warning**: p99 > 1000ms
- **Critical**: p99 > 2000ms

**Usage**: Monitor data freshness and detect processing delays

**Example Queries**:
```promql
# P99 data age by symbol
histogram_quantile(0.99, rate(nt_data_age_ms_bucket[5m])) by (symbol)

# Average data age
rate(nt_data_age_ms_sum[5m]) / rate(nt_data_age_ms_count[5m])
```

### Coordination Metrics (Multi-Instance Mode)

#### `nt_lease_conflicts_total`
**Type**: Counter
**Description**: Number of lease conflicts detected (multiple nodes attempting to own same symbol)

**Thresholds**:
- **Normal**: 0-1 conflicts/hour (expected during rebalancing)
- **Warning**: > 5 conflicts/hour
- **Critical**: > 20 conflicts/hour (indicates configuration or Redis issues)

**Example Query**:
```promql
# Lease conflicts per hour
rate(nt_lease_conflicts_total[1h]) * 3600
```

**Alert Example**:
```yaml
- alert: FrequentLeaseConflicts
  expr: rate(nt_lease_conflicts_total[1h]) * 3600 > 5
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Frequent lease conflicts detected"
    description: "{{ $value }} conflicts/hour (threshold: 5)"
```

#### `nt_hrw_rebalances_total`
**Type**: Counter
**Description**: Number of HRW rebalancing cycles executed

**Usage**: Track rebalancing frequency and detect excessive churn

**Example Query**:
```promql
# Rebalancing rate
rate(nt_hrw_rebalances_total[5m])
```

#### `nt_ws_resubscribe_total`
**Type**: Counter
**Labels**: `reason` (e.g., "disconnect", "symbol_acquired", "symbol_released")
**Description**: Number of WebSocket resubscription events

**Thresholds**:
- **Normal**: < 1 resubscription/min per node
- **Warning**: > 5 resubscriptions/min (connection instability)
- **Critical**: > 20 resubscriptions/min (persistent connection issues)

**Example Queries**:
```promql
# Resubscription rate by reason
rate(nt_ws_resubscribe_total[5m]) by (reason)

# Total resubscriptions (all reasons)
sum(rate(nt_ws_resubscribe_total[5m]))
```

**Alert Example**:
```yaml
- alert: FrequentWebSocketReconnects
  expr: rate(nt_ws_resubscribe_total{reason="disconnect"}[5m]) > 0.083  # 5/min
  for: 2m
  labels:
    severity: warning
  annotations:
    summary: "Frequent WebSocket reconnections"
    description: "Reconnecting {{ $value }} times/sec"
```

### Dashboard Panels for NautilusTrader Metrics

**Recommended Grafana Panels**:

1. **Node Health Overview**
   - Stat panel: Count of alive nodes (`sum(nt_node_heartbeat)`)
   - Table: Node ID, symbols assigned, uptime

2. **Symbol Distribution**
   - Bar chart: Symbols per node (`nt_symbols_assigned`)
   - Heatmap: Symbol ownership over time

3. **Calculation Performance**
   - Heatmap: Calculation latency by metric and cycle
   - Line chart: P50, P95, P99 latencies over time

4. **Data Freshness**
   - Line chart: Data age P99 by symbol
   - Gauge: Current data age (latest value)

5. **Coordination Health**
   - Counter: Lease conflicts over time
   - Line chart: Rebalancing frequency
   - Stacked area: WebSocket resubscriptions by reason

---

## Dashboard Recommendations

### Primary Dashboard Panels

1. **Data Freshness**
   - Gauge: Current `context8_report_age_ms`
   - Time series: Last 15 minutes
   - Color thresholds: Green (<1s), Yellow (1-5s), Red (>5s)

2. **Ingestion Status**
   - Single stat: Current status ("ok", "degraded", "down")
   - Time series: Status transitions over time

3. **Processing Performance**
   - Stream lag histogram (p50, p95, p99)
   - MCP response time histogram
   - Calculation latency histogram

4. **Throughput**
   - Event processing rate (events/sec)
   - Report generation rate (reports/sec)
   - MCP request rate (requests/sec)

5. **Errors**
   - Error rate by component (stacked area chart)
   - Error breakdown by type (table)
   - Recent error log entries

6. **Flow Metrics**
   - Orders per second (line chart)
   - Net flow (line chart with +/- coloring)

### Example Grafana Query

```promql
# Data age over time
context8_report_age_ms

# P99 stream lag
histogram_quantile(0.99, rate(context8_stream_lag_ms_bucket[5m]))

# Error rate by component
sum(rate(context8_errors_total[5m])) by (component)

# Event processing rate
rate(context8_events_processed_total[1m])
```

---

## Testing Health Monitoring (Phase 5 - T096)

### Test Procedure: Degradation Detection

**Objective**: Verify ingestion status state machine transitions work correctly

**Steps**:
1. Ensure system is healthy (`status = "ok"`)
2. Stop producer service:
   ```bash
   docker stop context8-producer
   ```
3. Monitor logs and metrics:
   ```bash
   # Watch analytics logs for status transitions
   docker logs -f context8-analytics | grep ingestion_status_transition

   # Query Prometheus
   curl http://localhost:9090/api/v1/query?query=context8_report_age_ms
   ```

**Expected Behavior**:
- **T+0s**: Status remains `"ok"` (data age starts increasing)
- **T+2s**: Transition log: `"ok" → "degraded"` (after 2 seconds of stale data)
- **T+5s**: Transition log: `"degraded" → "down"` (data age > 5000ms)

4. Restart producer:
   ```bash
   docker start context8-producer
   ```

**Expected Recovery**:
- **T+recovery**: Transition log: `"down" → "ok"` (fresh data received)
- **Data age**: Drops below 1000ms
- **Fresh flag**: Returns to `true`

**Verification**:
```bash
# Check current report status
curl http://localhost:8080/get_report?symbol=BTCUSDT | jq '.ingestion'

# Expected output after recovery:
# {
#   "status": "ok",
#   "fresh": true
# }
```

---

## Operational Procedures

### Daily Checks
- ✅ All services healthy (docker compose ps)
- ✅ Data age < 1000ms
- ✅ No error spikes in last 24h
- ✅ Event processing rate is normal

### Weekly Reviews
- Review error patterns and trends
- Analyze performance degradation over time
- Check for resource utilization trends
- Verify backup and recovery procedures

### Incident Response

**If ingestion status is "degraded" or "down"**:
1. Check service health: `docker compose ps`
2. Review recent logs: `docker compose logs --tail=100 producer analytics`
3. Verify Redis connectivity: `docker exec context8-redis redis-cli PING`
4. Check Binance API status (external monitoring)
5. Restart affected services if needed
6. Document incident and root cause

**If MCP responses are slow**:
1. Check Redis latency
2. Verify cache hit rate
3. Review report generation latency
4. Check for resource contention

---

## Alerting Best Practices

1. **Use appropriate severity levels**:
   - `info`: Informational, no action needed
   - `warning`: Requires attention, not urgent
   - `critical`: Immediate action required

2. **Set reasonable `for` durations**:
   - Avoid alert fatigue from transient spikes
   - Balance between quick detection and false positives

3. **Include actionable context**:
   - Clear summary of the problem
   - Relevant metric values
   - Link to runbook or remediation steps

4. **Test alerts regularly**:
   - Simulate failure conditions
   - Verify notification delivery
   - Practice incident response procedures

---

## Next Steps

After Phase 5-6 implementation:
- [ ] Configure Prometheus alert rules in `prometheus.yml`
- [ ] Set up Alertmanager for notification routing
- [ ] Create Grafana dashboards
- [ ] Test all alerting scenarios
- [ ] Document incident response procedures

**Status**: Health monitoring and flow metrics are now implemented and ready for operational use.
