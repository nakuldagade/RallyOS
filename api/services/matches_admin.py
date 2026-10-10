"""Removing analysed matches: the database rows, and the files that belong to the match.

What goes: the match, its rallies, events, disputes and insights (children first, so the foreign keys are satisfied); the served
copy `media/<id>/`, the pipeline output `demo/out/<id>/`, a human-confirmed score override and the cached coach reports in the
runtime folder, and for a match made by live mode the whole session folder (chunks and per-chunk results).
What stays: the original upload in `media/uploads/` (it may be the only copy of someone's video), the Glicko-2 ratings and rating
history (a rating update is not undone by deleting the match that caused it), and the demo match, which the app links to.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from sqlmodel import Session, delete, select

from api.config import settings
from api.models import Dispute, DrawMatch, Event, Insight, Match, Rally, RatingHistory

PROTECTED = {"m_001"}               # the demo match used by "Open demo match" and the pitch


def _rm(path: Path) -> bool:
    if path.is_dir():
        shutil.rmtree(path, ignore_errors=True)
        return True
    if path.is_file():
        path.unlink(missing_ok=True)
        return True
    return False


def delete_match(session: Session, match_id: str, *, files: bool = True) -> dict:
    """Remove one match. Returns what was removed; raises PermissionError for the protected demo match, KeyError if unknown."""
    if match_id in PROTECTED:
        raise PermissionError("the demo match is protected")
    row = session.get(Match, match_id)
    if row is None:
        raise KeyError(match_id)
    rally_ids = session.exec(select(Rally.id).where(Rally.match_id == match_id)).all()
    counts = {"events": 0, "rallies": len(rally_ids)}
    session.exec(delete(Dispute).where(Dispute.match_id == match_id))
    session.exec(delete(Insight).where(Insight.match_id == match_id))
    if rally_ids:
        counts["events"] = len(session.exec(select(Event.id).where(Event.rally_id.in_(rally_ids))).all())
        session.exec(delete(Event).where(Event.rally_id.in_(rally_ids)))
        session.exec(delete(Rally).where(Rally.match_id == match_id))
    for model in (RatingHistory, DrawMatch):                      # keep these rows, only let go of the reference
        for r in session.exec(select(model).where(model.match_id == match_id)).all():
            r.match_id = None
            session.add(r)
    session.delete(row)
    session.commit()
    removed: list[str] = []
    if files:
        targets = [settings.media_dir / match_id, settings.out_dir / match_id, settings.runtime_dir / f"{match_id}.json",
                   *settings.runtime_dir.glob(f"{match_id}.report.*.json")]
        if match_id.startswith("m_"):
            targets.append(settings.live_dir / f"s_{match_id[2:]}")        # a match made by live mode keeps its session folder
        removed = [str(t) for t in targets if _rm(t)]
    return {"match_id": match_id, **counts, "files_removed": len(removed)}


def delete_matches(session: Session, ids: list[str]) -> dict:
    done, skipped = [], []
    for mid in dict.fromkeys(ids):
        try:
            done.append(delete_match(session, mid))
        except PermissionError as exc:
            skipped.append({"match_id": mid, "reason": str(exc)})
        except KeyError:
            skipped.append({"match_id": mid, "reason": "not found"})
    return {"deleted": done, "skipped": skipped}


def default_named(session: Session) -> list[str]:
    """Ids of matches whose players still carry the pipeline's placeholder names (nobody named them)."""
    from api.services import store

    out = []
    for row in session.exec(select(Match)).all():
        try:
            data = store.load_match(row.id, session)
        except (KeyError, FileNotFoundError):
            continue
        names = [p.get("name") for p in data.get("players", [])]
        if names and all(n in ("Near player", "Far player") for n in names):
            out.append(row.id)
    return out
