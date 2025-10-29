"""Liquidity analytics calculators for market data.

Includes volume profile (POC/VAH/VAL), liquidity walls, and vacuum detection.
"""
import numpy as np
from typing import Optional
from src.state.symbol_state import TradeTick, OrderBookL2


def calculate_volume_profile(
    trades: list[TradeTick],
    tick_size: float = 0.01,
    bins_per_tick: int = 5
) -> dict | None:
    """Calculate volume profile with POC, VAH, and VAL.

    Uses tick-based binning to compute Point of Control (POC), Value Area High (VAH),
    and Value Area Low (VAL) from trade history.

    Args:
        trades: List of TradeTick objects
        tick_size: Minimum price increment (e.g., 0.01 for BTCUSDT)
        bins_per_tick: Number of bins per tick (default 5 for precision)

    Returns:
        dict with POC, VAH, VAL, window_sec, trade_count or None if insufficient data

    Example:
        {
            "POC": 43250.5,
            "VAH": 43500.0,
            "VAL": 43000.0,
            "window_sec": 1800,
            "trade_count": 1523
        }
    """
    # T061: Validation - minimum 10 trades required
    if not trades or len(trades) < 10:
        return None

    # Extract prices and volumes from trades
    prices = np.array([t.price for t in trades])
    volumes = np.array([t.volume for t in trades])

    # T058: Tick-based binning (5 bins per tick)
    bin_size = tick_size / bins_per_tick
    bins = np.arange(prices.min(), prices.max() + bin_size, bin_size)

    # Create histogram weighted by volume
    hist, edges = np.histogram(prices, bins=bins, weights=volumes)

    # T059: POC calculation - find bin with max volume
    poc_idx = np.argmax(hist)
    poc_price = (edges[poc_idx] + edges[poc_idx + 1]) / 2

    # T060: VAH/VAL calculation - expand from POC until 70% volume reached
    total_volume = hist.sum()
    target_volume = total_volume * 0.70

    # Start from POC and expand in both directions
    left_idx = poc_idx
    right_idx = poc_idx
    accumulated_volume = hist[poc_idx]

    # Expand outward until we reach 70% of total volume
    while accumulated_volume < target_volume:
        # Check which direction has more volume
        left_volume = hist[left_idx - 1] if left_idx > 0 else 0
        right_volume = hist[right_idx + 1] if right_idx < len(hist) - 1 else 0

        if left_volume >= right_volume and left_idx > 0:
            left_idx -= 1
            accumulated_volume += hist[left_idx]
        elif right_idx < len(hist) - 1:
            right_idx += 1
            accumulated_volume += hist[right_idx]
        else:
            # Can't expand further
            break

    val = edges[left_idx]
    vah = edges[right_idx + 1]

    # T061: Validate invariant VAL <= POC <= VAH
    if not (val <= poc_price <= vah):
        # This shouldn't happen with correct implementation, but guard against edge cases
        return None

    # Calculate time window
    if len(trades) >= 2:
        window_sec = int((trades[-1].timestamp - trades[0].timestamp).total_seconds())
    else:
        window_sec = 0

    return {
        "POC": float(poc_price),
        "VAH": float(vah),
        "VAL": float(val),
        "window_sec": window_sec,
        "trade_count": len(trades)
    }


def detect_liquidity_walls(
    order_book: OrderBookL2,
    quantity_history: list[float],
    side: str = "both"
) -> list[dict]:
    """Detect liquidity walls in the order book.

    Liquidity walls are large concentrated orders significantly above normal size.
    Uses P95 percentile as baseline threshold.

    Args:
        order_book: OrderBookL2 with current bid/ask levels
        quantity_history: Historical quantities for percentile calculation
        side: "bid", "ask", or "both"

    Returns:
        List of detected walls with structure:
        [{
            "side": "bid" | "ask",
            "price": 43250.5,
            "quantity": 15.5,
            "severity": "high" | "medium" | "low",
            "distance_bps": 25  # Distance from mid price in basis points
        }]
    """
    walls = []

    # T062: Calculate P95 threshold
    if not quantity_history or len(quantity_history) < 10:
        return walls

    quantities = np.array(quantity_history)
    p95_threshold = np.percentile(quantities, 95, method='linear')

    # Calculate mid price for distance calculation
    best_bid = order_book.get_best_bid()
    best_ask = order_book.get_best_ask()

    if not best_bid or not best_ask:
        return walls

    mid_price = (best_bid.price + best_ask.price) / 2

    # T063: Detect walls on bid side
    if side in ("bid", "both"):
        for price, qty in order_book.top_bids:
            if qty >= p95_threshold * 1.5:  # At least 1.5x P95
                # Classify severity
                if qty >= p95_threshold * 3.0:
                    severity = "high"
                elif qty >= p95_threshold * 2.0:
                    severity = "medium"
                else:
                    severity = "low"

                # Calculate distance in basis points
                distance_bps = abs((price - mid_price) / mid_price * 10000)

                walls.append({
                    "side": "bid",
                    "price": float(price),
                    "quantity": float(qty),
                    "severity": severity,
                    "distance_bps": int(distance_bps)
                })

    # T063: Detect walls on ask side
    if side in ("ask", "both"):
        for price, qty in order_book.top_asks:
            if qty >= p95_threshold * 1.5:
                # Classify severity
                if qty >= p95_threshold * 3.0:
                    severity = "high"
                elif qty >= p95_threshold * 2.0:
                    severity = "medium"
                else:
                    severity = "low"

                # Calculate distance in basis points
                distance_bps = abs((price - mid_price) / mid_price * 10000)

                walls.append({
                    "side": "ask",
                    "price": float(price),
                    "quantity": float(qty),
                    "severity": severity,
                    "distance_bps": int(distance_bps)
                })

    return walls


def detect_liquidity_vacuums(
    order_book: OrderBookL2,
    quantity_history: list[float],
    side: str = "both"
) -> list[dict]:
    """Detect liquidity vacuums in the order book.

    Liquidity vacuums are consecutive levels with abnormally low quantities.
    Uses P10 percentile as threshold for "thin" levels.

    Args:
        order_book: OrderBookL2 with current bid/ask levels
        quantity_history: Historical quantities for percentile calculation
        side: "bid", "ask", or "both"

    Returns:
        List of detected vacuums:
        [{
            "side": "bid" | "ask",
            "price_start": 43200.0,
            "price_end": 43100.0,
            "level_count": 12,
            "severity": "high" | "medium" | "low"
        }]
    """
    vacuums = []

    # T064: Calculate P10 threshold
    if not quantity_history or len(quantity_history) < 10:
        return vacuums

    quantities = np.array(quantity_history)
    p10_threshold = np.percentile(quantities, 10, method='linear')

    # T065: Detect vacuums on bid side (3+ consecutive thin levels)
    if side in ("bid", "both"):
        thin_run = []
        for price, qty in order_book.top_bids:
            if qty < p10_threshold:
                thin_run.append(price)
            else:
                # End of thin run
                if len(thin_run) >= 3:
                    # Classify severity based on run length
                    if len(thin_run) >= 10:
                        severity = "high"
                    elif len(thin_run) >= 6:
                        severity = "medium"
                    else:
                        severity = "low"

                    vacuums.append({
                        "side": "bid",
                        "price_start": float(thin_run[0]),
                        "price_end": float(thin_run[-1]),
                        "level_count": len(thin_run),
                        "severity": severity
                    })
                thin_run = []

        # Check final run
        if len(thin_run) >= 3:
            if len(thin_run) >= 10:
                severity = "high"
            elif len(thin_run) >= 6:
                severity = "medium"
            else:
                severity = "low"

            vacuums.append({
                "side": "bid",
                "price_start": float(thin_run[0]),
                "price_end": float(thin_run[-1]),
                "level_count": len(thin_run),
                "severity": severity
            })

    # T065: Detect vacuums on ask side
    if side in ("ask", "both"):
        thin_run = []
        for price, qty in order_book.top_asks:
            if qty < p10_threshold:
                thin_run.append(price)
            else:
                # End of thin run
                if len(thin_run) >= 3:
                    # Classify severity
                    if len(thin_run) >= 10:
                        severity = "high"
                    elif len(thin_run) >= 6:
                        severity = "medium"
                    else:
                        severity = "low"

                    vacuums.append({
                        "side": "ask",
                        "price_start": float(thin_run[0]),
                        "price_end": float(thin_run[-1]),
                        "level_count": len(thin_run),
                        "severity": severity
                    })
                thin_run = []

        # Check final run
        if len(thin_run) >= 3:
            if len(thin_run) >= 10:
                severity = "high"
            elif len(thin_run) >= 6:
                severity = "medium"
            else:
                severity = "low"

            vacuums.append({
                "side": "ask",
                "price_start": float(thin_run[0]),
                "price_end": float(thin_run[-1]),
                "level_count": len(thin_run),
                "severity": severity
            })

    return vacuums
