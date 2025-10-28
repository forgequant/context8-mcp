# context8-mcp: Real-Time Crypto Market Analysis MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

> **Real-time cryptocurrency market analysis system providing LLMs with comprehensive, sub-second fresh market reports via MCP interface.**

## 🎯 Overview

context8-mcp is an event-driven system that:
- Ingests live market data from Binance Spot via NautilusTrader
- Calculates advanced market microstructure metrics (spreads, depth, liquidity, anomalies)
- Serves comprehensive market reports through an MCP (Model Context Protocol) interface
- Maintains data freshness ≤1 second with <150ms API response times

### Key Features

- **Sub-second Latency**: Data age ≤1000ms for healthy operation
- **Comprehensive Metrics**:
  - Price analysis (spread, mid-price, micro-price)
  - Order book depth and imbalance
  - Liquidity features (walls, vacuums, volume profile)
  - Flow metrics (order rate, net buying/selling pressure)
  - Anomaly detection (spoofing, iceberg orders, flash crash risk)
  - Health scoring (0-100 composite metric)
- **Production-Ready**: Docker Compose deployment, Prometheus metrics, structured logging
- **Read-Only MCP**: Safe, stateless interface for LLM consumption

## 🚀 Quick Start

### Prerequisites

- Docker 20.10+ and Docker Compose 2.0+
- 4GB RAM minimum (8GB recommended)
- Internet connection for Binance WebSocket streams

### Deploy Locally

```bash
# Clone the repository
git clone <repository-url> context8-mcp
cd context8-mcp

# Create configuration
cp .env.example .env
# Edit .env if needed (defaults work for public Binance data)

# Start all services
docker-compose up

# Wait ~15-20 seconds for startup, then test
curl http://localhost:8080/get_report?symbol=BTCUSDT
```

For detailed instructions, see [docs/quickstart.md](./docs/quickstart.md).

## 📋 Project Structure

```
context8-mcp/
├── producer/          # Python: NautilusTrader data ingestion
├── analytics/         # Go: Event processing and report generation
├── mcp/               # Go: MCP server (read-only API)
├── tests/             # Integration and contract tests
├── docs/              # Documentation and schemas
│   ├── quickstart.md
│   ├── metrics.md
│   ├── architecture.md
│   └── schemas/       # JSON schemas for events and reports
├── specs/             # Feature specifications and design docs
├── docker-compose.yml # Local deployment orchestration
├── Makefile           # Build and test commands
└── .env.example       # Configuration template
```

## 🛠️ Development

### Build Services

```bash
make build
```

### Run Tests

```bash
make test
```

### Lint Code

```bash
make lint
```

### Clean Build Artifacts

```bash
make clean
```

## 📊 Architecture

The system follows an event-driven architecture with five layers:

```
Binance Exchange (WebSocket)
    ↓
NautilusTrader Producer (Python)
    ↓
Redis Streams (Message Bus)
    ↓
Analytics Service (Go)
    ↓
Redis KV (Report Cache)
    ↓
MCP Server (Go)
    ↓
LLM Clients
```

For detailed architecture documentation, see [docs/architecture.md](./docs/architecture.md).

## 📈 Monitoring

- **Prometheus Metrics**: Exposed on port 9090
- **Health Endpoints**: Each service has `/health` endpoint
- **Structured Logging**: JSON logs with component, symbol, lag_ms fields

Key metrics:
- `context8_stream_lag_ms`: Event processing latency
- `context8_mcp_request_duration_ms`: API response time
- `context8_report_age_ms`: Data staleness

## 🔧 Configuration

All configuration via environment variables (see `.env.example`):

- `SYMBOLS`: Trading pairs to track (default: BTCUSDT,ETHUSDT)
- `REDIS_URL`: Redis connection string
- `CACHE_TTL_SEC`: Report cache duration (default: 300)
- `LOG_LEVEL`: Logging verbosity (debug/info/warn/error)

See `.env.example` for complete options.

## 📝 Documentation

- [Quickstart Guide](./docs/quickstart.md) - Get started in 10 minutes
- [Architecture Overview](./docs/architecture.md) - System design and data flow
- [Metrics Documentation](./docs/metrics.md) - Calculation formulas and algorithms
- [API Reference](./docs/schemas/mcp.json) - MCP interface specification
- [Runbooks](./docs/runbooks/) - Deployment and troubleshooting guides

## 🤝 Contributing

This project follows the Specify development workflow. To contribute:

1. Review the constitution at `.specify/memory/constitution.md`
2. Check open issues and feature specs in `specs/`
3. Run tests before submitting: `make test`
4. Ensure linters pass: `make lint`

## 📄 License

MIT License - see [LICENSE](./LICENSE) file for details.

## 🙏 Acknowledgments

- [NautilusTrader](https://github.com/nautechsystems/nautilus_trader) - High-performance market data ingestion
- [Redis](https://redis.io/) - In-memory message bus and cache
- [Prometheus](https://prometheus.io/) - Metrics and monitoring

---

**Status**: 🚧 MVP Development
**Last Updated**: 2025-10-28
