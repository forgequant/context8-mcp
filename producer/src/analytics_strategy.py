"""Market analytics strategy for embedded NautilusTrader analytics.

Implements fast-cycle market analytics with distributed coordination.
Generates reports every 250ms (configurable) and publishes to Redis KV store.
"""
import time
import random
import asyncio
from typing import Any, Dict, Set
import pandas as pd
from nautilus_trader.trading import Strategy
from nautilus_trader.trading.config import StrategyConfig
from nautilus_trader.model.data import TradeTick, OrderBookDeltas
from nautilus_trader.model.identifiers import InstrumentId
import structlog

from datetime import datetime, timezone
from src.state.symbol_state import SymbolState, TradeTick as StateTradeTick, PriceQty
from src.reporters.fast_cycle import generate_fast_report
from src.reporters.redis_cache import publish_report
from src.reporters.slow_cycle import calculate_slow_metrics, enrich_report  # US3
from src.metrics.prometheus import PrometheusMetrics
from src.coordinator.membership import NodeMembership
from src.coordinator.lease_manager import LeaseManager
from src.coordinator.assignment import SymbolAssignmentController

logger = structlog.get_logger()


class AnalyticsStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for market analytics strategy."""
    redis_client: Any = None  # Injected Redis client
    symbols: list[str] = []
    node_id: str = ""
    report_period_ms: int = 250
    slow_period_ms: int = 2000  # US3: Slow-cycle period
    metrics: Any = None  # Injected PrometheusMetrics
    # US2: Coordination parameters
    enable_coordination: bool = False
    heartbeat_interval_sec: float = 1.0
    rebalance_interval_sec: float = 2.5
    lease_ttl_ms: int = 2000
    min_hold_ms: int = 2000
    hrw_sticky_pct: float = 0.02


class MarketAnalyticsStrategy(Strategy):
    """Market analytics strategy with fast-cycle report generation.

    Subscribes to order book deltas and trade ticks, maintains per-symbol state,
    and generates market analytics reports on a fast cycle (default 250ms).

    For MVP (User Story 1), this implements:
    - Fast-cycle calculations (spread, depth, flow, health)
    - Report generation and Redis KV publishing
    - Prometheus metrics recording
    """

    def __init__(self, config: AnalyticsStrategyConfig) -> None:
        super().__init__(config)
        self.redis_client = config.redis_client
        self.symbols = config.symbols  # All symbols to potentially manage
        self.node_id = config.node_id
        self.report_period_ms = config.report_period_ms
        self.slow_period_ms = config.slow_period_ms  # US3: Slow-cycle period
        self.metrics: PrometheusMetrics = config.metrics

        # US2: Coordination parameters
        self.enable_coordination = config.enable_coordination
        self.heartbeat_interval_sec = config.heartbeat_interval_sec
        self.rebalance_interval_sec = config.rebalance_interval_sec
        self.lease_ttl_ms = config.lease_ttl_ms

        # Per-symbol state tracking
        self.symbol_states: Dict[str, SymbolState] = {}

        # US2: Distributed coordination components
        self.membership: NodeMembership | None = None
        self.lease_manager: LeaseManager | None = None
        self.assignment_controller: SymbolAssignmentController | None = None

        # Tracking currently owned symbols (vs all configured symbols)
        self.owned_symbols: Set[str] = set()

        # Writer tokens per symbol (from leases)
        self.writer_tokens: Dict[str, int] = {}

        # Default token for single-instance mode
        self.default_writer_token = 1

        # Background task tracking
        self._heartbeat_task = None
        self._rebalance_task = None
        self._lease_renewal_task = None

        # US3: Slow-cycle state tracking
        self._slow_cycle_running = False  # T074: Lag detection flag
        self._slow_cycle_skip_count = 0

        # T082: Structured logging with mandatory fields
        self._structured_logger = structlog.get_logger().bind(
            component="analytics_strategy",
            node_id=self.node_id
        )

        # Initialize coordination if enabled
        if self.enable_coordination:
            import socket
            import os

            self.membership = NodeMembership(
                redis_client=self.redis_client,
                node_id=self.node_id,
                hostname=socket.gethostname(),
                pid=os.getpid(),
                metrics_url=f"http://{socket.gethostname()}:9101/metrics",
                heartbeat_interval_sec=self.heartbeat_interval_sec,
                ttl_sec=int(self.heartbeat_interval_sec * 5)
            )

            self.lease_manager = LeaseManager(
                redis_client=self.redis_client,
                node_id=self.node_id
            )

            self.assignment_controller = SymbolAssignmentController(
                membership=self.membership,
                lease_manager=self.lease_manager,
                symbols=self.symbols,
                lease_ttl_ms=self.lease_ttl_ms,
                min_hold_ms=config.min_hold_ms,
                sticky_pct=config.hrw_sticky_pct
            )

            self.log.info(
                f"Analytics strategy initialized with coordination: node={self.node_id}, "
                f"symbols={self.symbols}, period_ms={self.report_period_ms}, "
                f"coordination=enabled"
            )
        else:
            # Single-instance mode: own all symbols immediately
            self.owned_symbols = set(self.symbols)
            self.log.info(
                f"Analytics strategy initialized: node={self.node_id}, "
                f"symbols={self.symbols}, period_ms={self.report_period_ms}, "
                f"coordination=disabled (single-instance mode)"
            )

    def on_start(self) -> None:
        """Called when strategy starts. Subscribe to market data and setup timer."""
        self.log.info(f"Analytics strategy starting for symbols: {self.symbols}")

        if self.enable_coordination:
            # US2: Start coordination background tasks
            self.log.info("Starting coordination tasks (heartbeat, rebalance, lease renewal)")

            # Start heartbeat loop
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop_async())

            # Start rebalancing loop
            self._rebalance_task = asyncio.create_task(self._rebalance_loop_async())

            # Start lease renewal loop
            self._lease_renewal_task = asyncio.create_task(self._lease_renewal_loop_async())

            # In coordination mode, symbols are acquired dynamically via rebalancing
            # Initial rebalance will happen soon
            self.log.info("Coordination mode: symbols will be acquired via HRW assignment")
        else:
            # Single-instance mode: initialize and subscribe to all symbols immediately
            for symbol_str in self.owned_symbols:
                self._initialize_symbol(symbol_str)
                self._subscribe_symbol(symbol_str)

            # T086: Update health status with owned symbols in single-instance mode
            self.metrics.update_health_status(owned_symbols=list(self.owned_symbols))

        # Setup fast-cycle timer (e.g., every 250ms)
        self.clock.set_timer(
            name="fast_cycle",
            interval=pd.Timedelta(milliseconds=self.report_period_ms),
            callback=self.on_fast_cycle,
        )

        # T072: Setup slow-cycle timer (US3: e.g., every 2000ms)
        self.clock.set_timer(
            name="slow_cycle",
            interval=pd.Timedelta(milliseconds=self.slow_period_ms),
            callback=self.on_slow_cycle,
        )

        # US2: Update metrics
        if self.metrics and self.enable_coordination:
            self.metrics.node_heartbeat.labels(node=self.node_id).set(1)
            self.metrics.symbols_assigned.labels(node=self.node_id).set(len(self.owned_symbols))

        self.log.info(
            f"Analytics strategy started: fast_cycle={self.report_period_ms}ms, "
            f"slow_cycle={self.slow_period_ms}ms, "
            f"owned_symbols={len(self.owned_symbols)}, coordination={self.enable_coordination}"
        )

    def on_fast_cycle(self, event) -> None:
        """Fast-cycle callback: generate and publish reports.

        Called every report_period_ms (default 250ms).
        Iterates over owned symbol states, generates reports, publishes to Redis,
        and records metrics.
        """
        cycle_start = time.perf_counter()

        # Only process owned symbols
        owned_states = {s: state for s, state in self.symbol_states.items() if s in self.owned_symbols}

        # Debug: log cycle execution
        self.log.info(f"fast_cycle_start: processing {len(owned_states)} symbols")

        for symbol, state in owned_states.items():
            try:
                # Calculate report generation time
                report_start = time.perf_counter()

                # US2: Validate fencing token before generating report
                if self.enable_coordination and self.lease_manager:
                    current_token = self.writer_tokens.get(symbol)
                    if current_token is None:
                        self.log.warning(f"report_skipped_no_lease: {symbol}")
                        continue

                    # Verify token hasn't changed (stale writer detection)
                    lease_info = self.lease_manager.get_lease_info(symbol)
                    if lease_info and lease_info.get("token") != current_token:
                        # T083: Structured log for lease conflict
                        self._structured_logger.bind(symbol=symbol).warning(
                            "lease_conflict",
                            our_token=current_token,
                            current_token=lease_info.get('token'),
                            reason="stale_token"
                        )
                        if self.metrics:
                            self.metrics.lease_conflicts.inc()
                        continue

                # Generate report (use per-symbol token in US2 mode, default token otherwise)
                writer_token = self.writer_tokens.get(symbol, self.default_writer_token) if self.enable_coordination else self.default_writer_token
                report = generate_fast_report(
                    state=state,
                    node_id=self.node_id,
                    writer_token=writer_token,
                    ticker_data=None  # TODO: Add ticker data integration
                )

                if report is None:
                    self.log.info(
                        f"report_skipped_insufficient_data for {symbol}: "
                        f"best_bid={state.best_bid}, best_ask={state.best_ask}, "
                        f"top_bids={len(state.order_book.top_bids)}, "
                        f"top_asks={len(state.order_book.top_asks)}"
                    )
                    continue

                report_gen_time_ms = (time.perf_counter() - report_start) * 1000

                # Publish to Redis
                publish_start = time.perf_counter()
                success = publish_report(
                    redis_client=self.redis_client,
                    symbol=symbol,
                    report=report
                )
                publish_time_ms = (time.perf_counter() - publish_start) * 1000

                if success:
                    # Record metrics
                    if self.metrics:
                        self.metrics.report_publish_rate.labels(
                            symbol=symbol
                        ).inc()

                        self.metrics.data_age.labels(
                            symbol=symbol
                        ).observe(report["data_age_ms"])

                        self.metrics.calc_latency.labels(
                            metric="report_generation",
                            cycle="fast"
                        ).observe(report_gen_time_ms)

                        self.metrics.calc_latency.labels(
                            metric="redis_publish",
                            cycle="fast"
                        ).observe(publish_time_ms)

                    # T082: Structured log for report publication with lag_ms
                    self._structured_logger.bind(
                        symbol=symbol,
                        lag_ms=report['data_age_ms']
                    ).debug(
                        "report_published",
                        report_gen_ms=round(report_gen_time_ms, 2),
                        publish_ms=round(publish_time_ms, 2),
                        writer_token=writer_token
                    )
                else:
                    self.log.warning(
                        f"report_publish_failed for {symbol}"
                    )

            except Exception as e:
                # T083: Structured log for calculation errors
                self._structured_logger.bind(symbol=symbol).error(
                    "calculation_error",
                    error_type=type(e).__name__,
                    error_message=str(e),
                    phase="fast_cycle"
                )

        # Record total cycle time
        cycle_time_ms = (time.perf_counter() - cycle_start) * 1000
        if self.metrics:
            self.metrics.calc_latency.labels(
                metric="fast_cycle_total",
                cycle="fast"
            ).observe(cycle_time_ms)

        if cycle_time_ms > self.report_period_ms * 0.8:
            # Warn if cycle takes >80% of period (risk of falling behind)
            utilization_pct = round((cycle_time_ms / self.report_period_ms) * 100, 1)
            self.log.warning(
                f"fast_cycle_slow: cycle_time_ms={round(cycle_time_ms, 2)}, "
                f"period_ms={self.report_period_ms}, utilization_pct={utilization_pct}"
            )

    def on_slow_cycle(self, event) -> None:
        """T073: Slow-cycle callback: calculate advanced analytics and enrich reports.

        Called every slow_period_ms (default 2000ms).
        Calculates volume profile, liquidity walls/vacuums, and anomaly detection.
        """
        # T074: Lag detection - skip if previous cycle still running
        if self._slow_cycle_running:
            self._slow_cycle_skip_count += 1
            self.log.warning(
                f"slow_cycle_skip: previous cycle still running, "
                f"skip_count={self._slow_cycle_skip_count}"
            )
            return

        self._slow_cycle_running = True
        cycle_start = time.perf_counter()

        try:
            # Process each owned symbol
            for symbol in list(self.owned_symbols):
                if symbol not in self.symbol_states:
                    continue

                state = self.symbol_states[symbol]

                try:
                    # T073: Calculate slow-cycle metrics
                    start_time = time.perf_counter()
                    slow_metrics = calculate_slow_metrics(state, tick_size=0.01)
                    calc_time_ms = (time.perf_counter() - start_time) * 1000

                    # Record metrics for slow calculations (T075-T077)
                    if self.metrics:
                        # T075: Volume profile latency
                        if slow_metrics.get("volume_profile"):
                            self.metrics.calc_latency.labels(
                                metric="volume_profile",
                                cycle="slow"
                            ).observe(calc_time_ms)

                        # T076: Liquidity calculation latency
                        if slow_metrics.get("liquidity_walls") or slow_metrics.get("liquidity_vacuums"):
                            self.metrics.calc_latency.labels(
                                metric="liquidity",
                                cycle="slow"
                            ).observe(calc_time_ms)

                        # T077: Anomaly detection latency
                        if slow_metrics.get("anomalies"):
                            self.metrics.calc_latency.labels(
                                metric="anomalies",
                                cycle="slow"
                            ).observe(calc_time_ms)

                    # Fetch current (fast-cycle) report from Redis
                    report_json = self.redis_client.get(f"report:{symbol}")

                    if report_json:
                        import json
                        base_report = json.loads(report_json)

                        # T071: Enrich report with slow-cycle data
                        enriched_report = enrich_report(base_report, slow_metrics)

                        # Publish enriched report
                        publish_report(
                            redis_client=self.redis_client,
                            symbol=symbol,
                            report=enriched_report
                        )

                        self._structured_logger.bind(symbol=symbol).debug(
                            "slow_cycle_enriched",
                            calc_time_ms=round(calc_time_ms, 2)
                        )

                except Exception as e:
                    self._structured_logger.bind(symbol=symbol).error(
                        "calculation_error",
                        error_type=type(e).__name__,
                        error_message=str(e),
                        phase="slow_cycle"
                    )

        finally:
            self._slow_cycle_running = False

        # Record total cycle time
        cycle_time_ms = (time.perf_counter() - cycle_start) * 1000

        if cycle_time_ms > self.slow_period_ms * 0.8:
            # Warn if cycle takes >80% of period
            utilization_pct = round((cycle_time_ms / self.slow_period_ms) * 100, 1)
            self.log.warning(
                f"slow_cycle_slow: cycle_time_ms={round(cycle_time_ms, 2)}, "
                f"period_ms={self.slow_period_ms}, utilization_pct={utilization_pct}"
            )

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        """Handle order book delta updates. Update symbol state from NautilusTrader cache."""
        symbol = deltas.instrument_id.symbol.value

        if symbol not in self.symbol_states:
            self.log.warning(
                f"order_book_deltas_untracked_symbol: {symbol}"
            )
            return

        state = self.symbol_states[symbol]

        try:
            # Use NautilusTrader's built-in order book from cache
            order_book = self.cache.order_book(deltas.instrument_id)

            if order_book is None:
                return

            # Extract best bid/ask from NautilusTrader order book
            best_bid_price = order_book.best_bid_price()
            best_ask_price = order_book.best_ask_price()
            best_bid_qty = order_book.best_bid_size()
            best_ask_qty = order_book.best_ask_size()

            # Only construct PriceQty if both price and qty are positive
            if best_bid_price and best_bid_qty and float(best_bid_qty) > 0:
                state.best_bid = PriceQty(
                    price=float(best_bid_price),
                    qty=float(best_bid_qty)
                )

            if best_ask_price and best_ask_qty and float(best_ask_qty) > 0:
                state.best_ask = PriceQty(
                    price=float(best_ask_price),
                    qty=float(best_ask_qty)
                )

            # Update timestamp if we got any order book data
            if best_bid_price or best_ask_price:
                state.last_event_ts = datetime.now(timezone.utc)

            # Extract full depth (up to 20 levels) from NautilusTrader order book
            state.order_book.bids.clear()
            state.order_book.asks.clear()

            # NautilusTrader provides methods to get all levels
            # Try to extract bid levels
            try:
                # Method 1: Try using bids() method (returns list of BookLevel)
                if hasattr(order_book, 'bids') and callable(order_book.bids):
                    bid_levels = order_book.bids()
                    for level in bid_levels[:20]:  # Take top 20
                        # Handle both method and property access
                        price_val = level.price() if callable(level.price) else level.price
                        size_val = level.size() if callable(level.size) else level.size
                        price = float(price_val)
                        qty = float(size_val)
                        if qty > 0:
                            state.order_book.bids[price] = qty
                # Method 2: Try accessing bids as property/attribute
                elif hasattr(order_book, 'bids'):
                    # Some versions might have bids as a SortedDict or similar
                    bids_data = order_book.bids
                    if hasattr(bids_data, 'items'):
                        for price, orders in list(bids_data.items())[:20]:
                            total_qty = sum(float(o.size) for o in orders) if hasattr(orders, '__iter__') else float(orders)
                            if total_qty > 0:
                                state.order_book.bids[float(price)] = total_qty
                # Fallback: use best bid only
                elif best_bid_price and best_bid_qty:
                    state.order_book.bids[float(best_bid_price)] = float(best_bid_qty)
            except Exception as e:
                self.log.warning(
                    f"bid_extraction_error for {symbol}: {type(e).__name__} - {e}, "
                    f"falling back to best bid only"
                )
                if best_bid_price and best_bid_qty:
                    state.order_book.bids[float(best_bid_price)] = float(best_bid_qty)

            # Try to extract ask levels
            try:
                # Method 1: Try using asks() method
                if hasattr(order_book, 'asks') and callable(order_book.asks):
                    ask_levels = order_book.asks()
                    for level in ask_levels[:20]:  # Take top 20
                        # Handle both method and property access
                        price_val = level.price() if callable(level.price) else level.price
                        size_val = level.size() if callable(level.size) else level.size
                        price = float(price_val)
                        qty = float(size_val)
                        if qty > 0:
                            state.order_book.asks[price] = qty
                # Method 2: Try accessing asks as property/attribute
                elif hasattr(order_book, 'asks'):
                    asks_data = order_book.asks
                    if hasattr(asks_data, 'items'):
                        for price, orders in list(asks_data.items())[:20]:
                            total_qty = sum(float(o.size) for o in orders) if hasattr(orders, '__iter__') else float(orders)
                            if total_qty > 0:
                                state.order_book.asks[float(price)] = total_qty
                # Fallback: use best ask only
                elif best_ask_price and best_ask_qty:
                    state.order_book.asks[float(best_ask_price)] = float(best_ask_qty)
            except Exception as e:
                self.log.warning(
                    f"ask_extraction_error for {symbol}: {type(e).__name__} - {e}, "
                    f"falling back to best ask only"
                )
                if best_ask_price and best_ask_qty:
                    state.order_book.asks[float(best_ask_price)] = float(best_ask_qty)

            # Recompute top levels
            state.order_book._recompute_top()

            # Log successful depth extraction
            self.log.debug(
                f"order_book_updated for {symbol}: "
                f"bid_levels={len(state.order_book.bids)}, "
                f"ask_levels={len(state.order_book.asks)}"
            )

        except Exception as e:
            self.log.error(
                f"order_book_update_error for {symbol}: {type(e).__name__} - {e}"
            )

    def on_trade_tick(self, tick: TradeTick) -> None:
        """Handle trade tick updates. Update symbol state."""
        symbol = tick.instrument_id.symbol.value

        if symbol not in self.symbol_states:
            self.log.warning(
                f"trade_tick_untracked_symbol: {symbol}"
            )
            return

        state = self.symbol_states[symbol]

        try:
            # Convert NautilusTrader TradeTick to StateTradeTick
            # ts_init is in nanoseconds, convert to datetime
            from datetime import datetime, timezone
            timestamp = datetime.fromtimestamp(tick.ts_init / 1_000_000_000, tz=timezone.utc)

            state_tick = StateTradeTick(
                timestamp=timestamp,
                price=float(tick.price),
                volume=float(tick.size),
                aggressor_side="BUY" if tick.aggressor_side.name == "BUYER" else "SELL"
            )

            state.add_trade(state_tick)

        except Exception as e:
            self.log.error(
                f"trade_tick_update_error for {symbol}: {type(e).__name__} - {e}"
            )

    # ========================================================================
    # US2: Coordination background loops
    # ========================================================================

    async def _heartbeat_loop_async(self):
        """Background task: Send heartbeats with jitter."""
        self.log.info("heartbeat_loop_started")

        while True:
            try:
                # Send heartbeat
                if self.membership:
                    self.membership.heartbeat()

                    # Update metrics
                    if self.metrics:
                        self.metrics.node_heartbeat.labels(node=self.node_id).set(1)

                    # Discover cluster members
                    active_nodes = self.membership.discover()

                    # T082: Structured log for heartbeat
                    self._structured_logger.debug(
                        "heartbeat_sent",
                        cluster_size=len(active_nodes)
                    )

                # Add jitter (±10%) to prevent thundering herd
                jitter = random.uniform(-0.1, 0.1)
                sleep_sec = self.heartbeat_interval_sec * (1 + jitter)
                await asyncio.sleep(sleep_sec)

            except Exception as e:
                self.log.error(f"heartbeat_loop_error: {type(e).__name__} - {e}")
                await asyncio.sleep(self.heartbeat_interval_sec)

    async def _rebalance_loop_async(self):
        """Background task: Rebalance symbol assignments via HRW."""
        self.log.info("rebalance_loop_started")

        # Initial delay to allow heartbeat to establish membership
        await asyncio.sleep(0.5)

        while True:
            try:
                if not self.assignment_controller:
                    await asyncio.sleep(self.rebalance_interval_sec)
                    continue

                # Trigger rebalancing
                rebalance_result = self.assignment_controller.rebalance()

                symbols_to_acquire = rebalance_result.get("acquire", [])
                symbols_to_release = rebalance_result.get("release", [])

                # T083: Log rebalance trigger if changes detected
                if symbols_to_acquire or symbols_to_release:
                    self._structured_logger.info(
                        "rebalance_triggered",
                        symbols_to_acquire=len(symbols_to_acquire),
                        symbols_to_release=len(symbols_to_release),
                        total_owned=len(self.owned_symbols)
                    )

                # Release dropped symbols
                for symbol in symbols_to_release:
                    # T082: Structured log for rebalance drop
                    self._structured_logger.bind(symbol=symbol).info(
                        "symbol_dropped_by_rebalance",
                        reason="hrw_reassignment"
                    )
                    await self._on_symbol_dropped_async(symbol)

                # Acquire new symbols
                for symbol in symbols_to_acquire:
                    # T082: Structured log for rebalance acquisition
                    self._structured_logger.bind(symbol=symbol).info(
                        "symbol_acquired_by_rebalance",
                        reason="hrw_reassignment"
                    )
                    await self._on_symbol_acquired_async(symbol)

                # Update metrics
                if self.metrics:
                    self.metrics.symbols_assigned.labels(node=self.node_id).set(len(self.owned_symbols))
                    if len(symbols_to_acquire) > 0 or len(symbols_to_release) > 0:
                        self.metrics.hrw_rebalances.inc()

                # Add jitter to rebalance interval
                jitter = random.uniform(-0.1, 0.1)
                sleep_sec = self.rebalance_interval_sec * (1 + jitter)
                await asyncio.sleep(sleep_sec)

            except Exception as e:
                self.log.error(f"rebalance_loop_error: {type(e).__name__} - {e}")
                await asyncio.sleep(self.rebalance_interval_sec)

    async def _lease_renewal_loop_async(self):
        """Background task: Renew leases for owned symbols."""
        self.log.info("lease_renewal_loop_started")

        # Renew at ttl/2 (e.g., every 1000ms for 2000ms TTL)
        renewal_interval_sec = (self.lease_ttl_ms / 2) / 1000

        while True:
            try:
                if not self.lease_manager:
                    await asyncio.sleep(renewal_interval_sec)
                    continue

                # Renew leases for all owned symbols
                symbols_to_drop = []

                for symbol in list(self.owned_symbols):
                    try:
                        renewed = self.lease_manager.renew(symbol, self.lease_ttl_ms)

                        if renewed:
                            # T083: Log successful lease renewal
                            self._structured_logger.bind(symbol=symbol).debug(
                                "lease_renewed",
                                ttl_ms=self.lease_ttl_ms
                            )
                        else:
                            # Lost lease ownership - mark for dropping
                            # T082: Structured log for lease loss
                            self._structured_logger.bind(symbol=symbol).warning(
                                "lease_lost",
                                reason="renewal_failed"
                            )
                            symbols_to_drop.append(symbol)

                            # Record metric
                            if self.metrics:
                                self.metrics.lease_conflicts.inc()

                    except Exception as e:
                        self.log.error(
                            f"lease_renewal_error: symbol={symbol}, error={type(e).__name__} - {e}"
                        )

                # Drop symbols where lease renewal failed
                for symbol in symbols_to_drop:
                    await self._on_symbol_dropped_async(symbol)

                # Sleep until next renewal
                await asyncio.sleep(renewal_interval_sec)

            except Exception as e:
                self.log.error(f"lease_renewal_loop_error: {type(e).__name__} - {e}")
                await asyncio.sleep(renewal_interval_sec)

    # ========================================================================
    # US2: Symbol lifecycle handlers
    # ========================================================================

    async def _on_symbol_acquired_async(self, symbol: str):
        """Handler: Symbol acquired via rebalancing.

        1. Get token from assignment controller (lease already acquired)
        2. Initialize state
        3. Subscribe to market data
        4. Mark as owned
        """
        try:
            # Get token from assignment controller (lease already acquired by rebalance)
            if self.assignment_controller:
                token = self.assignment_controller.get_token_for_symbol(symbol)
                if token is None:
                    self.log.warning(
                        f"symbol_acquire_failed_no_token: {symbol}, no token from assignment controller"
                    )
                    return

                self.writer_tokens[symbol] = token
                self.log.info(f"token_retrieved: symbol={symbol}, token={token}")

            # Initialize symbol state
            self._initialize_symbol(symbol)

            # Subscribe to market data
            self._subscribe_symbol(symbol)

            # Mark as owned
            self.owned_symbols.add(symbol)

            # T086: Update health status with owned symbols
            self.metrics.update_health_status(owned_symbols=list(self.owned_symbols))

            # T082: Structured log for symbol acquisition
            self._structured_logger.bind(symbol=symbol).info(
                "symbol_acquired",
                owned_symbols=len(self.owned_symbols),
                writer_token=token
            )

        except Exception as e:
            self.log.error(
                f"symbol_acquire_error: symbol={symbol}, error={type(e).__name__} - {e}"
            )

    async def _on_symbol_dropped_async(self, symbol: str):
        """Handler: Symbol dropped via rebalancing or lease loss.

        1. Unsubscribe from market data
        2. Release lease
        3. Cleanup state
        4. Remove from owned
        """
        try:
            # Unsubscribe from market data
            self._unsubscribe_symbol(symbol)

            # Release lease
            if self.lease_manager:
                released = self.lease_manager.release(symbol)
                if released:
                    self.log.info(f"lease_released: {symbol}")
                else:
                    self.log.warning(f"lease_release_failed: {symbol} (already released?)")

                # Remove writer token
                self.writer_tokens.pop(symbol, None)

            # Remove from owned
            self.owned_symbols.discard(symbol)

            # T086: Update health status with owned symbols
            self.metrics.update_health_status(owned_symbols=list(self.owned_symbols))

            # Cleanup state (keep for potential re-acquisition)
            # Don't delete state immediately - allow reuse if symbol comes back
            # self.symbol_states.pop(symbol, None)

            # T082: Structured log for symbol drop
            self._structured_logger.bind(symbol=symbol).info(
                "symbol_dropped",
                owned_symbols=len(self.owned_symbols)
            )

        except Exception as e:
            self.log.error(
                f"symbol_drop_error: symbol={symbol}, error={type(e).__name__} - {e}"
            )

    # ========================================================================
    # US2: Helper methods
    # ========================================================================

    def _initialize_symbol(self, symbol: str):
        """Initialize symbol state."""
        if symbol not in self.symbol_states:
            self.symbol_states[symbol] = SymbolState(symbol=symbol)
            self.log.info(f"symbol_state_initialized: {symbol}")

    def _subscribe_symbol(self, symbol: str):
        """Subscribe to market data for symbol."""
        try:
            instrument_id = InstrumentId.from_str(f"{symbol}.BINANCE")

            # Verify instrument exists
            instrument = self.cache.instrument(instrument_id)
            if instrument is None:
                self.log.error(
                    f"instrument_not_found: {symbol} ({instrument_id}), "
                    f"available: {self.cache.instrument_ids()}"
                )
                return

            # Subscribe to order book deltas (depth 20)
            self.subscribe_order_book_deltas(instrument_id, depth=20)

            # Subscribe to trade ticks
            self.subscribe_trade_ticks(instrument_id)

            self.log.info(f"subscriptions_created: {symbol} ({instrument_id})")

        except Exception as e:
            self.log.error(
                f"subscription_failed: symbol={symbol}, error={type(e).__name__} - {e}"
            )

    def _unsubscribe_symbol(self, symbol: str):
        """Unsubscribe from market data for symbol."""
        try:
            instrument_id = InstrumentId.from_str(f"{symbol}.BINANCE")
            self.unsubscribe_order_book_deltas(instrument_id)
            self.unsubscribe_trade_ticks(instrument_id)
            self.log.info(f"unsubscribed: {symbol}")

        except Exception as e:
            self.log.error(
                f"unsubscribe_failed: symbol={symbol}, error={type(e).__name__} - {e}"
            )

    # ========================================================================
    # Lifecycle: Stop
    # ========================================================================

    def on_stop(self) -> None:
        """Called when strategy stops. Cleanup resources."""
        self.log.info("analytics_strategy_stopping")

        # US2: Cancel coordination background tasks
        if self.enable_coordination:
            self.log.info("stopping_coordination_tasks")

            if self._heartbeat_task:
                self._heartbeat_task.cancel()
                self.log.info("heartbeat_task_cancelled")

            if self._rebalance_task:
                self._rebalance_task.cancel()
                self.log.info("rebalance_task_cancelled")

            if self._lease_renewal_task:
                self._lease_renewal_task.cancel()
                self.log.info("lease_renewal_task_cancelled")

            # Release all leases
            if self.lease_manager:
                for symbol in list(self.owned_symbols):
                    try:
                        released = self.lease_manager.release(symbol)
                        if released:
                            # T082: Structured log for lease release on shutdown
                            self._structured_logger.bind(symbol=symbol).info(
                                "lease_released",
                                reason="shutdown"
                            )
                    except Exception as e:
                        self.log.error(f"lease_release_error: {symbol}, {e}")

            # Update metrics
            if self.metrics:
                self.metrics.node_heartbeat.labels(node=self.node_id).set(0)
                self.metrics.symbols_assigned.labels(node=self.node_id).set(0)

        # Cancel timers
        try:
            self.clock.cancel_timer("fast_cycle")
        except Exception as e:
            self.log.error(
                "timer_cancel_error",
                timer="fast_cycle",
                error=str(e)
            )

        # Unsubscribe from market data (only owned symbols)
        for symbol_str in list(self.owned_symbols):
            try:
                instrument_id = InstrumentId.from_str(f"{symbol_str}.BINANCE")
                self.unsubscribe_order_book_deltas(instrument_id)
                self.unsubscribe_trade_ticks(instrument_id)
            except Exception as e:
                self.log.error(
                    f"unsubscribe_failed for {symbol_str}: {e}"
                )

        # Clear symbol states
        self.symbol_states.clear()
        self.owned_symbols.clear()
        self.writer_tokens.clear()

        self.log.info("analytics_strategy_stopped")
