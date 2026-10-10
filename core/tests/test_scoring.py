"""Scoring rules for all six sports (AGENTS.md §20.2)."""

import random

import pytest

from rallyos import list_sports
from rallyos.rules import MatchOver, engine_for

SPORTS = ["badminton", "tennis", "table_tennis", "pickleball", "padel", "squash"]


def tennis_game(engine, side):
    """Side wins a game to love."""
    return engine.play([side] * 4)


# -- generic ----------------------------------------------------------------

def test_all_six_sports_present():
    assert set(SPORTS) <= set(list_sports())


@pytest.mark.parametrize("sport", SPORTS)
@pytest.mark.parametrize("seed", range(5))
def test_random_match_terminates(sport, seed):
    rng = random.Random(seed)
    eng = engine_for(sport, doubles=(sport == "pickleball"))
    for _ in range(5000):
        if eng.finished:
            break
        eng.point(rng.randint(0, 1))
    assert eng.finished and eng.winner in (0, 1)
    with pytest.raises(MatchOver):
        eng.point(0)


@pytest.mark.parametrize("sport", SPORTS)
def test_undo_restores_previous_state(sport):
    eng = engine_for(sport)
    eng.play([0, 1, 1, 0, 0])
    before = eng.snapshot()
    eng.point(1)
    assert eng.undo() == before


def test_invalid_side_rejected():
    with pytest.raises(ValueError):
        engine_for("badminton").point(2)


# -- badminton --------------------------------------------------------------

def test_badminton_game_to_21():
    eng = engine_for("badminton")
    s = eng.play([0] * 21)
    assert s["games"] == [[21, 0]] and s["current"] == [0, 0]


def test_badminton_deuce_needs_two_clear():
    eng = engine_for("badminton")
    eng.play([0, 1] * 20)                 # 20-20
    s = eng.point(0)                      # 21-20: not yet
    assert s["games"] == [] and s["current"] == [21, 20]
    s = eng.point(0)                      # 22-20
    assert s["games"] == [[22, 20]]


def test_badminton_cap_at_30():
    eng = engine_for("badminton")
    eng.play([0, 1] * 29)                 # 29-29
    s = eng.point(1)                      # 29-30: golden point
    assert s["games"] == [[29, 30]]


def test_badminton_winner_serves_and_parity_court():
    eng = engine_for("badminton")
    s = eng.snapshot()
    assert s["server"] == 0 and s["serve_court"] == "right"     # 0-0
    s = eng.point(1)
    assert s["server"] == 1 and s["serve_court"] == "left"      # server on 1 (odd)
    s = eng.point(1)
    assert s["serve_court"] == "right"


def test_badminton_match_best_of_three_and_next_game_server():
    eng = engine_for("badminton")
    eng.play([1] * 21)
    assert eng.server == 1                 # game winner serves first in next game
    eng.play([0] * 21)
    assert not eng.finished
    s = eng.play([0] * 21)
    assert s["finished"] and s["winner"] == 0
    assert s["games"] == [[0, 21], [21, 0], [21, 0]]
    assert s["score_str"] == "0-21, 21-0, 21-0"


# -- tennis -----------------------------------------------------------------

def test_tennis_point_names_and_advantage():
    eng = engine_for("tennis")
    assert eng.point(0)["points_display"] == "15-0"
    eng.play([0, 1, 1, 1, 0])             # 40-40
    assert eng.snapshot()["points_display"] == "40-40"
    assert eng.point(1)["points_display"] == "40-AD"
    assert eng.point(0)["points_display"] == "40-40"   # back to deuce
    eng.play([0, 0])
    assert eng.snapshot()["games"] == [1, 0]


def test_tennis_serve_alternates_by_game():
    eng = engine_for("tennis")
    assert eng.server == 0
    tennis_game(eng, 1)
    assert eng.server == 1
    tennis_game(eng, 1)
    assert eng.server == 0


def test_tennis_set_6_4_and_7_5():
    eng = engine_for("tennis")
    for side in [0, 1] * 4 + [0, 0]:      # 6-4
        tennis_game(eng, side)
    assert eng.snapshot()["sets"] == [[6, 4]]
    for side in [0, 1] * 5 + [1, 1]:      # 5-7
        tennis_game(eng, side)
    assert eng.snapshot()["sets"] == [[6, 4], [5, 7]]


def test_tennis_tiebreak_at_6_6():
    eng = engine_for("tennis")
    for side in [0, 1] * 6:
        tennis_game(eng, side)
    s = eng.snapshot()
    assert s["tiebreak"] and s["games"] == [6, 6]
    # Tiebreak serve: first point A, then B B, A A, B B ...
    tb_first = eng.server
    order = []
    for w in [0, 1] * 5:                  # 5-5
        order.append(eng.server)
        eng.point(w)
    assert order[:5] == [tb_first, 1 - tb_first, 1 - tb_first, tb_first, tb_first]
    eng.play([0, 0])                      # 7-5
    s = eng.snapshot()
    assert s["sets"] == [[7, 6]] and not s["tiebreak"]
    assert s["tiebreak_scores"] == {"0": [7, 5]}
    assert s["score_str"].startswith("7-6(5)")
    assert eng.server == 1 - tb_first     # tiebreak receiver serves first next set


def test_tennis_tiebreak_needs_two_clear():
    eng = engine_for("tennis")
    for side in [0, 1] * 6:
        tennis_game(eng, side)
    eng.play([0, 1] * 6)                  # 6-6 in the tiebreak
    eng.point(0)                          # 7-6
    assert eng.snapshot()["tiebreak"]
    eng.point(0)                          # 8-6
    assert eng.snapshot()["sets"] == [[7, 6]]


def test_tennis_match_two_sets():
    eng = engine_for("tennis")
    for _ in range(12):
        tennis_game(eng, 1)
    s = eng.snapshot()
    assert s["finished"] and s["winner"] == 1 and s["sets"] == [[0, 6], [0, 6]]


def test_tennis_match_tiebreak_variant():
    eng = engine_for("tennis", variant="match_tiebreak")
    for _ in range(6):
        tennis_game(eng, 0)
    for _ in range(6):
        tennis_game(eng, 1)
    s = eng.snapshot()
    assert s["match_tiebreak"] and s["tiebreak"]
    eng.play([0] * 9)
    assert not eng.finished
    s = eng.point(0)                      # 10-0
    assert s["finished"] and s["winner"] == 0 and s["sets"][-1] == [10, 0]


# -- table tennis -----------------------------------------------------------

def test_table_tennis_game_to_11_win_by_2():
    eng = engine_for("table_tennis")
    eng.play([0, 1] * 10)                 # 10-10
    eng.point(0)
    assert eng.snapshot()["games"] == []
    s = eng.point(0)
    assert s["games"] == [[12, 10]]


def test_table_tennis_serve_every_two_then_every_one_at_deuce():
    eng = engine_for("table_tennis")
    servers = []
    for w in [0, 1] * 11:                 # through 11-11
        servers.append(eng.server)
        eng.point(w)
    assert servers[:8] == [0, 0, 1, 1, 0, 0, 1, 1]
    assert servers[20:22] == [0, 1]       # from 10-10: alternate every point


def test_table_tennis_first_server_alternates_by_game_and_best_of_five():
    eng = engine_for("table_tennis")
    eng.play([0] * 11)
    assert eng.server == 1
    eng.play([0] * 11)
    assert eng.server == 0 and not eng.finished
    s = eng.play([0] * 11)
    assert s["finished"] and len(s["games"]) == 3


# -- pickleball -------------------------------------------------------------

def test_pickleball_doubles_starts_0_0_2_and_side_out():
    eng = engine_for("pickleball", doubles=True)
    s = eng.snapshot()
    assert s["call"] == "0-0-2" and s["server"] == 0
    s = eng.point(1)                      # first server loses: immediate side out
    assert s["server"] == 1 and s["server_number"] == 1 and s["current"] == [0, 0]


def test_pickleball_only_server_scores_and_server_rotation():
    eng = engine_for("pickleball", doubles=True)
    eng.point(1)                          # side out -> side 1, server 1
    s = eng.point(1)
    assert s["current"] == [0, 1] and s["call"] == "1-0-1"
    s = eng.point(0)                      # receiving side wins: no point, server 2
    assert s["current"] == [0, 1] and s["server"] == 1 and s["server_number"] == 2
    s = eng.point(0)                      # side out
    assert s["server"] == 0 and s["server_number"] == 1 and s["current"] == [0, 1]


def test_pickleball_singles_side_out_and_game():
    eng = engine_for("pickleball")
    eng.point(1)
    assert eng.server == 1
    eng.play([1] * 11)
    s = eng.snapshot()
    assert s["games"] == [[0, 11]]
    assert s["server"] == 1               # next_game_server: alternate (side 0 served first in game 1)


def test_pickleball_win_by_two():
    eng = engine_for("pickleball")
    for _ in range(10):                   # 10-10 via alternating serve holds
        eng.point(0)
    eng.point(1)                          # side out
    for _ in range(10):
        eng.point(1)
    eng.point(0)                          # side out
    assert eng.snapshot()["current"] == [10, 10]
    eng.point(0)
    assert eng.snapshot()["games"] == []
    eng.point(0)
    assert eng.snapshot()["games"] == [[12, 10]]


def test_pickleball_rally_scoring_variant():
    eng = engine_for("pickleball", variant="rally")
    s = eng.point(1)                      # receiver scores under rally scoring
    assert s["type"] == "rally_point" and s["current"] == [0, 1]


# -- padel ------------------------------------------------------------------

def test_padel_advantage_by_default():
    eng = engine_for("padel")
    eng.play([0, 1] * 3)                  # 40-40
    eng.point(0)
    assert eng.snapshot()["points_display"] == "AD-40"


def test_padel_golden_point_variant():
    eng = engine_for("padel", variant="golden_point")
    eng.play([0, 1] * 3)                  # 40-40
    s = eng.point(1)
    assert s["games"] == [0, 1] and s["points"] == [0, 0]


def test_padel_set_and_tiebreak():
    eng = engine_for("padel")
    for side in [0, 1] * 6:
        eng.play([side] * 4)
    assert eng.snapshot()["tiebreak"]
    eng.play([1] * 7)
    assert eng.snapshot()["sets"] == [[6, 7]]


# -- squash -----------------------------------------------------------------

def test_squash_par_to_11_win_by_2():
    eng = engine_for("squash")
    eng.play([0, 1] * 10)
    eng.point(1)
    assert eng.snapshot()["games"] == []
    assert eng.point(1)["games"] == [[10, 12]]


def test_squash_hand_out_and_best_of_five():
    eng = engine_for("squash")
    assert eng.point(1)["server"] == 1    # receiver wins rally -> hand-out
    eng.undo()
    for _ in range(2):
        eng.play([0] * 11)
    assert not eng.finished
    s = eng.play([0] * 11)
    assert s["finished"] and s["games"] == [[11, 0]] * 3
