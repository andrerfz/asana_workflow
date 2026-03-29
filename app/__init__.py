"""Asana Workflow Dashboard — app entry point."""
import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

# Configure logging so all loggers (including agent_worker) output to stderr/Docker logs
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    stream=sys.stderr,
)

from .config import STATIC_DIR
from .routes.tasks import router as tasks_router
from .routes.ai import router as ai_router
from .routes.history import router as history_router
from .routes.repos import router as repos_router
from .routes.worktrees import router as worktrees_router
from .routes.agent import router as agent_router
from .routes.guides import router as guides_router

log = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_MINUTES", "5")) * 60  # seconds


async def _poll_loop():
    """Background polling: refresh cached tasks from Asana every N minutes."""
    from .services.task_cache import refresh_cache
    # Initial fetch on startup
    await refresh_cache()
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            await refresh_cache()
            log.info("Auto-refresh: cache updated")
        except Exception as e:
            log.warning("Auto-refresh failed: %s", e)


def _recover_stale_runs():
    """On startup, reset any runs stuck in active phases (interrupted by restart)."""
    from .agent import AGENT_RUNS_DIR
    from .agent import recover_stale_runs
    recovered = recover_stale_runs(AGENT_RUNS_DIR)
    for r in recovered:
        log.info("Recovered stale run %s: %s → error", r["task_gid"], r["old_phase"])


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Recover runs that were active when the container stopped
    _recover_stale_runs()

    # Register WS broadcast as agent event callback
    from .agent import register_event_callback, start_agent
    from .agent import agent_queue
    from .agent import ws_manager
    register_event_callback(ws_manager.broadcast)

    # Set queue callback to actually start agents
    agent_queue.set_start_callback(start_agent)

    task = asyncio.create_task(_poll_loop())
    yield
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


app = FastAPI(title="Asana Workflow Dashboard", lifespan=lifespan)

# Mount routers
app.include_router(tasks_router)
app.include_router(ai_router)
app.include_router(history_router)
app.include_router(repos_router)
app.include_router(worktrees_router)
app.include_router(agent_router)
app.include_router(guides_router)

# ── IDE integration ──

@app.post("/api/ide/open")
async def open_in_ide(body: dict):
    """Open a path in a desktop IDE via macOS `open -a` or CLI command."""
    import subprocess as _sp
    from fastapi import HTTPException as _HTTPException
    app_name = body.get("app", "")
    cli = body.get("cli", "")
    cli_args = body.get("cliArgs", [])
    path = body.get("path", "")
    if (not app_name and not cli) or not path:
        raise _HTTPException(400, "app or cli, and path are required")
    # Validate path exists
    import os as _os
    real_path = _os.path.realpath(path)
    if not _os.path.exists(real_path):
        raise _HTTPException(404, f"Path not found: {path}")
    try:
        if cli:
            # CLI-based IDEs (VS Code, Cursor) — supports -r to reuse window
            cmd = [cli] + (cli_args or []) + [real_path]
            _sp.Popen(cmd)
        else:
            # macOS `open -a` for JetBrains IDEs (naturally reuses existing window)
            _sp.Popen(["open", "-a", app_name, real_path])
    except Exception as e:
        raise _HTTPException(500, f"Failed to open IDE: {e}")
    return {"status": "ok"}

# Static files
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


def _file_version(filename: str) -> int:
    """Return file mtime as cache-busting version."""
    try:
        return int((STATIC_DIR / filename).stat().st_mtime)
    except OSError:
        return 0


@app.get("/")
async def index():
    import re
    html = (STATIC_DIR / "index.html").read_text()
    def _add_version(m):
        attr, filename = m.group(1), m.group(2)
        return f'{attr}="/static/{filename}?v={_file_version(filename)}"'
    html = re.sub(
        r'((?:src|href))="/static/([^"]+)"',
        _add_version,
        html,
    )
    return HTMLResponse(html)


@app.websocket("/ws/agent")
async def websocket_agent(ws: WebSocket):
    """WebSocket endpoint for real-time agent events."""
    from .agent import ws_manager as _ws
    await _ws.connect(ws)
    try:
        while True:
            msg = await ws.receive_text()
            if msg == "ping":
                await ws.send_text('{"event":"pong","data":{}}')
    except WebSocketDisconnect:
        _ws.disconnect(ws)
    except Exception:
        _ws.disconnect(ws)
