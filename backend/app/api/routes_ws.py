from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from ..jobs.manager import JobManager
from ..security import verify_token

router = APIRouter()

_TERMINAL = {"JOB_COMPLETED", "JOB_CANCELLED", "JOB_FAILED"}


@router.websocket("/ws/jobs/{job_id}")
async def job_progress_ws(
    websocket: WebSocket,
    job_id: str,
    token: str = Query(default=""),
    after_seq: int = Query(default=0),
) -> None:
    """進捗をストリームする。token はクエリで検証（WS はヘッダ制約があるため）。"""
    expected: str = websocket.app.state.token
    if not verify_token(token, expected):
        await websocket.close(code=4401)
        return
    await websocket.accept()

    manager: JobManager = websocket.app.state.manager
    last_seq = after_seq
    try:
        while True:
            events = manager.hub.events_since(job_id, last_seq)
            for ev in events:
                await websocket.send_json(ev.to_dict())
                last_seq = ev.seq
            if events and events[-1].type.value in _TERMINAL:
                break
            await asyncio.sleep(0.2)
    except WebSocketDisconnect:
        return
    finally:
        try:
            await websocket.close()
        except RuntimeError:
            pass
