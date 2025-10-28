# Reference Repositories (.refs/)

## Purpose

This directory contains reference repositories with **working code examples** that MUST be consulted before implementing any integration, library usage, or architectural pattern in the context8-mcp project.

## Mandatory Consultation

⚠️ **CONSTITUTIONAL REQUIREMENT** (Principle 10: Reference-First Development)

**Before writing ANY integration or library usage code, you MUST:**

1. Open `INDEX.yaml` in this directory
2. Identify the relevant category for your task
3. Read the key files from applicable reference repositories
4. Extract working patterns, error handling, and best practices
5. Adapt patterns to context8-mcp architecture
6. Document which references you consulted in code comments

## Quick Category Reference

| Category | Use When |
|----------|----------|
| **Exchange Integrations** | Binance API, WebSockets, order books, trades |
| **Redis Streams & Cache** | Redis Streams consumer/producer, XACK, cache ops |
| **Message Brokers** | Understanding pub/sub patterns (NATS, Kafka) |
| **MCP Integration** | Implementing MCP server, tool registration |
| **Market Data Processing** | NautilusTrader, microprice, volume profile, spoofing |

## Index Structure

See `INDEX.yaml` for the complete catalog with:
- Repository paths and purposes
- Key files to read for each use case
- Mandatory consultation workflow
- Examples for common tasks
- Anti-patterns to avoid

## Enforcement

- **Code Reviews**: Reviewers verify reference consultation
- **PR Requirements**: Document which references were consulted
- **Deviations**: Must be justified in code comments

## Updating the Index

When adding new reference repositories:

1. Clone the repository to `.refs/`
2. Update `INDEX.yaml` with:
   - Repository metadata (path, language, purpose)
   - Use cases and key files
   - Relevant category assignment
3. Increment `INDEX.yaml` version (minor bump)
4. Update sync_log with date and action

## Examples

### ✅ Correct Workflow

```
Task: Implement Redis Streams consumer with consumer group

Steps:
1. Open INDEX.yaml → locate "Redis Streams & Cache" category
2. Read go-redis repository:
   - stream_commands.go (API reference)
   - examples/redis-stream/* (working examples)
3. Extract XREADGROUP + XACK pattern from examples
4. Implement in context8-mcp with proper error handling
5. Add comment: "// Pattern from go-redis examples/redis-stream/main.go"
```

### ❌ Incorrect Workflow

```
Task: Implement Redis Streams consumer with consumer group

Steps:
1. Google "redis streams golang"
2. Copy random Stack Overflow code
3. Miss XACK acknowledgment → data loss in production
4. ⚠️ VIOLATION: Did not consult .refs/INDEX.yaml
```

## Philosophy

**Why Reference-First Development?**

- **Eliminates common bugs**: Reference code has battle-tested edge case handling
- **Accelerates development**: Don't reinvent solved problems
- **Ensures consistency**: All integrations follow proven patterns
- **Reduces technical debt**: Avoid architectural mismatches from ad-hoc implementations

Reference repositories are not just examples—they are the **source of truth** for integration patterns in this project.

---

**Constitution Reference**: Principle 10 (Reference-First Development)
**Index Version**: See `INDEX.yaml` header
**Last Updated**: 2025-10-28
