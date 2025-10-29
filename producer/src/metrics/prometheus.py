"""Prometheus metrics for embedded analytics."""
from prometheus_client import Counter, Gauge, Histogram, make_wsgi_app
from wsgiref.simple_server import make_server, WSGIRequestHandler
import json
import time
import threading
import structlog

logger = structlog.get_logger()


class HealthStatus:
    """Health status information for the node."""

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.start_time = time.time()
        self.owned_symbols: list[str] = []
        self.configured_symbols: list[str] = []
        self.coordination_enabled: bool = False
        self.is_healthy: bool = True

    def to_dict(self) -> dict:
        """Convert health status to dictionary."""
        uptime_sec = time.time() - self.start_time
        return {
            "status": "healthy" if self.is_healthy else "unhealthy",
            "node_id": self.node_id,
            "uptime_seconds": round(uptime_sec, 2),
            "coordination": {
                "enabled": self.coordination_enabled,
                "owned_symbols": self.owned_symbols,
                "configured_symbols": self.configured_symbols,
            }
        }


class HealthCheckHandler(WSGIRequestHandler):
    """Custom WSGI request handler that logs less verbosely."""

    def log_message(self, format, *args):
        """Suppress default logging (we use structlog)."""
        pass


def create_wsgi_app(health_status: HealthStatus):
    """Create WSGI app that serves both /metrics and /health endpoints."""
    metrics_app = make_wsgi_app()

    def app(environ, start_response):
        path = environ.get('PATH_INFO', '/')

        if path == '/health':
            # Serve health endpoint
            status = '200 OK' if health_status.is_healthy else '503 Service Unavailable'
            headers = [('Content-Type', 'application/json')]
            start_response(status, headers)
            return [json.dumps(health_status.to_dict()).encode('utf-8')]

        elif path == '/metrics' or path == '/':
            # Serve Prometheus metrics
            return metrics_app(environ, start_response)

        else:
            # 404 for unknown paths
            status = '404 Not Found'
            headers = [('Content-Type', 'text/plain')]
            start_response(status, headers)
            return [b'Not Found']

    return app


class PrometheusMetrics:
    """Prometheus metrics for NautilusTrader embedded analytics."""

    def __init__(self, port: int = 9101, node_id: str = ""):
        """Initialize Prometheus metrics and start HTTP server.

        Args:
            port: Port for metrics HTTP server
            node_id: Node identifier for health status
        """
        self.port = port
        self.node_id = node_id

        # T086: Initialize health status
        self.health_status = HealthStatus(node_id=node_id)

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

        # T086: Start HTTP server for /metrics and /health endpoints
        try:
            wsgi_app = create_wsgi_app(self.health_status)
            httpd = make_server('', port, wsgi_app, handler_class=HealthCheckHandler)

            # Run server in background thread
            server_thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            server_thread.start()

            logger.info("http_server_started", port=port, endpoints=["/metrics", "/health"])
        except OSError as e:
            if "Address already in use" in str(e):
                logger.warning("http_port_already_in_use", port=port)
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

    def update_health_status(
        self,
        owned_symbols: list[str] | None = None,
        configured_symbols: list[str] | None = None,
        coordination_enabled: bool | None = None,
        is_healthy: bool | None = None
    ) -> None:
        """Update health status information.

        Args:
            owned_symbols: List of symbols currently owned by this node
            configured_symbols: List of all configured symbols
            coordination_enabled: Whether multi-instance coordination is enabled
            is_healthy: Health status (True=healthy, False=unhealthy)
        """
        if owned_symbols is not None:
            self.health_status.owned_symbols = owned_symbols
        if configured_symbols is not None:
            self.health_status.configured_symbols = configured_symbols
        if coordination_enabled is not None:
            self.health_status.coordination_enabled = coordination_enabled
        if is_healthy is not None:
            self.health_status.is_healthy = is_healthy

    def validate_metrics(self) -> tuple[bool, list[str]]:
        """T085: Validate that all expected metrics are registered.

        Returns:
            Tuple of (all_present, missing_metrics)
        """
        # Map metric names to actual attribute names
        metric_to_attr = {
            'nt_node_heartbeat': 'node_heartbeat',
            'nt_symbols_assigned': 'symbols_assigned',
            'nt_calc_latency_ms': 'calc_latency',
            'nt_report_publish_total': 'report_publish_rate',
            'nt_data_age_ms': 'data_age',
            'nt_lease_conflicts_total': 'lease_conflicts',
            'nt_hrw_rebalances_total': 'hrw_rebalances',
            'nt_ws_resubscribe_total': 'ws_resubscribe',
        }

        missing = []
        for metric_name, attr_name in metric_to_attr.items():
            if not hasattr(self, attr_name):
                missing.append(metric_name)
                logger.warning("metric_not_found", metric=metric_name, expected_attr=attr_name)

        all_present = len(missing) == 0
        return all_present, missing

    def __repr__(self) -> str:
        return f"PrometheusMetrics(port={self.port})"
