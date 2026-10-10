"""Pydantic response models. MatchJSON mirrors the match.json contract (AGENTS.md §11.3).
Keep in sync with web/lib/types.ts. extra='allow' so new pipeline fields never break the API."""
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class _Loose(BaseModel):
    model_config = ConfigDict(extra="allow")


class VideoInfo(_Loose):
    src: str
    overlay: Optional[str] = None
    fps: float
    width: int
    height: int
    duration_s: float
    sha256: Optional[str] = None


class Calibration(_Loose):
    method: str = "auto"
    homography: list[list[float]]
    focal_px: Optional[float] = None
    reprojection_error_px: Optional[float] = None


class PlayerRef(_Loose):
    track_id: int
    player_id: Optional[str] = None
    name: str = ""
    side: Optional[str] = None
    color: Optional[str] = None


class RallyOut(_Loose):
    idx: int
    t_start: float
    t_end: float
    hits: int
    winner_track_id: Optional[int] = None
    end_reason: Optional[str] = None
    confidence: float
    score_after: Optional[str] = None


class EventOut(_Loose):
    id: str
    rally_idx: int
    t: float
    type: str
    track_id: Optional[int] = None
    px: Optional[list[float]] = None
    court: Optional[list[float]] = None
    confidence: float


class DisputeOut(_Loose):
    id: str
    event_id: str
    clip_url: Optional[str] = None
    call: str
    prob: float
    status: str = "open"


class InsightOut(_Loose):
    player_track_id: Optional[int] = None
    text: str
    stat_ids: list[str] = []
    clip_t: list[float] = []


class MatchJSON(_Loose):
    schema_version: str = "1.0"
    match_id: str
    sport: str
    sport_confidence: Optional[float] = None
    video: VideoInfo
    calibration: Calibration
    players: list[PlayerRef]
    tracks_url: Optional[str] = None
    rallies: list[RallyOut]
    events: list[EventOut]
    score: dict[str, Any]
    stats: dict[str, Any]
    disputes: list[DisputeOut] = []
    insights: list[InsightOut] = []


class MatchSummary(BaseModel):
    match_id: str
    title: Optional[str] = None
    sport: str
    status: str = "processed"
    players: list[str] = []
    games: list[list[int]] = []
    winner_track_id: Optional[int] = None
    confirmed_by_human: bool = False
    evidence_level: str = "assisted"
    duration_s: Optional[float] = None
    rallies: int = 0
    sha256: Optional[str] = None
    ball_tracker: Optional[str] = None              # e.g. "racketvision" when the shuttle came from the plug-in


class ScoreConfirm(BaseModel):
    games: list[list[int]]
    winner_track_id: Optional[int] = None


class ReportInsight(BaseModel):
    text: str
    stat_ids: list[str]
    clip_t: list[float]
    player_track_id: Optional[int] = None
    grounded: bool = True


class CoachReport(BaseModel):
    match_id: str
    source: str                     # "pipeline" | "claude" | "template"
    insights: list[ReportInsight]
    note: Optional[str] = None      # why a report is empty, e.g. no player stats yet
