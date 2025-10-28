#!/usr/bin/env python3
"""
Simplified Binance market data producer using WebSocket API.
Connects to public Binance WebSocket streams and publishes to Redis.
No API keys required - uses public data only.
"""

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

import redis
import structlog
import websocket

log = structlog.get_logger()


class BinancePublicProducer:
    """Producer that connects to Binance public WebSocket streams."""

    def __init__(self, symbols: list[str], redis_url: str, stream_key: str):
        self.symbols = [s.lower() for s in symbols]  # Binance uses lowercase
        self.redis_url = redis_url
        self.stream_key = stream_key

        # Connect to Redis
        self.redis_client = redis.from_url(redis_url, decode_responses=False)

        # Build WebSocket URL for combined streams
        # https://binance-docs.github.io/apidocs/spot/en/#websocket-market-streams
        streams = []
        for symbol in self.symbols:
            streams.append(f"{symbol}@trade")  # Trade ticks
            streams.append(f"{symbol}@bookTicker")  # Best bid/ask
            streams.append(f"{symbol}@depth20@100ms")  # Order book depth (20 levels, 100ms updates)

        stream_names = "/".join(streams)
        self.ws_url = f"wss://stream.binance.com:9443/stream?streams={stream_names}"

        log.info("producer_initialized", symbols=symbols, streams_count=len(streams))

    def publish_event(self, event_type: str, symbol: str, payload: dict[str, Any]) -> None:
        """Publish event to Redis Streams."""
        try:
            # Format time as RFC3339 for Go: remove +00:00 and add Z for UTC
            ts = datetime.now(timezone.utc).isoformat().replace('+00:00', '') + 'Z'

            envelope = {
                "type": event_type,
                "symbol": symbol.upper(),
                "venue": "BINANCE",
                "ts_event": ts,  # RFC3339 format: 2025-10-28T12:00:00.123456Z
                "payload": payload,
            }

            # Serialize to JSON
            message_json = json.dumps(envelope)

            # Publish to Redis Stream
            stream_id = self.redis_client.xadd(
                self.stream_key,
                {"data": message_json},
                maxlen=10000,  # Keep last 10k messages
            )

            log.debug("event_published", type=event_type, symbol=symbol, stream_id=stream_id)

        except Exception as e:
            log.error("publish_failed", error=str(e), event_type=event_type)

    def on_message(self, ws, message: str) -> None:
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(message)

            # Binance combined stream format: {"stream": "...", "data": {...}}
            if "stream" not in data or "data" not in data:
                return

            stream_name = data["stream"]
            stream_data = data["data"]

            # Extract symbol and event type
            parts = stream_name.split("@")
            if len(parts) < 2:
                return

            symbol = parts[0].upper()
            stream_type = parts[1]

            # Process based on stream type
            if stream_type == "trade":
                self.process_trade(symbol, stream_data)
            elif stream_type == "bookTicker":
                self.process_book_ticker(symbol, stream_data)
            elif stream_type.startswith("depth"):
                self.process_depth(symbol, stream_data)

        except Exception as e:
            log.error("message_processing_failed", error=str(e), message=message[:200])

    def process_trade(self, symbol: str, data: dict) -> None:
        """Process trade tick data."""
        payload = {
            "price": float(data["p"]),  # Price
            "qty": float(data["q"]),  # Quantity (renamed to match Go model)
            "side": "sell" if data["m"] else "buy",  # buyer_maker=true means sell order was filled
            "trade_id": str(data["t"]),  # Trade ID
        }
        self.publish_event("trade_tick", symbol, payload)

    def process_book_ticker(self, symbol: str, data: dict) -> None:
        """Process best bid/ask ticker."""
        payload = {
            "last_price": 0.0,  # Not available in bookTicker
            "price_change_pct": 0.0,  # Not available in bookTicker
            "high_24h": 0.0,  # Not available in bookTicker
            "low_24h": 0.0,  # Not available in bookTicker
            "volume_24h": 0.0,  # Not available in bookTicker
            "best_bid": [float(data["b"]), float(data["B"])],  # [price, qty]
            "best_ask": [float(data["a"]), float(data["A"])],  # [price, qty]
        }
        self.publish_event("ticker_24h", symbol, payload)

    def process_depth(self, symbol: str, data: dict) -> None:
        """Process order book depth."""
        # Convert to Go's expected format: [][2]float64
        bids = [[float(p), float(q)] for p, q in data["bids"]]
        asks = [[float(p), float(q)] for p, q in data["asks"]]

        payload = {
            "bids": bids,
            "asks": asks,
            "levels": len(bids),  # Number of levels
        }
        self.publish_event("order_book_depth", symbol, payload)

    def on_error(self, ws, error) -> None:
        """Handle WebSocket errors."""
        log.error("websocket_error", error=str(error))

    def on_close(self, ws, close_status_code, close_msg) -> None:
        """Handle WebSocket close."""
        log.warning("websocket_closed", code=close_status_code, message=close_msg)

    def on_open(self, ws) -> None:
        """Handle WebSocket open."""
        log.info("websocket_connected", url=self.ws_url)

    def run(self) -> None:
        """Start the WebSocket connection and run forever."""
        log.info("producer_starting", url=self.ws_url)

        ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open,
        )

        # Run forever with automatic reconnection
        ws.run_forever(
            ping_interval=20,  # Send ping every 20s
            ping_timeout=10,  # Wait 10s for pong
        )


def main():
    """Main entry point."""
    log.info("simple_producer_starting")

    # Load configuration from environment
    symbols = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT").split(",")
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    stream_key = os.getenv("STREAM_KEY", "nt:binance")

    producer = BinancePublicProducer(
        symbols=symbols,
        redis_url=redis_url,
        stream_key=stream_key,
    )

    try:
        producer.run()
    except KeyboardInterrupt:
        log.info("producer_interrupted")
        sys.exit(0)
    except Exception as e:
        log.error("producer_fatal_error", error=str(e), error_type=type(e).__name__)
        sys.exit(1)


if __name__ == "__main__":
    main()
