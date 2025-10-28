"""Order flow and trade rate calculations."""
from datetime import datetime, timedelta, timezone
from typing import Optional
from ..state.symbol_state import SymbolState


def calculate_orders_per_sec(state: SymbolState, window_seconds: int = 10) -> float:
    """Calculate order flow rate (trades per second) over time window.

    Args:
        state: Symbol state with trade buffers
        window_seconds: Time window in seconds (default 10)

    Returns:
        Trades per second over the window
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    recent_trades = state.trade_buffer_10s.filter_by_time(cutoff)

    if not recent_trades:
        return 0.0

    trade_count = len(recent_trades)
    trades_per_sec = trade_count / window_seconds

    return round(trades_per_sec, 2)


def calculate_net_flow(state: SymbolState, window_seconds: int = 30) -> Optional[dict]:
    """Calculate net order flow (buy volume - sell volume) over time window.

    Positive net flow indicates buying pressure (bullish).
    Negative net flow indicates selling pressure (bearish).

    Args:
        state: Symbol state with trade buffers
        window_seconds: Time window in seconds (default 30)

    Returns:
        Dictionary with buy_volume, sell_volume, net_flow, or None if no trades
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    recent_trades = state.trade_buffer_30s.filter_by_time(cutoff)

    if not recent_trades:
        return None

    buy_volume = 0.0
    sell_volume = 0.0

    for trade in recent_trades:
        if trade.aggressor_side == "BUY":
            buy_volume += trade.volume
        elif trade.aggressor_side == "SELL":
            sell_volume += trade.volume

    net_flow = buy_volume - sell_volume

    return {
        "buy_volume": round(buy_volume, 8),
        "sell_volume": round(sell_volume, 8),
        "net_flow": round(net_flow, 8),
    }
