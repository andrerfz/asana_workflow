.PHONY: help build up down restart recreate logs shell clean dev setup

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

# --- Docker commands ---

build: ## Build the Docker image
	docker compose build
	@echo ""
	@echo "\033[1;32m  Build complete. Run: make up\033[0m"
	@echo ""

up: ## Start the container (detached)
	docker compose up -d
	@echo ""
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo "\033[1;32m  Dashboard running at:\033[0m"
	@echo "\033[1;36m  http://localhost:8765\033[0m"
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo ""

down: ## Stop the container
	docker compose down

recreate: ## Full rebuild: stop, build, start
	docker compose down
	docker compose build
	docker compose up -d
	@echo ""
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo "\033[1;32m  Dashboard rebuilt and running at:\033[0m"
	@echo "\033[1;36m  http://localhost:8765\033[0m"
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo ""

restart: ## Restart the container
	docker compose restart

logs: ## Tail container logs
	docker compose logs -f asana-workflow

shell: ## Open a shell inside the container
	docker compose exec asana-workflow /bin/bash

# --- Development ---

dev: ## Run locally without Docker (hot reload)
	@echo ""
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo "\033[1;32m  Dashboard starting at:\033[0m"
	@echo "\033[1;36m  http://localhost:8765\033[0m"
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo ""
	uvicorn main:app --host 127.0.0.1 --port 8765 --reload

setup: ## First-time setup: copy .env, install deps, create data dir
	@test -f .env || cp .env.example .env
	@mkdir -p data
	pip install -r requirements.txt
	@echo ""
	@echo "✓ Setup done. Edit .env with your Asana PAT, then run: make dev"

# --- Utility ---

clean: ## Remove container, image, and local data
	docker compose down --rmi local -v
	rm -rf data/__pycache__

sync: ## Trigger a sync to Asana (push scope scores)
	curl -s -X POST http://localhost:8765/api/sync | python3 -m json.tool

refresh: ## Fetch and display tasks from API
	curl -s http://localhost:8765/api/tasks | python3 -m json.tool

status: ## Quick health check
	@curl -s -o /dev/null -w "HTTP %{http_code} — " http://localhost:8765/ && echo "Dashboard OK" || echo "Dashboard DOWN"
