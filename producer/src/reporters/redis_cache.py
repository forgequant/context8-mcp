"""Redis report caching and publishing."""
import json
import time
from typing import Optional
from redis import Redis, RedisError
import structlog

logger = structlog.get_logger()


def publish_report(
    redis_client: Redis,
    symbol: str,
    report: dict,
    max_retries: int = 3,
    retry_delay_ms: int = 100
) -> bool:
    """Publish market report to Redis cache.

    Uses Redis SET with KEEPTTL to preserve existing TTL on the key.
    Includes exponential backoff retry logic on failures.

    Args:
        redis_client: Redis client instance (with connection pooling)
        symbol: Trading pair symbol (e.g., "BTCUSDT")
        report: Complete market report dictionary
        max_retries: Maximum number of retry attempts (default 3)
        retry_delay_ms: Initial retry delay in milliseconds (doubles each retry)

    Returns:
        True if published successfully, False otherwise
    """
    key = f"report:{symbol}"

    try:
        # Serialize report to JSON
        report_json = json.dumps(report, separators=(',', ':'))

        # Attempt to publish with retries
        for attempt in range(max_retries):
            try:
                # SET with KEEPTTL preserves existing TTL (or no expiry if not set)
                result = redis_client.set(key, report_json, keepttl=True)

                if result:
                    logger.debug(
                        "report_published",
                        symbol=symbol,
                        key=key,
                        size_bytes=len(report_json),
                        attempt=attempt + 1
                    )
                    return True
                else:
                    logger.warning(
                        "report_publish_failed_no_result",
                        symbol=symbol,
                        key=key,
                        attempt=attempt + 1
                    )

            except RedisError as e:
                logger.warning(
                    "report_publish_redis_error",
                    symbol=symbol,
                    key=key,
                    attempt=attempt + 1,
                    max_retries=max_retries,
                    error=str(e)
                )

                # Exponential backoff before retry
                if attempt < max_retries - 1:
                    delay_sec = (retry_delay_ms * (2 ** attempt)) / 1000
                    time.sleep(delay_sec)
                    continue
                else:
                    # Final attempt failed
                    logger.error(
                        "report_publish_max_retries_exceeded",
                        symbol=symbol,
                        key=key,
                        max_retries=max_retries,
                        error=str(e)
                    )
                    return False

    except (TypeError, ValueError) as e:
        # JSON serialization error
        logger.error(
            "report_serialization_error",
            symbol=symbol,
            error=str(e),
            report_keys=list(report.keys()) if isinstance(report, dict) else "not_dict"
        )
        return False

    except Exception as e:
        # Unexpected error
        logger.error(
            "report_publish_unexpected_error",
            symbol=symbol,
            key=key,
            error=str(e),
            error_type=type(e).__name__
        )
        return False

    return False


def get_report(
    redis_client: Redis,
    symbol: str
) -> Optional[dict]:
    """Retrieve market report from Redis cache.

    Args:
        redis_client: Redis client instance
        symbol: Trading pair symbol (e.g., "BTCUSDT")

    Returns:
        Report dictionary if found, None otherwise
    """
    key = f"report:{symbol}"

    try:
        report_json = redis_client.get(key)

        if report_json:
            report = json.loads(report_json)
            return report
        else:
            return None

    except (RedisError, json.JSONDecodeError) as e:
        logger.error(
            "report_retrieval_error",
            symbol=symbol,
            key=key,
            error=str(e)
        )
        return None
