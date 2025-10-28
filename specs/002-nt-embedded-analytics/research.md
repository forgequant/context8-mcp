# Research & Technical Decisions: Embedded Market Analytics

**Feature**: 002-nt-embedded-analytics
**Date**: 2025-10-28
**Purpose**: Resolve all technical unknowns before Phase 1 design

---

## Research Task 1: HRW Consistent Hashing Implementation

### Decision
Use **hashlib.blake2b** (Python standard library) for HRW consistent hashing with custom hysteresis implementation.

### Rationale
- **blake2b advantages**:
  - Standard library (no external dependency)
  - Cryptographically strong (low collision rate)
  - Fast performance (comparable to xxhash for our use case)
  - Deterministic across Python versions

- **xxhash comparison**:
  - Slightly faster (~10-20%) but requires `xxhash` package
  - Not standard library (adds dependency)
  - Non-cryptographic hash (acceptable but unnecessary complexity)

- **Hysteresis algorithm**:
  - Calculate base HRW weight: `weight = hash(node_id + symbol) / MAX_HASH`
  - Apply sticky bonus: `if current_owner == node_id: weight *= (1 + sticky_pct)`
  - Add minimum hold time check: reject reassignment if `time_since_acquisition < min_hold_ms`

### Alternatives Considered
- **xxhash**: Rejected due to external dependency when stdlib is sufficient
- **hashlib.md5**: Rejected - deprecated for security reasons (even though not security-critical here)
- **Simple modulo hashing**: Rejected - poor distribution, no hysteresis support

### Implementation Guidance
```python
import hashlib
from typing import List

def hrw_hash(node_id: str, symbol: str) -> int:
    """Highest Random Weight hash using blake2b."""
    h = hashlib.blake2b(digest_size=8)  # 64-bit hash
    h.update(f"{node_id}:{symbol}".encode('utf-8'))
    return int.from_bytes(h.digest(), byteorder='big')

def select_node(
    symbol: str,
    nodes: List[str],
    current_owner: str | None = None,
    sticky_pct: float = 0.02  # 2% bonus
) -> str:
    """Select node for symbol using HRW with hysteresis."""
    weights = {}
    for node in nodes:
        weight = hrw_hash(node, symbol)
        if current_owner and node == current_owner:
            weight = int(weight * (1 + sticky_pct))  # Sticky bonus
        weights[node] = weight
    return max(weights, key=weights.get)
```

**References Consulted**: None specific (standard consistent hashing algorithm + custom hysteresis)

---

## Research Task 2: Redis Lua Scripts for Lease Management

### Decision
Use **redis-py `Script` class** with pre-registered Lua scripts stored in `producer/lua/` directory. Scripts cached in Redis via SHA1 for efficiency.

### Rationale
- **redis-py Script pattern** (from go-redis reference):
  - Automatic script caching (SCRIPT LOAD → EVALSHA)
  - Type-safe result conversion
  - Atomic operations within Lua (no race conditions)

- **Separate .lua files**:
  - Version control for critical logic
  - Easy testing and review
  - Clear separation from Python code

### Alternatives Considered
- **Inline Lua strings in Python**: Rejected - hard to test, version control issues
- **Redis transactions (MULTI/EXEC)**: Rejected - not atomic for conditional logic (need Lua for IF/THEN)
- **Python-level locking**: Rejected - not distributed, requires additional coordination

### Implementation Guidance

**File: `producer/lua/acquire_lease.lua`**
```lua
-- Acquire writer lease with fencing token
-- KEYS[1] = report:writer:{symbol}
-- KEYS[2] = report:writer:token:{symbol}
-- ARGV[1] = node_id
-- ARGV[2] = ttl_ms
-- Returns: token (int) if acquired, nil if failed

local acquired = redis.call("SET", KEYS[1], ARGV[1], "PX", ARGV[2], "NX")
if acquired then
    local token = redis.call("INCR", KEYS[2])
    return token
else
    return nil
end
```

**File: `producer/lua/renew_lease.lua`**
```lua
-- Renew lease only if still owner
-- KEYS[1] = report:writer:{symbol}
-- ARGV[1] = node_id (expected owner)
-- ARGV[2] = ttl_ms (new TTL)
-- Returns: 1 if renewed, 0 if not owner

local current_owner = redis.call("GET", KEYS[1])
if current_owner == ARGV[1] then
    redis.call("PEXPIRE", KEYS[1], ARGV[2])
    return 1
else
    return 0
end
```

**File: `producer/lua/release_lease.lua`**
```lua
-- Release lease only if still owner
-- KEYS[1] = report:writer:{symbol}
-- ARGV[1] = node_id (expected owner)
-- Returns: 1 if released, 0 if not owner

local current_owner = redis.call("GET", KEYS[1])
if current_owner == ARGV[1] then
    redis.call("DEL", KEYS[1])
    return 1
else
    return 0
end
```

**Python usage:**
```python
from redis import Redis
from redis.commands.core import Script

class LeaseManager:
    def __init__(self, redis_client: Redis):
        self.redis = redis_client
        # Load scripts once at init
        with open('producer/lua/acquire_lease.lua') as f:
            self.acquire_script = Script(redis_client, f.read())
        with open('producer/lua/renew_lease.lua') as f:
            self.renew_script = Script(redis_client, f.read())
        with open('producer/lua/release_lease.lua') as f:
            self.release_script = Script(redis_client, f.read())

    def acquire(self, symbol: str, node_id: str, ttl_ms: int) -> int | None:
        keys = [f"report:writer:{symbol}", f"report:writer:token:{symbol}"]
        return self.acquire_script(keys=keys, args=[node_id, ttl_ms])
```

**References Consulted**: `.refs/go-redis/example/lua-scripting/main.go` - Script registration pattern

---

## Research Task 3: Percentile Calculation Methods

### Decision
Use **numpy.percentile** with `method='linear'` (default) for P95/P10 calculations on rolling windows.

### Rationale
- **Performance**: NumPy implementation is C-optimized, ~10-50x faster than pure Python
- **Correctness**: Industry-standard interpolation method, matches statistical expectations
- **Simplicity**: One-line calculation, no custom code to maintain
- **Memory efficiency**: Operates on numpy arrays directly (no list conversions)

### Alternatives Considered
- **Manual interpolation**: Rejected - error-prone, slower, no benefit
- **numpy.quantile**: Equivalent to percentile (just different parameterization)
- **scipy.stats.scoreatpercentile**: Deprecated, use numpy.percentile instead
- **Approximate percentiles (t-digest)**: Rejected - exact calculation fast enough for 10K samples

### Implementation Guidance
```python
import numpy as np
from collections import deque

class PercentileTracker:
    def __init__(self, max_size: int = 10000):
        self.values = deque(maxlen=max_size)  # Auto-discards oldest

    def add(self, value: float):
        self.values.append(value)

    def p95(self) -> float | None:
        if len(self.values) < 20:  # Minimum samples for meaningful percentile
            return None
        arr = np.array(self.values)
        return np.percentile(arr, 95, method='linear')

    def p10(self) -> float | None:
        if len(self.values) < 20:
            return None
        arr = np.array(self.values)
        return np.percentile(arr, 10, method='linear')
```

**Performance**: `np.percentile` on 10,000 floats: ~0.5ms (acceptable for slow-cycle 2000ms budget)

**References Consulted**: `.refs/spoof.io/` (general statistical patterns, no specific percentile code found)

---

## Research Task 4: Volume Profile Binning Strategy

### Decision
Use **tick-size based binning** with configurable multiplier (default: 5 ticks per bin). Dynamic bin width based on instrument tick size.

### Rationale
- **Tick-size alignment**: Bins align with actual price increments traded on exchange
- **Adaptive**: Works across different instruments (BTC $0.01 ticks vs altcoins $0.0001 ticks)
- **Standard in industry**: Market Profile® uses tick-based bins
- **Configurable**: Can adjust bin_width multiplier (5 = coarser, 1 = finer)

### Alternatives Considered
- **Fixed dollar bins ($10, $100)**: Rejected - not adaptive, breaks on different price ranges
- **ATR-based bins**: Rejected - requires historical volatility calculation, overkill for MVP
- **Percentage bins (0.1%)**: Rejected - uneven bin sizes at different price levels, complicates POC calculation
- **Point-and-figure (3-box reversal)**: Rejected - not true volume profile, different purpose

### Implementation Guidance
```python
from collections import defaultdict
from dataclasses import dataclass

@dataclass
class VolumeProfile:
    POC: float  # Point of Control
    VAH: float  # Value Area High
    VAL: float  # Value Area Low
    window_sec: int
    trade_count: int

def calculate_volume_profile(
    trades: list[tuple[float, float]],  # (price, volume) pairs
    tick_size: float,
    bin_width: int = 5  # Number of ticks per bin
) -> VolumeProfile | None:
    if len(trades) < 10:
        return None  # Insufficient data

    bin_size = tick_size * bin_width

    # Aggregate volume into bins
    bins = defaultdict(float)
    for price, volume in trades:
        bin_key = int(price / bin_size) * bin_size
        bins[bin_key] += volume

    # Find POC (bin with max volume)
    poc_bin = max(bins, key=bins.get)
    POC = poc_bin + (bin_size / 2)  # Center of bin

    # Calculate Value Area (70% of volume around POC)
    total_volume = sum(bins.values())
    target_volume = total_volume * 0.70

    # Expand from POC until reaching 70% volume
    sorted_bins = sorted(bins.items())
    poc_idx = next(i for i, (b, _) in enumerate(sorted_bins) if b == poc_bin)

    accumulated = bins[poc_bin]
    low_idx = high_idx = poc_idx

    while accumulated < target_volume:
        # Expand to side with more volume
        low_vol = bins[sorted_bins[low_idx - 1][0]] if low_idx > 0 else 0
        high_vol = bins[sorted_bins[high_idx + 1][0]] if high_idx < len(sorted_bins) - 1 else 0

        if low_vol > high_vol and low_idx > 0:
            low_idx -= 1
            accumulated += bins[sorted_bins[low_idx][0]]
        elif high_idx < len(sorted_bins) - 1:
            high_idx += 1
            accumulated += bins[sorted_bins[high_idx][0]]
        else:
            break

    VAL = sorted_bins[low_idx][0]
    VAH = sorted_bins[high_idx][0] + bin_size

    # Validate invariant
    if not (VAL <= POC <= VAH):
        raise ValueError(f"Volume profile invariant violated: {VAL} <= {POC} <= {VAH}")

    return VolumeProfile(POC=POC, VAH=VAH, VAL=VAL, window_sec=1800, trade_count=len(trades))
```

**References Consulted**: `.refs/py-market-profile/` (confirmed tick-based binning approach, adapted algorithm)

---

## Research Task 5: NautilusTrader Strategy Lifecycle

### Decision
Use **`self.clock.set_timer()`** with recurring timers for both fast-cycle (250ms) and slow-cycle (2000ms). Separate callback functions for each cycle.

### Rationale
- **Native Nautilus pattern**: `clock.set_timer()` is the standard way to schedule recurring actions
- **Async-compatible**: Nautilus clock handles asyncio event loop integration
- **Precise timing**: Clock uses high-resolution timers, sub-millisecond accuracy
- **Lifecycle-aware**: Timers automatically stop on `on_stop()`, no manual cleanup needed

### Alternatives Considered
- **asyncio.Timer**: Rejected - Nautilus clock provides better integration
- **Threading.Timer**: Rejected - not async-safe, would block Nautilus event loop
- **Manual time tracking in callbacks**: Rejected - error-prone, no guaranteed periodicity

### Implementation Guidance
```python
from nautilus_trader.trading.strategy import Strategy
from nautilus_trader.common.events import TimeEvent
import pandas as pd

class MarketAnalyticsStrategy(Strategy):
    FAST_CYCLE_TIMER = "fast_cycle"
    SLOW_CYCLE_TIMER = "slow_cycle"

    def __init__(self, config: dict):
        super().__init__()
        self.fast_period_ms = config.get('NT_REPORT_PERIOD_MS', 250)
        self.slow_period_ms = config.get('NT_SLOW_PERIOD_MS', 2000)
        self.symbol_states = {}  # Per-symbol calculation state

    def on_start(self):
        self.log.info("Starting embedded analytics strategy")

        # Setup fast cycle (L1/L2/flow/health)
        self.clock.set_timer(
            name=self.FAST_CYCLE_TIMER,
            interval=pd.Timedelta(milliseconds=self.fast_period_ms),
            callback=self.on_fast_cycle,
        )

        # Setup slow cycle (volume profile, liquidity, anomalies)
        self.clock.set_timer(
            name=self.SLOW_CYCLE_TIMER,
            interval=pd.Timedelta(milliseconds=self.slow_period_ms),
            callback=self.on_slow_cycle,
        )

        # Subscribe to market data
        for symbol in self.config['symbols']:
            self.subscribe_order_book_deltas(symbol)
            self.subscribe_trade_ticks(symbol)

    def on_fast_cycle(self, event: TimeEvent):
        """Execute fast-cycle calculations (100-250ms)."""
        for symbol, state in self.symbol_states.items():
            try:
                # Calculate L1/L2/flow metrics
                report = self.generate_fast_report(state)
                # Publish to Redis
                self.publish_report(symbol, report)
            except Exception as e:
                self.log.error(f"Fast cycle error for {symbol}: {e}")

    def on_slow_cycle(self, event: TimeEvent):
        """Execute slow-cycle calculations (1-5s)."""
        for symbol, state in self.symbol_states.items():
            try:
                # Calculate volume profile, walls, vacuums, anomalies
                enrichment = self.calculate_slow_metrics(state)
                # Merge into existing report (don't overwrite fast fields)
                self.enrich_report(symbol, enrichment)
            except Exception as e:
                self.log.error(f"Slow cycle error for {symbol}: {e}")

    def on_stop(self):
        self.log.info("Stopping embedded analytics strategy")
        # Timers automatically cancelled by Nautilus framework
```

**Note**: If fast-cycle calculations exceed period (lag accumulation), skip ticks to maintain cadence:
```python
def on_fast_cycle(self, event: TimeEvent):
    if self.is_lagging():  # Check if previous cycle still running
        self.log.warning("Skipping fast cycle due to lag")
        return
    # ... normal processing
```

**References Consulted**: `.refs/nautilus_trader/examples/backtest/example_02_use_clock_timer/strategy.py` - Timer setup pattern

---

## Research Task 6: Prometheus Metrics in Python

### Decision
Use **prometheus_client** with global registry, exposing metrics via built-in HTTP server on configurable port (default: 9101). Initialize metrics in `__init__`, update in callbacks.

### Rationale
- **Standard library**: prometheus_client is the official Python client
- **Low overhead**: Metrics stored in-memory, no external dependencies
- **Async-safe**: Thread-safe counters/histograms work with asyncio
- **Built-in HTTP server**: `start_http_server(port)` handles exposition automatically

### Alternatives Considered
- **Manual Prometheus text format**: Rejected - reinventing wheel, error-prone
- **StatsD + Prometheus exporter**: Rejected - unnecessary hop, adds latency
- **OpenTelemetry**: Rejected - overkill for simple metrics, heavier dependency

### Implementation Guidance
```python
from prometheus_client import Counter, Gauge, Histogram, Summary, start_http_server
from prometheus_client import REGISTRY

class PrometheusMetrics:
    def __init__(self, port: int = 9101):
        # Node health
        self.node_heartbeat = Gauge('nt_node_heartbeat', 'Node alive', ['node'])
        self.symbols_assigned = Gauge('nt_symbols_assigned', 'Symbols assigned to node', ['node'])

        # Calculation latency
        self.calc_latency = Histogram(
            'nt_calc_latency_ms',
            'Calculation latency in milliseconds',
            ['metric'],
            buckets=[1, 5, 10, 20, 50, 100, 200, 500, 1000]  # Tuned for 20ms/500ms targets
        )

        # Publishing
        self.report_publish_rate = Counter('nt_report_publish_rate', 'Reports published', ['symbol'])
        self.data_age = Summary('nt_data_age_ms', 'Data age in milliseconds', ['symbol'])

        # Coordination
        self.lease_conflicts = Counter('nt_lease_conflicts_total', 'Lease conflict count')
        self.hrw_rebalances = Counter('nt_hrw_rebalances_total', 'HRW rebalance count')
        self.ws_resubscribe = Counter('nt_ws_resubscribe_total', 'WebSocket resubscribes', ['reason'])

        # Start HTTP server for /metrics endpoint
        start_http_server(port)

    def record_calculation(self, metric_name: str, duration_ms: float):
        self.calc_latency.labels(metric=metric_name).observe(duration_ms)

    def publish_report(self, symbol: str, data_age_ms: float):
        self.report_publish_rate.labels(symbol=symbol).inc()
        self.data_age.labels(symbol=symbol).observe(data_age_ms)
```

**Histogram buckets**: Chosen to capture fast-cycle (20ms p99 target) and slow-cycle (500ms p99 target) distributions.

**References Consulted**: None (standard prometheus_client documentation patterns)

---

## Research Task 7: Redis Connection Pooling

### Decision
Use **redis-py ConnectionPool** with `max_connections=20`, `socket_timeout=5`, `socket_connect_timeout=2`. Single shared pool for all operations (heartbeat, lease, publishing).

### Rationale
- **Connection pooling essential**: Avoid overhead of connection per operation (~10ms TCP handshake)
- **Max connections sizing**: 20 connections sufficient for:
  - Heartbeat: 1/sec × 1 connection = 1 active
  - Lease renewal: 1/sec per symbol × 15 symbols = 15 active (burst)
  - Report publishing: 10/sec per symbol × 15 symbols = 150 ops/sec (but reuse connections)
  - Discovery (SCAN): ~1/sec × 1 connection = 1 active
  - Total peak: ~20 concurrent connections

- **Timeouts**: Short timeouts (2s connect, 5s operation) to fail fast during network issues

### Alternatives Considered
- **Separate pools per operation type**: Rejected - unnecessary complexity, no isolation benefit
- **Unlimited connections**: Rejected - can exhaust file descriptors, no backpressure
- **Pipeline all operations**: Rejected - lease/heartbeat need immediate feedback, can't batch

### Implementation Guidance
```python
import redis
from redis.connection import ConnectionPool
from redis.retry import Retry
from redis.backoff import ExponentialBackoff

class RedisClient:
    def __init__(self, url: str, password: str = None):
        # Create connection pool
        self.pool = ConnectionPool.from_url(
            url,
            password=password,
            max_connections=20,
            socket_timeout=5,  # 5s operation timeout
            socket_connect_timeout=2,  # 2s connect timeout
            socket_keepalive=True,
            socket_keepalive_options={
                1: 1,  # TCP_KEEPIDLE (seconds)
                2: 1,  # TCP_KEEPINTVL (seconds)
                3: 3,  # TCP_KEEPCNT (probes)
            },
            retry=Retry(ExponentialBackoff(), retries=3),  # Auto-retry on connection errors
            retry_on_timeout=True,
            health_check_interval=30,  # Check connection health every 30s
        )

        # Create client using pool
        self.client = redis.Redis(connection_pool=self.pool, decode_responses=True)

    def close(self):
        self.pool.disconnect()

# Usage:
redis_client = RedisClient(url="redis://redis:6379", password=None)
redis_client.client.set("key", "value")  # Automatically uses pooled connection
```

**Retry strategy**: Exponential backoff with 3 retries handles transient network issues. Total retry time: ~1s (acceptable for non-critical ops).

**References Consulted**: `.refs/go-redis/` (similar connection pool patterns, adapted to redis-py)

---

## Research Task 8: Chaos Testing Approaches

### Decision
Use **pytest fixtures** with **Docker network manipulation** (`tc` traffic control) and **pytest-timeout** for simulating failures. Chaos scenarios as separate test module.

### Rationale
- **pytest fixtures**: Reusable setup/teardown for chaos scenarios
- **Docker tc (traffic control)**: Can simulate network partitions, latency, packet loss without separate tool
- **pytest-timeout**: Detect test hangs during chaos (important for deadlock detection)
- **No external tools**: Avoid dependencies on Chaos Monkey, Toxiproxy, etc. for simpler setup

### Alternatives Considered
- **Toxiproxy**: Rejected - requires separate proxy service, harder to integrate with Docker Compose
- **Chaos Mesh**: Rejected - Kubernetes-only, overkill for local testing
- **Manual Docker commands**: Rejected - not integrated with test lifecycle, cleanup issues

### Implementation Guidance

**File: `producer/tests/system/test_chaos.py`**
```python
import pytest
import subprocess
import time
from redis import Redis

@pytest.fixture
def network_partition(docker_compose_project):
    """Fixture to simulate network partition between producer and Redis."""
    def _partition(container_name: str, duration_sec: int):
        # Block traffic to Redis using iptables
        subprocess.run([
            "docker", "exec", container_name,
            "iptables", "-A", "OUTPUT", "-p", "tcp", "--dport", "6379", "-j", "DROP"
        ], check=True)

        time.sleep(duration_sec)

        # Restore traffic
        subprocess.run([
            "docker", "exec", container_name,
            "iptables", "-D", "OUTPUT", "-p", "tcp", "--dport", "6379", "-j", "DROP"
        ], check=True)

    yield _partition

@pytest.fixture
def clock_skew(docker_compose_project):
    """Fixture to introduce clock skew on container."""
    def _skew(container_name: str, offset_sec: int):
        # Set container clock offset
        subprocess.run([
            "docker", "exec", container_name,
            "date", "-s", f"+{offset_sec} seconds"
        ], check=True)

    yield _skew

    # Cleanup: reset clock (or just restart container)

@pytest.mark.chaos
@pytest.mark.timeout(60)  # Test must complete within 60s
def test_failover_during_partition(network_partition):
    """Test symbol reassignment during network partition."""
    # Start 3 producers with 15 symbols
    # Trigger partition on producer-2 for 5 seconds
    network_partition("context8_producer-2", duration_sec=5)

    # Verify:
    # 1. Producer-2 loses leases within 2-3 seconds
    # 2. Producer-1 or Producer-3 acquires orphaned symbols
    # 3. No duplicate writers (check writerToken in reports)
    # 4. Data age < 1000ms maintained after reassignment

@pytest.mark.chaos
def test_instance_flapping():
    """Test rapid instance crash/restart cycle."""
    for _ in range(10):  # 10 crashes over 60 seconds
        subprocess.run(["docker", "compose", "stop", "producer-2"], check=True)
        time.sleep(3)
        subprocess.run(["docker", "compose", "start", "producer-2"], check=True)
        time.sleep(3)

    # Verify system stabilized, no stuck assignments

@pytest.mark.chaos
def test_redis_failover():
    """Test Redis primary failover (if using Redis cluster)."""
    # Simulate Redis primary failure
    subprocess.run(["docker", "compose", "stop", "redis"], check=True)
    time.sleep(2)
    subprocess.run(["docker", "compose", "start", "redis"], check=True)

    # Verify producers reconnect and resume publishing
```

**Docker network commands** (for more advanced chaos):
```bash
# Add 100ms latency to Redis container
docker exec redis tc qdisc add dev eth0 root netem delay 100ms

# Add 10% packet loss
docker exec redis tc qdisc add dev eth0 root netem loss 10%

# Remove chaos
docker exec redis tc qdisc del dev eth0 root
```

**References Consulted**: None (standard pytest + Docker patterns)

---

## Summary of Decisions

| Research Task | Decision | Key Library/Pattern |
|---------------|----------|---------------------|
| HRW Hashing | hashlib.blake2b + custom hysteresis | Python stdlib |
| Lua Scripts | redis-py Script class, .lua files | redis-py + Lua |
| Percentiles | numpy.percentile (method='linear') | NumPy |
| Volume Profile | Tick-size bins (5 ticks default) | Custom algorithm |
| Nautilus Timers | clock.set_timer() with callbacks | Nautilus Strategy |
| Prometheus | prometheus_client + HTTP server | prometheus_client |
| Redis Pooling | ConnectionPool (max 20 conn) | redis-py |
| Chaos Testing | pytest fixtures + Docker tc | pytest + Docker |

---

## Implementation Readiness

All 8 technical unknowns resolved. Proceed to Phase 1 design artifacts:
- data-model.md (entity specifications)
- contracts/report-schema-v1.1.json (extended schema)
- quickstart.md (deployment guide)

**Next Action**: Mark Phase 0 complete, begin Phase 1.
