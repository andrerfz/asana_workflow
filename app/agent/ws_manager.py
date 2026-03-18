"""WebSocket connection manager for real-time agent events."""
import asyncio
import json
import logging
from fastapi import WebSocket

log = logging.getLogger(__name__)

_WS_SEND_TIMEOUT = 5  # seconds — drop client if send takes longer


class WSManager:
    """Manages WebSocket connections and broadcasts agent events."""

    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        log.info("WS connected (%d total)", len(self._connections))

    def disconnect(self, ws: WebSocket):
        if ws in self._connections:
            self._connections.remove(ws)
        log.info("WS disconnected (%d total)", len(self._connections))

    async def broadcast(self, event: str, data: dict):
        """Send an event to all connected clients with timeout protection."""
        message = json.dumps({"event": event, "data": data})
        dead = []
        for ws in self._connections:
            try:
                await asyncio.wait_for(ws.send_text(message), timeout=_WS_SEND_TIMEOUT)
            except asyncio.TimeoutError:
                log.warning("WS send timed out after %ds, dropping client", _WS_SEND_TIMEOUT)
                dead.append(ws)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._connections)


# Singleton
ws_manager = WSManager()
