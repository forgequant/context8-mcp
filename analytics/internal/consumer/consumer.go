package consumer

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"

	"analytics/internal/models"
)

// EventHandler processes deserialized market events.
type EventHandler func(ctx context.Context, envelope *models.MarketEventEnvelope, streamID string) error

// Consumer reads market events from Redis Streams using consumer groups.
//
// Reference-First Implementation:
// - Consulted .refs/go-redis/doctests/stream_tutorial_test.go
// - Implements XREADGROUP + XACK pattern for at-least-once delivery
// - Uses consumer groups per constitution principle 1 (layered EDA)
type Consumer struct {
	client        *redis.Client
	streamKey     string
	consumerGroup string
	consumerName  string
	handler       EventHandler
	logger        *slog.Logger
}

// Config holds consumer configuration.
type Config struct {
	RedisURL      string
	RedisPassword string
	StreamKey     string        // e.g., "nt:binance"
	ConsumerGroup string        // e.g., "context8"
	ConsumerName  string        // e.g., "analytics-1"
	BlockTime     time.Duration // How long to block waiting for messages
	BatchSize     int64         // Number of messages to read per batch
}

// New creates a new Redis Streams consumer.
func New(cfg Config, handler EventHandler, logger *slog.Logger) (*Consumer, error) {
	// Parse Redis URL and create client
	opt, err := redis.ParseURL(cfg.RedisURL)
	if err != nil {
		return nil, fmt.Errorf("invalid redis URL: %w", err)
	}

	if cfg.RedisPassword != "" {
		opt.Password = cfg.RedisPassword
	}

	client := redis.NewClient(opt)

	// Verify connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis ping failed: %w", err)
	}

	consumer := &Consumer{
		client:        client,
		streamKey:     cfg.StreamKey,
		consumerGroup: cfg.ConsumerGroup,
		consumerName:  cfg.ConsumerName,
		handler:       handler,
		logger:        logger.With("component", "consumer", "stream_key", cfg.StreamKey),
	}

	// Create consumer group if it doesn't exist
	// Pattern from .refs/go-redis: XGroupCreateMkStream creates stream if missing
	err = client.XGroupCreateMkStream(ctx, cfg.StreamKey, cfg.ConsumerGroup, "0").Err()
	if err != nil && err.Error() != "BUSYGROUP Consumer Group name already exists" {
		return nil, fmt.Errorf("failed to create consumer group: %w", err)
	}

	consumer.logger.Info("consumer_initialized",
		"consumer_group", cfg.ConsumerGroup,
		"consumer_name", cfg.ConsumerName,
	)

	return consumer, nil
}

// Start begins consuming messages from the stream.
// Blocks until context is cancelled.
func (c *Consumer) Start(ctx context.Context) error {
	c.logger.Info("consumer_starting")

	// Pattern from .refs/go-redis: XREADGROUP with ">" reads new messages
	// Use BLOCK to wait for new messages instead of busy-waiting
	blockTime := 5 * time.Second
	batchSize := int64(10)

	for {
		select {
		case <-ctx.Done():
			c.logger.Info("consumer_stopping")
			return ctx.Err()
		default:
			// XREADGROUP: Read from consumer group
			// ">" means read only new messages not yet delivered to this group
			streams, err := c.client.XReadGroup(ctx, &redis.XReadGroupArgs{
				Group:    c.consumerGroup,
				Consumer: c.consumerName,
				Streams:  []string{c.streamKey, ">"},
				Count:    batchSize,
				Block:    blockTime,
				NoAck:    false, // We'll explicitly XACK after processing
			}).Result()

			if err != nil {
				if err == redis.Nil {
					// No new messages, continue loop
					continue
				}
				c.logger.Error("xreadgroup_failed", "error", err)
				time.Sleep(1 * time.Second) // Back off on error
				continue
			}

			// Process messages from all streams (usually just one)
			for _, stream := range streams {
				for _, message := range stream.Messages {
					if err := c.processMessage(ctx, message); err != nil {
						c.logger.Error("message_processing_failed",
							"stream_id", message.ID,
							"error", err,
						)
						// Continue processing other messages despite error
						// Constitution principle 3: Idempotency ensures safe retries
						continue
					}

					// XACK: Acknowledge message after successful processing
					// Pattern from .refs/go-redis: XAck(stream, group, ids...)
					if err := c.client.XAck(ctx, c.streamKey, c.consumerGroup, message.ID).Err(); err != nil {
						c.logger.Error("xack_failed",
							"stream_id", message.ID,
							"error", err,
						)
						// Continue despite XACK failure - message will be redelivered
					} else {
						c.logger.Debug("message_acknowledged", "stream_id", message.ID)
					}
				}
			}
		}
	}
}

// processMessage deserializes and processes a single message.
func (c *Consumer) processMessage(ctx context.Context, msg redis.XMessage) error {
	startTime := time.Now()

	// Extract JSON payload from Redis Stream message
	// Per constitution principle 2, message format is: {data: <json_bytes>}
	dataField, ok := msg.Values["data"]
	if !ok {
		return fmt.Errorf("message missing 'data' field")
	}

	jsonBytes, ok := dataField.(string)
	if !ok {
		return fmt.Errorf("data field is not a string")
	}

	// Deserialize MarketEventEnvelope from JSON
	var envelope models.MarketEventEnvelope
	if err := json.Unmarshal([]byte(jsonBytes), &envelope); err != nil {
		return fmt.Errorf("json unmarshal failed: %w", err)
	}

	// Calculate lag: time since event was generated
	// Per constitution principle 7: SLO for data_age_ms <= 1000
	lagMs := time.Since(envelope.TsEvent).Milliseconds()

	c.logger.Debug("event_received",
		"stream_id", msg.ID,
		"symbol", envelope.Symbol,
		"type", envelope.Type,
		"lag_ms", lagMs,
	)

	// Call handler with deserialized event
	if err := c.handler(ctx, &envelope, msg.ID); err != nil {
		return fmt.Errorf("handler failed: %w", err)
	}

	processingMs := time.Since(startTime).Milliseconds()

	c.logger.Info("event_processed",
		"stream_id", msg.ID,
		"symbol", envelope.Symbol,
		"type", envelope.Type,
		"lag_ms", lagMs,
		"processing_ms", processingMs,
	)

	return nil
}

// Close closes the Redis connection.
func (c *Consumer) Close() error {
	c.logger.Info("consumer_closing")
	return c.client.Close()
}
