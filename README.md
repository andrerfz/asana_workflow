# Asana Workflow Dashboard

A FastAPI-powered dashboard for managing Asana tasks with AI-driven classification, prioritization, and an autonomous coding agent that plans, implements, tests, and delivers task solutions using Claude Code CLI.

## Features

- **Task Dashboard** — View, filter, and manage Asana tasks in card, table, or cluster views
- **AI Classification** — Automatically classify tasks by type, scope, and priority using Claude
- **AI Coding Agent** — Autonomous agent that reads task requirements, creates a plan, writes code, runs tests, performs QA review, and delivers via PR — with human approval gates at each step
- **Real-time Updates** — WebSocket-based live logs, phase transitions, and notifications
- **Agent Guidance** — Send feedback to a running agent mid-coding; it pauses and resumes with your message in the same conversation context
- **Smart Testing** — Auto-selects fast vs full test suite based on whether migrations are present
- **Git Worktree Isolation** — Each agent task gets its own worktree, keeping your main branch clean
- **Multi-repo Support** — Agent can work across multiple repositories per task
- **IDE Integration** — Open worktrees directly in PhpStorm, VS Code, Cursor, or other IDEs

## Quick Start

### 1. Setup

```bash
make setup
```

This copies `.env.example` to `.env`, installs Python dependencies, and creates the `data/` directory.

### 2. Configure

Edit `.env` with your credentials:

```env
# Required
ASANA_PAT=your_asana_personal_access_token
ASANA_PROJECT_GID=your_project_gid
ASANA_SECTION_GID=your_section_gid

# Optional — enables AI classification
ANTHROPIC_API_KEY=your_anthropic_api_key

# Required for AI Agent feature
PROJECTS_DIR=/path/to/your/projects
```

### 3. Run

**Local development (with hot reload):**

```bash
make dev
```

**With Docker:**

```bash
make build
make up
```

Open [http://localhost:8765](http://localhost:8765)

## AI Agent Setup

The agent uses [Claude Code CLI](https://docs.anthropic.com/en/docs/claude-code) to autonomously write code. Additional setup is required:

### 1. Install Claude Code CLI

```bash
npm install -g @anthropic-ai/claude-code
claude login
```

### 2. Generate Auth Token (for Docker)

```bash
make setup-agent
```

This generates an OAuth token (valid 1 year) and saves it to your `.env`. The token allows the agent to run Claude Code inside the Docker container without interactive login.

### 3. Configure Repos

In the dashboard, go to **Settings > Repos** and add your repositories with:

- **Path** — Absolute path to the repo
- **Default branch** — `master` or `main`
- **Test command** — e.g., `make test`
- **Fast test command** — e.g., `make agent-test-no-migrations` (used when no migration files are changed)
- **Test description** — Explains test modes to the agent

## Agent Workflow

```
Start → Planning → [Human Approval] → Coding → Rebase → Testing → QA Review → [Human Approval] → Done
                        ↑                                                              |
                        └──────────────── Revise / Reject ─────────────────────────────┘
```

1. **Planning** — Agent reads the Asana task, analyzes the codebase, and proposes an implementation plan
2. **Approval** — You review and approve, reject, or revise the plan with feedback
3. **Coding** — Agent implements the plan using Claude Code CLI in an isolated git worktree
4. **Guide** — Optionally send real-time guidance to redirect the agent mid-coding
5. **Testing** — Runs your test suite; auto-retries with fixes on failure
6. **QA Review** — Automated code review against task requirements
7. **Delivery** — Auto-commits, rebases onto latest default branch, and notifies via Asana comment

## Architecture

```
app/
├── __init__.py              # FastAPI app, lifespan, WebSocket
├── config.py                # Environment variables, paths
├── routes/
│   ├── agent.py             # Agent API (start, stop, guide, queue, settings)
│   ├── ai.py                # AI classification endpoints
│   ├── tasks.py             # Task CRUD
│   ├── repos.py             # Repository registry
│   ├── worktrees.py         # Git worktree management
│   └── history.py           # Task history
├── services/
│   ├── asana_client.py      # Asana API wrapper
│   ├── repo_manager.py      # Repo config and health checks
│   ├── worktree_manager.py  # Git worktree lifecycle
│   ├── ai_classifier.py     # Claude-based task classification
│   ├── classifier.py        # Rule-based scoring engine
│   ├── task_cache.py        # In-memory task cache with Asana sync
│   └── storage.py           # JSON file persistence
├── agent/
│   ├── executor.py          # Main agent engine
│   ├── claude_client.py     # Claude Code CLI wrapper (stream, resume, kill)
│   ├── state.py             # Run persistence, logging, broadcasting
│   ├── phases.py            # Phase enum and workflow graph
│   ├── queue.py             # Concurrent execution queue
│   ├── memory.py            # Per-repo knowledge base
│   ├── stream_parser.py     # CLI output parsing
│   └── ws_manager.py        # WebSocket broadcasting
└── static/                  # Vanilla JS SPA frontend
```

## Available Commands

| Command | Description |
|---------|-------------|
| `make dev` | Run locally with hot reload |
| `make build` | Build Docker image |
| `make up` | Start container |
| `make down` | Stop container |
| `make recreate` | Full rebuild and restart |
| `make logs` | Tail container logs |
| `make shell` | Open shell in container |
| `make test` | Run test suite |
| `make setup` | First-time setup |
| `make setup-agent` | Generate Claude Code auth token |
| `make sync` | Trigger Asana sync |
| `make status` | Health check |
| `make clean` | Remove container and local data |

## Tech Stack

- **Backend** — Python 3.12, FastAPI, uvicorn, httpx
- **Frontend** — Vanilla JavaScript SPA (no framework)
- **AI** — Claude API (classification), Claude Code CLI (agent)
- **Infrastructure** — Docker, git worktrees
- **Integration** — Asana API, WebSockets

## License

Private project.