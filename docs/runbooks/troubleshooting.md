# Troubleshooting Guide

## Quick Diagnostics

### Check System Health

```bash
# 1. Check all services are running
docker compose ps

# 2. Check service health
curl http://localhost:8080/health

# 3. Test data freshness
curl "http://localhost:8080/get_report?symbol=BTCUSDT" | jq '.ingestion'

# 4. Check Prometheus targets
curl http://localhost:9090/api/v1/targets | jq '.data.activeTargets[].health'
```

## Common Issues

### 1. Services Won't Start

#### Symptom
```bash
docker compose up
# Error: port already in use
```

#### Diagnosis
```bash
# Check port conflicts
netstat -tuln | grep -E "6379|8080|9090"
lsof -i :8080
```

#### Solutions

**Option A: Stop conflicting services**
```bash
# Find and stop process using port
sudo kill $(lsof -t -i:8080)
```

**Option B: Change ports in docker-compose.yml**
```yaml
mcp:
  ports:
    - "8081:8080"  # Use 8081 instead
```

### 2. Data Not Fresh (fresh=false)

#### Symptom
```json
{
  "ingestion": {
    "status": "degraded",
    "fresh": false
  },
  "data_age_ms": 5000
}
```

#### Diagnosis
```bash
# Check producer logs
docker compose logs producer --tail 50

# Check for WebSocket errors
docker compose logs producer | grep -i "error\|closed\|timeout"

# Check analytics is consuming
docker compose logs analytics --tail 20 | grep "event_processed"
```

#### Root Causes & Solutions

**A. Producer WebSocket Disconnected**
```bash
# Logs show: "websocket_closed" or "ping/pong timed out"

# Solution: Restart producer
docker compose restart producer

# Wait 10 seconds and verify
curl "http://localhost:8080/get_report?symbol=BTCUSDT" | jq '.ingestion.fresh'
```

**B. Binance API Rate Limiting**
```bash
# Logs show: HTTP 429 or rate limit errors

# Solution: Reduce polling or wait
# Binance public streams shouldn't rate limit, but check:
docker compose logs producer | grep "429\|rate"
```

**C. Network Issues**
```bash
# Test internet connectivity
docker compose exec producer ping -c 3 stream.binance.com

# If fails, check Docker network
docker network inspect context8-mcp_context8-network
```

### 3. High API Latency (>150ms)

#### Symptom
```bash
time curl "http://localhost:8080/get_report?symbol=BTCUSDT"
# real 0m0.250s  (too slow!)
```

#### Diagnosis
```bash
# Check CPU/memory usage
docker stats --no-stream

# Check Redis latency
docker compose exec redis redis-cli --latency

# Check report cache hits
docker compose exec redis redis-cli INFO stats | grep keyspace
```

#### Solutions

**A. High CPU Usage**
```bash
# Scale analytics service
docker compose up -d --scale analytics=3

# Or increase CPU limit
# In docker-compose.yml:
analytics:
  deploy:
    resources:
      limits:
        cpus: '2'
```

**B. Redis Memory Pressure**
```bash
# Check memory usage
docker compose exec redis redis-cli INFO memory

# If near maxmemory, increase limit in docker-compose.yml:
redis:
  command: redis-server --maxmemory 1gb --maxmemory-policy allkeys-lru
```

**C. Network Latency**
```bash
# If running remotely, add local caching layer
# or move MCP server closer to clients
```

### 4. Missing Symbol (404 Error)

#### Symptom
```bash
curl "http://localhost:8080/get_report?symbol=BTCUSDT"
# {"error":"symbol_not_indexed","message":"Symbol not found in cache"}
```

#### Diagnosis
```bash
# Check SYMBOLS configuration
docker compose exec analytics env | grep SYMBOLS

# Check producer is tracking symbol
docker compose logs producer | grep BTCUSDT

# Check analytics is processing symbol
docker compose logs analytics | grep BTCUSDT

# Check Redis cache
docker compose exec redis redis-cli KEYS "report:*"
```

#### Solutions

**A. Symbol Not Configured**
```bash
# Add symbol to .env
SYMBOLS=BTCUSDT,ETHUSDT,SOLUSDT

# Restart services
docker compose restart producer analytics
```

**B. System Just Started**
```bash
# Wait 10-20 seconds after startup for first reports

# Monitor logs until you see:
docker compose logs analytics | grep "report_cached"
```

### 5. Producer Crashes on Startup

#### Symptom
```bash
docker compose ps
# context8-producer  Exit 1
```

#### Diagnosis
```bash
# Check producer logs
docker compose logs producer

# Common errors:
# - "Redis connection refused"
# - "No module named 'nautilus_trader'"
# - "SYMBOLS not set"
```

#### Solutions

**A. Redis Not Ready**
```bash
# Ensure depends_on is configured (should be in docker-compose.yml)
# Restart:
docker compose up -d
```

**B. Missing Dependencies**
```bash
# Rebuild producer image
docker compose build producer
docker compose up -d producer
```

**C. Invalid Configuration**
```bash
# Check .env file
cat .env

# Validate symbols format (comma-separated, no spaces)
SYMBOLS=BTCUSDT,ETHUSDT  # Correct
SYMBOLS=BTC USDT, ETH USDT  # Wrong!
```

### 6. Analytics Not Processing Events

#### Symptom
```bash
docker compose logs analytics
# No "event_processed" messages
```

#### Diagnosis
```bash
# Check consumer group status
docker compose exec redis redis-cli XINFO GROUPS nt:binance

# Check pending messages
docker compose exec redis redis-cli XPENDING nt:binance context8

# Check stream length
docker compose exec redis redis-cli XLEN nt:binance
```

#### Solutions

**A. Consumer Group Not Created**
```bash
# Should be auto-created, but if not:
docker compose exec redis redis-cli XGROUP CREATE nt:binance context8 0 MKSTREAM

# Restart analytics
docker compose restart analytics
```

**B. Events Stuck in Pending**
```bash
# Check pending messages
docker compose exec redis redis-cli XPENDING nt:binance context8 - + 10

# Force reclaim old messages (>1 min)
docker compose restart analytics  # Will reclaim on startup
```

### 7. Prometheus Metrics Not Appearing

#### Symptom
```bash
curl http://localhost:9090/api/v1/targets
# Shows analytics/mcp as "down"
```

#### Diagnosis
```bash
# Check metrics endpoints directly
curl http://localhost:9091/metrics  # analytics (if exposed)
docker compose exec analytics wget -O- http://localhost:9091/metrics

# Check Prometheus config
docker compose exec prometheus cat /etc/prometheus/prometheus.yml
```

#### Solutions

**A. Wrong Port Configuration**
```bash
# Verify ports in prometheus.yml match services
# Analytics exposes :9091 internally
# MCP exposes :9092 internally
```

**B. Network Isolation**
```bash
# Ensure Prometheus can reach services
docker compose exec prometheus ping analytics
docker compose exec prometheus ping mcp
```

## Log Analysis

### Enable Debug Logging

```bash
# In .env file
LOG_LEVEL=debug

# Restart services
docker compose restart
```

### Useful Log Filters

```bash
# Show only errors
docker compose logs | grep -i error

# Show producer WebSocket issues
docker compose logs producer | grep -E "websocket|error"

# Show analytics event processing
docker compose logs analytics | grep "event_processed" | tail -20

# Show MCP requests
docker compose logs mcp | grep "get_report"

# Show health status changes
docker compose logs | grep -E "status|health|degraded"
```

## Performance Tuning

### Reduce Event Processing Lag

```bash
# Increase analytics instances
docker compose up -d --scale analytics=3

# Or tune batch size (in analytics config)
CONSUMER_BATCH_SIZE=50  # Default: 10
```

### Optimize Redis

```bash
# Tune maxmemory and eviction
redis:
  command: >
    redis-server
    --maxmemory 2gb
    --maxmemory-policy allkeys-lru
    --save ""
```

### Reduce Network Traffic

```bash
# Limit tracked symbols
SYMBOLS=BTCUSDT  # Track only one

# Increase cache TTL
CACHE_TTL_SEC=600  # 10 minutes (default: 300)
```

## Recovery Procedures

### Complete System Reset

```bash
# Stop and remove all containers and volumes
docker compose down -v

# Remove images
docker compose rm -f
docker rmi context8-mcp-producer context8-mcp-analytics context8-mcp-mcp

# Rebuild and start fresh
docker compose build
docker compose up -d

# Wait 20 seconds and verify
curl "http://localhost:8080/get_report?symbol=BTCUSDT"
```

### Partial Service Restart

```bash
# Restart single service
docker compose restart analytics

# Recreate service (rebuild)
docker compose up -d --force-recreate analytics
```

## Getting Help

### Collect Diagnostic Information

```bash
# Create diagnostic bundle
mkdir -p /tmp/context8-diagnostics
docker compose ps > /tmp/context8-diagnostics/services.txt
docker compose logs > /tmp/context8-diagnostics/logs.txt
docker stats --no-stream > /tmp/context8-diagnostics/stats.txt
cp .env /tmp/context8-diagnostics/config.txt  # Remove secrets!
tar czf context8-diagnostics.tar.gz /tmp/context8-diagnostics/
```

### Where to Ask

1. Check existing documentation:
   - [Architecture](../architecture.md)
   - [Metrics](../metrics.md)
   - [Monitoring](./monitoring.md)

2. Review specifications:
   - Feature specs in `specs/001-market-report-mcp/`
   - Constitution in `.specify/memory/constitution.md`

3. File an issue:
   - Include diagnostic bundle
   - Describe expected vs actual behavior
   - Include relevant log snippets

---

**Last Updated**: 2025-10-28
