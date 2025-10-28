package models

import "time"

// MarketEventEnvelope is the standardized wrapper for all market events.
type MarketEventEnvelope struct {
	Type    string    `json:"type"`     // trade_tick, order_book_depth, order_book_deltas, ticker_24h
	Venue   string    `json:"venue"`    // BINANCE
	Symbol  string    `json:"symbol"`   // e.g., BTCUSDT
	TsEvent time.Time `json:"ts_event"` // UTC timestamp from exchange
	Payload any       `json:"payload"`  // Type-specific event data
}

// TradeTick represents a single executed trade.
type TradeTick struct {
	Price   float64 `json:"price"`
	Qty     float64 `json:"qty"`
	Side    string  `json:"side"` // "buy" or "sell"
	TradeID string  `json:"trade_id"`
}

// OrderBookDepth represents a full order book snapshot.
type OrderBookDepth struct {
	Bids   [][2]float64 `json:"bids"`   // [[price, qty], ...]
	Asks   [][2]float64 `json:"asks"`   // [[price, qty], ...]
	Levels int          `json:"levels"` // Number of levels (20 for MVP)
}

// OrderBookDeltas represents incremental order book updates.
type OrderBookDeltas struct {
	BidsUpd [][2]float64 `json:"bids_upd"` // [[price, new_qty], ...] qty=0 means remove
	AsksUpd [][2]float64 `json:"asks_upd"` // [[price, new_qty], ...]
}

// Ticker24h represents 24-hour rolling statistics.
type Ticker24h struct {
	LastPrice      float64    `json:"last_price"`
	PriceChangePct float64    `json:"price_change_pct"`
	High24h        float64    `json:"high_24h"`
	Low24h         float64    `json:"low_24h"`
	Volume24h      float64    `json:"volume_24h"`
	BestBid        [2]float64 `json:"best_bid"` // [price, qty]
	BestAsk        [2]float64 `json:"best_ask"` // [price, qty]
}
