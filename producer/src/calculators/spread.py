"""Spread metrics calculations."""
from typing import Optional
from ..state.symbol_state import SymbolState, PriceQty


def calculate_spread_bps(best_bid: PriceQty, best_ask: PriceQty) -> float:
    """Calculate spread in basis points.

    Args:
        best_bid: Best bid price and quantity
        best_ask: Best ask price and quantity

    Returns:
        Spread in basis points (1 bps = 0.01%)
    """
    if best_bid.price <= 0 or best_ask.price <= 0:
        return 0.0

    mid = (best_bid.price + best_ask.price) / 2
    spread = best_ask.price - best_bid.price
    spread_bps = (spread / mid) * 10000  # Convert to basis points

    return round(spread_bps, 4)


def calculate_mid_price(best_bid: PriceQty, best_ask: PriceQty) -> float:
    """Calculate mid price (simple average).

    Args:
        best_bid: Best bid price and quantity
        best_ask: Best ask price and quantity

    Returns:
        Mid price rounded to 8 decimals
    """
    mid = (best_bid.price + best_ask.price) / 2
    return round(mid, 8)


def calculate_micro_price(best_bid: PriceQty, best_ask: PriceQty) -> float:
    """Calculate volume-weighted microprice.

    Microprice weights bid/ask by opposite side quantity to reflect
    true market equilibrium price.

    Formula: (ask_qty * bid_price + bid_qty * ask_price) / (bid_qty + ask_qty)

    Args:
        best_bid: Best bid price and quantity
        best_ask: Best ask price and quantity

    Returns:
        Microprice rounded to 8 decimals
    """
    total_qty = best_bid.qty + best_ask.qty

    if total_qty == 0:
        # Fallback to mid price if no quantities
        return calculate_mid_price(best_bid, best_ask)

    # Volume-weighted price
    micro = (best_ask.qty * best_bid.price + best_bid.qty * best_ask.price) / total_qty

    return round(micro, 8)


def calculate_spread_metrics(state: SymbolState) -> Optional[dict]:
    """Calculate all spread metrics for symbol state.

    Args:
        state: Symbol state with order book

    Returns:
        Dictionary with spread_bps, mid_price, micro_price, or None if no bid/ask
    """
    if not state.best_bid or not state.best_ask:
        return None

    return {
        "spread_bps": calculate_spread_bps(state.best_bid, state.best_ask),
        "mid_price": calculate_mid_price(state.best_bid, state.best_ask),
        "micro_price": calculate_micro_price(state.best_bid, state.best_ask),
    }
