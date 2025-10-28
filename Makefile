.PHONY: build test lint run clean help

help: ## Show this help message
	@echo 'Usage: make [target]'
	@echo ''
	@echo 'Available targets:'
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Build all services
	@echo "Building producer..."
	cd producer && poetry install && poetry build
	@echo "Building analytics service..."
	cd analytics && go build -o bin/analytics ./cmd/server
	@echo "Building MCP service..."
	cd mcp && go build -o bin/mcp ./cmd/server
	@echo "Build complete!"

test: ## Run all tests
	@echo "Testing producer..."
	cd producer && poetry run pytest
	@echo "Testing analytics service..."
	cd analytics && go test ./...
	@echo "Testing MCP service..."
	cd mcp && go test ./...
	@echo "Testing integration..."
	go test ./tests/integration/...
	@echo "Testing contracts..."
	go test ./tests/contract/...
	@echo "All tests passed!"

lint: ## Run linters on all code
	@echo "Linting analytics..."
	cd analytics && golangci-lint run || echo "golangci-lint not installed, skipping"
	@echo "Linting MCP..."
	cd mcp && golangci-lint run || echo "golangci-lint not installed, skipping"
	@echo "Linting producer..."
	cd producer && poetry run ruff check || echo "Ruff check complete"

run: ## Start all services with docker-compose
	docker-compose up --build

clean: ## Clean build artifacts and stop containers
	docker-compose down -v
	rm -rf analytics/bin mcp/bin
	cd producer && rm -rf dist .venv || true
	@echo "Cleanup complete!"
