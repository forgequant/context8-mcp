"""
Simple REST API server for ChatGPT Custom Actions.
Provides get_report endpoint for market data.
"""
import asyncio
import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.middleware.cors import CORSMiddleware
import uvicorn

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class RedisCache:
    """Redis cache reader for market reports."""

    def __init__(self, redis_url: str):
        """Initialize Redis connection."""
        self.redis_url = redis_url
        self.client: aioredis.Redis | None = None

    async def connect(self):
        """Connect to Redis."""
        try:
            self.client = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            await self.client.ping()
            logger.info(f"Connected to Redis at {self.redis_url}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise

    async def close(self):
        """Close Redis connection."""
        if self.client:
            await self.client.aclose()
            logger.info("Redis connection closed")

    async def get_report(self, symbol: str) -> dict[str, Any] | None:
        """
        Fetch market report from Redis cache.

        Args:
            symbol: Trading symbol (e.g., BTCUSDT)

        Returns:
            Market report as dict or None if not found
        """
        if not self.client:
            raise RuntimeError("Redis client not connected")

        cache_key = f"report:{symbol}"

        try:
            json_str = await self.client.get(cache_key)
            if json_str is None:
                return None

            report = json.loads(json_str)
            return report

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON for {symbol}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get report for {symbol}: {e}")
            raise


# Global cache instance
cache: RedisCache | None = None


async def startup():
    """Startup event handler."""
    global cache
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    cache = RedisCache(redis_url)
    await cache.connect()
    logger.info("REST API server initialized")


async def shutdown():
    """Shutdown event handler."""
    global cache
    if cache:
        await cache.close()
    logger.info("REST API server shutdown")


async def health(request):
    """Health check endpoint."""
    return JSONResponse({
        "status": "healthy",
        "service": "context8-rest-api"
    })


async def get_report(request):
    """
    Get market report for a symbol.

    Query params:
        symbol: Trading symbol (e.g., BTCUSDT)
    """
    symbol = request.query_params.get("symbol", "").upper()

    if not symbol:
        return JSONResponse({
            "error": "Missing required parameter: symbol",
            "error_code": "MISSING_PARAMETER"
        }, status_code=400)

    # Validate symbol pattern
    import re
    if not re.match(r"^[A-Z0-9]+USDT$", symbol):
        return JSONResponse({
            "error": f"Invalid symbol format: {symbol}. Must match pattern: ^[A-Z0-9]+USDT$",
            "error_code": "INVALID_SYMBOL"
        }, status_code=400)

    try:
        report = await cache.get_report(symbol)

        if report is None:
            return JSONResponse({
                "error": f"Symbol '{symbol}' not found in cache",
                "error_code": "SYMBOL_NOT_FOUND"
            }, status_code=404)

        return JSONResponse(report)

    except Exception as e:
        logger.error(f"Failed to retrieve report for {symbol}: {e}", exc_info=True)
        return JSONResponse({
            "error": f"Failed to retrieve report: {str(e)}",
            "error_code": "INTERNAL_ERROR"
        }, status_code=500)


async def list_symbols(request):
    """
    List available symbols.
    """
    # Get all report:* keys from Redis
    try:
        keys = []
        async for key in cache.client.scan_iter("report:*"):
            symbol = key.replace("report:", "")
            keys.append(symbol)

        return JSONResponse({
            "symbols": sorted(keys),
            "count": len(keys)
        })

    except Exception as e:
        logger.error(f"Failed to list symbols: {e}", exc_info=True)
        return JSONResponse({
            "error": f"Failed to list symbols: {str(e)}",
            "error_code": "INTERNAL_ERROR"
        }, status_code=500)


# Create Starlette app
app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/api/report", get_report, methods=["GET"]),
        Route("/api/symbols", list_symbols, methods=["GET"]),
    ],
    on_startup=[startup],
    on_shutdown=[shutdown]
)

# Add CORS middleware for ChatGPT
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
