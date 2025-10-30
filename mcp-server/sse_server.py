"""
MCP Server with SSE transport for ChatGPT integration.
Provides HTTP endpoint with Server-Sent Events.
"""
import asyncio
import json
import logging
import os
from typing import Any

import redis.asyncio as aioredis
from mcp.server import Server
from mcp.types import Tool, TextContent
from starlette.applications import Starlette
from starlette.responses import StreamingResponse
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
    """MCP Server for Context8 market data."""

    def __init__(self, redis_url: str):
        """Initialize MCP server."""
        self.cache = RedisCache(redis_url)
        self.server = Server("context8-mcp")
        self._register_handlers()

    async def initialize(self):
        """Initialize server and connect to Redis."""
        await self.cache.connect()
        logger.info("Context8 MCP Server initialized")

    async def shutdown(self):
        """Shutdown server and close connections."""
        await self.cache.close()
        logger.info("Context8 MCP Server shutdown")

    def _register_handlers(self):
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

    async def handle_sse_request(self, request):
        """
        Handle SSE request with JSON-RPC over SSE.
        Compatible with ChatGPT MCP integration.
        """
        # Parse JSON-RPC request BEFORE creating the streaming response
        try:
            body = await request.json()
            logger.info(f"SSE request: {body}")
        except Exception as e:
            logger.error(f"Failed to parse request body: {e}")
            from starlette.responses import JSONResponse
            return JSONResponse(
                {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}},
                status_code=400
            )

        async def event_stream():
            try:

                method = body.get("method")
                params = body.get("params", {})
                request_id = body.get("id", 1)

                # Handle tools/list
                if method == "tools/list":
                    tools = [
                        {
                            "name": "get_report",
                            "description": "Retrieve real-time market data report for a tracked symbol",
                            "inputSchema": {
                                "type": "object",
                                "properties": {
                                    "symbol": {
                                        "type": "string",
                                        "description": "Trading symbol (e.g., BTCUSDT)",
                                        "pattern": "^[A-Z0-9]+USDT$"
                                    }
                                },
                                "required": ["symbol"]
                            }
                        }
                    ]

                    response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"tools": tools}
                    }

                    yield f"data: {json.dumps(response)}\n\n"

                # Handle tools/call
                elif method == "tools/call":
                    tool_name = params.get("name")
                    arguments = params.get("arguments", {})

                    if tool_name == "get_report":
                        symbol = arguments.get("symbol")

                        if not symbol:
                            error_response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32602,
                                    "message": "Missing required parameter: symbol"
                                }
                            }
                            yield f"data: {json.dumps(error_response)}\n\n"
                            return

                        # Get report from cache
                        report = await self.cache.get_report(symbol)

                        if report is None:
                            error_response = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "error": {
                                    "code": -32001,
                                    "message": f"Symbol '{symbol}' not found in cache"
                                }
                            }
                            yield f"data: {json.dumps(error_response)}\n\n"
                            return

                        # Success response
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [
                                    {
                                        "type": "text",
                                        "text": json.dumps(report, indent=2)
                                    }
                                ]
                            }
                        }

                        yield f"data: {json.dumps(response)}\n\n"
                    else:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "code": -32601,
                                "message": f"Tool '{tool_name}' not found"
                            }
                        }
                        yield f"data: {json.dumps(error_response)}\n\n"

                else:
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {
                            "code": -32601,
                            "message": f"Method '{method}' not found"
                        }
                    }
                    yield f"data: {json.dumps(error_response)}\n\n"

            except Exception as e:
                logger.error(f"Error handling SSE request: {e}", exc_info=True)
                error_response = {
                    "jsonrpc": "2.0",
                    "id": request_id if 'request_id' in locals() else 1,
                    "error": {
                        "code": -32603,
                        "message": f"Internal error: {str(e)}"
                    }
                }
                yield f"data: {json.dumps(error_response)}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no"
            }
        )

    def health_check(self, request):
        """Health check endpoint."""
        from starlette.responses import JSONResponse
        return JSONResponse({"status": "healthy"})


# Global server instance
mcp_server: Context8MCPServer | None = None


async def startup():
    """Startup event handler."""
    global mcp_server
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
    mcp_server = Context8MCPServer(redis_url)
    await mcp_server.initialize()


async def shutdown():
    """Shutdown event handler."""
    global mcp_server
    if mcp_server:
        await mcp_server.shutdown()


async def sse_endpoint(request):
    """SSE endpoint handler."""
    return await mcp_server.handle_sse_request(request)


async def health_endpoint(request):
    """Health check endpoint handler."""
    return mcp_server.health_check(request)


# Create Starlette app
app = Starlette(
    routes=[
        Route("/mcp/sse", sse_endpoint, methods=["POST"]),
        Route("/health", health_endpoint, methods=["GET"]),
    ],
    on_startup=[startup],
    on_shutdown=[shutdown]
)

# Add CORS middleware
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
