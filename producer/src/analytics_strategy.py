"""Market analytics strategy for embedded NautilusTrader analytics.

Implements fast-cycle market analytics with distributed coordination.
Generates reports every 250ms (configurable) and publishes to Redis KV store.
"""
import time
from typing import Any, Dict
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
from src.metrics.prometheus import PrometheusMetrics

logger = structlog.get_logger()


class AnalyticsStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for market analytics strategy."""
    redis_client: Any = None  # Injected Redis client
    symbols: list[str] = []
    node_id: str = ""
    report_period_ms: int = 250
    metrics: Any = None  # Injected PrometheusMetrics


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
        self.symbols = config.symbols
        self.node_id = config.node_id
        self.report_period_ms = config.report_period_ms
        self.metrics: PrometheusMetrics = config.metrics

        # Per-symbol state tracking
        self.symbol_states: Dict[str, SymbolState] = {}

        # Temporary writer token (MVP: single instance, no leases yet)
        # TODO US2: Integrate LeaseManager for distributed coordination
        self.writer_token = 1

        self.log.info(
            f"Analytics strategy initialized: node={self.node_id}, "
            f"symbols={self.symbols}, period_ms={self.report_period_ms}"
        )

    def on_start(self) -> None:
        """Called when strategy starts. Subscribe to market data and setup timer."""
        self.log.info(f"Analytics strategy starting for symbols: {self.symbols}")

        # Initialize symbol states
        for symbol_str in self.symbols:
            self.symbol_states[symbol_str] = SymbolState(symbol=symbol_str)
            self.log.info(f"Symbol state initialized: {symbol_str}")

        # Subscribe to market data for each symbol
        for symbol_str in self.symbols:
            try:
                instrument_id = InstrumentId.from_str(f"{symbol_str}.BINANCE")

                # Verify instrument exists
                instrument = self.cache.instrument(instrument_id)
                if instrument is None:
                    self.log.error(
                        f"Instrument not found: {symbol_str} ({instrument_id}), "
                        f"available: {self.cache.instrument_ids()}"
                    )
                    continue

                # Subscribe to order book deltas (depth 20)
                self.subscribe_order_book_deltas(instrument_id, depth=20)

                # Subscribe to trade ticks
                self.subscribe_trade_ticks(instrument_id)

                self.log.info(
                    f"Subscriptions created for {symbol_str} ({instrument_id})"
                )

            except Exception as e:
                self.log.error(
                    f"Subscription failed for {symbol_str}: {type(e).__name__} - {e}"
                )

        # Setup fast-cycle timer (e.g., every 250ms)
        self.clock.set_timer(
            name="fast_cycle",
            interval=pd.Timedelta(milliseconds=self.report_period_ms),
            callback=self.on_fast_cycle,
        )

        self.log.info(
            f"Analytics strategy started with fast cycle interval: {self.report_period_ms}ms"
        )

    def on_fast_cycle(self, event) -> None:
        """Fast-cycle callback: generate and publish reports.

        Called every report_period_ms (default 250ms).
        Iterates over all symbol states, generates reports, publishes to Redis,
        and records metrics.
        """
        cycle_start = time.perf_counter()

        # Debug: log cycle execution
        self.log.info(f"fast_cycle_start: processing {len(self.symbol_states)} symbols")

        for symbol, state in self.symbol_states.items():
            try:
                # Calculate report generation time
                report_start = time.perf_counter()

                # Generate report
                report = generate_fast_report(
                    state=state,
                    node_id=self.node_id,
                    writer_token=self.writer_token,
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

                    self.log.debug(
                        f"report_published: {symbol}, data_age_ms={report['data_age_ms']}, "
                        f"report_gen_ms={round(report_gen_time_ms, 2)}, "
                        f"publish_ms={round(publish_time_ms, 2)}"
                    )
                else:
                    self.log.warning(
                        f"report_publish_failed for {symbol}"
                    )

            except Exception as e:
                self.log.error(
                    f"fast_cycle_error for {symbol}: {type(e).__name__} - {e}"
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

            if best_bid_price and best_ask_price:
                state.best_bid = PriceQty(
                    price=float(best_bid_price),
                    qty=float(best_bid_qty) if best_bid_qty else 0.0
                )
                state.best_ask = PriceQty(
                    price=float(best_ask_price),
                    qty=float(best_ask_qty) if best_ask_qty else 0.0
                )

                # Update timestamp
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

    def on_stop(self) -> None:
        """Called when strategy stops. Cleanup resources."""
        self.log.info("analytics_strategy_stopping")

        # Cancel timers
        try:
            self.clock.cancel_timer("fast_cycle")
        except Exception as e:
            self.log.error(
                "timer_cancel_error",
                timer="fast_cycle",
                error=str(e)
            )

        # Unsubscribe from market data
        for symbol_str in self.symbols:
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

        # TODO US2: Release leases in distributed mode

        self.log.info("analytics_strategy_stopped")
