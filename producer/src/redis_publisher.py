"""Redis Streams publisher for market events.

Publishes MarketEventEnvelope to Redis Streams with JSON serialization.
Implements constitution principle 2 (Message Bus Contract) with snake_case field naming.
"""

import json
import time
from typing import Any
from dataclasses import asdict, dataclass

import redis
import structlog
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import TradeTick, QuoteTick, OrderBookDelta, OrderBookDeltas
from nautilus_trader.model.identifiers import InstrumentId

log = structlog.get_logger()


def _nanoseconds_to_rfc3339(nanos: int) -> str:
    """Convert Unix nanoseconds to RFC3339 timestamp string.

    Args:
        nanos: Unix timestamp in nanoseconds

    Returns:
        RFC3339 formatted string (e.g., 2025-10-28T12:00:00.123456Z)
    """
    from datetime import datetime, timezone
    seconds = nanos / 1_000_000_000
    dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
    # Format with microseconds and Z suffix for UTC
    return dt.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


@dataclass
class MarketEventEnvelope:
    """Envelope for market events published to Redis Streams.

    Implements data-model.md section 1.1 with snake_case field naming
    per constitution principle 2 (Message Bus Contract).
    """
    symbol: str
    venue: str
    type: str
    ts_event: str  # RFC3339 timestamp (e.g., 2025-10-28T12:00:00.123456Z)
    payload: dict[str, Any]


class RedisPublisher:
    """Publishes market events to Redis Streams.

    Reference-First Implementation:
    - Consulted .refs/go-redis for XADD patterns
    - Adapted to Python redis-py library
    - XADD ensures at-least-once delivery per constitution principle 1
    """

    def __init__(self, redis_url: str, stream_key: str, redis_password: str = ""):
        """Initialize Redis publisher.

        Args:
            redis_url: Redis connection URL (e.g., redis://localhost:6379)
            stream_key: Redis Stream key (e.g., nt:binance) per constitution principle 5
            redis_password: Redis password (optional)
        """
        self.redis_url = redis_url
        self.stream_key = stream_key

        # Parse Redis URL and create connection
        self.redis_client = redis.from_url(
            redis_url,
            password=redis_password if redis_password else None,
            decode_responses=False,  # We'll handle JSON encoding
        )

        self.log = log.bind(component="redis_publisher", stream_key=stream_key)
        self.log.info("redis_publisher_initialized", redis_url=redis_url)

    def publish_event(self, envelope: MarketEventEnvelope) -> str:
        """Publish a market event envelope to Redis Streams.

        Args:
            envelope: Market event envelope to publish

        Returns:
            str: Redis Stream message ID (e.g., "1234567890123-0")

        Per constitution principle 2, uses XADD to append to stream with JSON payload.
        """
        start_time = time.time()

        # Convert envelope to dict and serialize to JSON
        # Using snake_case per constitution principle 2 (Message Bus Contract)
        envelope_dict = asdict(envelope)
        json_payload = json.dumps(envelope_dict).encode('utf-8')

        # XADD: Append to stream
        # Pattern from .refs/go-redis stream_commands.go - XADD key * field value
        try:
            stream_id = self.redis_client.xadd(
                name=self.stream_key,
                fields={"data": json_payload},
                maxlen=100000,  # Trim stream to last 100k messages (prevent unbounded growth)
                approximate=True,  # Approximate trimming for performance
            )

            elapsed_ms = (time.time() - start_time) * 1000

            self.log.info(
                "event_published",
                symbol=envelope.symbol,
                type=envelope.type,
                stream_id=stream_id.decode('utf-8') if isinstance(stream_id, bytes) else stream_id,
                latency_ms=round(elapsed_ms, 2),
            )

            return stream_id.decode('utf-8') if isinstance(stream_id, bytes) else stream_id

        except redis.RedisError as e:
            self.log.error(
                "event_publish_failed",
                symbol=envelope.symbol,
                type=envelope.type,
                error=str(e),
            )
            raise

    def publish_trade_tick(self, tick: TradeTick) -> str:
        """Publish a trade tick to Redis Streams.

        Args:
            tick: NautilusTrader TradeTick object

        Returns:
            str: Redis Stream message ID
        """
        envelope = self._trade_tick_to_envelope(tick)
        return self.publish_event(envelope)

    def publish_quote_tick(self, tick: QuoteTick) -> str:
        """Publish a quote tick (best bid/ask) to Redis Streams.

        Args:
            tick: NautilusTrader QuoteTick object

        Returns:
            str: Redis Stream message ID
        """
        envelope = self._quote_tick_to_envelope(tick)
        return self.publish_event(envelope)

    def publish_order_book_deltas(self, deltas: OrderBookDeltas) -> str:
        """Publish order book deltas to Redis Streams.

        Args:
            deltas: NautilusTrader OrderBookDeltas object

        Returns:
            str: Redis Stream message ID
        """
        envelope = self._order_book_deltas_to_envelope(deltas)
        return self.publish_event(envelope)

    # Note: publish_order_book_depth removed for MVP
    # Full order book snapshots will be reconstructed from deltas
    # Uncomment and implement when OrderBook import is available

    def _trade_tick_to_envelope(self, tick: TradeTick) -> MarketEventEnvelope:
        """Convert NautilusTrader TradeTick to MarketEventEnvelope.

        Implements data-model.md section 1.2 (TradeTick payload).
        """
        instrument_id: InstrumentId = tick.instrument_id

        return MarketEventEnvelope(
            symbol=instrument_id.symbol.value,
            venue=instrument_id.venue.value,
            type="trade_tick",
            ts_event=_nanoseconds_to_rfc3339(tick.ts_event),
            payload={
                "price": str(tick.price),
                "size": str(tick.size),
                "aggressor_side": tick.aggressor_side.name,
                "trade_id": tick.trade_id.value,
            }
        )

    def _quote_tick_to_envelope(self, tick: QuoteTick) -> MarketEventEnvelope:
        """Convert NautilusTrader QuoteTick to MarketEventEnvelope.

        Used for ticker_24h equivalent data.
        """
        instrument_id: InstrumentId = tick.instrument_id

        return MarketEventEnvelope(
            symbol=instrument_id.symbol.value,
            venue=instrument_id.venue.value,
            type="ticker_24h",
            ts_event=_nanoseconds_to_rfc3339(tick.ts_event),
            payload={
                "bid_price": str(tick.bid_price),
                "bid_size": str(tick.bid_size),
                "ask_price": str(tick.ask_price),
                "ask_size": str(tick.ask_size),
            }
        )

    def _order_book_deltas_to_envelope(self, deltas: OrderBookDeltas) -> MarketEventEnvelope:
        """Convert NautilusTrader OrderBookDeltas to MarketEventEnvelope.

        Implements data-model.md section 1.4 (OrderBookDeltas payload).
        """
        instrument_id: InstrumentId = deltas.instrument_id

        delta_list = []
        for delta in deltas.deltas:
            delta_list.append({
                "side": delta.order.side.name,
                "action": delta.action.name,
                "price": str(delta.order.price),
                "size": str(delta.order.size),
                "order_id": delta.order.order_id,
            })

        return MarketEventEnvelope(
            symbol=instrument_id.symbol.value,
            venue=instrument_id.venue.value,
            type="order_book_deltas",
            ts_event=_nanoseconds_to_rfc3339(deltas.ts_event),
            payload={
                "deltas": delta_list,
            }
        )

    # _order_book_to_envelope removed for MVP - see publish_order_book_depth comment

    def close(self):
        """Close Redis connection."""
        self.redis_client.close()
        self.log.info("redis_publisher_closed")
