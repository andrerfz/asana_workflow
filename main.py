"""Asana Workflow Dashboard — app entry point."""
import os
import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from config import STATIC_DIR
from routes.tasks import router as tasks_router
from routes.ai import router as ai_router
from routes.history import router as history_router

log = logging.getLogger(__name__)

POLL_INTERVAL = int(os.getenv("POLL_INTERVAL_MINUTES", "5")) * 60  # seconds


async def _poll_loop():
    """Background polling: refresh cached tasks from Asana every N minutes."""
    from task_cache import refresh_cache
    # Initial fetch on startup
    await refresh_cache()
    while True:
        await asyncio.sleep(POLL_INTERVAL)
        try:
            await refresh_cache()
            log.info("Auto-refresh: cache updated")
        except Exception as e:
            log.warning("Auto-refresh failed: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
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
    html = (STATIC_DIR / "index.html").read_text()
    html = html.replace(
        'href="/static/style.css"',
        f'href="/static/style.css?v={_file_version("style.css")}"',
    ).replace(
        'src="/static/app.js"',
        f'src="/static/app.js?v={_file_version("app.js")}"',
    )
    return HTMLResponse(html)
