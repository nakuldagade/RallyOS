"""Sport YAML integrity and device selection."""

import pytest

from rallyos import get_device, list_sports, load_sport
from rallyos.rules import ENGINES

REQUIRED = ["sport", "court", "net", "projectile", "events", "scoring", "shots", "capture"]


@pytest.mark.parametrize("name", list_sports())
def test_sport_yaml_schema(name):
    cfg = load_sport(name)
    for key in REQUIRED:
        assert key in cfg, f"{name}: missing {key}"
    assert cfg["sport"] == name
    assert cfg["scoring"]["type"] in ENGINES
    assert cfg["projectile"]["size_m"] > 0


@pytest.mark.parametrize("name", list_sports())
def test_court_lines_inside_court(name):
    court = load_sport(name)["court"]
    ids = [line["id"] for line in court["lines"]]
    assert len(ids) == len(set(ids)), f"{name}: duplicate line ids"
    eps = 1e-6
    for line in court["lines"]:
        for x, y in (line["p1"], line["p2"]):
            assert -eps <= x <= court["width"] + eps and -eps <= y <= court["length"] + eps, line
    for fid in court.get("fingerprint_lines", []):
        assert fid in ids


def test_badminton_and_pickleball_differ_on_inner_lines():
    b, p = load_sport("badminton")["court"], load_sport("pickleball")["court"]
    assert abs(b["length"] - p["length"]) < 0.05 and b["width"] == p["width"]
    assert set(b["fingerprint_lines"]).isdisjoint(line["id"] for line in p["lines"])


def test_load_sport_returns_copy():
    load_sport("badminton")["scoring"]["points_to_win"] = 99
    assert load_sport("badminton")["scoring"]["points_to_win"] == 21


def test_unknown_sport():
    with pytest.raises(KeyError):
        load_sport("curling")


def test_device_cpu_and_env(monkeypatch):
    assert get_device("cpu") == "cpu"
    monkeypatch.setenv("RALLYOS_DEVICE", "cpu")
    assert get_device() == "cpu"
    assert get_device("auto") in ("cpu", "cuda")


def test_device_cuda_falls_back(monkeypatch):
    import rallyos.device as dev

    monkeypatch.setattr(dev, "_cuda_available", lambda: False)
    with pytest.warns(RuntimeWarning):
        assert dev.get_device("cuda") == "cpu"
    with pytest.raises(ValueError):
        dev.get_device("tpu")
