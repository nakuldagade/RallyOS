"""/v1/live: continuous capture in 5-second chunks, results pushed over SSE while the match is still being played.

    POST /live/sessions                       create (sport or "auto", optional corners)
    POST /live/sessions/{id}/sign             where and how to upload a chunk (local: this API; Cloudinary: a signature)
    POST /live/sessions/{id}/chunks           upload a chunk file (multipart), idempotent per seq
    POST /live/sessions/{id}/chunks/register  a chunk already stored at a URL: the API downloads it to analyse it
    POST /live/sessions/{id}/corners          corrected court corners: stored chunks are re-run, the session continues
    POST /live/sessions/{id}/stop             end the match: finalise and import it
    GET  /live/sessions/{id}/stream           SSE: every event of the session, resumable with Last-Event-ID
    GET  /live/sessions/{id}[/snapshot]       state, and the provisional match so far
    POST /live/sessions/{id}/resume           rebuild a session from its folder after the server restarted
    POST /live/mock                           replay a processed match as if it were live (no camera)

Routers stay thin; the logic lives in services/live.py and core/rallyos/live.
"""
import asyncio
import json
import threading

from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlmodel import Session

from api.db import get_session
from api.config import settings
from api.services import live as live_service
from api.services import live_hub, live_mock, store
from api.services.storage import get_storage

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
    ls = live_service.get(session_id)
    return {"session_id": session_id, "meta": log.meta, "events": len(log.all()), "closed": log.closed, **(ls.info() if ls else {})}


# -- the real thing: sessions fed by chunks ----------------------------------------------------------------------------

class SessionCreate(BaseModel):
    sport: str = "auto"
    corners: list[list[float]] | None = None          # near-left, near-right, far-right, far-left in video pixels
    names: dict[str, str] | None = None               # {"1": "near player", "2": "far player"}
    chunk_seconds: float | None = None


class ChunkRegister(BaseModel):
    seq: int
    url: str
    t0: float | None = None
    duration: float | None = None
    upload_s: float | None = None


class StopBody(BaseModel):
    last_seq: int | None = None                        # the last chunk the client sent: the worker waits for it


class CornersBody(BaseModel):
    taps: list[list[float]]


def _session(session_id: str) -> "live_service.LiveSession":
    ls = live_service.get(session_id)
    if ls is None:
        raise HTTPException(404, "unknown live session (after a restart, POST /resume brings it back from disk)")
    return ls


def _valid_corners(corners: list | None) -> list | None:
    if corners is None:
        return None
    if len(corners) != 4 or any(len(c) != 2 for c in corners):
        raise HTTPException(400, "corners must be 4 points [[x,y],...]: near-left, near-right, far-right, far-left")
    return [[float(x), float(y)] for x, y in corners]


@router.post("/live/sessions", status_code=201)
def create_session(body: SessionCreate):
    from rallyos.sports import list_sports

    if body.sport not in ("auto", "") and body.sport not in list_sports():
        raise HTTPException(404, f"unknown sport {body.sport!r}; available: {list_sports()}")
    names = {int(k): v.strip()[:40] for k, v in (body.names or {}).items() if k.isdigit() and v.strip()}
    storage = get_storage()
    ls = live_service.LiveSession(sport=body.sport, taps=_valid_corners(body.corners), names=names or None,
                                  chunk_seconds=body.chunk_seconds, storage=storage)
    return {"session_id": ls.id, "chunk_seconds": ls.chunk_seconds, "storage": storage.name,
            "stream": f"/v1/live/sessions/{ls.id}/stream", "sign": f"/v1/live/sessions/{ls.id}/sign",
            "chunks": f"/v1/live/sessions/{ls.id}/chunks", "stop": f"/v1/live/sessions/{ls.id}/stop"}


@router.post("/live/sessions/{session_id}/sign")
def sign(session_id: str, seq: int | None = None):
    ls = _session(session_id)
    return ls.storage.sign(session_id, seq)


@router.post("/live/sessions/{session_id}/chunks")
async def upload_chunk(session_id: str, chunk: UploadFile = File(...), seq: int = Form(...), t0: float | None = Form(None),
                       duration: float | None = Form(None), upload_s: float | None = Form(None)):
    ls = _session(session_id)
    if seq < 0:
        raise HTTPException(400, "seq must be 0 or more")
    if seq in ls.received or seq < ls.next_seq:                       # a retry: do not even store it again
        return {"seq": seq, "duplicate": True}
    data = await chunk.read()
    if not data:
        raise HTTPException(400, "empty chunk")
    if len(data) > live_service.MAX_CHUNK_BYTES:
        raise HTTPException(413, "chunk too large")
    name = chunk.filename or "chunk.webm"
    ext = "." + name.rsplit(".", 1)[-1] if "." in name else ".webm"
    path = ls.storage.save_chunk(session_id, seq, data, ext)
    try:
        return ls.add_chunk(seq, path, t0, duration, upload_s)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


def _download(url: str, dest: Path) -> Path:
    """Fetch a chunk stored elsewhere (Cloudinary) so it can be analysed here. Only hosts on the allow-list."""
    from urllib.parse import urlparse

    import httpx

    u = urlparse(url)
    if u.scheme not in ("https", "http") or u.hostname not in settings.chunk_url_hosts:
        raise HTTPException(400, f"chunk URL host {u.hostname!r} is not allowed (RALLYOS_CHUNK_URL_HOSTS)")
    r = httpx.get(url, timeout=60.0, follow_redirects=False)
    if r.status_code != 200 or not r.content:
        raise HTTPException(502, f"could not fetch the chunk ({r.status_code})")
    if len(r.content) > live_service.MAX_CHUNK_BYTES:
        raise HTTPException(413, "chunk too large")
    dest.write_bytes(r.content)
    return dest


@router.post("/live/sessions/{session_id}/chunks/register")
def register_chunk(session_id: str, body: ChunkRegister):
    ls = _session(session_id)
    if body.seq in ls.received or body.seq < ls.next_seq:
        return {"seq": body.seq, "duplicate": True}
    tail = body.url.split("?")[0].rsplit("/", 1)[-1]
    ext = "." + tail.rsplit(".", 1)[-1] if "." in tail else ".webm"
    path = _download(body.url, ls.storage.chunk_path(session_id, body.seq, ext))
    try:
        return ls.add_chunk(body.seq, path, body.t0, body.duration, body.upload_s)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@router.post("/live/sessions/{session_id}/corners", status_code=202)
def corners(session_id: str, body: CornersBody):
    ls = _session(session_id)
    ls.set_corners(_valid_corners(body.taps))
    return {"accepted": True, "note": "the stored chunks are re-run with these corners; watch for the 'recomputed' event"}


@router.post("/live/sessions/{session_id}/stop", status_code=202)
def stop(session_id: str, body: StopBody | None = None):
    ls = _session(session_id)
    ls.stop(body.last_seq if body else None)
    return {"stopping": True, "stream": f"/v1/live/sessions/{session_id}/stream"}


@router.get("/live/sessions/{session_id}/snapshot")
def snapshot(session_id: str):
    return _session(session_id).snapshot()


@router.post("/live/sessions/{session_id}/resume", status_code=201)
def resume(session_id: str):
    if live_service.get(session_id) is not None:
        return live_service.get(session_id).info()
    try:
        ls = live_service.LiveSession.from_disk(session_id, storage=get_storage())
    except KeyError:
        raise HTTPException(404, "no saved session with this id") from None
    return {"session_id": ls.id, "resuming": True, "stream": f"/v1/live/sessions/{ls.id}/stream"}
