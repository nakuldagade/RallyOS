"""Live sessions: an append-only event log per session that SSE clients read from.

One log per session, written by whatever produces results (the mock replayer, or the StreamAnalyzer worker) and read
by any number of SSE clients, each from its own position, so a late or reconnecting browser (Last-Event-ID) gets the
whole story from the start. Thread-safe: producers run in worker threads, readers in the event loop.

The event vocabulary (every event is a JSON object with a "type"):

    session            {session_id, status, sport, chunk_seconds, mode}
    calibration_status {quality: high|check|none, sport, corners_px, precision, method, note}
    chunk_received     {seq, t0, t1}
    chunk_processed    {seq, t0, t1, process_s, lag_s, rtf, frames, dropped_frames, reduced_quality}
    positions          {seq, samples: [{t, players: [{track_id, court, px}], ball: {px, court, conf, interp} | null}]}
    new_events         {seq, events: [...]}                 hits and landings, every one provisional
    rally_closed       {rally: {...}}
    stats              {per_player, match, ball, score, rallies}   running, provisional
    lag                {lag_s, max_lag_s, avg_latency_s}
    finalising         {}
    finalised          {match_id}
    error              {message}

Everything produced while a match is running carries provisional: true until "finalised".
"""
from __future__ import annotations

import threading
import time
import uuid
from typing import Any

MAX_EVENTS = 20000          # a session log never grows without bound


class SessionLog:
    def __init__(self, session_id: str, meta: dict | None = None):
        self.session_id = session_id
        self.meta = dict(meta or {})
        self.created = time.time()
        self._events: list[dict] = []
        self._next_id = 0
        self._lock = threading.Lock()
        self.closed = False

    def emit(self, type_: str, **data: Any) -> int:
        with self._lock:
            ev = {"id": self._next_id, "type": type_, "at": round(time.time(), 3), **data}
            self._next_id += 1
            self._events.append(ev)
            if len(self._events) > MAX_EVENTS:                # keep the newest; ids stay increasing
                del self._events[: len(self._events) - MAX_EVENTS]
            if type_ in ("finalised", "error"):
                self.closed = True
            return ev["id"]

    def since(self, last_id: int) -> list[dict]:
        """Events with id > last_id (last_id = -1 for everything)."""
        with self._lock:
            if not self._events:
                return []
            first = self._events[0]["id"]
            start = max(0, last_id + 1 - first)
            return list(self._events[start:])

    def all(self) -> list[dict]:
        return self.since(-1)


SESSIONS: dict[str, SessionLog] = {}


def new_session(meta: dict | None = None, session_id: str | None = None) -> SessionLog:
    sid = session_id or "s_" + uuid.uuid4().hex[:10]
    log = SessionLog(sid, meta)
    SESSIONS[sid] = log
    return log


def get_session(session_id: str) -> SessionLog | None:
    return SESSIONS.get(session_id)
