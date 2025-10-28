# Implementation Plan: [FEATURE]

**Branch**: `[###-feature-name]` | **Date**: [DATE] | **Spec**: [link]
**Input**: Feature specification from `/specs/[###-feature-name]/spec.md`

**Note**: This template is filled in by the `/speckit.plan` command. See `.specify/templates/commands/plan.md` for the execution workflow.

## Summary

[Extract from feature spec: primary requirement + technical approach from research]

## Technical Context

<!--
  ACTION REQUIRED: Replace the content in this section with the technical details
  for the project. The structure here is presented in advisory capacity to guide
  the iteration process.
-->

**Language/Version**: [e.g., Python 3.11, Swift 5.9, Rust 1.75 or NEEDS CLARIFICATION]  
**Primary Dependencies**: [e.g., FastAPI, UIKit, LLVM or NEEDS CLARIFICATION]  
**Storage**: [if applicable, e.g., PostgreSQL, CoreData, files or N/A]  
**Testing**: [e.g., pytest, XCTest, cargo test or NEEDS CLARIFICATION]  
**Target Platform**: [e.g., Linux server, iOS 15+, WASM or NEEDS CLARIFICATION]
**Project Type**: [single/web/mobile - determines source structure]  
**Performance Goals**: [domain-specific, e.g., 1000 req/s, 10k lines/sec, 60 fps or NEEDS CLARIFICATION]  
**Constraints**: [domain-specific, e.g., <200ms p95, <100MB memory, offline-capable or NEEDS CLARIFICATION]  
**Scale/Scope**: [domain-specific, e.g., 10k users, 1M LOC, 50 screens or NEEDS CLARIFICATION]

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Architecture Compliance (Principle 1)
- [ ] Feature follows layered EDA: Ingestion → Message Bus → Analytics → Cache → MCP
- [ ] Uses Redis Streams with consumer groups and XACK acknowledgment
- [ ] Respects single stream key topology (`nt:binance` for MVP)

### Message Bus Contract (Principle 2)
- [ ] All events use JSON format with `snake_case` fields
- [ ] Mandatory fields present: `symbol`, `venue`, `type`, `ts_event`, `payload`
- [ ] Event types limited to MVP-allowed: `trade_tick`, `order_book_depth|deltas`, `ticker_24h`

### Idempotency & Time (Principle 3)
- [ ] All event handlers are idempotent (safe for replay/retry)
- [ ] All timestamps in UTC (RFC3339), converted at layer boundaries

### Technology Stack (Principle 4)
- [ ] Analytics/backend services implemented in Go ≥ 1.24
- [ ] Python dependencies locked in `poetry.lock` or `requirements.txt`

### Report Contract (Principle 6)
- [ ] Report includes all mandatory fields: identification, 24h stats, L1/spread, depth, liquidity, flows, anomalies, health
- [ ] All calculation formulas documented in `/docs/metrics.md`
- [ ] `report_version` follows semantic versioning

### SLO Compliance (Principle 7)
- [ ] Feature supports `data_age_ms ≤ 1000` for healthy status
- [ ] Report generation design targets ≤ 250 ms on warm cache
- [ ] Graceful degradation implemented for data source failures

### Security (Principle 8)
- [ ] No secrets in code or repository (use `.env` or vault)
- [ ] MCP endpoints remain read-only (no side effects)
- [ ] Complies with Binance API Terms of Service

### Quality & Testing (Principle 9)
- [ ] Unit tests for all calculation logic
- [ ] Property-based tests for metric formulas
- [ ] MCP contract tests (schema + timeout validation)
- [ ] JSON schemas defined for events and reports

### Reference-First Development (Principle 10)
- [ ] `.refs/INDEX.yaml` consulted for relevant integrations/libraries
- [ ] Reference repository patterns used (e.g., go-redis for streams, go-binance for WebSocket)
- [ ] Deviations from reference patterns documented in code comments
- [ ] PRs document which reference repositories were consulted

### Observability (Principle 11)
- [ ] Structured JSON logging with: `component`, `symbol`, `lag_ms`, `stream_id`

### MCP Contract (Principle 13)
- [ ] MCP method signature: `get_report(symbol: string) -> ReportJSON | null`
- [ ] Response sourced from cache only (no computation triggered)
- [ ] Timeout ≤ 150 ms enforced

## Project Structure

### Documentation (this feature)

```text
specs/[###-feature]/
├── plan.md              # This file (/speckit.plan command output)
├── research.md          # Phase 0 output (/speckit.plan command)
├── data-model.md        # Phase 1 output (/speckit.plan command)
├── quickstart.md        # Phase 1 output (/speckit.plan command)
├── contracts/           # Phase 1 output (/speckit.plan command)
└── tasks.md             # Phase 2 output (/speckit.tasks command - NOT created by /speckit.plan)
```

### Source Code (repository root)
<!--
  ACTION REQUIRED: Replace the placeholder tree below with the concrete layout
  for this feature. Delete unused options and expand the chosen structure with
  real paths (e.g., apps/admin, packages/something). The delivered plan must
  not include Option labels.
-->

```text
# [REMOVE IF UNUSED] Option 1: Single project (DEFAULT)
src/
├── models/
├── services/
├── cli/
└── lib/

tests/
├── contract/
├── integration/
└── unit/

# [REMOVE IF UNUSED] Option 2: Web application (when "frontend" + "backend" detected)
backend/
├── src/
│   ├── models/
│   ├── services/
│   └── api/
└── tests/

frontend/
├── src/
│   ├── components/
│   ├── pages/
│   └── services/
└── tests/

# [REMOVE IF UNUSED] Option 3: Mobile + API (when "iOS/Android" detected)
api/
└── [same as backend above]

ios/ or android/
└── [platform-specific structure: feature modules, UI flows, platform tests]
```

**Structure Decision**: [Document the selected structure and reference the real
directories captured above]

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |
