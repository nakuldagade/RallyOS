"""FastAPI app. Until the real pipeline exists, GET /v1/matches/{id} serves data/mock/match.json.

    uvicorn api.main:app --reload --port 8000     # docs at http://localhost:8000/docs
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from rallyos import list_sports, load_sport

ROOT = Path(__file__).resolve().parents[1]
MOCK_MATCH = ROOT / "data" / "mock" / "match.json"

app = FastAPI(title="RallyOS API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict:
    return {"ok": True}


@app.get("/v1/sports")
def sports() -> list[dict]:
    return [{"sport": s, "display_name": load_sport(s).get("display_name", s)} for s in list_sports()]


@app.get("/v1/sports/{name}")
def sport(name: str) -> dict:
    try:
        return load_sport(name)
    except KeyError:
        raise HTTPException(404, f"unknown sport {name!r}") from None


@app.get("/v1/matches/{match_id}")
def match(match_id: str) -> dict:
    data = json.loads(MOCK_MATCH.read_text(encoding="utf-8"))
    if match_id != data["match_id"]:
        raise HTTPException(404, f"match {match_id!r} not found")
    return data
