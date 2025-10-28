"""Fast-cycle report generation for market analytics."""
from datetime import datetime, timezone
from typing import Optional
from ..state.symbol_state import SymbolState
from ..calculators.spread import calculate_spread_metrics
from ..calculators.depth import calculate_depth_metrics
from ..calculators.flow import calculate_orders_per_sec, calculate_net_flow
from ..calculators.health import calculate_health_score


def generate_fast_report(
    state: SymbolState,
    node_id: str,
    writer_token: int,
    ticker_data: Optional[dict] = None
) -> Optional[dict]:
    """Generate fast-cycle market report.

    Combines spread, depth, flow, and health metrics into a complete report
    conforming to MarketReport v1.1 schema.

    Args:
        state: Symbol state with order book and trade data
        node_id: Unique identifier of this producer instance
        writer_token: Monotonic fencing token from writer lease
        ticker_data: Optional 24h ticker statistics (last_price, change_24h_pct, etc.)

    Returns:
        Complete market report dictionary, or None if insufficient data
    """
    # Require minimum data to generate report
    if not state.best_bid or not state.best_ask:
        return None

    # Current timestamp
    now = datetime.now(timezone.utc)
    updated_at_ms = int(now.timestamp() * 1000)

    # Calculate data age and ingestion status
    data_age_ms = state.get_data_age_ms()
    if data_age_ms is None:
        data_age_ms = 0

    if data_age_ms > 2000:
        ingestion_status = "down"
    elif data_age_ms > 1000:
        ingestion_status = "degraded"
    else:
        ingestion_status = "ok"

    last_update = state.last_event_ts or now

    # Calculate spread metrics
    spread_metrics = calculate_spread_metrics(state)
    if not spread_metrics:
        return None

    # Calculate depth metrics
    depth_metrics = calculate_depth_metrics(state)
    if not depth_metrics:
        return None

    # Calculate flow metrics
    orders_per_sec = calculate_orders_per_sec(state)
    net_flow_data = calculate_net_flow(state)
    net_flow = net_flow_data["net_flow"] if net_flow_data else 0.0

    # Calculate health score
    health_data = calculate_health_score(
        data_age_ms=data_age_ms,
        spread_bps=spread_metrics["spread_bps"],
        imbalance=depth_metrics["imbalance"],
        has_anomalies=False  # Fast cycle doesn't detect anomalies yet
    )

    # Build depth object with top 20 levels
    depth_bids = [
        {"price": price, "qty": qty}
        for price, qty in state.order_book.top_bids
    ]
    depth_asks = [
        {"price": price, "qty": qty}
        for price, qty in state.order_book.top_asks
    ]

    # Extract ticker data (with fallbacks)
    last_price = state.last_trade.price if state.last_trade else spread_metrics["mid_price"]

    if ticker_data:
        change_24h_pct = ticker_data.get("change_24h_pct", 0.0)
        high_24h = ticker_data.get("high_24h", last_price)
        low_24h = ticker_data.get("low_24h", last_price)
        volume_24h = ticker_data.get("volume_24h", 0.0)
    else:
        # Fallback values when ticker data not available
        change_24h_pct = 0.0
        high_24h = last_price
        low_24h = last_price
        volume_24h = 0.0

    # Assemble complete report
    report = {
        "schemaVersion": "1.1",
        "writer": {
            "nodeId": node_id,
            "writerToken": writer_token,
        },
        "updatedAt": updated_at_ms,
        "symbol": state.symbol,
        "venue": "BINANCE",
        "generated_at": now.isoformat().replace('+00:00', 'Z'),
        "data_age_ms": data_age_ms,
        "ingestion": {
            "status": ingestion_status,
            "last_update": last_update.isoformat().replace('+00:00', 'Z'),
        },
        "last_price": last_price,
        "change_24h_pct": change_24h_pct,
        "high_24h": high_24h,
        "low_24h": low_24h,
        "volume_24h": volume_24h,
        "best_bid": {
            "price": state.best_bid.price,
            "qty": state.best_bid.qty,
        },
        "best_ask": {
            "price": state.best_ask.price,
            "qty": state.best_ask.qty,
        },
        "spread_bps": spread_metrics["spread_bps"],
        "mid_price": spread_metrics["mid_price"],
        "micro_price": spread_metrics["micro_price"],
        "depth": {
            "top20_bid": depth_bids,
            "top20_ask": depth_asks,
            "sum_bid": depth_metrics["total_bid_qty"],
            "sum_ask": depth_metrics["total_ask_qty"],
            "imbalance": depth_metrics["imbalance"],
        },
        "flow": {
            "orders_per_sec": orders_per_sec,
            "net_flow": net_flow,
        },
        "health": {
            "score": int(health_data["score"]),
            "components": {
                "spread": 0.0,
                "depth": 0.0,
                "balance": 0.0,
                "flow": 0.0,
                "anomalies": 0.0,
                "freshness": float(health_data["score"])  # MVP: use overall score for freshness
            },
        },
    }

    return report
