package handlers

import (
	"context"
	"encoding/json"
	"log/slog"
	"net/http"

	"mcp/internal/models"
)

// CacheReader is the interface for reading reports from cache.
type CacheReader interface {
	GetReport(ctx context.Context, symbol string) (*models.MarketReport, error)
}

// GetReportHandler handles GET /get_report requests.
//
// Implements constitution principle 13 (MCP Contract - Read-Only):
// - Method: get_report(symbol: string) -> ReportJSON | null
// - Response sourced from Redis cache (no computation)
// - Timeout ≤ 150 ms (enforced by middleware)
// - Missing symbol → HTTP 404
type GetReportHandler struct {
	cache  CacheReader
	logger *slog.Logger
}

// NewGetReportHandler creates a new get_report handler.
func NewGetReportHandler(cache CacheReader, logger *slog.Logger) *GetReportHandler {
	return &GetReportHandler{
		cache:  cache,
		logger: logger.With("handler", "get_report"),
	}
}

// ServeHTTP handles the get_report request.
func (h *GetReportHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	// Only accept GET requests
	if r.Method != http.MethodGet {
		h.sendError(w, http.StatusMethodNotAllowed, "method_not_allowed", "Only GET requests are supported")
		return
	}

	// Extract symbol from query parameters
	symbol := r.URL.Query().Get("symbol")
	if symbol == "" {
		h.sendError(w, http.StatusBadRequest, "missing_parameter", "symbol parameter is required")
		return
	}

	h.logger.Debug("get_report_request", "symbol", symbol, "remote_addr", r.RemoteAddr)

	// Get report from cache
	report, err := h.cache.GetReport(r.Context(), symbol)
	if err != nil {
		h.logger.Error("cache_read_failed", "symbol", symbol, "error", err)
		h.sendError(w, http.StatusInternalServerError, "backend_unavailable", "Failed to read from cache")
		return
	}

	// Symbol not found in cache (FR-024)
	if report == nil {
		h.logger.Debug("symbol_not_indexed", "symbol", symbol)
		h.sendError(w, http.StatusNotFound, "symbol_not_indexed", "Symbol not found in cache")
		return
	}

	// Return report as JSON
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)

	if err := json.NewEncoder(w).Encode(report); err != nil {
		h.logger.Error("json_encode_failed", "symbol", symbol, "error", err)
		return
	}

	h.logger.Info("get_report_success",
		"symbol", symbol,
		"data_age_ms", report.DataAgeMs,
		"fresh", report.Ingestion.Fresh,
		"status", report.Ingestion.Status,
	)
}

// sendError sends a JSON error response.
func (h *GetReportHandler) sendError(w http.ResponseWriter, statusCode int, errorCode string, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(statusCode)

	errorResp := models.ErrorResponse{
		Error:   errorCode,
		Message: message,
	}

	json.NewEncoder(w).Encode(errorResp)
}
