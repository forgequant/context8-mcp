# Tasks: ChatGPT MCP Provider Integration

**Input**: Design documents from `/specs/003-chatgpt-mcp-provider/`
**Prerequisites**: plan.md, spec.md, research.md
**Feature Branch**: `003-chatgpt-mcp-provider`

**Tests**: Not explicitly requested in specification - tests marked as OPTIONAL below for reference

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `- [ ] [ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and Go module setup for MCP provider

- [ ] T001 Add santhosh-tekuri/jsonschema/v5 dependency to mcp/go.mod for JSON Schema validation
- [ ] T002 Create mcp/internal/mcp/ directory structure for MCP protocol components
- [ ] T003 Create mcp/internal/handlers/ subdirectory for MCP HTTP handlers

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core MCP protocol infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 [P] Define MCP protocol structs (Tool, TextContent, JSONRPCRequest, JSONRPCResponse) in mcp/internal/mcp/types.go
- [ ] T005 [P] Implement SSE event writer with http.Flusher in mcp/internal/mcp/sse.go
- [ ] T006 [P] Create JSON Schema compiler and validation function in mcp/internal/mcp/validation.go
- [ ] T007 Define get_report tool schema (symbol parameter with ^[A-Z]+USDT$ pattern) in mcp/internal/mcp/schemas.go
- [ ] T008 Implement JSON-RPC 2.0 request parser with error handling in mcp/internal/mcp/jsonrpc.go
- [ ] T009 Create correlation ID middleware for request tracing in mcp/internal/handlers/middleware.go

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Query Market Reports via ChatGPT (Priority: P1) 🎯 MVP

**Goal**: Enable ChatGPT to retrieve real-time market reports for tracked symbols with proper formatting and freshness indicators

**Independent Test**: Configure ChatGPT with MCP server URL, request "market report for BTCUSDT", verify structured JSON response with markdown_content and data_age_ms fields

### Tests for User Story 1 (OPTIONAL - not explicitly requested) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T010 [P] [US1] Contract test for tool invocation endpoint in mcp/internal/handlers/mcp_invoke_test.go
- [ ] T011 [P] [US1] Integration test for Redis cache read path in mcp/internal/handlers/integration_test.go
- [ ] T012 [P] [US1] Timeout test for 150ms Redis constraint in mcp/internal/mcp/timeout_test.go

### Implementation for User Story 1

- [ ] T013 [P] [US1] Implement tool invocation handler (call_tool JSON-RPC method) in mcp/internal/handlers/mcp_invoke.go
- [ ] T014 [P] [US1] Create structured logging helper for MCP requests (component, symbol, tool_name, correlation_id) in mcp/internal/mcp/logging.go
- [ ] T015 [US1] Implement get_report tool executor that calls existing cache.Reader.GetReport() in mcp/internal/mcp/tools.go
- [ ] T016 [US1] Add parameter validation for get_report (validate symbol against JSON Schema) in mcp/internal/mcp/invocation.go
- [ ] T017 [US1] Implement error response formatting for MCP protocol (symbol_not_found, invalid_params) in mcp/internal/mcp/errors.go
- [ ] T018 [US1] Add HTTP POST /mcp/invoke route with SSE transport to mcp/cmd/server/main.go
- [ ] T019 [US1] Implement context timeout enforcement (500ms end-to-end) in mcp/internal/handlers/mcp_invoke.go
- [ ] T020 [US1] Add cache_hit boolean and latency_ms to structured logs in mcp/internal/handlers/mcp_invoke.go

**Checkpoint**: At this point, User Story 1 should be fully functional - ChatGPT can query market reports via /mcp/invoke endpoint

---

## Phase 4: User Story 2 - Discover Available Tools (Priority: P2)

**Goal**: Enable ChatGPT to discover available MCP tools and their parameter schemas without external documentation

**Independent Test**: Call /mcp/capabilities endpoint and verify response contains get_report tool with complete JSON Schema for symbol parameter

### Tests for User Story 2 (OPTIONAL - not explicitly requested) ⚠️

- [ ] T021 [P] [US2] Contract test for capabilities endpoint response format in mcp/internal/handlers/mcp_capabilities_test.go
- [ ] T022 [P] [US2] Schema validation test for tool definitions in mcp/internal/mcp/capabilities_test.go

### Implementation for User Story 2

- [ ] T023 [P] [US2] Define MCP capabilities response structure (tools array with name, description, inputSchema) in mcp/internal/mcp/capabilities.go
- [ ] T024 [US2] Implement list_tools JSON-RPC handler returning get_report tool metadata in mcp/internal/handlers/mcp_capabilities.go
- [ ] T025 [US2] Add dynamic symbol enumeration from Redis using SCAN command (pattern: report:*) in mcp/internal/mcp/capabilities.go; extract symbol from key suffix
- [ ] T026 [US2] Add HTTP GET /mcp/capabilities route to mcp/cmd/server/main.go
- [ ] T027 [US2] Add caching for capabilities response (1-minute TTL) in mcp/internal/handlers/mcp_capabilities.go

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently - ChatGPT can discover tools and invoke them

---

## Phase 5: User Story 3 - Handle Connection Failures Gracefully (Priority: P3)

**Goal**: Provide clear, actionable error messages when Redis is unavailable or requests fail

**Independent Test**: Stop Redis container, make /mcp/invoke request, verify response contains "data source unavailable" error with retry suggestions and HTTP 503 status

### Tests for User Story 3 (OPTIONAL - not explicitly requested) ⚠️

- [ ] T028 [P] [US3] Error handling test for Redis connection failure in mcp/internal/handlers/error_test.go
- [ ] T029 [P] [US3] Timeout error test for request exceeding 500ms threshold in mcp/internal/handlers/timeout_test.go
- [ ] T030 [P] [US3] Parameter validation error test for invalid symbol format in mcp/internal/mcp/validation_test.go

### Implementation for User Story 3

- [ ] T031 [P] [US3] Implement Redis connection error detection and mapping to MCP error code in mcp/internal/mcp/errors.go
- [ ] T032 [P] [US3] Add timeout error handling with remaining time in error response in mcp/internal/handlers/mcp_invoke.go
- [ ] T033 [US3] Create detailed validation error messages (parameter name, expected format, received value) in mcp/internal/mcp/validation.go
- [ ] T034 [US3] Implement HTTP status code mapping (400=validation, 503=unavailable, 504=timeout) in mcp/internal/handlers/mcp_invoke.go
- [ ] T035 [US3] Add error logging with correlation IDs for debugging in mcp/internal/handlers/mcp_invoke.go
- [ ] T036 [US3] Implement health check enhancement to detect Redis connectivity in mcp/internal/handlers/health.go

**Checkpoint**: All user stories should now be independently functional with robust error handling

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories and production readiness

- [ ] T037 [P] Add Go linting with golangci-lint to mcp/ directory
- [ ] T038 [P] Add Prometheus metrics for MCP endpoint latency (mcp_invoke_latency_ms histogram) in mcp/internal/handlers/metrics.go
- [ ] T039 [P] Create Dockerfile for MCP server with Go 1.24+ base image in mcp/Dockerfile
- [ ] T040 Update docker-compose.yml to include mcp-provider service with Redis dependency
- [ ] T041 [P] Add environment variable configuration for SSE keep-alive interval in mcp/internal/config/config.go
- [ ] T042 Document MCP endpoints and SSE transport in mcp/README.md
- [ ] T043 Add example ChatGPT configuration for MCP server in specs/003-chatgpt-mcp-provider/examples/chatgpt-config.json
- [ ] T044 Add security audit for input validation and Redis query injection prevention
- [ ] T045 Run performance benchmark for 100 concurrent requests (SC-002 requirement)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - User stories can then proceed in parallel (if staffed)
  - Or sequentially in priority order (P1 → P2 → P3)
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Can start after Foundational (Phase 2) - Independent of US1 (different endpoints)
- **User Story 3 (P3)**: Can start after Foundational (Phase 2) - Enhances US1 and US2 error handling but independently testable

### Within Each User Story

- Tests (if included) MUST be written and FAIL before implementation
- Core protocol components before HTTP handlers
- Tool execution before endpoint wiring
- Error handling before logging enhancements
- Story complete before moving to next priority

### Parallel Opportunities

- All Setup tasks can run in parallel (independent file operations)
- Within Foundational: T004, T005, T006, T007 can run in parallel (different files)
- Within US1 tests: T010, T011, T012 can run in parallel
- Within US1: T013 and T014 can run in parallel (different files)
- Within US2 tests: T021, T022 can run in parallel
- Within US2: T023 can start before T024 (dependency)
- Within US3 tests: T028, T029, T030 can run in parallel
- Within US3: T031 and T032 can run in parallel (different files)
- Different user stories (US1, US2, US3) can be worked on in parallel by different team members after Foundational phase

---

## Parallel Example: User Story 1

```bash
# Launch all tests for User Story 1 together (if tests requested):
Task: T010 - Contract test for tool invocation endpoint
Task: T011 - Integration test for Redis cache read path
Task: T012 - Timeout test for 150ms Redis constraint

# Launch parallel implementation tasks:
Task: T013 - Implement tool invocation handler
Task: T014 - Create structured logging helper

# Sequential after T013, T014 complete:
Task: T015 - Implement get_report tool executor
Task: T016 - Add parameter validation for get_report
```

---

## Parallel Example: Foundational Phase

```bash
# All foundational tasks with [P] can start simultaneously:
Task: T004 - Define MCP protocol structs
Task: T005 - Implement SSE event writer
Task: T006 - Create JSON Schema validation
Task: T007 - Define get_report tool schema

# Sequential after parallel tasks:
Task: T008 - Implement JSON-RPC parser (depends on T004)
Task: T009 - Create correlation ID middleware
```

---

## Out-of-Scope Items (Explicitly Not Implemented)

The following items from spec.md "Out of Scope" section have **no tasks** by design:

- **Authentication/Authorization** (spec.md:133): Deferred to future phase - no user identity in MVP
- **Rate Limiting** (spec.md:134): Not needed for single-user MVP; add when multi-tenant
- **Custom Report Formats** (spec.md:135): Only existing JSON/markdown format supported
- **Historical Data Queries** (spec.md:136): Only current cached report served
- **Webhook/Push Notifications** (spec.md:137): Pull-based queries only (MCP protocol constraint)
- **Multi-Venue Support** (spec.md:138): Single data source (Binance via producer)
- **Administrative UI** (spec.md:139): CLI/env var operations only
- **Claude Code Integration** (spec.md:140): ChatGPT SSE transport only (STDIO not implemented)
- **Write Operations** (spec.md:141): Read-only by constitution (Principle 13)

**Rationale**: These items are intentionally excluded from MVP to maintain focus on core ChatGPT integration. Constitution Principle 0 (Mission and Boundaries) permits deferred features.

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T009) - CRITICAL
3. Complete Phase 3: User Story 1 (T010-T020)
4. **STOP and VALIDATE**: Test User Story 1 independently
   - Start Redis and producer services
   - Configure ChatGPT with MCP server URL
   - Request "market report for BTCUSDT"
   - Verify structured JSON response with all required fields
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready (T001-T009)
2. Add User Story 1 → Test independently → Deploy/Demo (T010-T020) **MVP!**
3. Add User Story 2 → Test independently → Deploy/Demo (T021-T027)
4. Add User Story 3 → Test independently → Deploy/Demo (T028-T036)
5. Polish phase → Production-ready (T037-T045)

Each story adds value without breaking previous stories

### Parallel Team Strategy

With multiple developers after Foundational phase completes:

1. **Team completes Setup + Foundational together** (T001-T009)
2. **Once Foundational is done:**
   - Developer A: User Story 1 (T010-T020) - Core functionality
   - Developer B: User Story 2 (T021-T027) - Tool discovery
   - Developer C: User Story 3 (T028-T036) - Error handling
3. Stories complete and integrate independently

---

## Success Metrics

### From Specification (spec.md Success Criteria)

- **SC-001**: End-to-end latency under 500ms → Verified by T012, enforced by T019
- **SC-002**: 100 concurrent requests without errors → Verified by T045
- **SC-003**: 100% proper MCP response formatting → Verified by T010, T021
- **SC-004**: 99.9% uptime when Redis available → Monitored by T036
- **SC-005**: Actionable error messages → Implemented by T033, T034, T035
- **SC-006**: Health check under 100ms → Enhanced by T036

### Task Completion Validation

- **After T020 (US1 complete)**: ChatGPT can retrieve market reports
- **After T027 (US2 complete)**: ChatGPT can discover available tools
- **After T036 (US3 complete)**: System handles all error conditions gracefully
- **After T045 (Polish complete)**: System is production-ready

---

## Edge Cases Coverage

From spec.md edge cases section:

- **Stale data detection**: Handled by existing `data_age_ms` field in cached reports (T015 returns unmodified)
- **Concurrent requests**: SSE connections are independent (T005 handles per-connection state)
- **Invalid report format**: Redis schema validation happens at producer level (out of scope for MCP provider)
- **Partial Redis data**: Existing cache.Reader.GetReport() handles (T015 reuses this logic)
- **Malformed JSON parameters**: Caught by T008 JSON-RPC parser and T016 validation
- **Network latency**: Enforced by T019 context timeout (500ms total including Redis 150ms)

---

## Notes

- All file paths use `mcp/` prefix as this extends existing MCP server
- Tasks reference existing components: cache.Reader (mcp/internal/cache/reader.go), chi router, config.Config
- [P] tasks are in different files and can run in parallel
- [Story] labels map to spec.md user stories for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing (if tests are written)
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- No vague tasks - all include specific file paths and clear actions
