"""Configuration management for producer service."""
import os
from dataclasses import dataclass
from typing import List
from dotenv import load_dotenv

load_dotenv()


@dataclass
class ProducerConfig:
    """Configuration for the producer service."""

    # Binance API
    binance_api_key: str = ""
    binance_api_secret: str = ""

    # Redis
    redis_url: str = "redis://localhost:6379"
    redis_password: str = ""
    stream_key: str = "nt:binance"

    # Symbols
    symbols: List[str] = None

    # Observability
    log_level: str = "info"

    # Embedded Analytics (Feature: 002-nt-embedded-analytics)
    nt_enable_kv_reports: bool = False
    nt_enable_streams: bool = True
    nt_report_period_ms: int = 250
    nt_slow_period_ms: int = 2000
    # US2: Multi-instance coordination
    nt_enable_multi_instance: bool = False
    nt_lease_ttl_ms: int = 2000
    nt_node_id: str = ""
    nt_hrw_sticky_pct: float = 0.02
    nt_min_hold_ms: int = 2000
    nt_metrics_port: int = 9101

    @classmethod
    def from_env(cls) -> "ProducerConfig":
        """Load configuration from environment variables."""
        symbols_str = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT")
        symbols = [s.strip() for s in symbols_str.split(",")]

        # Generate node_id if not provided
        import socket
        node_id = os.getenv("NT_NODE_ID", "")
        if not node_id:
            node_id = f"nt-{socket.gethostname()}-{os.getpid()}"

        return cls(
            binance_api_key=os.getenv("BINANCE_API_KEY", ""),
            binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            redis_password=os.getenv("REDIS_PASSWORD", ""),
            stream_key=os.getenv("STREAM_KEY", "nt:binance"),
            symbols=symbols,
            # T084: Support NT_LOG_LEVEL with fallback to LOG_LEVEL
            log_level=os.getenv("NT_LOG_LEVEL", os.getenv("LOG_LEVEL", "info")).lower(),
            nt_enable_kv_reports=os.getenv("NT_ENABLE_KV_REPORTS", "false").lower() == "true",
            nt_enable_streams=os.getenv("NT_ENABLE_STREAMS", "true").lower() == "true",
            nt_report_period_ms=int(os.getenv("NT_REPORT_PERIOD_MS", "250")),
            nt_slow_period_ms=int(os.getenv("NT_SLOW_PERIOD_MS", "2000")),
            # US2: Multi-instance coordination
            nt_enable_multi_instance=os.getenv("NT_ENABLE_MULTI_INSTANCE", "false").lower() == "true",
            nt_lease_ttl_ms=int(os.getenv("NT_LEASE_TTL_MS", "2000")),
            nt_node_id=node_id,
            nt_hrw_sticky_pct=float(os.getenv("NT_HRW_STICKY_PCT", "0.02")),
            nt_min_hold_ms=int(os.getenv("NT_MIN_HOLD_MS", "2000")),
            nt_metrics_port=int(os.getenv("NT_METRICS_PORT", "9101")),
        )

    def validate(self) -> None:
        """Validate configuration."""
        if not self.symbols:
            raise ValueError("At least one symbol must be configured")

        for symbol in self.symbols:
            if not symbol.endswith("USDT"):
                raise ValueError(f"Symbol {symbol} must end with USDT for MVP")

        if self.log_level not in ["debug", "info", "warn", "error"]:
            raise ValueError(f"Invalid log level: {self.log_level}")

        # Validate analytics configuration
        if self.nt_enable_kv_reports:
            if self.nt_report_period_ms < 100 or self.nt_report_period_ms > 1000:
                raise ValueError(f"NT_REPORT_PERIOD_MS must be 100-1000ms, got {self.nt_report_period_ms}")

            if self.nt_slow_period_ms < 1000:
                raise ValueError(f"NT_SLOW_PERIOD_MS must be >= 1000ms, got {self.nt_slow_period_ms}")

            if self.nt_lease_ttl_ms < 2 * (self.nt_report_period_ms):
                raise ValueError(f"NT_LEASE_TTL_MS must be >= 2x report period for safe renewal")

            if not 0 <= self.nt_hrw_sticky_pct <= 0.1:
                raise ValueError(f"NT_HRW_STICKY_PCT must be 0-0.1 (0-10%), got {self.nt_hrw_sticky_pct}")

            if not self.nt_node_id:
                raise ValueError("NT_NODE_ID must be set when analytics enabled")

    def get_analytics_config(self) -> dict:
        """Get analytics configuration as dictionary.

        Returns:
            Dictionary with all analytics configuration fields
        """
        return {
            "enabled": self.nt_enable_kv_reports,
            "enable_streams": self.nt_enable_streams,
            "node_id": self.nt_node_id,
            "report_period_ms": self.nt_report_period_ms,
            "slow_period_ms": self.nt_slow_period_ms,
            # US2: Multi-instance coordination
            "enable_multi_instance": self.nt_enable_multi_instance,
            "lease_ttl_ms": self.nt_lease_ttl_ms,
            "hrw_sticky_pct": self.nt_hrw_sticky_pct,
            "min_hold_ms": self.nt_min_hold_ms,
            "metrics_port": self.nt_metrics_port,
            "redis_url": self.redis_url,
            "redis_password": self.redis_password,
            "symbols": self.symbols,
        }
