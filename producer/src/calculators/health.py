"""Market health score calculation."""
from typing import Optional


def calculate_health_score(
    data_age_ms: Optional[int],
    spread_bps: Optional[float],
    imbalance: Optional[float],
    has_anomalies: bool = False
) -> dict:
    """Calculate overall market health score.

    Combines multiple factors:
    - Data freshness: <1000ms=ok, 1000-2000ms=degraded, >2000ms=down
    - Spread quality: <10bps=excellent, <50bps=good, >50bps=poor
    - Depth balance: abs(imbalance)<0.3=balanced, <0.6=moderate, >=0.6=imbalanced
    - Anomalies: presence of detected anomalies degrades score

    Args:
        data_age_ms: Age of last market data update in milliseconds
        spread_bps: Bid-ask spread in basis points
        imbalance: Order book imbalance [-1, 1]
        has_anomalies: Whether anomalies detected

    Returns:
        Dictionary with status ("ok"|"degraded"|"down") and numerical score [0-100]
    """
    score = 100.0
    issues = []

    # Data freshness scoring (40 points)
    if data_age_ms is None:
        score -= 40
        issues.append("no_data")
        status = "down"
    elif data_age_ms > 2000:
        score -= 40
        issues.append("stale_data")
        status = "down"
    elif data_age_ms > 1000:
        score -= 20
        issues.append("degraded_freshness")
        status = "degraded"
    else:
        status = "ok"

    # Spread quality scoring (30 points)
    if spread_bps is None:
        score -= 30
        issues.append("no_spread")
    elif spread_bps > 100:  # Very wide spread
        score -= 30
        issues.append("wide_spread")
        if status == "ok":
            status = "degraded"
    elif spread_bps > 50:  # Moderate spread
        score -= 15
        issues.append("moderate_spread")

    # Depth balance scoring (20 points)
    if imbalance is not None:
        abs_imbalance = abs(imbalance)
        if abs_imbalance >= 0.6:  # Severe imbalance
            score -= 20
            issues.append("severe_imbalance")
            if status == "ok":
                status = "degraded"
        elif abs_imbalance >= 0.3:  # Moderate imbalance
            score -= 10
            issues.append("moderate_imbalance")

    # Anomaly detection (10 points)
    if has_anomalies:
        score -= 10
        issues.append("anomalies_detected")
        if status == "ok":
            status = "degraded"

    # Ensure score is within [0, 100]
    score = max(0.0, min(100.0, score))

    return {
        "status": status,
        "score": round(score, 1),
        "issues": issues,
    }
