FROM golang:1.23-alpine AS builder

WORKDIR /build

# Install build dependencies
RUN apk add --no-cache git

# Copy source code first (needed for go mod tidy to scan imports)
COPY . .

# Download dependencies and generate go.sum
RUN go mod download
RUN go mod tidy

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o mcp ./cmd/server

# Final stage
FROM alpine:latest

RUN apk --no-cache add ca-certificates wget

WORKDIR /app

# Copy binary from builder
COPY --from=builder /build/mcp .

# MCP API port
EXPOSE 8080

# Metrics port
EXPOSE 9092

CMD ["./mcp"]
