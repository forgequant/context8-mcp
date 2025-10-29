"""Slow-cycle report generation for compute-intensive analytics.

Calculates volume profile, liquidity features, and anomaly detection,
then enriches existing fast-cycle reports.
"""
from datetime import datetime, timezone
from typing import Any
import structlog

from src.state.symbol_state import SymbolState
from src.calculators.liquidity import (
    calculate_volume_profile,
    detect_liquidity_walls,
    detect_liquidity_vacuums
)
from src.calculators.anomalies import (
    detect_spoofing,
    detect_iceberg,
    detect_flash_crash_risk,
    calculate_flow_acceleration
)
from src.calculators.spread import calculate_mid_price
from src.calculators.depth import calculate_depth_metrics

logger = structlog.get_logger()


def calculate_slow_metrics(
    state: SymbolState,
    tick_size: float = 0.01
) -> dict[str, Any]:
    """Calculate slow-cycle analytics (volume profile, liquidity, anomalies).

    T070: Calls all slow-cycle calculators and returns computed metrics.

    Args:
        state: SymbolState with order book and trade history
        tick_size: Minimum price increment for volume profile binning

    Returns:
        Dictionary with slow-cycle metrics:
        {
            "volume_profile": {...},
            "liquidity_walls": [...],
            "liquidity_vacuums": [...],
            "anomalies": [...]
        }
    """
    metrics = {
        "volume_profile": None,
        "liquidity_walls": [],
        "liquidity_vacuums": [],
        "anomalies": []
    }

    try:
        # Calculate volume profile from 30-minute trade window
        trades_30min = list(state.trade_buffer_30min)
        if len(trades_30min) >= 10:
            metrics["volume_profile"] = calculate_volume_profile(
                trades=trades_30min,
                tick_size=tick_size,
                bins_per_tick=5
            )

        # Calculate mid price for anomaly detection
        mid_price = None
        if state.best_bid and state.best_ask:
            mid_price = calculate_mid_price(state.best_bid, state.best_ask)

        # Get quantity history for liquidity calculations
        quantity_history = list(state.quantity_history)

        # Detect liquidity walls
        if len(quantity_history) >= 10:
            metrics["liquidity_walls"] = detect_liquidity_walls(
                order_book=state.order_book,
                quantity_history=quantity_history,
                side="both"
            )

        # Detect liquidity vacuums
        if len(quantity_history) >= 10:
            metrics["liquidity_vacuums"] = detect_liquidity_vacuums(
                order_book=state.order_book,
                quantity_history=quantity_history,
                side="both"
            )

        # Detect anomalies (spoofing, iceberg, flash crash risk)
        anomalies = []

        if mid_price:
            # Spoofing detection
            spoofing = detect_spoofing(
                order_book=state.order_book,
                mid_price=mid_price
            )
            anomalies.extend(spoofing)

        # Iceberg detection (use 30s trade window)
        trades_30s = list(state.trade_buffer_30s)
        if len(trades_30s) >= 5:
            iceberg = detect_iceberg(
                trades=trades_30s,
                order_book=state.order_book
            )
            anomalies.extend(iceberg)

        # Flash crash risk detection
        if state.best_bid and state.best_ask:
            # Calculate required inputs
            depth_metrics = calculate_depth_metrics(state)
            trades_10s = list(state.trade_buffer_10s)
            flow_acceleration = calculate_flow_acceleration(trades_10s, window_sec=10)

            # Estimate spread in bps
            spread_bps = 0.0
            if mid_price and mid_price > 0:
                spread = state.best_ask.price - state.best_bid.price
                spread_bps = (spread / mid_price) * 10000

            # Only detect flash crash if we have depth metrics
            if depth_metrics is not None:
                flash_crash = detect_flash_crash_risk(
                    spread_bps=spread_bps,
                    depth_imbalance=depth_metrics.get("imbalance", 0.0),
                    flow_acceleration=flow_acceleration
                )

                if flash_crash:
                    anomalies.append(flash_crash)

        metrics["anomalies"] = anomalies

    except Exception as e:
        logger.error(
            "slow_metrics_calculation_error",
            symbol=state.symbol,
            error=str(e),
            error_type=type(e).__name__
        )

    return metrics


def enrich_report(
    base_report: dict[str, Any],
    slow_metrics: dict[str, Any]
) -> dict[str, Any]:
    """Enrich fast-cycle report with slow-cycle analytics.

    T071: Merges slow-cycle metrics into existing report without overwriting
    fast-cycle fields (spread, depth, flow, health).

    Args:
        base_report: Existing fast-cycle report
        slow_metrics: Slow-cycle metrics from calculate_slow_metrics()

    Returns:
        Enriched report with both fast and slow cycle data
    """
    # Create a copy to avoid modifying the original
    enriched = base_report.copy()

    # Add slow-cycle analytics to appropriate sections
    # Volume profile goes into analytics section
    if slow_metrics.get("volume_profile"):
        if "analytics" not in enriched:
            enriched["analytics"] = {}

        enriched["analytics"]["volume_profile"] = slow_metrics["volume_profile"]

    # Liquidity features
    if slow_metrics.get("liquidity_walls") or slow_metrics.get("liquidity_vacuums"):
        if "liquidity" not in enriched:
            enriched["liquidity"] = {}

        if slow_metrics.get("liquidity_walls"):
            enriched["liquidity"]["walls"] = slow_metrics["liquidity_walls"]

        if slow_metrics.get("liquidity_vacuums"):
            enriched["liquidity"]["vacuums"] = slow_metrics["liquidity_vacuums"]

    # Anomalies
    if slow_metrics.get("anomalies"):
        enriched["anomalies"] = slow_metrics["anomalies"]

    # Update timestamp to reflect enrichment
    enriched["slow_cycle_updated_at"] = int(datetime.now(timezone.utc).timestamp() * 1000)

    return enriched
