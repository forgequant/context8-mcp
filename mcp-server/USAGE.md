# MCP Server Usage Guide

## Overview

The Context8 MCP Server uses stdio transport and is designed to be integrated with Claude Desktop or other MCP clients, not to run as a standalone daemon.

## Docker Usage

### Running the MCP Server

```bash
# Run interactively (with stdin/stdout)
docker compose run --rm mcp

# The server will start and wait for MCP protocol messages on stdin
```

### Testing with sample input

```bash
# Send a list_tools request
echo '{"jsonrpc": "2.0", "id": 1, "method": "tools/list"}' | docker compose run --rm mcp
```

## Local Development

### Setup

```bash
cd mcp-server
pip install uv
uv pip install -e .
```

### Run locally

```bash
export REDIS_URL=redis://localhost:6379
python server.py
```

## Claude Desktop Integration

To use this MCP server with Claude Desktop, add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "context8": {
      "command": "docker",
      "args": [
        "compose",
        "-f",
        "/path/to/context8-mcp/docker-compose.yml",
        "run",
        "--rm",
        "mcp"
      ],
      "env": {
        "REDIS_URL": "redis://host.docker.internal:6379"
      }
    }
  }
}
```

Note: Replace `/path/to/context8-mcp` with the actual path to your project.

## MCP Protocol

The server implements the following MCP methods:

### tools/list

Returns available tools:
- `get_report` - Retrieve market data report for a symbol

### tools/call

Execute a tool:

```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "get_report",
    "arguments": {
      "symbol": "BTCUSDT"
    }
  }
}
```

## Troubleshooting

### Redis Connection Issues

If you see connection errors, ensure:
1. Redis service is running: `docker compose ps`
2. Redis URL is correct in environment variables
3. Network connectivity between containers

### Symbol Not Found

If you get "symbol not found" errors:
1. Check that the producer service is running and ingesting data
2. Verify the symbol exists in Redis: `docker exec context8-redis redis-cli GET report:BTCUSDT`
3. Wait a few seconds for initial data ingestion

## Development

### Fixing deprecation warning

The server uses `redis.asyncio` which has deprecated `close()` in favor of `aclose()`. To fix:

```python
# Replace in server.py line 50
await self.client.aclose()  # instead of close()
```

### Adding new tools

1. Add tool definition in `list_tools()` handler
2. Implement tool logic in `call_tool()` handler
3. Update README with new tool documentation
