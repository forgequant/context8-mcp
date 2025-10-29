# NautilusTrader Embedded Analytics - Troubleshooting Guide

**User Story 4: Operational Observability (T088)**
**Last Updated**: 2025-10-29

This runbook provides systematic troubleshooting procedures for common issues in the NautilusTrader producer service with embedded analytics.

---

## Quick Reference

| Symptom | Likely Cause | Section |
|---------|--------------|---------|
| Market data is stale (P95 age > 1s) | Exchange connection, Redis issues | [Stale Data](#1-market-data-stale) |
| Lease conflicts spike | Clock skew, Redis connectivity | [Lease Conflicts](#2-lease-conflicts) |
| Excessive rebalancing | Node flapping, network issues | [Excessive Rebalancing](#3-excessive-rebalancing) |
| Producer node shows down | Process crashed, heartbeat timeout | [Node Down](#4-producer-node-down) |
| Fast cycle processing slow | CPU overload, too many symbols | [Slow Processing](#5-slow-calculation-performance) |
| Low report publish rate | Symbol not assigned, producer stuck | [Low Publish Rate](#6-low-report-publish-rate) |
| WebSocket reconnection loops | Exchange API issues, network | [WebSocket Issues](#7-websocket-reconnection-loops) |

---

## 1. Market Data Stale

### Symptoms
- Prometheus alert: `MarketDataStale` or `MarketDataCritical`
- Metric: `nt_data_age_ms` P95 > 1000ms (warning) or > 5000ms (critical)
- Health endpoint shows old `owned_symbols` data

### Root Causes

#### A. Exchange WebSocket Disconnected
**Diagnosis:**
```bash
# Check producer logs for WebSocket errors
docker logs producer | grep -i "websocket\|disconnect\|reconnect"

# Check resubscription metric
curl -s http://localhost:9101/metrics | grep nt_ws_resubscribe_total
```

**Resolution:**
1. Check exchange API status (e.g., https://www.binance.com/en/support)
2. Verify network connectivity to exchange:
   ```bash
   docker exec producer ping -c 4 api.binance.com
   ```
3. If persistent, restart producer:
   ```bash
   docker compose restart producer
   ```

#### B. Redis Write Failures
**Diagnosis:**
```bash
# Check Redis connectivity
docker exec producer redis-cli -h redis PING

# Check Redis slowlog
docker exec context8-redis redis-cli SLOWLOG GET 10

# Check Redis memory
docker exec context8-redis redis-cli INFO memory
```

**Resolution:**
1. If Redis is down:
   ```bash
   docker compose restart redis
   ```
2. If Redis is out of memory:
   ```bash
   # Check maxmemory policy
   docker exec context8-redis redis-cli CONFIG GET maxmemory-policy

   # Increase memory limit or enable eviction
   docker exec context8-redis redis-cli CONFIG SET maxmemory-policy allkeys-lru
   ```

#### C. Producer CPU/Memory Overload
**Diagnosis:**
```bash
# Check producer resource usage
docker stats producer --no-stream

# Check if slow cycle is lagging
docker logs producer | grep "slow_cycle_lag_detected"
```

**Resolution:**
1. Reduce number of symbols per producer (scale horizontally)
2. Increase container CPU/memory limits in docker-compose.yml
3. Disable slow-cycle analytics temporarily:
   ```bash
   # Set slow cycle period to 0 to disable
   docker compose run -e NT_SLOW_PERIOD_MS=0 producer
   ```

---

## 2. Lease Conflicts

### Symptoms
- Prometheus alert: `LeaseConflictSpike`
- Metric: `nt_lease_conflicts_total` rate > 0.1 conflicts/sec
- Logs show: `lease_conflict: fencing_token_mismatch`

### Root Causes

#### A. Clock Skew Between Nodes
**Diagnosis:**
```bash
# Check system time on all producer nodes
docker exec producer-node-001 date
docker exec producer-node-002 date
docker exec producer-node-003 date

# Check time difference (should be < 100ms)
```

**Resolution:**
1. Enable NTP synchronization on host systems
2. If running in cloud, verify VM time sync is enabled
3. For Docker, ensure host time is synchronized

#### B. Redis Connectivity Issues
**Diagnosis:**
```bash
# Check Redis latency from each producer
for node in producer-node-001 producer-node-002 producer-node-003; do
  echo "=== $node ==="
  docker exec $node redis-cli -h redis --latency-history
done
```

**Resolution:**
1. Check network connectivity between producers and Redis
2. Verify Redis is not overloaded (check CPU, memory)
3. Consider increasing `NT_LEASE_TTL_MS` if network is consistently slow:
   ```bash
   # Increase lease TTL from 2000ms to 3000ms
   docker compose run -e NT_LEASE_TTL_MS=3000 producer
   ```

#### C. Incorrect Configuration
**Diagnosis:**
```bash
# Verify lease configuration
docker logs producer | grep "lease_ttl_ms\|min_hold_ms"

# Check for mismatched configurations
docker exec producer-node-001 env | grep NT_LEASE
docker exec producer-node-002 env | grep NT_LEASE
```

**Resolution:**
1. Ensure all nodes have identical lease configuration:
   - `NT_LEASE_TTL_MS` (default: 2000ms)
   - `NT_MIN_HOLD_MS` (default: 2000ms)
2. Verify `NT_LEASE_TTL_MS` > `NT_REPORT_PERIOD_MS` (lease TTL should be longer than report period)

---

## 3. Excessive Rebalancing

### Symptoms
- Prometheus alert: `ExcessiveRebalancing`
- Metric: `nt_hrw_rebalances_total` rate > 0.05 rebalances/sec (> 3/min)
- Logs show frequent `rebalancing_triggered` events

### Root Causes

#### A. Node Flapping (Starting/Stopping Repeatedly)
**Diagnosis:**
```bash
# Check container restart count
docker ps -a --filter name=producer --format "{{.Names}}\t{{.Status}}"

# Check for crash patterns
docker logs producer | grep "fatal_error\|panic\|exit"

# Check node heartbeat stability
curl -s http://localhost:9101/metrics | grep nt_node_heartbeat
```

**Resolution:**
1. Identify why nodes are restarting:
   - OOM kills: Increase memory limits
   - Crashes: Review error logs and fix bugs
   - Health check failures: Adjust health check thresholds
2. Stabilize the cluster before adding/removing nodes

#### B. Network Connectivity Issues
**Diagnosis:**
```bash
# Check if nodes can reach each other via Redis
for node in producer-node-001 producer-node-002; do
  echo "=== $node ==="
  docker exec $node redis-cli -h redis GET "nt:node:$node"
done

# Monitor heartbeat expiration
watch -n 1 'docker exec context8-redis redis-cli TTL nt:node:producer-node-001'
```

**Resolution:**
1. Verify network stability between producers and Redis
2. Increase heartbeat interval if network is flaky:
   ```bash
   # Default is 1000ms, increase to 2000ms if needed
   docker compose run -e NT_HEARTBEAT_INTERVAL_MS=2000 producer
   ```
3. Increase heartbeat TTL multiplier (currently 5x interval):
   - Heartbeat key TTL = `NT_HEARTBEAT_INTERVAL_MS * 5`

#### C. Overly Aggressive Rebalancing
**Diagnosis:**
```bash
# Check rebalance interval
docker logs producer | grep "rebalance_interval_sec"
```

**Resolution:**
1. Increase rebalance interval to reduce churn:
   ```bash
   # Increase from 2.5s to 5s
   docker compose run -e NT_REBALANCE_INTERVAL_SEC=5.0 producer
   ```
2. Increase sticky percentage to reduce reassignments:
   ```bash
   # Increase sticky bonus from 2% to 5%
   docker compose run -e NT_HRW_STICKY_PCT=0.05 producer
   ```
3. Increase `NT_MIN_HOLD_MS` to prevent rapid ownership changes:
   ```bash
   # Increase from 2000ms to 5000ms
   docker compose run -e NT_MIN_HOLD_MS=5000 producer
   ```

---

## 4. Producer Node Down

### Symptoms
- Prometheus alert: `ProducerDown` or `NoActiveProducers`
- Metric: `nt_node_heartbeat == 0` for specific node
- Health endpoint unreachable (connection refused)

### Root Causes

#### A. Process Crashed or Exited
**Diagnosis:**
```bash
# Check container status
docker ps -a --filter name=producer

# Check exit code and logs
docker inspect producer --format='{{.State.ExitCode}}'
docker logs --tail=100 producer
```

**Resolution:**
1. Review logs for crash reason:
   - Uncaught exception: Fix bug in code
   - OOM kill: Increase memory limit
   - SIGKILL: Check host system logs
2. Restart the producer:
   ```bash
   docker compose restart producer
   ```
3. If persistent crashes, disable problematic features:
   ```bash
   # Disable analytics to isolate issue
   docker compose run -e NT_ENABLE_KV_REPORTS=false producer
   ```

#### B. Resource Exhaustion
**Diagnosis:**
```bash
# Check resource usage
docker stats producer --no-stream

# Check host system resources
free -h
df -h
```

**Resolution:**
1. If out of memory:
   - Increase Docker memory limit
   - Reduce number of symbols
   - Check for memory leaks (review NautilusTrader cache settings)
2. If out of CPU:
   - Add more producer nodes to distribute load
   - Reduce calculation frequency (increase `NT_REPORT_PERIOD_MS`)
3. If out of disk:
   - Clean up Docker images/volumes
   - Check Redis persistence settings

#### C. Deadlock or Hung Process
**Diagnosis:**
```bash
# Check if process is responsive
docker exec producer ps aux

# Check if threads are blocked
docker exec producer python -c "import threading; print(threading.enumerate())"

# Check if timers are firing
docker logs producer --tail=50 | grep "fast_cycle\|slow_cycle"
```

**Resolution:**
1. Send SIGTERM to trigger graceful shutdown:
   ```bash
   docker kill --signal=TERM producer
   ```
2. If unresponsive, force kill and restart:
   ```bash
   docker kill producer
   docker compose up -d producer
   ```
3. Enable debug logging to diagnose:
   ```bash
   docker compose run -e NT_LOG_LEVEL=debug producer
   ```

---

## 5. Slow Calculation Performance

### Symptoms
- Prometheus alert: `FastCycleSlowProcessing` or `SlowCycleSlowProcessing`
- Metric: `nt_calc_latency_ms` P95 > 200ms (fast) or > 1500ms (slow)
- Reports have large gaps between timestamps

### Root Causes

#### A. CPU Overload
**Diagnosis:**
```bash
# Check CPU usage per metric
curl -s http://localhost:9101/metrics | grep nt_calc_latency_ms_sum

# Check producer CPU
docker stats producer --no-stream --format "{{.CPUPerc}}"
```

**Resolution:**
1. Reduce load per producer:
   - Scale horizontally (add more producer nodes)
   - Reduce symbols per node
2. Optimize calculations:
   - Reduce order book depth (default: 20 levels)
   - Reduce slow-cycle frequency
3. Increase CPU limits:
   ```yaml
   # docker-compose.yml
   services:
     producer:
       deploy:
         resources:
           limits:
             cpus: '2.0'  # Increase from 1.0
   ```

#### B. Too Many Symbols Per Producer
**Diagnosis:**
```bash
# Check symbol distribution
for port in 9101 9102 9103; do
  echo "=== Port $port ==="
  curl -s http://localhost:$port/health | jq '.coordination.owned_symbols | length'
done
```

**Resolution:**
1. Add more producer nodes to distribute symbols
2. Target 2-3 symbols per node for optimal performance
3. Verify HRW is balancing correctly:
   ```bash
   # All nodes should have similar symbol counts
   curl -s http://localhost:9101/metrics | grep nt_symbols_assigned
   ```

#### C. Slow Redis Operations
**Diagnosis:**
```bash
# Check Redis latency
docker exec context8-redis redis-cli --latency

# Check slow queries
docker exec context8-redis redis-cli SLOWLOG GET 10
```

**Resolution:**
1. Optimize Redis performance:
   - Disable persistence if acceptable (`save ""` in redis.conf)
   - Enable pipelining for batch operations
2. Scale Redis vertically (more CPU/memory)
3. Consider Redis Cluster for horizontal scaling

---

## 6. Low Report Publish Rate

### Symptoms
- Prometheus alert: `LowReportPublishRate`
- Metric: `nt_report_publish_total` rate < 2 Hz for symbol
- MCP queries return stale data

### Root Causes

#### A. Symbol Not Assigned to Any Node
**Diagnosis:**
```bash
# Check which node owns the symbol
for port in 9101 9102 9103; do
  echo "=== Port $port ==="
  curl -s http://localhost:$port/health | jq '.coordination.owned_symbols'
done

# Verify symbol is in configured list
docker exec producer env | grep SYMBOLS
```

**Resolution:**
1. Verify symbol is in `SYMBOLS` environment variable
2. Restart producers to trigger rebalancing
3. Check if symbol subscription succeeded:
   ```bash
   docker logs producer | grep "Subscribed to instrument: BTCUSDT"
   ```

#### B. Producer Stuck in Slow Cycle
**Diagnosis:**
```bash
# Check for slow cycle lag warnings
docker logs producer | grep "slow_cycle_lag\|slow_cycle_skip"

# Check slow cycle latency
curl -s http://localhost:9101/metrics | grep 'nt_calc_latency_ms.*slow'
```

**Resolution:**
1. Slow cycle is blocking fast cycle - reduce slow cycle load:
   - Increase `NT_SLOW_PERIOD_MS` (e.g., from 2000ms to 5000ms)
   - Disable volume profile if not needed
2. Check if trade buffer is too large (30-min window)

#### C. Exchange Data Feed Issue
**Diagnosis:**
```bash
# Check for order book delta events
docker logs producer | grep "order_book_deltas_published\|trade_tick_published"

# Check WebSocket subscription status
docker logs producer | grep "Subscribed to instrument"
```

**Resolution:**
1. Verify exchange is publishing data for this symbol
2. Check if symbol is delisted or suspended
3. Restart producer to reestablish WebSocket connection

---

## 7. WebSocket Reconnection Loops

### Symptoms
- Prometheus alert: `ExcessiveWebSocketResubscriptions`
- Metric: `nt_ws_resubscribe_total` rate > 0.1 reconnects/sec
- Logs show repeated `websocket_disconnected` events

### Root Causes

#### A. Exchange API Issues
**Diagnosis:**
```bash
# Check Binance API status
curl -s https://api.binance.com/api/v3/ping

# Check for rate limiting errors
docker logs producer | grep "429\|rate_limit\|too_many_requests"
```

**Resolution:**
1. Check exchange status page for incidents
2. If rate limited:
   - Reduce subscription count
   - Use API keys with higher limits
   - Add backoff/retry logic (already implemented in NautilusTrader)
3. Wait for exchange to recover if service degradation

#### B. Network Connectivity Issues
**Diagnosis:**
```bash
# Check network connectivity
docker exec producer ping -c 10 stream.binance.com

# Check for packet loss
docker exec producer traceroute stream.binance.com
```

**Resolution:**
1. Verify network stability
2. Check firewall rules (WebSocket uses port 443)
3. If behind proxy, verify WebSocket passthrough is enabled

#### C. Symbol Rebalancing
**Diagnosis:**
```bash
# Check resubscription reasons
docker logs producer | grep "ws_resubscribe.*reason"

# If reason=symbol_acquired, it's due to rebalancing (expected)
```

**Resolution:**
1. If due to rebalancing, see [Excessive Rebalancing](#3-excessive-rebalancing)
2. This is expected behavior during ownership changes
3. Consider increasing `NT_MIN_HOLD_MS` to reduce rebalancing frequency

---

## 8. General Debugging Procedures

### Enable Debug Logging
```bash
# Restart with debug logging
docker compose run -e NT_LOG_LEVEL=debug producer

# Filter for specific component
docker logs producer | grep "analytics_strategy\|coordinator"
```

### Check Health Status
```bash
# Get health status
curl http://localhost:9101/health | jq

# Monitor health over time
watch -n 1 'curl -s http://localhost:9101/health | jq'
```

### Inspect Prometheus Metrics
```bash
# Get all metrics
curl http://localhost:9101/metrics

# Filter for specific metric
curl -s http://localhost:9101/metrics | grep nt_calc_latency

# Query Prometheus for time series
curl 'http://localhost:9090/api/v1/query?query=nt_node_heartbeat'
```

### Check Redis State
```bash
# Check lease keys
docker exec context8-redis redis-cli KEYS "report:writer:*"

# Check heartbeat keys
docker exec context8-redis redis-cli KEYS "nt:node:*"

# Inspect specific lease
docker exec context8-redis redis-cli GET "report:writer:BTCUSDT"
docker exec context8-redis redis-cli GET "report:writer:token:BTCUSDT"
```

### Validate Configuration
```bash
# Check all NT environment variables
docker exec producer env | grep NT_

# Verify configuration was loaded correctly
docker logs producer | grep "configuration_loaded"
```

---

## 9. Performance Tuning Cheat Sheet

### For High-Frequency Trading (Low Latency)
```bash
NT_REPORT_PERIOD_MS=100        # Fast cycle every 100ms
NT_SLOW_PERIOD_MS=5000         # Slow cycle every 5s
NT_ENABLE_STREAMS=true         # Enable Redis Streams for real-time
```

### For Resource-Constrained Environments
```bash
NT_REPORT_PERIOD_MS=500        # Slower fast cycle
NT_SLOW_PERIOD_MS=10000        # Less frequent slow cycle
NT_ENABLE_STREAMS=false        # KV-only mode
SYMBOLS=BTCUSDT,ETHUSDT        # Fewer symbols
```

### For Multi-Instance Stability
```bash
NT_LEASE_TTL_MS=3000           # Longer lease TTL
NT_MIN_HOLD_MS=5000            # Prevent rapid ownership changes
NT_HRW_STICKY_PCT=0.05         # 5% sticky bonus for current owner
NT_REBALANCE_INTERVAL_SEC=5.0  # Less frequent rebalancing
```

### For Maximum Throughput
```bash
# Scale horizontally (3+ producer nodes)
# Each node handles 2-3 symbols
NT_REPORT_PERIOD_MS=250
NT_SLOW_PERIOD_MS=2000
NT_ENABLE_KV_REPORTS=true
NT_ENABLE_MULTI_INSTANCE=true
```

---

## 10. Escalation Procedures

### When to Escalate
- Critical alerts firing for > 10 minutes
- Data pipeline completely down (`NoActiveProducers`)
- Multiple nodes crashing repeatedly
- Redis corruption or data loss
- Unknown or undiagnosed issues

### Escalation Checklist
1. Gather diagnostic information:
   ```bash
   # Save logs
   docker logs producer > producer.log
   docker logs context8-redis > redis.log

   # Save metrics snapshot
   curl http://localhost:9101/metrics > metrics.txt
   curl http://localhost:9101/health > health.json

   # Save configuration
   docker exec producer env | grep NT_ > config.txt
   ```
2. Document timeline of events and symptoms
3. Include any error messages or stack traces
4. Provide Prometheus alert history
5. Note any recent changes (deployments, config changes)

### Contact Points
- **Infrastructure Issues**: DevOps team
- **NautilusTrader Bugs**: https://github.com/nautilus-trader/issues
- **Redis Issues**: Redis support or DevOps
- **Code Bugs**: Development team

---

## Related Documentation

- **Metrics Reference**: `docs/runbooks/monitoring.md`
- **Alert Rules**: `producer/config/prometheus-alerts.yml`
- **Architecture**: `specs/002-nt-embedded-analytics/spec.md`
- **Configuration**: `producer/README.md` (environment variables)
