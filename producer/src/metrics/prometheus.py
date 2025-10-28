"""Prometheus metrics for embedded analytics."""
from prometheus_client import Counter, Gauge, Histogram, start_http_server
import structlog

logger = structlog.get_logger()


class PrometheusMetrics:
    """Prometheus metrics for NautilusTrader embedded analytics."""

    def __init__(self, port: int = 9101):
        """Initialize Prometheus metrics and start HTTP server.

        Args:
            port: Port for metrics HTTP server
        """
        self.port = port

        # Node health metrics
        self.node_heartbeat = Gauge(
            'nt_node_heartbeat',
            'Node heartbeat status (1=alive, 0=dead)',
            ['node']
        )

        self.symbols_assigned = Gauge(
            'nt_symbols_assigned',
            'Number of symbols assigned to node',
            ['node']
        )

        # Calculation latency metrics
        self.calc_latency = Histogram(
            'nt_calc_latency_ms',
            'Calculation latency in milliseconds',
            ['metric', 'cycle'],
            buckets=[1, 5, 10, 20, 50, 100, 200, 500, 1000, 2000]
        )

        # Publishing metrics
        self.report_publish_rate = Counter(
            'nt_report_publish_total',
            'Total reports published',
            ['symbol']
        )

        self.data_age = Histogram(
            'nt_data_age_ms',
            'Data age in milliseconds (freshness indicator)',
            ['symbol'],
            buckets=[10, 50, 100, 250, 500, 750, 1000, 1500, 2000, 5000]
        )

        # Coordination metrics
        self.lease_conflicts = Counter(
            'nt_lease_conflicts_total',
            'Number of lease conflicts detected'
        )

        self.hrw_rebalances = Counter(
            'nt_hrw_rebalances_total',
            'Number of HRW rebalancing cycles executed'
        )

        self.ws_resubscribe = Counter(
            'nt_ws_resubscribe_total',
            'Number of WebSocket resubscriptions',
            ['reason']
        )

        # Start HTTP server for /metrics endpoint
        try:
            start_http_server(port)
            logger.info("prometheus_metrics_server_started", port=port)
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning("prometheus_port_already_in_use", port=port)
            else:
                raise

    def record_calculation(self, metric_name: str, cycle: str, duration_ms: float) -> None:
        """Record calculation latency.

        Args:
            metric_name: Name of metric (e.g., "spread", "depth", "flow")
            cycle: Cycle type ("fast" or "slow")
            duration_ms: Duration in milliseconds
        """
        self.calc_latency.labels(metric=metric_name, cycle=cycle).observe(duration_ms)

    def record_report_published(self, symbol: str, data_age_ms: float) -> None:
        """Record report publication.

        Args:
            symbol: Symbol reported
            data_age_ms: Data age in milliseconds
        """
        self.report_publish_rate.labels(symbol=symbol).inc()
        self.data_age.labels(symbol=symbol).observe(data_age_ms)

    def set_node_heartbeat(self, node_id: str, alive: bool = True) -> None:
        """Set node heartbeat status.

        Args:
            node_id: Node identifier
            alive: True if alive, False if dead
        """
        self.node_heartbeat.labels(node=node_id).set(1 if alive else 0)

    def set_symbols_assigned(self, node_id: str, count: int) -> None:
        """Set number of symbols assigned to node.

        Args:
            node_id: Node identifier
            count: Number of symbols
        """
        self.symbols_assigned.labels(node=node_id).set(count)

    def increment_lease_conflict(self) -> None:
        """Increment lease conflict counter."""
        self.lease_conflicts.inc()

    def increment_rebalance(self) -> None:
        """Increment rebalancing counter."""
        self.hrw_rebalances.inc()

    def increment_ws_resubscribe(self, reason: str) -> None:
        """Increment WebSocket resubscription counter.

        Args:
            reason: Reason for resubscription (e.g., "disconnect", "symbol_acquired")
        """
        self.ws_resubscribe.labels(reason=reason).inc()

    def __repr__(self) -> str:
        return f"PrometheusMetrics(port={self.port})"
