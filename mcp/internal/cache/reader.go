package cache

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"

	"mcp/internal/models"
)

// Reader reads market reports from Redis cache.
//
// Reference-First Implementation:
// - Consulted .refs/go-redis for GET commands
// - Implements cache key pattern per constitution principle 5: report:{symbol}
type Reader struct {
	client *redis.Client
	logger *slog.Logger
}

// New creates a new Redis cache reader.
func New(redisURL string, redisPassword string, logger *slog.Logger) (*Reader, error) {
	// Parse Redis URL
	opt, err := redis.ParseURL(redisURL)
	if err != nil {
		return nil, fmt.Errorf("invalid redis URL: %w", err)
	}

	if redisPassword != "" {
		opt.Password = redisPassword
	}

	client := redis.NewClient(opt)

	// Verify connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping failed: %w", err)
	}

	return &Reader{
		client: client,
		logger: logger.With("component", "cache_reader"),
	}, nil
}

// GetReport fetches a market report from Redis cache.
//
// Implements constitution principle 13 (MCP Contract):
// - Returns report from cache (no computation triggered)
// - Timeout enforced by caller
// - Missing symbol returns nil with no error
func (r *Reader) GetReport(ctx context.Context, symbol string) (*models.MarketReport, error) {
	startTime := time.Now()

	// Cache key per constitution principle 5
	cacheKey := fmt.Sprintf("report:%s", symbol)

	// GET from Redis
	jsonBytes, err := r.client.Get(ctx, cacheKey).Bytes()
	if err != nil {
		if err == redis.Nil {
			// Symbol not found in cache - this is not an error per FR-024
			r.logger.Debug("symbol_not_in_cache",
				"symbol", symbol,
				"cache_key", cacheKey,
			)
			return nil, nil
		}
		return nil, fmt.Errorf("redis GET failed: %w", err)
	}

	// Deserialize report
	var report models.MarketReport
	if err := json.Unmarshal(jsonBytes, &report); err != nil {
		return nil, fmt.Errorf("json unmarshal failed: %w", err)
	}

	elapsed := time.Since(startTime)

	r.logger.Debug("report_retrieved",
		"symbol", symbol,
		"cache_key", cacheKey,
		"latency_ms", elapsed.Milliseconds(),
		"data_age_ms", report.DataAgeMs,
		"fresh", report.Ingestion.Fresh,
	)

	return &report, nil
}

// Close closes the Redis connection.
func (r *Reader) Close() error {
	return r.client.Close()
}
