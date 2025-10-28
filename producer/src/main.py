"""Main entry point for the producer service.

Sets up NautilusTrader with Binance data client and publishes market events to Redis Streams.
Implements constitution principles 1, 2, and 4 (EDA architecture, Message Bus Contract, Tech Stack).

Reference-First Implementation:
- Consulted .refs/nautilus_trader/examples/sandbox/binance_spot_futures_sandbox.py
- Adapted TradingNode pattern for data-only publishing
- Integrated RedisPublisher for external message bus
"""

import asyncio
import signal
import sys
from typing import Any

import structlog
from nautilus_trader.adapters.binance.common.enums import BinanceAccountType
from nautilus_trader.adapters.binance.config import BinanceDataClientConfig
from nautilus_trader.adapters.binance.factories import BinanceLiveDataClientFactory
from nautilus_trader.adapters.binance import BINANCE
from nautilus_trader.config import CacheConfig, InstrumentProviderConfig, LoggingConfig, TradingNodeConfig
from nautilus_trader.live.node import TradingNode
from nautilus_trader.model.identifiers import TraderId, InstrumentId
from nautilus_trader.model.data import TradeTick, QuoteTick, OrderBookDelta, OrderBookDeltas
from nautilus_trader.trading import Strategy
from nautilus_trader.trading.config import StrategyConfig

from src.config import ProducerConfig
from src.redis_publisher import RedisPublisher
from src.redis_client import RedisClient
from src.analytics_strategy import MarketAnalyticsStrategy, AnalyticsStrategyConfig
from src.metrics.prometheus import PrometheusMetrics
from src.instrument_loader import load_binance_spot_instruments

# Configure structured logging per constitution principle 11
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

log = structlog.get_logger()


class PublisherStrategyConfig(StrategyConfig, frozen=True):
    """Configuration for publisher strategy."""
    redis_publisher: Any = None  # Injected dependency
    symbols: list[str] = []


class PublisherStrategy(Strategy):
    """Strategy that publishes market data to Redis Streams.

    This strategy subscribes to market data and publishes events to Redis Streams
    via RedisPublisher. Implements constitution principle 1 (layered EDA).
    """

    def __init__(self, config: PublisherStrategyConfig) -> None:
        super().__init__(config)
        self.redis_publisher: RedisPublisher = config.redis_publisher
        self.symbols = config.symbols
        # Note: self.log is already provided by Strategy parent class

    def on_start(self) -> None:
        """Called when strategy starts. Subscribe to market data."""
        self.log.info(f"Publisher strategy starting for symbols: {self.symbols}")

        # Subscribe to data for each symbol
        for symbol_str in self.symbols:
            try:
                # Parse instrument ID
                instrument_id = InstrumentId.from_str(f"{symbol_str}.BINANCE")

                # Verify instrument exists in cache
                instrument = self.cache.instrument(instrument_id)
                if instrument is None:
                    self.log.error(
                        f"Instrument not found: {symbol_str} ({instrument_id}). Available: {self.cache.instrument_ids()}"
                    )
                    continue

                # Subscribe to trade ticks per constitution principle 5 (Data Integration)
                self.subscribe_trade_ticks(instrument_id)

                # Subscribe to quote ticks (best bid/ask)
                self.subscribe_quote_ticks(instrument_id)

                # Subscribe to order book deltas per constitution principle 2
                self.subscribe_order_book_deltas(instrument_id, depth=20)

                self.log.info(
                    f"Subscribed to instrument: {symbol_str} ({instrument_id})"
                )

            except Exception as e:
                self.log.error(
                    f"Subscription failed for {symbol_str}: {type(e).__name__} - {str(e)}"
                )

        self.log.info("publisher_strategy_started")

    def on_trade_tick(self, tick: TradeTick) -> None:
        """Handle trade tick event. Publish to Redis Streams."""
        try:
            stream_id = self.redis_publisher.publish_trade_tick(tick)
            self.log.debug(
                f"trade_tick_published: symbol={tick.instrument_id.symbol.value}, "
                f"price={str(tick.price)}, size={str(tick.size)}, stream_id={stream_id}"
            )
        except Exception as e:
            self.log.error(
                f"trade_tick_publish_failed: symbol={tick.instrument_id.symbol.value}, error={str(e)}"
            )

    def on_quote_tick(self, tick: QuoteTick) -> None:
        """Handle quote tick event (best bid/ask). Publish to Redis Streams."""
        try:
            stream_id = self.redis_publisher.publish_quote_tick(tick)
            self.log.debug(
                f"quote_tick_published: symbol={tick.instrument_id.symbol.value}, "
                f"bid={str(tick.bid_price)}, ask={str(tick.ask_price)}, stream_id={stream_id}"
            )
        except Exception as e:
            self.log.error(
                f"quote_tick_publish_failed: symbol={tick.instrument_id.symbol.value}, error={str(e)}"
            )

    def on_order_book_deltas(self, deltas: OrderBookDeltas) -> None:
        """Handle order book deltas event. Publish to Redis Streams."""
        try:
            stream_id = self.redis_publisher.publish_order_book_deltas(deltas)
            self.log.debug(
                f"order_book_deltas_published: symbol={deltas.instrument_id.symbol.value}, "
                f"delta_count={len(deltas.deltas)}, stream_id={stream_id}"
            )
        except Exception as e:
            self.log.error(
                f"order_book_deltas_publish_failed: symbol={deltas.instrument_id.symbol.value}, error={str(e)}"
            )

    def on_stop(self) -> None:
        """Called when strategy stops. Cleanup subscriptions."""
        self.log.info("publisher_strategy_stopping")

        for symbol_str in self.symbols:
            try:
                instrument_id = InstrumentId.from_str(f"{symbol_str}.BINANCE")
                self.unsubscribe_trade_ticks(instrument_id)
                self.unsubscribe_quote_ticks(instrument_id)
                self.unsubscribe_order_book_deltas(instrument_id)
            except Exception as e:
                self.log.error(
                    f"unsubscribe_failed: symbol={symbol_str}, error={str(e)}"
                )

        self.log.info("publisher_strategy_stopped")


def main():
    """Main entry point for producer service."""
    log.info("producer_starting")

    # Load configuration
    config = ProducerConfig.from_env()
    try:
        config.validate()
    except ValueError as e:
        log.error("configuration_invalid", error=str(e))
        sys.exit(1)

    log.info(
        "configuration_loaded",
        redis_url=config.redis_url,
        stream_key=config.stream_key,
        symbols=config.symbols,
        log_level=config.log_level,
    )

    # Initialize Redis publisher
    redis_publisher = RedisPublisher(
        redis_url=config.redis_url,
        stream_key=config.stream_key,
        redis_password=config.redis_password,
    )

    # Configure NautilusTrader trading node
    # Reference: .refs/nautilus_trader/examples/sandbox/binance_spot_futures_sandbox.py
    node_config = TradingNodeConfig(
        trader_id=TraderId("CONTEXT8-PRODUCER-001"),
        logging=LoggingConfig(
            log_level=config.log_level.upper(),
            log_colors=False,  # Structured logging handles formatting
            use_pyo3=True,
        ),
        cache=CacheConfig(
            timestamps_as_iso8601=True,
            flush_on_start=False,
        ),
        data_clients={
            BINANCE: BinanceDataClientConfig(
                api_key=None,  # Public data only
                api_secret=None,
                account_type=BinanceAccountType.SPOT,
                base_url_http=None,
                base_url_ws=None,
                us=False,
                testnet=False,
                update_instruments_interval_mins=60,
                use_agg_trade_ticks=False,  # Use raw trade ticks per constitution
                instrument_provider=InstrumentProviderConfig(
                    load_all=False,  # Don't auto-load any instruments
                    load_ids=frozenset(),  # Empty set - we load manually via public API
                ),
            ),
        },
    )

    # Build trading node
    node = TradingNode(config=node_config)

    # Add publisher strategy with injected dependencies
    # Pattern: Dependency injection for testability and separation of concerns
    strategy_config = PublisherStrategyConfig(
        redis_publisher=redis_publisher,
        symbols=config.symbols,
    )
    strategy = PublisherStrategy(config=strategy_config)
    node.trader.add_strategy(strategy)

    # Conditionally add analytics strategy if enabled
    if config.nt_enable_kv_reports:
        log.info(f"analytics_enabled: node={config.nt_node_id}, period_ms={config.nt_report_period_ms}, port={config.nt_metrics_port}")

        # Initialize Prometheus metrics
        metrics = PrometheusMetrics(port=config.nt_metrics_port)
        metrics.set_node_heartbeat(config.nt_node_id, alive=True)
        metrics.set_symbols_assigned(config.nt_node_id, len(config.symbols))

        # Initialize Redis client for KV storage
        analytics_redis_client = RedisClient(
            url=config.redis_url,
            password=config.redis_password if config.redis_password else None
        )

        # Add analytics strategy with US2 coordination parameters
        analytics_config = AnalyticsStrategyConfig(
            redis_client=analytics_redis_client.get_client(),
            symbols=config.symbols,
            node_id=config.nt_node_id,
            report_period_ms=config.nt_report_period_ms,
            metrics=metrics,
            # US2: Multi-instance coordination
            enable_coordination=config.nt_enable_multi_instance,
            heartbeat_interval_sec=1.0,
            rebalance_interval_sec=2.5,
            lease_ttl_ms=config.nt_lease_ttl_ms,
            min_hold_ms=config.nt_min_hold_ms,
            hrw_sticky_pct=config.nt_hrw_sticky_pct,
        )
        analytics_strategy = MarketAnalyticsStrategy(config=analytics_config)
        node.trader.add_strategy(analytics_strategy)

        coordination_status = "enabled" if config.nt_enable_multi_instance else "disabled"
        log.info(f"Analytics strategy added for node {config.nt_node_id} (coordination={coordination_status})")
    else:
        log.info("Analytics disabled (NT_ENABLE_KV_REPORTS=false)")

    # Register data client factory per reference example
    node.add_data_client_factory(BINANCE, BinanceLiveDataClientFactory)

    # Build the node
    log.info("building_trading_node")
    node.build()

    # Load instruments from Binance public API (no auth required)
    log.info(f"loading_instruments_from_public_api: {config.symbols}")
    instruments = load_binance_spot_instruments(config.symbols)

    if not instruments:
        log.error("failed_to_load_instruments_cannot_continue")
        sys.exit(1)

    # Add instruments to cache
    for instrument_id, instrument in instruments.items():
        node.cache.add_instrument(instrument)
        log.info(f"cached_instrument: {instrument_id}")

    log.info(f"cached_{len(instruments)}_instruments_successfully")

    try:
        # Run the trading node (blocking)
        log.info("starting_trading_node")
        node.run()

    except Exception as e:
        log.error(
            "producer_error",
            error=str(e),
            error_type=type(e).__name__,
        )
        raise

    finally:
        # Shutdown gracefully
        log.info("producer_shutting_down")
        node.dispose()
        redis_publisher.close()
        log.info("producer_stopped")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("producer_interrupted")
        sys.exit(0)
    except Exception as e:
        log.error("producer_fatal_error", error=str(e), error_type=type(e).__name__)
        sys.exit(1)
