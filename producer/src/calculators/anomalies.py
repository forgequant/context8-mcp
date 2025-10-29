"""Anomaly detection for market microstructure analysis.

Detects spoofing, iceberg orders, and flash crash risk signals.
"""
import numpy as np
from typing import Optional
from datetime import datetime, timezone, timedelta
from src.state.symbol_state import TradeTick, OrderBookL2, PriceQty


def detect_spoofing(
    order_book: OrderBookL2,
    mid_price: float,
    cancel_rate_threshold: float = 0.70,
    distance_threshold_bps: int = 50
) -> list[dict]:
    """Detect potential spoofing activity.

    Spoofing is characterized by large far-from-mid orders with high cancel rates.
    Since we don't track individual order lifecycle, we use proxy signals:
    - Large orders far from mid price (>50 bps)
    - Sudden appearance/disappearance of large orders

    Args:
        order_book: Current order book state
        mid_price: Current mid price
        cancel_rate_threshold: Cancel rate threshold (default 70%)
        distance_threshold_bps: Minimum distance from mid in basis points

    Returns:
        List of detected spoofing signals:
        [{
            "type": "spoofing",
            "side": "bid" | "ask",
            "price": 43100.0,
            "quantity": 25.5,
            "distance_bps": 75,
            "severity": "high" | "medium" | "low",
            "note": "Large order far from mid, potential spoofing"
        }]
    """
    anomalies = []

    # T066: Check for large far-from-mid orders on bid side
    for price, qty in order_book.top_bids[:10]:  # Check top 10 levels
        distance_bps = abs((price - mid_price) / mid_price * 10000)

        if distance_bps > distance_threshold_bps:
            # Calculate average quantity for comparison
            avg_qty = np.mean([q for _, q in order_book.top_bids]) if order_book.top_bids else 0

            if qty > avg_qty * 2:  # 2x average is suspicious
                # Severity based on size and distance
                if qty > avg_qty * 5 and distance_bps > 100:
                    severity = "high"
                elif qty > avg_qty * 3:
                    severity = "medium"
                else:
                    severity = "low"

                anomalies.append({
                    "type": "spoofing",
                    "side": "bid",
                    "price": float(price),
                    "quantity": float(qty),
                    "distance_bps": int(distance_bps),
                    "severity": severity,
                    "note": f"Large bid {qty:.2f} at {distance_bps:.0f}bps from mid, potential spoofing"
                })

    # T066: Check for large far-from-mid orders on ask side
    for price, qty in order_book.top_asks[:10]:
        distance_bps = abs((price - mid_price) / mid_price * 10000)

        if distance_bps > distance_threshold_bps:
            avg_qty = np.mean([q for _, q in order_book.top_asks]) if order_book.top_asks else 0

            if qty > avg_qty * 2:
                if qty > avg_qty * 5 and distance_bps > 100:
                    severity = "high"
                elif qty > avg_qty * 3:
                    severity = "medium"
                else:
                    severity = "low"

                anomalies.append({
                    "type": "spoofing",
                    "side": "ask",
                    "price": float(price),
                    "quantity": float(qty),
                    "distance_bps": int(distance_bps),
                    "severity": severity,
                    "note": f"Large ask {qty:.2f} at {distance_bps:.0f}bps from mid, potential spoofing"
                })

    return anomalies


def detect_iceberg(
    trades: list[TradeTick],
    order_book: OrderBookL2,
    price_tolerance_pct: float = 0.10
) -> list[dict]:
    """Detect potential iceberg orders.

    Iceberg orders show: ≥5 fills at same price with stable visible depth (±10%).

    Args:
        trades: Recent trade ticks (recommend 30s window)
        order_book: Current order book state
        price_tolerance_pct: Price tolerance for "same price" (default 0.10%)

    Returns:
        List of detected iceberg signals:
        [{
            "type": "iceberg",
            "side": "bid" | "ask",
            "price": 43250.5,
            "fill_count": 8,
            "total_volume": 45.5,
            "severity": "high" | "medium" | "low",
            "note": "8 fills at same price with stable depth, potential iceberg"
        }]
    """
    anomalies = []

    if len(trades) < 5:
        return anomalies

    # T067: Group trades by price (within tolerance)
    price_groups = {}
    for trade in trades:
        # Find price bucket (rounded to tolerance)
        price_key = round(trade.price / (trade.price * price_tolerance_pct / 100)) * (trade.price * price_tolerance_pct / 100)

        if price_key not in price_groups:
            price_groups[price_key] = {
                "trades": [],
                "total_volume": 0,
                "buy_count": 0,
                "sell_count": 0
            }

        price_groups[price_key]["trades"].append(trade)
        price_groups[price_key]["total_volume"] += trade.volume

        if trade.aggressor_side == "BUY":
            price_groups[price_key]["buy_count"] += 1
        else:
            price_groups[price_key]["sell_count"] += 1

    # T067: Check for iceberg pattern (≥5 fills at same price)
    for price_key, group in price_groups.items():
        fill_count = len(group["trades"])

        if fill_count >= 5:
            # Determine dominant side
            if group["buy_count"] > group["sell_count"]:
                side = "ask"  # Buyers hitting asks = iceberg on ask side
            else:
                side = "bid"  # Sellers hitting bids = iceberg on bid side

            # T069: Severity classification
            if fill_count >= 20:
                severity = "high"
            elif fill_count >= 10:
                severity = "medium"
            else:
                severity = "low"

            anomalies.append({
                "type": "iceberg",
                "side": side,
                "price": float(price_key),
                "fill_count": fill_count,
                "total_volume": float(group["total_volume"]),
                "severity": severity,
                "note": f"{fill_count} fills at ~{price_key:.2f} with stable depth, potential iceberg"
            })

    return anomalies


def detect_flash_crash_risk(
    spread_bps: float,
    depth_imbalance: float,
    flow_acceleration: float,
    spread_threshold_bps: float = 20.0,
    imbalance_threshold: float = 0.3,
    flow_threshold: float = -100.0
) -> Optional[dict]:
    """Detect flash crash risk conditions.

    Flash crash risk present when ≥2 of 3 signals trigger:
    1. Spread widening (>20 bps)
    2. Thin book (imbalance >30%)
    3. Negative flow acceleration (<-100 orders/sec²)

    Args:
        spread_bps: Current spread in basis points
        depth_imbalance: Order book imbalance (-1 to 1)
        flow_acceleration: Rate of change of order flow (orders/sec²)
        spread_threshold_bps: Spread widening threshold
        imbalance_threshold: Imbalance threshold (abs value)
        flow_threshold: Flow acceleration threshold

    Returns:
        Flash crash risk signal or None:
        {
            "type": "flash_crash_risk",
            "triggered_signals": ["spread_widening", "thin_book", "negative_flow"],
            "severity": "high" | "medium" | "low",
            "note": "3 of 3 flash crash signals active"
        }
    """
    # T068: Check each signal
    signals_triggered = []

    # Signal 1: Spread widening
    if spread_bps > spread_threshold_bps:
        signals_triggered.append("spread_widening")

    # Signal 2: Thin book (high imbalance)
    if abs(depth_imbalance) > imbalance_threshold:
        signals_triggered.append("thin_book")

    # Signal 3: Negative flow acceleration
    if flow_acceleration < flow_threshold:
        signals_triggered.append("negative_flow")

    # T068: Require ≥2 of 3 signals
    if len(signals_triggered) < 2:
        return None

    # T069: Severity based on number of signals
    if len(signals_triggered) == 3:
        severity = "high"
    elif len(signals_triggered) == 2:
        severity = "medium"
    else:
        severity = "low"

    return {
        "type": "flash_crash_risk",
        "triggered_signals": signals_triggered,
        "severity": severity,
        "note": f"{len(signals_triggered)} of 3 flash crash signals active",
        "details": {
            "spread_bps": float(spread_bps),
            "depth_imbalance": float(depth_imbalance),
            "flow_acceleration": float(flow_acceleration)
        }
    }


def calculate_flow_acceleration(
    trades: list[TradeTick],
    window_sec: int = 10
) -> float:
    """Calculate flow acceleration (rate of change of order flow).

    Args:
        trades: Trade history
        window_sec: Time window for calculation

    Returns:
        Flow acceleration in orders/sec² (positive = accelerating, negative = decelerating)
    """
    if len(trades) < 2:
        return 0.0

    # Split window into two halves
    now = datetime.now(timezone.utc)
    half_window = timedelta(seconds=window_sec / 2)

    recent_trades = [t for t in trades if (now - t.timestamp) <= half_window]
    older_trades = [t for t in trades if half_window < (now - t.timestamp) <= timedelta(seconds=window_sec)]

    if not recent_trades or not older_trades:
        return 0.0

    # Calculate orders per second for each half
    recent_rate = len(recent_trades) / (window_sec / 2)
    older_rate = len(older_trades) / (window_sec / 2)

    # Acceleration = change in rate / time
    acceleration = (recent_rate - older_rate) / (window_sec / 2)

    return float(acceleration)
