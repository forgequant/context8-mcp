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

    @classmethod
    def from_env(cls) -> "ProducerConfig":
        """Load configuration from environment variables."""
        symbols_str = os.getenv("SYMBOLS", "BTCUSDT,ETHUSDT")
        symbols = [s.strip() for s in symbols_str.split(",")]

        return cls(
            binance_api_key=os.getenv("BINANCE_API_KEY", ""),
            binance_api_secret=os.getenv("BINANCE_API_SECRET", ""),
            redis_url=os.getenv("REDIS_URL", "redis://localhost:6379"),
            redis_password=os.getenv("REDIS_PASSWORD", ""),
            stream_key=os.getenv("STREAM_KEY", "nt:binance"),
            symbols=symbols,
            log_level=os.getenv("LOG_LEVEL", "info").lower(),
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
