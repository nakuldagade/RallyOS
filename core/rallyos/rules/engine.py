"""Generic scoring state machine driven by the `scoring:` block of a sport YAML.

No `if sport == ...` branches: three scoring families cover all six sports, and every
number (points to win, cap, serve rotation, tiebreaks) comes from the config.

  rally_point  every rally scores                    badminton, table tennis, squash (PAR), pickleball rally variant
  side_out     only the serving side scores          pickleball (traditional)
  game_set     points -> games -> sets, deuce, tiebreaks   tennis, padel

Sides are 0 and 1. Feed rally winners with `engine.point(side)`; `undo()` supports
human correction (POST /matches/{id}/score/confirm).
"""

from __future__ import annotations

from rallyos.sports import load_sport


class MatchOver(Exception):
    """Raised when a point is added after the match has been decided."""


class _Engine:
    type = ""

    def __init__(self, cfg: dict, *, doubles: bool = False, first_server: int = 0):
        if first_server not in (0, 1):
            raise ValueError("first_server must be 0 or 1")
        self.cfg = cfg
        self.doubles = doubles
        self.first_server = first_server
        self.rallies: list[int] = []
        self._reset()

    # -- public API ---------------------------------------------------------
    @property
    def finished(self) -> bool:
        return self.winner is not None

    def point(self, winner: int) -> dict:
        if winner not in (0, 1):
            raise ValueError("winner must be side 0 or 1")
        if self.finished:
            raise MatchOver(f"match already won by side {self.winner}")
        self.rallies.append(winner)
        self._apply(winner)
        return self.snapshot()

    def play(self, winners) -> dict:
        for w in winners:
            self.point(w)
        return self.snapshot()

    def undo(self) -> dict:
        history = self.rallies[:-1]
        self.rallies = []
        self._reset()
        return self.play(history)

    def snapshot(self) -> dict:
        return {"type": self.type, "server": self.server, "finished": self.finished,
                "winner": self.winner, "score_str": self.score_str(), **self._state()}

    # -- per-family hooks ---------------------------------------------------
    def _reset(self) -> None:
        raise NotImplementedError

    def _apply(self, winner: int) -> None:
        raise NotImplementedError

    def _state(self) -> dict:
        raise NotImplementedError

    def score_str(self) -> str:
        raise NotImplementedError

    @property
    def server(self) -> int:
        raise NotImplementedError

    # -- shared helpers -----------------------------------------------------
    @staticmethod
    def _units_won(units: list[tuple[int, int]], side: int) -> int:
        return sum(1 for u in units if (u[0] > u[1]) == (side == 0))

    def _next_game_first_server(self, game_winner: int, prev_first: int) -> int:
        rule = self.cfg.get("next_game_server", "winner")
        if rule == "winner":
            return game_winner
        if rule == "alternate":
            return 1 - prev_first
        raise ValueError(f"unknown next_game_server {rule!r}")


class _PointsGameEngine(_Engine):
    """Shared game/match bookkeeping for families scored in plain points per game."""

    def _reset(self) -> None:
        self.games: list[tuple[int, int]] = []
        self.pts = [0, 0]
        self.game_first_server = self.first_server
        self.winner: int | None = None

    def _game_won(self, side: int) -> bool:
        p, o = self.pts[side], self.pts[1 - side]
        cap = self.cfg.get("cap")
        if cap and p >= cap:
            return True
        return p >= self.cfg["points_to_win"] and p - o >= self.cfg.get("win_by", 2)

    def _close_game(self, side: int) -> bool:
        """Record a won game; returns True if a new game starts."""
        self.games.append((self.pts[0], self.pts[1]))
        self.pts = [0, 0]
        if self._units_won(self.games, side) >= self.cfg["games_to_win"]:
            self.winner = side
            return False
        self.game_first_server = self._next_game_first_server(side, self.game_first_server)
        return True

    def _state(self) -> dict:
        return {"games": [list(g) for g in self.games], "current": list(self.pts)}

    def score_str(self) -> str:
        parts = [f"{a}-{b}" for a, b in self.games]
        if not self.finished:
            parts.append(f"{self.pts[0]}-{self.pts[1]}")
        return ", ".join(parts)


class RallyPointEngine(_PointsGameEngine):
    type = "rally_point"

    def _reset(self) -> None:
        super()._reset()
        self._server = self.first_server

    def _apply(self, w: int) -> None:
        self.pts[w] += 1
        if self._game_won(w):
            if self._close_game(w):
                self._server = self.game_first_server
            return
        if self.cfg.get("serve_rule", "winner_serves") == "winner_serves":
            self._server = w
        else:
            self._server = self._alternate_server()

    def _alternate_server(self) -> int:
        every = self.cfg.get("serve_every", 2)
        deuce_every = self.cfg.get("deuce_serve_every", every)
        n = sum(self.pts)
        deuce_at = 2 * (self.cfg["points_to_win"] - 1)
        if n < deuce_at:
            changes = n // every
        else:
            changes = deuce_at // every + (n - deuce_at) // deuce_every
        return self.game_first_server ^ (changes % 2)

    @property
    def server(self) -> int:
        return self._server

    def _state(self) -> dict:
        state = super()._state()
        if self.cfg.get("serve_court_by_parity") and not self.finished:
            state["serve_court"] = "right" if self.pts[self._server] % 2 == 0 else "left"
        return state


class SideOutEngine(_PointsGameEngine):
    """Only the serving side scores. Doubles: two servers per side, first side of a game gets one."""

    type = "side_out"

    def _reset(self) -> None:
        super()._reset()
        self._start_game(self.first_server)

    def _start_game(self, server: int) -> None:
        self._server = server
        self.server_number = self.cfg.get("first_server_number", 2) if self.doubles else 1

    def _apply(self, w: int) -> None:
        if w == self._server:
            self.pts[w] += 1
            if self._game_won(w) and self._close_game(w):
                self._start_game(self.game_first_server)
        elif self.doubles and self.server_number == 1:
            self.server_number = 2
        else:  # side out
            self._server = 1 - self._server
            self.server_number = 1

    @property
    def server(self) -> int:
        return self._server

    def _state(self) -> dict:
        state = super()._state()
        state["server_number"] = self.server_number if self.doubles else None
        s, r = self.pts[self._server], self.pts[1 - self._server]
        state["call"] = f"{s}-{r}-{self.server_number}" if self.doubles else f"{s}-{r}"
        return state


_TENNIS_POINTS = ("0", "15", "30", "40")


class GameSetEngine(_Engine):
    type = "game_set"

    def _reset(self) -> None:
        self.sets: list[tuple[int, int]] = []
        self.tiebreak_scores: dict[int, tuple[int, int]] = {}   # set index -> tiebreak points
        self.games = [0, 0]
        self.pts = [0, 0]
        self.tiebreak = False
        self.match_tiebreak = False
        self.game_server = self.first_server   # whose turn it is to serve the current game
        self.winner: int | None = None

    @property
    def _final_set(self) -> dict:
        return self.cfg.get("final_set") or {"type": "tiebreak"}

    def _in_final_set(self) -> bool:
        need = self.cfg["sets_to_win"] - 1
        return self._units_won(self.sets, 0) == need and self._units_won(self.sets, 1) == need

    def _tiebreak_target(self) -> int:
        if self.match_tiebreak or self._in_final_set():
            return self._final_set.get("points", self.cfg.get("tiebreak_points", 7))
        return self.cfg.get("tiebreak_points", 7)

    def _apply(self, w: int) -> None:
        self.pts[w] += 1
        p, o = self.pts[w], self.pts[1 - w]
        if self.tiebreak:
            if p >= self._tiebreak_target() and p - o >= 2:
                self._win_game(w)
        elif self.cfg.get("deuce", "advantage") == "golden_point":
            if p >= 4:
                self._win_game(w)
        elif p >= 4 and p - o >= 2:
            self._win_game(w)

    def _win_game(self, w: int) -> None:
        was_tiebreak, tb_pts = self.tiebreak, (self.pts[0], self.pts[1])
        self.pts = [0, 0]
        self.game_server = 1 - self.game_server   # a tiebreak counts as one game for serve rotation
        if self.match_tiebreak:
            self.sets.append(tb_pts)
            self._end_set(w)
            return
        self.games[w] += 1
        g, og = self.games[w], self.games[1 - w]
        if was_tiebreak:
            self.tiebreak_scores[len(self.sets)] = tb_pts
            self._end_set(w)
        elif g >= self.cfg["games_per_set"] and g - og >= 2:
            self._end_set(w)
        elif self.games == [self.cfg["tiebreak_at"]] * 2:
            if not (self._in_final_set() and self._final_set["type"] == "advantage"):
                self.tiebreak = True

    def _end_set(self, w: int) -> None:
        if not self.match_tiebreak:
            self.sets.append((self.games[0], self.games[1]))
        self.games = [0, 0]
        self.tiebreak = False
        self.match_tiebreak = False
        if self._units_won(self.sets, w) >= self.cfg["sets_to_win"]:
            self.winner = w
        elif self._in_final_set() and self._final_set["type"] == "match_tiebreak":
            self.tiebreak = self.match_tiebreak = True

    @property
    def server(self) -> int:
        if not self.tiebreak:
            return self.game_server
        n = sum(self.pts)   # tiebreak: first point by game_server, then two each
        return self.game_server if ((n + 1) // 2) % 2 == 0 else 1 - self.game_server

    def points_display(self) -> str:
        a, b = self.pts
        if self.tiebreak:
            return f"{a}-{b}"
        if a >= 3 and b >= 3:
            return "40-40" if a == b else ("AD-40" if a > b else "40-AD")
        return f"{_TENNIS_POINTS[a]}-{_TENNIS_POINTS[b]}"

    def _state(self) -> dict:
        return {"sets": [list(s) for s in self.sets], "games": list(self.games),
                "points": list(self.pts), "points_display": self.points_display(),
                "tiebreak": self.tiebreak, "match_tiebreak": self.match_tiebreak,
                "tiebreak_scores": {str(k): list(v) for k, v in self.tiebreak_scores.items()}}

    def score_str(self) -> str:
        parts = []
        for i, (a, b) in enumerate(self.sets):
            tb = self.tiebreak_scores.get(i)
            parts.append(f"{a}-{b}" + (f"({min(tb)})" if tb else ""))
        if not self.finished:
            if not self.match_tiebreak:
                parts.append(f"{self.games[0]}-{self.games[1]}")
            parts.append(f"[{self.points_display()}]")
        return " ".join(parts)


ENGINES: dict[str, type[_Engine]] = {e.type: e for e in (RallyPointEngine, SideOutEngine, GameSetEngine)}


def scoring_config(sport: str | dict, variant: str | None = None) -> dict:
    """The `scoring:` block for a sport name (or a full sport dict), with an optional variant merged in."""
    cfg = load_sport(sport) if isinstance(sport, str) else sport
    scoring = dict(cfg["scoring"])
    variants = scoring.pop("variants", {}) or {}
    if variant:
        if variant not in variants:
            raise KeyError(f"unknown variant {variant!r}; available: {sorted(variants)}")
        scoring.update(variants[variant])
    return scoring


def engine_for(sport: str | dict, *, variant: str | None = None, doubles: bool = False,
               first_server: int = 0) -> _Engine:
    """Build the scoring engine for a sport, e.g. engine_for("badminton") or engine_for("pickleball", doubles=True)."""
    scoring = scoring_config(sport, variant)
    try:
        cls = ENGINES[scoring["type"]]
    except KeyError:
        raise ValueError(f"unknown scoring type {scoring.get('type')!r}") from None
    return cls(scoring, doubles=doubles, first_server=first_server)
