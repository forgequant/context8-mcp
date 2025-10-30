# Context8 MCP Server

Python-based MCP (Model Context Protocol) server for Context8 market data.

## Overview

This server provides real-time market data reports from Redis cache via the MCP protocol. It exposes a single tool `get_report` that retrieves comprehensive market analysis for trading symbols.

## Architecture

- **Language**: Python 3.11+
- **Framework**: MCP SDK (`mcp>=1.7.1`)
- **Transport**: stdio (for Claude Desktop integration)
- **Cache**: Redis (async client via `redis-py`)
- **Deployment**: Docker container

## Features

- Read-only access to market reports from Redis
- Pattern-based symbol validation (e.g., BTCUSDT, ETHUSDT)
- Structured error responses with error codes
- Async Redis operations for optimal performance
- Docker-ready with uv for fast dependency management

## Tools

### get_report

Retrieve real-time market data report for a tracked symbol.

**Input Schema:**
```json
{
  "symbol": "BTCUSDT"  // Trading symbol (e.g., BTCUSDT, ETHUSDT, 1INCHUSDT)
}
```

**Output:**
Returns a comprehensive market report including:
- 24h statistics (price, volume, high, low)
- L1 orderbook metrics (best bid/ask, spread, micro price)
- Depth analysis (top 20 levels, imbalance)
- Liquidity analysis (walls, vacuums, volume profile)
- Flow metrics (orders/sec, net flow)
- Market anomalies
- Health score

**Error Codes:**
- `TOOL_NOT_FOUND` - Invalid tool name
- `MISSING_PARAMETER` - Missing required parameter
- `INVALID_SYMBOL` - Symbol doesn't match pattern
- `SYMBOL_NOT_FOUND` - Symbol not in Redis cache
- `INTERNAL_ERROR` - Server error

## Redis Schema

The server reads from Redis keys with the pattern:
```
report:{symbol}
```

Each key contains a JSON-serialized market report.

## Development

### Local Setup

```bash
# Install dependencies with uv
cd mcp-server
pip install uv
uv pip install -e .

# Run server
export REDIS_URL=redis://localhost:6379
python server.py
```

### Docker Build

```bash
# Build image
docker build -t context8-mcp-server .

# Run container
docker run -e REDIS_URL=redis://redis:6379 context8-mcp-server
```

### Testing

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check .
```

## Configuration

Environment variables:
- `REDIS_URL` - Redis connection URL (default: `redis://localhost:6379`)

## Migration from Go

This Python MCP server replaces the previous Go implementation with:
- Simpler codebase (single file vs multiple packages)
- Native Python ecosystem integration
- Same API contract and Redis schema
- Better suited for MCP protocol development

## References

- [MCP Specification](https://modelcontextprotocol.io/)
- [Redis Python Client](https://redis-py.readthedocs.io/)
- [Project CLAUDE.md](../CLAUDE.md)
