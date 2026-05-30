from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncGenerator

from fastapi import WebSocket


class LogStreamManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)
        self._buffers: dict[str, list[str]] = defaultdict(list)

    async def connect(self, job_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[job_id].append(websocket)
        for line in self._buffers.get(job_id, []):
            await websocket.send_text(line)

    def disconnect(self, job_id: str, websocket: WebSocket) -> None:
        if job_id in self._connections and websocket in self._connections[job_id]:
            self._connections[job_id].remove(websocket)

    async def publish(self, job_id: str, message: str) -> None:
        self._buffers[job_id].append(message)
        dead: list[WebSocket] = []
        for ws in self._connections.get(job_id, []):
            try:
                await ws.send_text(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(job_id, ws)

    async def stream_subprocess(self, job_id: str, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await self.publish(job_id, line.decode("utf-8", errors="replace").rstrip())


log_streams = LogStreamManager()
