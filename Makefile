.PHONY: help build up down restart recreate logs shell clean dev dev-ui setup setup-agent test frontend reload electron-start electron-build electron-install install-hooks

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

dev: ## Run FastAPI only — serves the last built frontend at :8765
	@echo ""
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo "\033[1;32m  Dashboard at: http://localhost:8765\033[0m"
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo ""
	uvicorn app:app --host 127.0.0.1 --port 8765 --reload

dev-ui: ## Run FastAPI + Angular HMR together (Ctrl+C stops both)
	@echo ""
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo "\033[1;32m  Backend:  http://localhost:8765\033[0m"
	@echo "\033[1;32m  Frontend: http://localhost:4200  (HMR)\033[0m"
	@echo "\033[1;32m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m"
	@echo ""
	@trap 'kill 0' EXIT; \
	uvicorn app:app --host 127.0.0.1 --port 8765 --reload & \
	cd frontend && npm start; \
	wait

setup: ## First-time setup: copy .env, install deps, build frontend
	@test -f .env || cp .env.example .env
	@mkdir -p data
	pip install -r requirements.txt
	cd frontend && npm install && npm run build
	@echo ""
	@echo "✓ Setup done. Edit .env with your Asana PAT, then run: make setup-agent"

setup-agent: ## Generate Claude Code auth token and add it to .env
	@./scripts/setup-agent.sh

# --- Frontend ---

frontend: ## Build Angular/Ionic frontend (outputs to app/static/)
	cd frontend && npm run build
	@echo ""
	@echo "\033[1;32m  Frontend built → app/static/\033[0m"
	@echo "\033[1;32m  Restart FastAPI to serve new build.\033[0m"
	@echo ""

reload: ## After code changes: rebuild frontend, restart backend, clear Electron's disk cache
	cd frontend && npm run build
	docker compose -f docker/docker-compose.yml --env-file .env restart
	@osascript -e 'quit app "Asana Workflow"' 2>/dev/null || true
	@sleep 1
	@rm -rf "$(HOME)/Library/Application Support/asana-workflow-desktop/Cache" \
	        "$(HOME)/Library/Application Support/asana-workflow-desktop/Code Cache" \
	        "$(HOME)/Library/Application Support/asana-workflow-desktop/GPUCache" \
	        "$(HOME)/Library/Application Support/asana-workflow-desktop/DawnGraphiteCache" \
	        "$(HOME)/Library/Application Support/asana-workflow-desktop/DawnWebGPUCache" \
	        "$(HOME)/Library/Application Support/asana-workflow-desktop/Shared Dictionary"
	@echo ""
	@echo "\033[1;32m  Frontend rebuilt, backend restarted, Electron cache cleared.\033[0m"
	@echo "\033[1;32m  Reopen the desktop app (or hard-refresh the browser tab).\033[0m"
	@echo ""

electron-start: ## Run desktop app (FastAPI + Electron window)
	cd electron && npm start

electron-build: ## Compile the macOS desktop app (.dmg + .zip + .app)
	@cd electron && [ -d node_modules ] || npm install
	cd electron && npm run dist
	@echo ""
	@echo "\033[1;32m  Built → electron/dist/\033[0m"
	@echo ""

electron-install: ## Build the .app and install it into /Applications (overwrites)
	@cd electron && [ -d node_modules ] || npm install
	cd electron && npm run pack
	rm -rf "/Applications/Asana Workflow.app"
	cp -R "electron/dist/mac-arm64/Asana Workflow.app" "/Applications/Asana Workflow.app"
	@xattr -dr com.apple.quarantine "/Applications/Asana Workflow.app" 2>/dev/null || true
	@echo ""
	@echo "\033[1;32m  Installed → /Applications/Asana Workflow.app\033[0m"
	@echo ""

install-hooks: ## Install git hooks (auto-rebuild desktop app when electron/ changes on master)
	@mkdir -p .git/hooks
	@cp scripts/hooks/post-merge .git/hooks/post-merge
	@chmod +x .git/hooks/post-merge
	@echo "\033[1;32m  Installed post-merge hook → .git/hooks/post-merge\033[0m"

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
