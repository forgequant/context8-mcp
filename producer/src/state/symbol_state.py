"""Per-symbol state management for market analytics calculations."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Tuple, Optional
from .ring_buffer import RingBuffer


@dataclass
class PriceQty:
    """Price and quantity pair for order book levels."""
    price: float
    qty: float

    def __post_init__(self):
        if self.price <= 0:
            raise ValueError(f"Price must be positive, got {self.price}")
        if self.qty <= 0:
            raise ValueError(f"Quantity must be positive, got {self.qty}")


@dataclass
class TradeTick:
    """Individual trade tick."""
    timestamp: datetime
    price: float
    volume: float  # Base currency quantity
    aggressor_side: str  # "BUY" or "SELL"

    def __post_init__(self):
        if self.aggressor_side not in ("BUY", "SELL"):
            raise ValueError(f"Invalid aggressor_side: {self.aggressor_side}")


class OrderBookL2:
    """Level 2 order book with top-N tracking."""

    def __init__(self, max_levels: int = 20):
        """Initialize order book.

        Args:
            max_levels: Maximum number of levels to track per side
        """
        self.bids: Dict[float, float] = {}  # price -> qty
        self.asks: Dict[float, float] = {}  # price -> qty
        self.top_bids: List[Tuple[float, float]] = []  # Sorted descending
        self.top_asks: List[Tuple[float, float]] = []  # Sorted ascending
        self.max_levels = max_levels

    def update_bid(self, price: float, qty: float) -> None:
        """Update or remove bid level.

        Args:
            price: Bid price
            qty: Quantity (0 to remove level)
        """
        if qty == 0:
            self.bids.pop(price, None)
        else:
            self.bids[price] = qty
        self._recompute_top()

    def update_ask(self, price: float, qty: float) -> None:
        """Update or remove ask level.

        Args:
            price: Ask price
            qty: Quantity (0 to remove level)
        """
        if qty == 0:
            self.asks.pop(price, None)
        else:
            self.asks[price] = qty
        self._recompute_top()

    def _recompute_top(self) -> None:
        """Recompute top N levels for both sides."""
        # Top bids: highest prices first
        self.top_bids = sorted(self.bids.items(), reverse=True)[:self.max_levels]
        # Top asks: lowest prices first
        self.top_asks = sorted(self.asks.items())[:self.max_levels]

    def get_best_bid(self) -> Optional[PriceQty]:
        """Get best bid (highest price)."""
        if self.top_bids:
            price, qty = self.top_bids[0]
            return PriceQty(price=price, qty=qty)
        return None

    def get_best_ask(self) -> Optional[PriceQty]:
        """Get best ask (lowest price)."""
        if self.top_asks:
            price, qty = self.top_asks[0]
            return PriceQty(price=price, qty=qty)
        return None


class SymbolState:
    """Complete state for a tracked symbol including order book and trade history."""

    def __init__(self, symbol: str):
        """Initialize symbol state.

        Args:
            symbol: Trading pair (e.g., "BTCUSDT")
        """
        self.symbol = symbol
        self.order_book = OrderBookL2(max_levels=20)

        # Last trade and best bid/ask
        self.last_trade: Optional[TradeTick] = None
        self.best_bid: Optional[PriceQty] = None
        self.best_ask: Optional[PriceQty] = None

        # Trade buffers for different time windows
        self.trade_buffer_10s = RingBuffer[TradeTick](1000)  # ~1000 trades for high-frequency
        self.trade_buffer_30s = RingBuffer[TradeTick](3000)
        self.trade_buffer_30min = RingBuffer[TradeTick](20000)  # 30min × ~10 trades/sec

        # Quantity history for percentile calculations
        self.quantity_history = RingBuffer[float](10000)

        # Last event timestamp for data freshness tracking
        self.last_event_ts: Optional[datetime] = None

    def update_order_book_bid(self, price: float, qty: float) -> None:
        """Update bid level in order book.

        Args:
            price: Bid price
            qty: Quantity (0 to remove)
        """
        self.order_book.update_bid(price, qty)
        self.best_bid = self.order_book.get_best_bid()

        # Track quantity for percentile calculations
        if qty > 0:
            self.quantity_history.append(qty)

        self.last_event_ts = datetime.now(timezone.utc)

    def update_order_book_ask(self, price: float, qty: float) -> None:
        """Update ask level in order book.

        Args:
            price: Ask price
            qty: Quantity (0 to remove)
        """
        self.order_book.update_ask(price, qty)
        self.best_ask = self.order_book.get_best_ask()

        # Track quantity for percentile calculations
        if qty > 0:
            self.quantity_history.append(qty)

        self.last_event_ts = datetime.now(timezone.utc)

    def add_trade(self, trade: TradeTick) -> None:
        """Add trade tick to all buffers.

        Args:
            trade: Trade tick to add
        """
        self.last_trade = trade
        self.trade_buffer_10s.append(trade)
        self.trade_buffer_30s.append(trade)
        self.trade_buffer_30min.append(trade)
        self.last_event_ts = trade.timestamp

    def check_order_book_invariants(self) -> bool:
        """Validate order book invariants.

        Returns:
            True if valid, False otherwise
        """
        if self.best_bid and self.best_ask:
            # No crossed book: best bid < best ask
            if self.best_bid.price >= self.best_ask.price:
                return False
        return True

    def validate_buffers_bounded(self) -> bool:
        """Validate all buffers respect their max size.

        Returns:
            True if all buffers within limits
        """
        checks = [
            len(self.trade_buffer_10s) <= self.trade_buffer_10s.max_size,
            len(self.trade_buffer_30s) <= self.trade_buffer_30s.max_size,
            len(self.trade_buffer_30min) <= self.trade_buffer_30min.max_size,
            len(self.quantity_history) <= self.quantity_history.max_size,
        ]
        return all(checks)

    def get_data_age_ms(self) -> Optional[int]:
        """Calculate data age in milliseconds.

        Returns:
            Age in milliseconds, or None if no events yet
        """
        if self.last_event_ts:
            age = (datetime.now(timezone.utc) - self.last_event_ts).total_seconds() * 1000
            return int(age)
        return None

    def __repr__(self) -> str:
        return (f"SymbolState(symbol={self.symbol}, "
                f"best_bid={self.best_bid}, best_ask={self.best_ask}, "
                f"trades_10s={len(self.trade_buffer_10s)}, "
                f"data_age_ms={self.get_data_age_ms()})")
