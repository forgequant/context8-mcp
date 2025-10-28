package aggregator

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"

	"analytics/internal/models"
)

// RedisPublisher publishes market reports to Redis KV cache.
//
// Reference-First Implementation:
// - Consulted .refs/go-redis for SET commands with expiration
// - Implements cache keys per constitution principle 5: report:{symbol}
type RedisPublisher struct {
	client *redis.Client
	ttl    time.Duration
	logger *slog.Logger
}

// NewRedisPublisher creates a new Redis cache publisher.
func NewRedisPublisher(redisURL string, redisPassword string, ttl time.Duration, logger *slog.Logger) (*RedisPublisher, error) {
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

	return &RedisPublisher{
		client: client,
		ttl:    ttl,
		logger: logger.With("component", "redis_publisher"),
	}, nil
}

// Publish stores a market report in Redis cache with TTL.
//
// Implements constitution principle 5 (Data Integration and Schema):
// - Cache key: report:{symbol}
// - Cache TTL: 2-5 minutes (configurable)
func (p *RedisPublisher) Publish(ctx context.Context, symbol string, report *models.MarketReport) error {
	startTime := time.Now()

	// Serialize report to JSON
	jsonBytes, err := json.Marshal(report)
	if err != nil {
		return fmt.Errorf("json marshal failed: %w", err)
	}

	// Cache key per constitution principle 5
	cacheKey := fmt.Sprintf("report:%s", symbol)

	// SET with expiration (TTL)
	// Pattern from .refs/go-redis: SET key value EX seconds
	err = p.client.Set(ctx, cacheKey, jsonBytes, p.ttl).Err()
	if err != nil {
		return fmt.Errorf("redis SET failed: %w", err)
	}

	elapsed := time.Since(startTime)

	p.logger.Info("report_cached",
		"symbol", symbol,
		"cache_key", cacheKey,
		"ttl_sec", p.ttl.Seconds(),
		"size_bytes", len(jsonBytes),
		"latency_ms", elapsed.Milliseconds(),
	)

	return nil
}

// Close closes the Redis connection.
func (p *RedisPublisher) Close() error {
	return p.client.Close()
}
