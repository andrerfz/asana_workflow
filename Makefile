.PHONY: help build up down restart recreate logs shell clean dev setup setup-agent test

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# --- Docker commands ---

build: ## Build the Docker image
	docker compose -f docker/docker-compose.yml --env-file .env build
	@echo ""
	@echo "\033[1;32m  Build complete. Run: make up\033[0m"
	@echo ""

up: ## Start the container (detached)
	docker compose -f docker/docker-compose.yml --env-file .env up -d
	@echo ""
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo "\033[1;32m  Dashboard running at:\033[0m"
	@echo "\033[1;36m  http://localhost:8765\033[0m"
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo ""

down: ## Stop the container
	docker compose -f docker/docker-compose.yml --env-file .env down

recreate: ## Full rebuild: stop, build, start
	docker compose -f docker/docker-compose.yml --env-file .env down
	docker compose -f docker/docker-compose.yml --env-file .env build
	docker compose -f docker/docker-compose.yml --env-file .env up -d
	@echo ""
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo "\033[1;32m  Dashboard rebuilt and running at:\033[0m"
	@echo "\033[1;36m  http://localhost:8765\033[0m"
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo ""

restart: ## Restart the container
	docker compose -f docker/docker-compose.yml --env-file .env restart

logs: ## Tail container logs
	docker compose -f docker/docker-compose.yml --env-file .env logs -f asana-workflow

shell: ## Open a shell inside the container
	docker compose -f docker/docker-compose.yml --env-file .env exec asana-workflow /bin/bash

# --- Development ---

dev: ## Run locally without Docker (hot reload)
	@echo ""
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo "\033[1;32m  Dashboard starting at:\033[0m"
	@echo "\033[1;36m  http://localhost:8765\033[0m"
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo ""
	uvicorn app:app --host 127.0.0.1 --port 8765 --reload

setup: ## First-time setup: copy .env, install deps, create data dir
	@test -f .env || cp .env.example .env
	@mkdir -p data
	pip install -r requirements.txt
	@echo ""
	@echo "✓ Setup done. Edit .env with your Asana PAT, then run: make setup-agent"

setup-agent: ## Generate Claude Code auth token and add it to .env
	@./scripts/setup-agent.sh

# --- Tests ---

test: ## Run tests inside the container
	docker compose -f docker/docker-compose.yml --env-file .env exec asana-workflow python -m pytest tests/ -v

# --- Utility ---

clean: ## Remove container, image, and local data
	docker compose -f docker/docker-compose.yml --env-file .env down --rmi local -v
	rm -rf data/__pycache__

sync: ## Trigger a sync to Asana (push scope scores)
	curl -s -X POST http://localhost:8765/api/sync | python3 -m json.tool

refresh: ## Fetch and display tasks from API
	curl -s http://localhost:8765/api/tasks | python3 -m json.tool

status: ## Quick health check
	@curl -s -o /dev/null -w "HTTP %{http_code} — " http://localhost:8765/ && echo "Dashboard OK" || echo "Dashboard DOWN"
