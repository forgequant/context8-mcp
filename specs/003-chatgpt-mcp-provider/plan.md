# Implementation Plan: ChatGPT MCP Provider Integration

**Branch**: `003-chatgpt-mcp-provider` | **Date**: 2025-10-29 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/003-chatgpt-mcp-provider/spec.md`

## Summary

Enable ChatGPT to query market data reports from context8-mcp by implementing a Go-based MCP (Model Context Protocol) server with SSE (Server-Sent Events) transport. The server exposes a capabilities endpoint for tool discovery and an invocation endpoint for executing `get_report` requests, serving cached market reports from Redis without triggering computation.

## Technical Context

**Language/Version**: Go 1.24+
**Primary Dependencies**:
- `github.com/go-chi/chi/v5` (HTTP router, existing in project)
- `github.com/go-redis/redis/v9` (Redis client, existing in project)
- MCP protocol library (NEEDS CLARIFICATION: official Go MCP library vs custom implementation)
- SSE library (NEEDS CLARIFICATION: standard library vs dedicated SSE package)

**Storage**: Redis (existing cache at `report:{symbol}` keys)
**Testing**: Go standard `testing` package + `golangci-lint`
**Target Platform**: Linux server (Docker container)
**Project Type**: Web service (HTTP/SSE endpoints)
**Performance Goals**:
- Capabilities endpoint: <100ms response time
- Tool invocation: <500ms end-to-end (spec requirement)
- Health check: <100ms (spec requirement)

**Constraints**:
- Read-only operations (no writes to Redis or event bus)
- Timeout ≤ 150ms for Redis operations (Constitution Principle 13)
- No computation triggered by MCP requests
- Must support 100 concurrent requests (spec requirement)

**Scale/Scope**:
- Single MCP server service
- ~10 tracked symbols initially
- 1 tool (`get_report`)
- 3-5 new Go files in `mcp/internal/`

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Architecture Compliance (Principle 1)
- [x] Feature follows layered EDA: MCP layer reads from Cache layer (Redis)
- [x] Does not modify message bus or analytics layers
- [x] Respects existing stream topology (read-only, no stream interaction)

**Justification**: MCP server is pure API layer reading from cache. No event handling or stream consumption.

### Message Bus Contract (Principle 2)
- [x] Not applicable - feature does not produce or consume events
- [x] Feature reads cached JSON reports (already compliant from producer)

**Justification**: MCP server sits above message bus layer, only reads cached results.

### Idempotency & Time (Principle 3)
- [x] MCP endpoints are naturally idempotent (read-only GET operations)
- [x] Timestamps in responses use existing UTC format from cached reports

**Justification**: Read-only operations are inherently idempotent.

### Technology Stack (Principle 4)
- [x] Implements service in Go ≥ 1.24 as required
- [x] No Python dependencies (Go-only service)

### Report Contract (Principle 6)
- [x] Returns existing report format unchanged (pass-through from cache)
- [x] Does not modify calculation logic or report fields
- [x] No impact on `report_version`

**Justification**: MCP server returns cached reports verbatim, does not compute metrics.

### SLO Compliance (Principle 7)
- [x] Does not impact data freshness SLO (reads existing `data_age_ms` from cache)
- [x] Targets <150ms Redis read + <350ms response formatting = <500ms total
- [x] Returns cached report with `ingestion.status` during degradation

**Justification**: Fast cache reads maintain sub-second response times.

### Security (Principle 8)
- [x] Read-only Redis access (no writes)
- [x] No external API calls beyond Redis
- [x] Configuration via environment variables (no secrets in code)

### Quality & Testing (Principle 9)
- [x] Unit tests for MCP protocol serialization/deserialization
- [x] Integration tests for Redis cache reads
- [x] Contract tests for MCP capabilities and tool invocation schemas
- [x] Timeout tests for 150ms Redis and 500ms end-to-end constraints

### Reference-First Development (Principle 10)
- [x] `.refs/INDEX.yaml` will be consulted for:
  - MCP protocol implementation (mcp-trader/hello-go provider)
  - SSE transport patterns (mcp-trader/mcp-gateway SSE server)
  - Redis cache reading patterns (existing context8-mcp/mcp/internal/cache)
  - HTTP server patterns (chi router from existing mcp/cmd/server/main.go)

**Justification**: Reference implementation at `/home/limerc/repos/ForgeTrade/mcp-trader` provides proven patterns.

### Observability (Principle 11)
- [x] Structured JSON logging with:
  - `component`: "mcp-provider"
  - `symbol`: requested symbol
  - `tool_name`: invoked tool
  - `correlation_id`: request trace ID
  - `cache_hit`: boolean for Redis cache presence

### MCP Contract (Principle 13)
- [x] Method signature matches: `get_report(symbol: string) -> ReportJSON | null`
- [x] Sources from Redis cache only (existing cache reader)
- [x] Enforces ≤150ms timeout on Redis operations

**Justification**: Extends existing HTTP MCP server (`mcp/cmd/server/main.go`) with MCP protocol wrapper.

## Phase 0: Research & Unknowns

### Research Tasks

1. **MCP Protocol Implementation** (NEEDS CLARIFICATION: library choice)
   - **Question**: Use official Go MCP SDK or implement custom JSON-RPC over SSE?
   - **Options**:
     - A) Official `mcp-go` library (if exists)
     - B) Custom implementation following mcp-trader patterns
   - **Research Needed**: Survey Go MCP libraries, evaluate maturity and maintenance

2. **SSE Transport** (NEEDS CLARIFICATION: library choice)
   - **Question**: Standard library `http.ResponseWriter` flushing or dedicated SSE package?
   - **Options**:
     - A) Standard library with `http.Flusher` interface
     - B) Dedicated SSE library (e.g., `r3labs/sse`)
   - **Research Needed**: Review mcp-trader SSE gateway implementation, evaluate ChatGPT SSE requirements

3. **MCP Capabilities Schema**
   - **Question**: JSON Schema version and required MCP protocol fields
   - **Research Needed**: Review MCP specification, extract required capability fields

4. **Tool Parameter Validation**
   - **Question**: JSON Schema validation library for tool parameters
   - **Options**:
     - A) `xeipuuv/gojsonschema`
     - B) `santhosh-tekuri/jsonschema`
     - C) Manual validation
   - **Research Needed**: Benchmark validation libraries, check mcp-trader approach

### Research Output

See [research.md](./research.md) for consolidated research findings and decisions.

## Phase 1: Design

### Data Model

**MCP Protocol Entities** (defined in plan Phase 1, implemented in mcp/internal/mcp/types.go):
- **MCPTool**: Tool metadata (name, description, parameter schema)
- **MCPToolInvocation**: Request payload for tool execution
- **MCPCapabilities**: Complete tool catalog for discovery
- **MCPResponse**: Standardized response wrapper

**Report Entity**: Existing `models.Report` struct from mcp/internal/cache (no changes required)

### API Contracts

**MCP Endpoints** (detailed in plan Phase 1 Design and research.md):

1. **GET /mcp/capabilities** - Tool discovery endpoint
   - Returns: JSON-RPC 2.0 response with tools array
   - Schema: MCP list_tools response format (research.md:177-201)

2. **POST /mcp/invoke** - Tool invocation endpoint
   - Accepts: JSON-RPC 2.0 request with tool name and parameters
   - Returns: MCP call_tool response (text/event-stream for SSE)
   - Timeout: 500ms end-to-end (SC-001)

3. **GET /health** - Health check endpoint (existing, enhanced in T036)
   - Returns: JSON with status and Redis connectivity check
   - Timeout: <100ms (SC-006)

### Integration Points

1. **Existing Cache Reader** (`mcp/internal/cache/reader.go`)
   - Already provides `GetReport(symbol string) (*models.Report, error)`
   - Reuse without modification

2. **Existing HTTP Server** (`mcp/cmd/server/main.go`)
   - Extend with MCP protocol endpoints
   - Add SSE transport handling

3. **Configuration** (`mcp/internal/config/config.go`)
   - Add MCP-specific settings (e.g., SSE keep-alive interval)

### Project Structure (New Files)

```text
mcp/
├── internal/
│   ├── mcp/
│   │   ├── capabilities.go    # Tool catalog and schema definitions
│   │   ├── invocation.go      # Tool invocation handler
│   │   ├── sse.go              # SSE transport layer
│   │   └── validation.go      # Parameter validation
│   └── handlers/
│       ├── mcp_capabilities.go # HTTP handler for /capabilities
│       ├── mcp_invoke.go       # HTTP handler for /invoke
│       └── mcp_sse.go          # SSE endpoint handler
└── cmd/
    └── server/
        └── main.go             # Extended with MCP routes
```

### Error Handling

| Error Condition | HTTP Status | MCP Error Code | Response |
|----------------|-------------|----------------|----------|
| Symbol not found | 404 | `symbol_not_found` | `{"error": "symbol_not_indexed", "symbol": "..."}` |
| Invalid tool name | 400 | `invalid_tool` | `{"error": "unknown_tool", "tool": "..."}` |
| Invalid parameters | 400 | `invalid_params` | `{"error": "validation_failed", "details": [...]}` |
| Redis timeout | 503 | `data_unavailable` | `{"error": "cache_timeout", "timeout_ms": 150}` |
| Redis connection error | 503 | `data_unavailable` | `{"error": "cache_unavailable"}` |
| Request timeout | 504 | `timeout` | `{"error": "request_timeout", "timeout_ms": 500}` |

### Logging Strategy

**Structured JSON fields**:
```json
{
  "level": "info|error|warn",
  "component": "mcp-server",
  "tool_name": "get_report",
  "symbol": "BTCUSDT",
  "correlation_id": "req-123abc",
  "cache_hit": true,
  "latency_ms": 45,
  "error": "optional_error_message"
}
```

## Phase 2: Implementation Tasks

*Generated by `/speckit.tasks` command - not part of `/speckit.plan` output*

See [tasks.md](./tasks.md) (generated separately)

## Quickstart

See [quickstart.md](./quickstart.md) for developer onboarding.

## Complexity Tracking

### Justified Additions
- **SSE Transport**: Required by ChatGPT MCP integration (spec requirement)
- **MCP Server Protocol**: Necessary for tool discovery and invocation (spec requirement)

### Alternatives Considered
- **gRPC instead of SSE**: Rejected - ChatGPT requires SSE transport per MCP specification
- **Extend existing HTTP API**: Rejected - MCP protocol has specific capability discovery and invocation semantics

### Technical Debt
- **Custom MCP implementation**: If no mature Go library exists, custom implementation creates maintenance burden
  - **Mitigation**: Thorough documentation, comprehensive tests, reference existing mcp-trader patterns

### Performance Trade-offs
- **JSON Schema validation overhead**: Parameter validation adds ~5-10ms per request
  - **Justification**: Required for proper error messages and security (prevent injection)
  - **Mitigation**: Cache compiled schemas, use fast validation library

## Constitution Re-Check (Post-Design)

*Re-evaluate after Phase 1 design completion*

### Changes from Initial Check
- [x] No architectural changes
- [x] All principles remain compliant

### New Considerations
- **SSE long-lived connections**: Does not violate read-only principle (no state mutations)
- **JSON Schema validation**: Adds latency but required for robust error handling
- **Custom MCP implementation**: Acceptable if no mature library exists, follows reference patterns

**Final Status**: ✅ PASS - All constitution principles satisfied

## References

- **MCP Specification**: [Model Context Protocol documentation](https://modelcontextprotocol.io)
- **Reference Implementation**: `/home/limerc/repos/ForgeTrade/mcp-trader` (hello-go server, SSE gateway)
- **Existing Code**: `mcp/internal/cache/reader.go`, `mcp/cmd/server/main.go`
- **Constitution**: `.specify/memory/constitution.md` v1.1.0

## Appendix: Decision Log

| Decision | Date | Rationale | Alternatives |
|----------|------|-----------|--------------|
| Go for MCP server | 2025-10-29 | Constitution Principle 4 mandate | N/A (required) |
| Extend existing HTTP server | 2025-10-29 | Reuse infrastructure, avoid duplication | Separate service (rejected: operational overhead) |
| SSE transport | 2025-10-29 | ChatGPT MCP requirement | WebSocket (rejected: not MCP standard) |
| Read-only design | 2025-10-29 | Constitution Principle 13 mandate | N/A (required) |
