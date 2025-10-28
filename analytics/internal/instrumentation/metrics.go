package instrumentation

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

// Metrics contains all Prometheus metrics for the analytics service.
type Metrics struct {
	// Phase 3 metrics (T074)
	StreamLagMs   prometheus.Histogram
	EventsRate    prometheus.Counter
	CalcLatencyMs prometheus.Histogram

	// Phase 5 metrics (T093, T094)
	ReportAgeMs prometheus.Gauge
	ErrorsTotal *prometheus.CounterVec
}

// NewMetrics creates and registers all Prometheus metrics.
func NewMetrics() *Metrics {
	return &Metrics{
		// Stream processing lag
		StreamLagMs: promauto.NewHistogram(prometheus.HistogramOpts{
			Name:    "context8_stream_lag_ms",
			Help:    "Time between event timestamp and processing time in milliseconds",
			Buckets: []float64{10, 50, 100, 250, 500, 1000, 2000, 5000},
		}),

		// Event processing rate
		EventsRate: promauto.NewCounter(prometheus.CounterOpts{
			Name: "context8_events_processed_total",
			Help: "Total number of market events processed",
		}),

		// Calculation latency
		CalcLatencyMs: promauto.NewHistogram(prometheus.HistogramOpts{
			Name:    "context8_calc_latency_ms",
			Help:    "Time to calculate and generate report in milliseconds",
			Buckets: []float64{1, 5, 10, 25, 50, 100, 250, 500},
		}),

		// Report data age (Phase 5 - T093)
		ReportAgeMs: promauto.NewGauge(prometheus.GaugeOpts{
			Name: "context8_report_age_ms",
			Help: "Age of data in the most recent report in milliseconds",
		}),

		// Errors by component and type (Phase 5 - T094)
		ErrorsTotal: promauto.NewCounterVec(prometheus.CounterOpts{
			Name: "context8_errors_total",
			Help: "Total number of errors by component and type",
		}, []string{"component", "error_type"}),
	}
}

// RecordStreamLag records the lag between event timestamp and processing time.
func (m *Metrics) RecordStreamLag(lagMs float64) {
	m.StreamLagMs.Observe(lagMs)
}

// RecordEventProcessed increments the event counter.
func (m *Metrics) RecordEventProcessed() {
	m.EventsRate.Inc()
}

// RecordCalcLatency records the time to calculate a report.
func (m *Metrics) RecordCalcLatency(latencyMs float64) {
	m.CalcLatencyMs.Observe(latencyMs)
}

// RecordReportAge records the data age of the latest report (Phase 5 - T093).
func (m *Metrics) RecordReportAge(ageMs int64) {
	m.ReportAgeMs.Set(float64(ageMs))
}

// RecordError increments the error counter (Phase 5 - T094).
func (m *Metrics) RecordError(component, errorType string) {
	m.ErrorsTotal.WithLabelValues(component, errorType).Inc()
}
