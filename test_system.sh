#!/bin/bash

# Quick system test script for context8-mcp
# Usage: ./test_system.sh

set -e

echo "╔═══════════════════════════════════════════════════════╗"
echo "║     Context8 MCP System Test                         ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test functions
test_passed() {
    echo -e "${GREEN}✓${NC} $1"
}

test_failed() {
    echo -e "${RED}✗${NC} $1"
    exit 1
}

test_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

echo "1. Checking Docker services..."
if ! docker compose ps | grep -q "Up"; then
    test_failed "Docker services are not running. Run: docker compose up -d"
fi

# Check all services are healthy
SERVICES=("context8-producer" "context8-mcp" "context8-redis")
for service in "${SERVICES[@]}"; do
    if docker compose ps | grep "$service" | grep -q "healthy"; then
        test_passed "$service is healthy"
    else
        test_warning "$service is not fully healthy yet (may need more time)"
    fi
done
echo ""

echo "2. Testing health endpoints..."
# Producer health check
if curl -s http://localhost:9101/metrics | grep -q "nt_node_heartbeat.*1.0"; then
    test_passed "Producer heartbeat OK"
else
    test_failed "Producer heartbeat FAILED"
fi

# MCP health check
if curl -s http://localhost:8080/health | grep -q "healthy"; then
    test_passed "MCP server health OK"
else
    test_failed "MCP server health FAILED"
fi
echo ""

echo "3. Testing market data retrieval..."
# Test BTCUSDT report
BTCUSDT_REPORT=$(curl -s "http://localhost:8080/get_report?symbol=BTCUSDT")
if echo "$BTCUSDT_REPORT" | jq -e '.symbol == "BTCUSDT"' > /dev/null 2>&1; then
    PRICE=$(echo "$BTCUSDT_REPORT" | jq -r '.last_price')
    SPREAD=$(echo "$BTCUSDT_REPORT" | jq -r '.spread_bps')
    AGE=$(echo "$BTCUSDT_REPORT" | jq -r '.data_age_ms')
    HEALTH=$(echo "$BTCUSDT_REPORT" | jq -r '.health.score')

    test_passed "BTCUSDT report retrieved"
    echo "   Price: $PRICE USDT"
    echo "   Spread: $SPREAD bps"
    echo "   Data age: ${AGE}ms"
    echo "   Health: ${HEALTH}/100"

    # Check data freshness
    if [ "$AGE" -lt 2000 ]; then
        test_passed "Data is fresh (< 2000ms)"
    else
        test_warning "Data age is high: ${AGE}ms"
    fi
else
    test_failed "BTCUSDT report retrieval FAILED"
fi
echo ""

# Test ETHUSDT report
ETHUSDT_REPORT=$(curl -s "http://localhost:8080/get_report?symbol=ETHUSDT")
if echo "$ETHUSDT_REPORT" | jq -e '.symbol == "ETHUSDT"' > /dev/null 2>&1; then
    PRICE=$(echo "$ETHUSDT_REPORT" | jq -r '.last_price')
    test_passed "ETHUSDT report retrieved (Price: $PRICE USDT)"
else
    test_failed "ETHUSDT report retrieval FAILED"
fi
echo ""

echo "4. Checking Prometheus metrics..."
# Check report publication
BTCUSDT_COUNT=$(curl -s http://localhost:9101/metrics | grep 'nt_report_publish_total{symbol="BTCUSDT"}' | awk '{print $2}' | head -1)
ETHUSDT_COUNT=$(curl -s http://localhost:9101/metrics | grep 'nt_report_publish_total{symbol="ETHUSDT"}' | awk '{print $2}' | head -1)

# Convert to integer for comparison
BTCUSDT_COUNT_INT=$(echo "$BTCUSDT_COUNT" | cut -d. -f1)

if [ ! -z "$BTCUSDT_COUNT" ] && [ ! -z "$BTCUSDT_COUNT_INT" ] && [ "$BTCUSDT_COUNT_INT" -gt 0 ] 2>/dev/null; then
    test_passed "Reports published: BTCUSDT=${BTCUSDT_COUNT}, ETHUSDT=${ETHUSDT_COUNT}"
else
    test_warning "Reports may not be published yet (metrics: BTCUSDT=${BTCUSDT_COUNT})"
fi

# Check symbols assigned
SYMBOLS=$(curl -s http://localhost:9101/metrics | grep 'nt_symbols_assigned' | awk '{print $2}' | head -1)
SYMBOLS_INT=$(echo "$SYMBOLS" | cut -d. -f1)
if [ "$SYMBOLS_INT" == "2" ] 2>/dev/null; then
    test_passed "Symbols assigned: 2 (BTCUSDT, ETHUSDT)"
else
    test_warning "Expected 2 symbols, got: $SYMBOLS"
fi
echo ""

echo "5. Testing Redis..."
REDIS_OPS=$(docker compose exec -T redis redis-cli INFO stats | grep "instantaneous_ops_per_sec" | cut -d: -f2 | tr -d '\r')
REDIS_HITS=$(docker compose exec -T redis redis-cli INFO stats | grep "keyspace_hits" | cut -d: -f2 | tr -d '\r')

if [ ! -z "$REDIS_OPS" ]; then
    test_passed "Redis ops/sec: $REDIS_OPS"
    test_passed "Redis cache hits: $REDIS_HITS"
else
    test_failed "Redis connection FAILED"
fi

# Check Redis keys
KEY_COUNT=$(docker compose exec -T redis redis-cli KEYS "report:*" | wc -l)
if [ "$KEY_COUNT" -ge 2 ]; then
    test_passed "Redis keys found: $KEY_COUNT"
else
    test_warning "Expected 2 keys, found: $KEY_COUNT (may need more time to populate)"
fi
echo ""

echo "6. Testing error handling..."
# Test invalid symbol
INVALID_RESPONSE=$(curl -s "http://localhost:8080/get_report?symbol=INVALID")
if echo "$INVALID_RESPONSE" | jq -e '.error == "symbol_not_indexed"' > /dev/null 2>&1; then
    test_passed "Error handling works (invalid symbol returns proper error)"
else
    test_warning "Error response format may differ"
fi
echo ""

echo "7. Performance check..."
# Measure report update frequency
echo "   Measuring report update frequency (5 seconds)..."
COUNT1=$(curl -s http://localhost:9101/metrics | grep 'nt_report_publish_total{symbol="BTCUSDT"}' | awk '{print $2}')
sleep 5
COUNT2=$(curl -s http://localhost:9101/metrics | grep 'nt_report_publish_total{symbol="BTCUSDT"}' | awk '{print $2}')

if [ ! -z "$COUNT1" ] && [ ! -z "$COUNT2" ]; then
    RATE=$(echo "scale=2; ($COUNT2 - $COUNT1) / 5" | bc)
    if (( $(echo "$RATE >= 3.5" | bc -l) )); then
        test_passed "Report rate: ${RATE} reports/sec (expected ~4)"
    else
        test_warning "Report rate: ${RATE} reports/sec (expected ~4)"
    fi
else
    test_warning "Could not measure report rate"
fi
echo ""

echo "╔═══════════════════════════════════════════════════════╗"
echo "║     All tests completed successfully! ✓              ║"
echo "╚═══════════════════════════════════════════════════════╝"
echo ""
echo "Next steps:"
echo "  • View real-time updates: docker compose logs producer --follow"
echo "  • Monitor metrics: watch -n 1 'curl -s http://localhost:9101/metrics | grep nt_report'"
echo "  • Get full report: curl -s http://localhost:8080/get_report?symbol=BTCUSDT | jq ."
echo "  • Read full guide: cat TEST_GUIDE.md"
echo ""
