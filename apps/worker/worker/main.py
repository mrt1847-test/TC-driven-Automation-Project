from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from worker.core.database import init_db
from worker.core.log_stream import log_streams
from worker.core.security import (
    WORKER_TOKEN_HEADER,
    WorkerTrustBoundaryMiddleware,
    allowed_origins,
    websocket_trust_denied_reason,
)
from worker.routers import (
    artifacts,
    cases,
    executions,
    generation,
    healing,
    mapping,
    projects,
    prompts,
    selector_candidates,
    settings,
    structuring,
    webwright_runs,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="TC Automation Studio Worker", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Content-Type", WORKER_TOKEN_HEADER],
)
app.add_middleware(WorkerTrustBoundaryMiddleware)

app.include_router(projects.router)
app.include_router(prompts.router)
app.include_router(prompts.preset_router)
app.include_router(prompts.preview_router)
app.include_router(prompts.payload_router)
app.include_router(artifacts.router)
app.include_router(cases.router)
app.include_router(selector_candidates.router)
app.include_router(webwright_runs.router)
app.include_router(mapping.router)
app.include_router(generation.router)
app.include_router(structuring.router)
app.include_router(executions.router)
app.include_router(executions.export_router)
app.include_router(healing.router)
app.include_router(settings.router)


@app.get("/")
def root():
    return {"service": "tc-automation-studio-worker", "status": "ok"}


@app.websocket("/ws/logs/{job_id}")
async def websocket_logs(job_id: str, websocket: WebSocket):
    denied_reason = websocket_trust_denied_reason(websocket)
    if denied_reason:
        await websocket.close(code=1008, reason=denied_reason)
        return
    await log_streams.connect(job_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        log_streams.disconnect(job_id, websocket)
