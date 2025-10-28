# Deployment Runbook

## Quick Deployment (Local)

### Prerequisites
- Docker 20.10+ with Docker Compose 2.0+
- 4GB RAM minimum (8GB recommended)
- Open ports: 6379 (Redis), 8080 (MCP), 9090 (Prometheus)

### Step-by-Step Deployment

1. **Clone and configure**
   ```bash
   git clone <repository-url> context8-mcp
   cd context8-mcp
   cp .env.example .env
   ```

2. **Review configuration** (.env file):
   ```bash
   # Default symbols (change if needed)
   SYMBOLS=BTCUSDT,ETHUSDT

   # Redis (defaults work for Docker Compose)
   REDIS_URL=redis://redis:6379
   REDIS_PASSWORD=

   # Performance tuning
   CACHE_TTL_SEC=300
   LOG_LEVEL=info
   ```

3. **Start services**
   ```bash
   docker compose up -d
   ```

4. **Verify startup** (wait 20 seconds):
   ```bash
   # Check all services are healthy
   docker compose ps

   # Expected output:
   # NAME                  STATUS
   # context8-redis        Up X minutes (healthy)
   # context8-producer     Up X minutes (healthy)
   # context8-analytics    Up X minutes (healthy)
   # context8-mcp          Up X minutes (healthy)
   # context8-prometheus   Up X minutes (healthy)
   ```

5. **Smoke test**
   ```bash
   # Test MCP endpoint
   curl http://localhost:8080/get_report?symbol=BTCUSDT | jq '.symbol, .ingestion.fresh'

   # Expected: Symbol name and fresh=true
   ```

6. **Monitor logs**
   ```bash
   # View all logs
   docker compose logs -f

   # View specific service
   docker compose logs -f analytics
   ```

## Production Deployment Considerations

### Resource Requirements

**Minimum**:
- CPU: 2 cores
- RAM: 4GB
- Disk: 10GB (mostly for logs and Docker images)
- Network: 10Mbps (for Binance WebSocket)

**Recommended**:
- CPU: 4 cores
- RAM: 8GB
- Disk: 50GB with log rotation
- Network: 100Mbps with stable connection

### Security

1. **Redis Password**:
   ```bash
   # Set strong password in .env
   REDIS_PASSWORD=<strong-random-password>
   ```

2. **Network Isolation**:
   - Only expose port 8080 (MCP) externally
   - Keep Redis (6379) and Prometheus (9090) internal
   - Use firewall rules or Docker network policies

3. **Secrets Management**:
   - NEVER commit .env to git (already in .gitignore)
   - Use environment-specific .env files
   - Consider using Docker secrets or Kubernetes secrets

### Scaling

#### Horizontal Scaling (Multiple Analytics Instances)

```yaml
# docker-compose.yml
analytics:
  image: context8-mcp-analytics
  deploy:
    replicas: 3  # Scale to 3 instances
  environment:
    CONSUMER_NAME: analytics-${HOSTNAME}  # Unique consumer names
```

Benefits:
- Higher throughput (parallel event processing)
- Fault tolerance (consumer group rebalancing)
- Maintained idempotency via Redis Streams consumer groups

#### Vertical Scaling

Increase resources per container:
```yaml
analytics:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 2G
```

### High Availability

1. **Redis Persistence**:
   ```yaml
   redis:
     command: redis-server --appendonly yes
     volumes:
       - redis-data:/data
   ```

2. **Health Checks**:
   All services have health checks configured. Monitor with:
   ```bash
   curl http://localhost:8080/health
   curl http://localhost:9091/health  # analytics (inside container)
   ```

3. **Automatic Restart**:
   ```yaml
   services:
     analytics:
       restart: unless-stopped
   ```

### Monitoring Setup

1. **Prometheus Alerts** (create `alerts.yml`):
   ```yaml
   groups:
     - name: context8
       rules:
         - alert: StaleData
           expr: context8_report_age_ms > 2000
           for: 30s
           annotations:
             summary: "Data is stale (>2s old)"

         - alert: HighLatency
           expr: context8_mcp_request_duration_ms > 100
           for: 1m
           annotations:
             summary: "MCP API latency >100ms"
   ```

2. **Grafana Dashboard**:
   - Import dashboard from `docs/grafana-dashboard.json` (TODO)
   - Connect to Prometheus at `http://prometheus:9090`

## Troubleshooting Common Issues

See [troubleshooting.md](./troubleshooting.md) for detailed debugging steps.

### Quick Checks

1. **Services won't start**:
   ```bash
   docker compose logs
   # Check for port conflicts, permission issues
   ```

2. **Data not fresh**:
   ```bash
   docker compose logs producer | grep error
   # Check Binance WebSocket connection
   ```

3. **High latency**:
   ```bash
   docker stats
   # Check CPU/memory usage
   ```

## Maintenance

### Log Rotation

```bash
# Configure Docker log rotation in /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

### Backup

```bash
# Backup Redis data
docker compose exec redis redis-cli SAVE
docker cp context8-redis:/data/dump.rdb ./backups/

# Backup configuration
cp .env ./backups/.env.$(date +%Y%m%d)
```

### Upgrade

```bash
# Pull latest images
git pull
docker compose pull

# Recreate containers
docker compose up -d --force-recreate

# Verify health
docker compose ps
```

## Rollback

```bash
# Rollback to previous version
git checkout <previous-commit>
docker compose up -d --force-recreate

# Or use specific image tags
docker compose down
docker pull context8-mcp-analytics:<previous-tag>
docker compose up -d
```

---

**Last Updated**: 2025-10-28
