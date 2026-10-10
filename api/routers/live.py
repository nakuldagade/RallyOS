"""/v1/live: continuous capture in 5-second chunks, results pushed over SSE while the match is still being played.

Phase A (this file so far): the SSE stream and a mock session that replays a processed match as if it were live. The real
session endpoints (create, sign, chunks, stop) come with the StreamAnalyzer. Routers stay thin; logic lives in services/.
"""
import asyncio
import json
import threading

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from api.db import get_session
from api.services import live_hub, live_mock, store

router = APIRouter(tags=["live"])


class MockStart(BaseModel):
    match_id: str
    speed: float = 1.0
    chunk_seconds: float = 5.0


@router.post("/live/mock", status_code=201)
def start_mock(body: MockStart, session: Session = Depends(get_session)):
    """Replay an already-processed match as a live session (a demo and a UI test bed: no camera needed)."""
    try:
        match = store.load_match(body.match_id, session)
        tracks = store.load_tracks(body.match_id)
    except KeyError:
        raise HTTPException(404, f"match {body.match_id} (with tracks) not found") from None
    log = live_hub.new_session({"mock": True})
    threading.Thread(target=live_mock.replay, args=(log, match, tracks),
                     kwargs={"speed": max(0.1, body.speed), "chunk_seconds": max(1.0, body.chunk_seconds)}, daemon=True).start()
    return {"session_id": log.session_id, "stream": f"/v1/live/sessions/{log.session_id}/stream"}


@router.get("/live/sessions/{session_id}/stream")
async def stream(session_id: str, request: Request, after: int = Query(-1, description="resume after this event id"),
                 last_event_id: str | None = Header(None)):
    """Server-sent events for one session. A reconnecting browser sends Last-Event-ID and gets only what it missed."""
    log = live_hub.get_session(session_id)
    if log is None:
        raise HTTPException(404, "unknown live session")
    start = int(last_event_id) if last_event_id and last_event_id.lstrip("-").isdigit() else after

    async def gen():
        last, idle = start, 0
        while True:
            fresh = log.since(last)
            for ev in fresh:
                last = ev["id"]
                yield f"id: {ev['id']}\ndata: {json.dumps(ev)}\n\n"
            idle = 0 if fresh else idle + 1
            if idle >= 100:                                # heartbeat so proxies keep the connection open
                yield ": keep-alive\n\n"
                idle = 0
            if log.closed and not fresh:
                break
            if await request.is_disconnected():
                break
            await asyncio.sleep(0.15)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/live/sessions/{session_id}")
def session_info(session_id: str):
    log = live_hub.get_session(session_id)
    if log is None:
        raise HTTPException(404, "unknown live session")
    return {"session_id": session_id, "meta": log.meta, "events": len(log.all()), "closed": log.closed}
