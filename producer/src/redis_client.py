"""Redis client with connection pooling for analytics."""
import socket
from typing import Optional
from redis import Redis, ConnectionPool
from redis.retry import Retry
from redis.backoff import ExponentialBackoff
import structlog

logger = structlog.get_logger()


class RedisClient:
    """Redis client with connection pooling and retry logic."""

    def __init__(
        self,
        url: str,
        password: Optional[str] = None,
        max_connections: int = 20,
        socket_timeout: int = 5,
        socket_connect_timeout: int = 2,
        retry_on_timeout: bool = True,
        health_check_interval: int = 30
    ):
        """Initialize Redis client with connection pool.

        Args:
            url: Redis URL (e.g., redis://localhost:6379)
            password: Redis password (optional)
            max_connections: Maximum connections in pool
            socket_timeout: Socket operation timeout in seconds
            socket_connect_timeout: Socket connection timeout in seconds
            retry_on_timeout: Whether to retry on timeout
            health_check_interval: Health check interval in seconds
        """
        self.url = url

        # Create connection pool
        self.pool = ConnectionPool.from_url(
            url,
            password=password,
            max_connections=max_connections,
            socket_timeout=socket_timeout,
            socket_connect_timeout=socket_connect_timeout,
            socket_keepalive=True,
            socket_keepalive_options={
                socket.TCP_KEEPIDLE: 60,
                socket.TCP_KEEPINTVL: 10,
                socket.TCP_KEEPCNT: 3
            },
            retry=Retry(ExponentialBackoff(), retries=3),
            retry_on_timeout=retry_on_timeout,
            health_check_interval=health_check_interval,
            decode_responses=True  # Auto-decode bytes to strings
        )

        # Create client using pool
        self.client = Redis(connection_pool=self.pool)

        logger.info(
            "redis_client_initialized",
            url=url,
            max_connections=max_connections,
            socket_timeout=socket_timeout
        )

    def get_client(self) -> Redis:
        """Get Redis client instance.

        Returns:
            Redis client (uses connection pool automatically)
        """
        return self.client

    def ping(self) -> bool:
        """Test Redis connection.

        Returns:
            True if connection successful
        """
        try:
            return self.client.ping()
        except Exception as e:
            logger.error("redis_ping_failed", error=str(e))
            return False

    def close(self) -> None:
        """Close connection pool and disconnect all connections."""
        try:
            self.pool.disconnect()
            logger.info("redis_client_closed")
        except Exception as e:
            logger.error("redis_client_close_error", error=str(e))

    def get_pool_stats(self) -> dict:
        """Get connection pool statistics.

        Returns:
            Dictionary with pool stats
        """
        return {
            "max_connections": self.pool.max_connections,
            "created_connections": len(self.pool._created_connections) if hasattr(self.pool, '_created_connections') else 0,
            "available_connections": len(self.pool._available_connections) if hasattr(self.pool, '_available_connections') else 0,
        }

    def __repr__(self) -> str:
        return f"RedisClient(url={self.url}, max_connections={self.pool.max_connections})"
