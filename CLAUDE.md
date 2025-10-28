# context8-mcp Development Guidelines

Auto-generated from all feature plans. Last updated: 2025-10-28

## Active Technologies

- Python 3.11+ + NautilusTrader (002-nt-embedded-analytics)
- redis-py 5.x + numpy 1.24+ + prometheus-client 0.19+ (002-nt-embedded-analytics)
- Go 1.24+ (MCP server)
- Redis 7.x (002-nt-embedded-analytics)

## Project Structure

```text
producer/
  coordinator/  # Distributed coordination (HRW, leases, heartbeat)
  calculators/  # Market analytics calculations
  state/        # Symbol state management (ring buffers, order book)
  reporters/    # Report assembly and publishing
  metrics/      # Prometheus metrics
mcp/
  internal/     # Go MCP server (read-only API)
specs/
  002-nt-embedded-analytics/  # Current feature
tests/
```

## Commands

**Python (NautilusTrader producer)**:
```bash
cd producer && pytest && ruff check .
```

**Go (MCP server)**:
```bash
cd mcp && go test ./... && golangci-lint run
```

## Code Style

### Python
- Use modern typing: `SomeType | None` instead of `Optional`, `dict` instead of `Dict`
- Prefer procedural over OOP unless justified
- Follow NautilusTrader Strategy patterns for timer-based callbacks
- Use `uv` for dependency management (not virtualenv)

### Go
- Use `ID` not `Id` (e.g., `userID` not `userId`)
- Use `any` instead of `interface{}` keyword

## NautilusTrader Patterns

### Timer-Based Callbacks

```python
from nautilus_trader.trading.strategy import Strategy
import pandas as pd

class MyStrategy(Strategy):
    def on_start(self):
        # Fast cycle (100-250ms)
        self.clock.set_timer(
            name="fast_cycle",
            interval=pd.Timedelta(milliseconds=250),
            callback=self.on_fast_cycle,
        )

        # Slow cycle (1-5s)
        self.clock.set_timer(
            name="slow_cycle",
            interval=pd.Timedelta(seconds=2),
            callback=self.on_slow_cycle,
        )

    def on_fast_cycle(self, event):
        # L1/L2/flow calculations
        pass

    def on_slow_cycle(self, event):
        # Volume profile, anomalies
        pass
```

### Accessing Order Book State

```python
from nautilus_trader.model.data import OrderBookDeltas
from nautilus_trader.model.identifiers import InstrumentId

def on_order_book_deltas(self, deltas: OrderBookDeltas):
    instrument_id = deltas.instrument_id
    order_book = self.cache.order_book(instrument_id)

    if order_book:
        best_bid = order_book.best_bid_price()
        best_ask = order_book.best_ask_price()
```

## Redis Patterns

### Lua Script Execution (redis-py)

Store Lua scripts in `.lua` files and use redis-py `Script` class:

```python
from redis import Redis
from redis.client import Script

# Load script once
with open("coordinator/scripts/acquire_lease.lua") as f:
    acquire_lease_script = Script(redis_client, f.read())

# Execute atomically
def acquire_lease(symbol: str, node_id: str, ttl_ms: int) -> int | None:
    """Acquire writer lease with fencing token."""
    lease_key = f"report:writer:{symbol}"
    token_key = f"report:writer:token:{symbol}"

    token = acquire_lease_script(
        keys=[lease_key, token_key],
        args=[node_id, ttl_ms]
    )

    return int(token) if token else None
```

Example Lua script (`acquire_lease.lua`):
```lua
-- KEYS[1]: report:writer:{symbol}
-- KEYS[2]: report:writer:token:{symbol}
-- ARGV[1]: node_id
-- ARGV[2]: ttl_ms

local acquired = redis.call("SET", KEYS[1], ARGV[1], "PX", ARGV[2], "NX")
if acquired then
    local token = redis.call("INCR", KEYS[2])
    return token
else
    return nil
end
```

### HRW Consistent Hashing with Hysteresis

```python
import hashlib

def hrw_hash(node_id: str, symbol: str) -> int:
    """Compute HRW hash using blake2b (8-byte digest)."""
    h = hashlib.blake2b(digest_size=8)
    h.update(f"{node_id}:{symbol}".encode('utf-8'))
    return int.from_bytes(h.digest(), byteorder='big')

def select_node(
    symbol: str,
    nodes: list[str],
    current_owner: str | None,
    sticky_pct: float = 0.02
) -> str:
    """
    Select node via HRW with sticky bonus to reduce rebalancing.

    Args:
        symbol: Symbol to assign
        nodes: List of active node IDs
        current_owner: Current owner (receives sticky bonus)
        sticky_pct: Sticky bonus percentage (default 2%)

    Returns:
        Node ID with highest weight
    """
    weights = {}
    for node in nodes:
        weight = hrw_hash(node, symbol)
        if current_owner and node == current_owner:
            weight = int(weight * (1 + sticky_pct))
        weights[node] = weight

    return max(weights, key=weights.get)
```

## Distributed Coordination Best Practices

### Writer Leases with Fencing Tokens

1. **Acquire lease atomically** (Lua script with SET NX PX + INCR)
2. **Renew at ttl/2 interval** (e.g., every 1000ms for 2000ms TTL)
3. **Always include fencing token in writes** (monotonically increasing)
4. **Check token before publishing** (reject stale writes)

```python
class WriterLease:
    def __init__(self, symbol: str, node_id: str, token: int, ttl_ms: int):
        self.symbol = symbol
        self.node_id = node_id
        self.token = token  # Fencing token
        self.expires_at = time.time() + (ttl_ms / 1000)

    def is_valid(self) -> bool:
        return time.time() < self.expires_at

    def should_renew(self) -> bool:
        # Renew at ttl/2 (50% of TTL remaining)
        return time.time() >= (self.expires_at - (self.ttl_ms / 2000))
```

### Heartbeat with Jitter

```python
import random

async def heartbeat_loop(node_id: str, interval_ms: int):
    while True:
        redis.set(f"nt:node:{node_id}", "alive", px=interval_ms * 5)

        # Add ±10% jitter to prevent thundering herd
        jitter = random.uniform(-0.1, 0.1)
        sleep_ms = interval_ms * (1 + jitter)
        await asyncio.sleep(sleep_ms / 1000)
```

## NumPy Patterns

### Percentile Calculations

```python
import numpy as np

# Liquidity walls: P95 of quantities
quantities = np.array([100.5, 250.0, 1500.0, 300.0])
p95_qty = np.percentile(quantities, 95, method='linear')

# Liquidity vacuums: P10 threshold
p10_qty = np.percentile(quantities, 10, method='linear')
```

### Volume Profile (Tick-Based Binning)

```python
def calculate_volume_profile(
    trades: list[tuple[float, float]],  # [(price, quantity)]
    tick_size: float = 0.01,
    bins_per_tick: int = 5
) -> dict:
    """
    Calculate POC, VAH, VAL using tick-based binning.

    Args:
        trades: List of (price, quantity) tuples
        tick_size: Minimum price increment
        bins_per_tick: Bins per tick (5 recommended)

    Returns:
        {POC, VAH, VAL, window_sec, trade_count}
    """
    prices = np.array([p for p, q in trades])
    volumes = np.array([q for p, q in trades])

    bin_size = tick_size / bins_per_tick
    bins = np.arange(prices.min(), prices.max() + bin_size, bin_size)

    hist, edges = np.histogram(prices, bins=bins, weights=volumes)

    poc_idx = np.argmax(hist)
    poc_price = (edges[poc_idx] + edges[poc_idx + 1]) / 2

    # Value area (70% of volume)
    total_volume = hist.sum()
    target_volume = total_volume * 0.70

    # Expand from POC until 70% volume reached
    # (implementation details in volume_profile.py)

    return {"POC": poc_price, "VAH": vah, "VAL": val}
```

## Prometheus Metrics

```python
from prometheus_client import Counter, Histogram, Gauge, start_http_server

# Metrics definitions
NODE_HEARTBEAT = Gauge('nt_node_heartbeat', 'Node heartbeat', ['node'])
SYMBOLS_ASSIGNED = Gauge('nt_symbols_assigned', 'Symbols assigned', ['node'])
LEASE_CONFLICTS = Counter('nt_lease_conflicts_total', 'Lease conflicts', ['symbol'])
CALC_LATENCY = Histogram(
    'nt_calc_latency_ms',
    'Calculation latency',
    ['metric', 'cycle'],
    buckets=[1, 5, 10, 20, 50, 100, 250, 500, 1000]
)

# Start metrics server
start_http_server(9101)

# Update metrics
NODE_HEARTBEAT.labels(node='nt-prod-01').set(1)
SYMBOLS_ASSIGNED.labels(node='nt-prod-01').set(5)

with CALC_LATENCY.labels(metric='spread', cycle='fast').time():
    calculate_spread()
```

## Redis Connection Pooling

```python
from redis import ConnectionPool, Redis

# Create pool once at startup
pool = ConnectionPool(
    host='redis',
    port=6379,
    max_connections=20,  # Max 20 per instance
    socket_keepalive=True,
    socket_keepalive_options={
        socket.TCP_KEEPIDLE: 60,
        socket.TCP_KEEPINTVL: 10,
        socket.TCP_KEEPCNT: 3
    }
)

# Reuse pool across application
redis_client = Redis(connection_pool=pool)
```

## Recent Changes

- 002-nt-embedded-analytics: Added Python 3.11+ + NautilusTrader + redis-py 5.x + numpy 1.24+ + prometheus-client (embedded analytics with distributed coordination)

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
