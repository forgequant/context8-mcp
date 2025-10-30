"""
SSE (Server-Sent Events) server for ChatGPT MCP integration.
Provides get_report tool via official MCP SSE transport.
"""
import asyncio
import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from mcp.types import Tool, TextContent
from starlette.responses import Response

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
            # Test connection
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
            # Get from Redis
            json_str = await self.client.get(cache_key)

            if json_str is None:
                logger.debug(f"Symbol {symbol} not found in cache")
                return None

            # Parse JSON
            report = json.loads(json_str)
            logger.debug(f"Retrieved report for {symbol}")
            return report

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON for {symbol}: {e}")
            raise
        except Exception as e:
            logger.error(f"Failed to get report for {symbol}: {e}")
            raise


class Context8MCPServer:
    """MCP Server for Context8 market data with ChatGPT-compatible SSE transport."""

    def __init__(self, redis_url: str):
        """Initialize MCP server."""
        self.cache = RedisCache(redis_url)
        self.server = Server("context8-mcp")

    async def initialize(self):
        """Initialize server and connect to Redis."""
        await self.cache.connect()
        logger.info("Context8 MCP Server initialized")

    async def shutdown(self):
        """Shutdown server and close connections."""
        await self.cache.close()
        logger.info("Context8 MCP Server shutdown")

    def register_handlers(self):
        """Register MCP handlers."""

        @self.server.list_tools()
        async def list_tools() -> list[Tool]:
            """List available tools."""
            return [
                Tool(
                    name="get_report",
                    description=(
                        "Retrieve real-time market data report for a tracked symbol "
                        "including orderbook metrics, volume profile, and flow analysis"
                    ),
                    inputSchema={
                        "type": "object",
                        "properties": {
                            "symbol": {
                                "type": "string",
                                "description": (
                                    "Trading symbol (e.g., BTCUSDT, ETHUSDT, "
                                    "1INCHUSDT, 1000SHIBUSDT)"
                                ),
                                "pattern": "^[A-Z0-9]+USDT$",
                            }
                        },
                        "required": ["symbol"],
                    }
                )
            ]

        @self.server.call_tool()
        async def call_tool(name: str, arguments: dict) -> list[TextContent]:
            """Call a tool."""
            if name != "get_report":
                error_msg = f"Tool '{name}' not found. Available tools: get_report"
                logger.warning(error_msg)
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": error_msg,
                        "error_code": "TOOL_NOT_FOUND"
                    }, indent=2)
                )]

            # Get symbol from arguments
            symbol = arguments.get("symbol")
            if not symbol:
                error_msg = "Missing required parameter: symbol"
                logger.warning(error_msg)
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": error_msg,
                        "error_code": "MISSING_PARAMETER"
                    }, indent=2)
                )]

            # Validate symbol pattern
            import re
            if not re.match(r"^[A-Z0-9]+USDT$", symbol):
                error_msg = f"Invalid symbol format: {symbol}. Must match pattern: ^[A-Z0-9]+USDT$"
                logger.warning(error_msg)
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": error_msg,
                        "error_code": "INVALID_SYMBOL"
                    }, indent=2)
                )]

            # Get report from cache
            try:
                report = await self.cache.get_report(symbol)

                if report is None:
                    error_msg = f"Symbol '{symbol}' not found in cache"
                    logger.info(error_msg)
                    return [TextContent(
                        type="text",
                        text=json.dumps({
                            "error": error_msg,
                            "error_code": "SYMBOL_NOT_FOUND"
                        }, indent=2)
                    )]

                # Return report as formatted JSON
                return [TextContent(
                    type="text",
                    text=json.dumps(report, indent=2)
                )]

            except Exception as e:
                error_msg = f"Failed to retrieve report: {str(e)}"
                logger.error(error_msg, exc_info=True)
                return [TextContent(
                    type="text",
                    text=json.dumps({
                        "error": error_msg,
                        "error_code": "INTERNAL_ERROR"
                    }, indent=2)
                )]

    def get_sse_app(self):
        """
        Create ASGI app for SSE transport compatible with ChatGPT.

        Returns:
            ASGI application
        """
        # Create SSE transport with official MCP protocol
        sse = SseServerTransport("/sse/messages")

        # Create main ASGI app that routes requests
        async def main_app(scope, receive, send):
            if scope["type"] != "http":
                return

            path = scope.get("path", "")
            method = scope.get("method", "GET")

            logger.info(f"Request: {method} {path}")

            # Health check endpoint
            if path == "/health":
                response = Response(
                    json.dumps({"status": "healthy", "service": "context8-mcp"}),
                    media_type="application/json"
                )
                await response(scope, receive, send)

            # SSE connection endpoint (GET only)
            elif (path == "/sse" or path == "/sse/") and method == "GET":
                logger.info(f"New SSE connection from {scope.get('client', ['unknown'])[0]}")
                async with sse.connect_sse(scope, receive, send) as (read_stream, write_stream):
                    init_options = self.server.create_initialization_options()
                    await self.server.run(read_stream, write_stream, init_options)

            # SSE messages endpoint (POST only)
            elif path.startswith("/sse/messages") and method == "POST":
                logger.info(f"Handling SSE message POST from {scope.get('client', ['unknown'])[0]}")
                await sse.handle_post_message(scope, receive, send)

            # Handle incorrect POST to /sse or /sse/
            elif (path == "/sse" or path == "/sse/") and method == "POST":
                logger.warning(f"POST request to {path} - should POST to /sse/messages instead")
                response = Response(
                    json.dumps({"error": "POST should be sent to /sse/messages with session_id parameter"}),
                    status_code=400,
                    media_type="application/json"
                )
                await response(scope, receive, send)

            # 404 for other paths
            else:
                logger.warning(f"No route matched for {method} {path}")
                response = Response(f"Not Found: {method} {path}", status_code=404)
                await response(scope, receive, send)

        return main_app


async def main():
    """Main entry point for SSE server."""
    import uvicorn

    # Get Redis URL from environment
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")

    # Create and initialize server
    mcp_server = Context8MCPServer(redis_url)
    await mcp_server.initialize()

    # Register handlers
    mcp_server.register_handlers()

    # Get ASGI app
    app = mcp_server.get_sse_app()

    # Run with uvicorn
    port = int(os.getenv("PORT", "8080"))
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=port,
        log_level="info",
        access_log=True,
    )
    uvicorn_server = uvicorn.Server(config)

    try:
        logger.info(f"Starting SSE server on http://0.0.0.0:{port}")
        await uvicorn_server.serve()
    finally:
        await mcp_server.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
