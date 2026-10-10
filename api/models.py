"""SQLModel tables from AGENTS.md §10. Frame-by-frame tracks are NOT here (tracks.json files)."""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


def now_iso() -> str:
    """Timestamps are stored as ISO-8601 UTC strings (portable across SQLModel versions)."""
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _json():
    return Field(default=None, sa_column=Column(JSON))


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(index=True, unique=True)
    name: str = ""
    role: str = "player"  # player | coach | organiser


class Player(SQLModel, table=True):
    id: str = Field(primary_key=True)                 # e.g. "p_anika"
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    name: str = ""
    sport: str = "badminton"
    rating: float = 1500.0                            # Glicko-2 (display scale)
    rd: float = 350.0
    vol: float = 0.06
    style_vec: Optional[list] = _json()               # [attack, defence, net_play, endurance]
    home_venue: Optional[int] = Field(default=None, foreign_key="venue.id")
    lat: Optional[float] = None
    lng: Optional[float] = None


class Venue(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    city: str = ""
    lat: float = 0.0
    lng: float = 0.0


class Court(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    venue_id: int = Field(foreign_key="venue.id")
    sport: str = "badminton"
    calibration_json: Optional[dict] = _json()        # saved venue profile (H, K) -> instant Smart Court
    smart_court: bool = False


class Match(SQLModel, table=True):
    id: str = Field(primary_key=True)                 # "m_001"
    sport: str = "badminton"
    court_id: Optional[int] = Field(default=None, foreign_key="court.id")
    p1: Optional[str] = None
    p2: Optional[str] = None
    p3: Optional[str] = None
    p4: Optional[str] = None
    status: str = "processed"                         # queued | processing | processed | failed
    score_json: Optional[dict] = _json()
    winner_player_id: Optional[str] = None
    evidence_level: str = "assisted"                  # self | assisted | video_verified
    video_url: Optional[str] = None
    sha256: Optional[str] = None
    json_path: Optional[str] = None                   # where the match.json lives
    created_at: str = Field(default_factory=now_iso)


class Rally(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: str = Field(foreign_key="match.id", index=True)
    idx: int
    t_start: float
    t_end: float
    hits: int = 0
    winner: Optional[int] = None                      # track_id
    end_reason: Optional[str] = None
    confidence: float = 0.0


class Event(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ref: str = ""                                     # id inside match.json, e.g. "e_0001"
    rally_id: int = Field(foreign_key="rally.id", index=True)
    t: float
    type: str
    player_id: Optional[str] = None
    track_id: Optional[int] = None
    court_x: Optional[float] = None
    court_y: Optional[float] = None
    speed_kmh: Optional[float] = None
    speed_err: Optional[float] = None
    confidence: float = 0.0
    interpolated: bool = False


class Dispute(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    ref: str = ""                                     # "d_001"
    match_id: str = Field(foreign_key="match.id", index=True)
    event_id: Optional[int] = Field(default=None, foreign_key="event.id")
    clip_url: Optional[str] = None
    call: str = "IN"
    prob: float = 0.5
    status: str = "open"


class Insight(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    match_id: str = Field(foreign_key="match.id", index=True)
    player_id: Optional[str] = None
    text: str
    stat_ids: Optional[list] = _json()
    clip_ts: Optional[list] = _json()


# ---- ecosystem tables ----
class Tournament(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    sport: str = "badminton"
    venue_id: Optional[int] = Field(default=None, foreign_key="venue.id")
    start_date: Optional[str] = None
    status: str = "open"


class Registration(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    player_id: str


class DrawMatch(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tournament_id: int = Field(foreign_key="tournament.id", index=True)
    round: int = 1
    slot: int = 0
    p1: Optional[str] = None
    p2: Optional[str] = None
    match_id: Optional[str] = None


class CoachPlayer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    coach_user_id: int = Field(foreign_key="user.id")
    player_id: str


class Meetup(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    organiser_id: str
    venue_id: Optional[int] = Field(default=None, foreign_key="venue.id")
    sport: str = "badminton"
    when: Optional[str] = None
    note: str = ""


class RatingHistory(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    player_id: str = Field(index=True)
    match_id: Optional[str] = None
    rating: float
    rd: float = 0.0
    evidence_level: str = "assisted"
    at: str = Field(default_factory=now_iso)


class Credential(SQLModel, table=True):
    """A login: kept apart from User so the user table needs no new column on a database that already has it."""
    user_id: int = Field(primary_key=True, foreign_key="user.id")
    password_hash: str = ""
    created_at: str = Field(default_factory=now_iso)
