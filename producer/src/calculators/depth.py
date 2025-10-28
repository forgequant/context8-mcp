"""Order book depth calculations."""
from typing import Optional
from ..state.symbol_state import SymbolState


def calculate_depth_metrics(state: SymbolState) -> Optional[dict]:
    """Calculate order book depth metrics from top levels.

    Computes:
    - total_bid_qty: Sum of quantities across top bid levels
    - total_ask_qty: Sum of quantities across top ask levels
    - imbalance: (bid_qty - ask_qty) / (bid_qty + ask_qty), range [-1, 1]

    Args:
        state: Symbol state with order book

    Returns:
        Dictionary with depth metrics, or None if order book incomplete
    """
    if not state.order_book.top_bids or not state.order_book.top_asks:
        return None

    # Sum quantities across top levels
    total_bid_qty = sum(qty for price, qty in state.order_book.top_bids)
    total_ask_qty = sum(qty for price, qty in state.order_book.top_asks)

    # Calculate imbalance: positive means more bids (bullish), negative means more asks (bearish)
    total_qty = total_bid_qty + total_ask_qty
    if total_qty == 0:
        imbalance = 0.0
    else:
        imbalance = (total_bid_qty - total_ask_qty) / total_qty

    return {
        "total_bid_qty": round(total_bid_qty, 8),
        "total_ask_qty": round(total_ask_qty, 8),
        "imbalance": round(imbalance, 4),
    }
