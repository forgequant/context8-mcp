# Feature Specification: ChatGPT MCP Provider Integration

**Feature Branch**: `003-chatgpt-mcp-provider`
**Created**: 2025-10-29
**Status**: Draft
**Input**: User description: "посмотри как сделано в mcp /home/limerc/repos/ForgeTrade/mcp-trader нужно нам тоже сделать интеграцию на go mcp для гпт. Используй еще локальные референсы."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Query Market Reports via ChatGPT (Priority: P1)

AI developers using ChatGPT need to access real-time market data and analytics from the context8-mcp system. They want to ask natural language questions like "Show me the market report for BTCUSDT" and receive comprehensive market intelligence without leaving their ChatGPT interface.

**Why this priority**: This is the core value proposition - enabling ChatGPT to access market data through a standardized protocol. Without this, users cannot leverage ChatGPT's natural language capabilities with our market data.

**Independent Test**: Can be fully tested by configuring ChatGPT with the MCP server URL, asking for a market report, and verifying that structured market data is returned with the correct format and freshness indicators.

**Acceptance Scenarios**:

1. **Given** ChatGPT is configured with the MCP server endpoint, **When** user asks "Generate a market report for BTCUSDT", **Then** ChatGPT receives a complete market data report from Redis with price overview, order book metrics, and liquidity analysis
2. **Given** the MCP server is running and connected to Redis, **When** a report request is made for a tracked symbol, **Then** the response includes data freshness indicators and generation timestamps
3. **Given** user requests a report for an untracked symbol, **When** the request is processed, **Then** the system returns a clear error message indicating the symbol is not available

---

### User Story 2 - Discover Available Tools (Priority: P2)

ChatGPT needs to discover what market data capabilities are available from the MCP provider. Users expect ChatGPT to know which symbols, metrics, and report types can be queried without manual documentation lookup.

**Why this priority**: Tool discovery is essential for usability but can be implemented after the basic report retrieval works. It enables self-documenting API behavior.

**Independent Test**: Can be tested by calling the capabilities endpoint and verifying that all available tools, their parameters, and descriptions are returned in the MCP standard format.

**Acceptance Scenarios**:

1. **Given** the MCP server is running, **When** ChatGPT queries the capabilities endpoint, **Then** it receives a list of all available tools including get_report with parameter schemas
2. **Given** capabilities are returned, **When** ChatGPT examines tool definitions, **Then** each tool includes name, description, and complete parameter schemas
3. **Given** new symbols are added to Redis, **When** capabilities are queried, **Then** the available symbols list reflects current tracking state

---

### User Story 3 - Handle Connection Failures Gracefully (Priority: P3)

When Redis is unavailable or the MCP server encounters errors, ChatGPT users should receive clear, actionable error messages rather than cryptic failures. The system should degrade gracefully and provide diagnostic information.

**Why this priority**: Error handling is important for production reliability but doesn't block core functionality testing. Can be added once basic happy-path works.

**Independent Test**: Can be tested by intentionally stopping Redis, making requests, and verifying that proper error messages are returned with appropriate HTTP status codes.

**Acceptance Scenarios**:

1. **Given** Redis connection fails, **When** a report is requested, **Then** the MCP server returns an error indicating data source unavailability with retry suggestions
2. **Given** a request times out, **When** the timeout threshold is exceeded, **Then** the request is terminated with a timeout error message
3. **Given** invalid parameters are provided, **When** the tool is invoked, **Then** the server returns validation errors with specific parameter issues

---

### Edge Cases

- What happens when Redis contains stale data (data_age exceeds acceptable threshold)?
- How does the system handle concurrent requests for the same symbol?
- What if the requested report format is invalid or unsupported?
- How does the server behave when Redis returns partial data (missing some expected keys)?
- What happens if ChatGPT sends malformed JSON in tool parameters?
- How is the system affected when network latency between MCP server and Redis exceeds normal thresholds?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST implement the Model Context Protocol (MCP) specification to enable ChatGPT integration
- **FR-002**: System MUST expose a capabilities endpoint that lists available tools (get_report) with complete parameter schemas
- **FR-003**: System MUST provide a tool invocation endpoint that accepts tool name and parameters and returns results in MCP format
- **FR-004**: System MUST retrieve market report data from Redis using the existing cache reader component
- **FR-005**: System MUST return market reports in the established JSON format with markdown_content, symbol, generated_at, and data_age_ms fields
- **FR-006**: System MUST validate all incoming tool parameters (symbol) before processing using JSON Schema Draft 7
- **FR-007**: System MUST include request correlation IDs in all logs for traceability
- **FR-008**: System MUST support graceful shutdown with proper connection cleanup
- **FR-009**: System MUST enforce request timeouts to prevent resource exhaustion
- **FR-010**: System MUST return appropriate HTTP status codes for different error conditions (400 for validation, 500 for server errors, 503 for unavailable dependencies)
- **FR-011**: System MUST expose a health check endpoint for container orchestration
- **FR-012**: System MUST log all requests, responses, and errors in structured JSON format
- **FR-013**: System MUST support configuration via environment variables (port, Redis URL, timeout settings)

### Key Entities

- **Tool**: Represents an available capability exposed to ChatGPT (e.g., get_report). Contains name, description, and parameter schema following JSON Schema specification.
- **Tool Invocation**: A request from ChatGPT to execute a specific tool with provided parameters. Includes tool name, parameters object, and correlation ID.
- **Market Report**: The data payload returned from Redis containing market intelligence. Includes markdown_content, symbol identifier, generation timestamp, and data freshness indicators.
- **Capability Manifest**: The complete list of tools and their schemas exposed by the provider, returned during capability discovery.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: ChatGPT users can retrieve market reports with end-to-end latency under 500ms (from request to response)
- **SC-002**: The MCP server successfully processes 100 concurrent report requests without errors or timeouts
- **SC-003**: 100% of valid tool invocations return properly formatted MCP responses with correct correlation IDs
- **SC-004**: The system achieves 99.9% uptime when Redis is available (excluding planned maintenance)
- **SC-005**: All errors include actionable messages that guide users toward resolution
- **SC-006**: The health check endpoint responds in under 100ms and accurately reflects system state

## Assumptions *(mandatory)*

1. The existing Redis cache reader component (mcp/internal/cache) can be reused without modification
2. The existing market report format in Redis is sufficient and doesn't require schema changes
3. ChatGPT will use Server-Sent Events (SSE) transport similar to the mcp-trader reference implementation
4. The MCP server will run as a containerized service alongside producer and analytics components
5. Authentication and authorization are handled externally (no user-level access control required in this phase)
6. The report generation frequency and caching strategy remain unchanged (managed by producer component)
7. Network connectivity between MCP server and Redis is reliable (same Docker network)
8. JSON schema validation for tool parameters follows standard JSON Schema Draft 7 specification

## Dependencies *(mandatory)*

### External Systems
- **Redis**: Required for retrieving cached market reports. MCP server cannot function without Redis connectivity.
- **ChatGPT**: The primary consumer of this MCP provider. Testing requires access to ChatGPT with MCP server configuration capabilities.

### Internal Components
- **Producer**: Must be running to generate and populate market reports in Redis
- **Cache Reader**: The existing mcp/internal/cache package provides Redis data access

### Reference Implementation
- **mcp-trader repository**: Located at /home/limerc/repos/ForgeTrade/mcp-trader, provides architectural patterns for MCP provider implementation, particularly the hello-go provider structure and SSE gateway patterns

## Out of Scope *(mandatory)*

The following are explicitly NOT included in this feature:

1. **Data Generation**: This feature only exposes existing market data; it does not create or compute new analytics
2. **Authentication/Authorization**: User identity verification and access control are deferred to a future phase
3. **Rate Limiting**: Request throttling and quota management are not implemented in this version
4. **Custom Report Formats**: Only the existing JSON/markdown format is supported; no new formats or customization options
5. **Historical Data Queries**: Only the most recent cached report per symbol is available; time-series queries are out of scope
6. **Webhook/Push Notifications**: The system only supports pull-based queries; real-time push notifications are not included
7. **Multi-Venue Support**: Only the single existing data source (Binance via producer) is supported; no venue routing logic
8. **Administrative UI**: No web interface for configuration or monitoring; operations are CLI/environment variable based
9. **Claude Code Integration**: This feature targets ChatGPT specifically; Claude Code support via STDIO transport is not included
10. **Write Operations**: The MCP provider is read-only; no ability to modify settings, trigger regeneration, or update data
