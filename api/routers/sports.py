"""GET/POST /v1/sports. Sport configs live in core/rallyos/sports/*.yaml; adding a sport = adding a YAML."""
import re

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from rallyos import list_sports, load_sport
from rallyos.rules import engine_for
from rallyos.sports import SPORTS_DIR, _load

router = APIRouter(tags=["sports"])
REQUIRED = ("sport", "court", "projectile", "scoring")


class SportIn(BaseModel):
    yaml_text: str


def _out(name: str) -> dict:
    return {**load_sport(name), "yaml": (SPORTS_DIR / f"{name}.yaml").read_text(encoding="utf-8")}


@router.get("/sports")
def sports():
    return [_out(s) for s in list_sports()]


@router.get("/sports/{name}")
def sport(name: str):
    if name not in list_sports():
        raise HTTPException(404, f"unknown sport {name!r}")
    return _out(name)


@router.post("/sports", status_code=201)
def register_sport(body: SportIn):
    try:
        cfg = yaml.safe_load(body.yaml_text)
    except yaml.YAMLError as e:
        raise HTTPException(400, f"invalid YAML: {e}") from None
    if not isinstance(cfg, dict) or any(k not in cfg for k in REQUIRED):
        raise HTTPException(400, f"sport YAML needs keys {list(REQUIRED)}")
    name = str(cfg["sport"])
    if not re.fullmatch(r"[a-z][a-z0-9_]{1,40}", name):
        raise HTTPException(400, "sport name must be lowercase letters, digits, underscores")
    if name in list_sports():
        raise HTTPException(409, f"sport {name!r} already exists")
    try:
        engine_for(cfg)                       # the scoring block must drive the generic engine
    except (KeyError, ValueError, TypeError) as e:
        raise HTTPException(400, f"invalid scoring block: {e}") from None
    (SPORTS_DIR / f"{name}.yaml").write_text(body.yaml_text, encoding="utf-8")
    _load.cache_clear()
    return {"registered": name}
