"""POST /v1/auth/login, /v1/auth/register, GET /v1/auth/me. Two roles: player and coach."""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from api.db import get_session
from api.models import Credential, Player, User
from api.services import auth
from api.services.access import current_user, player_of

router = APIRouter(tags=["auth"])
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class Login(BaseModel):
    email: str
    password: str
    role: str | None = None            # "player" or "coach": the login page says which door was used


class Register(BaseModel):
    name: str
    email: str
    password: str
    role: str = "player"


def _view(user: User, session: Session) -> dict:
    p = player_of(user, session) if user.role == "player" else None
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role, "player_id": p.id if p else None}


@router.post("/auth/login")
def login(body: Login, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == body.email.strip().lower())).first()
    cred = session.get(Credential, user.id) if user else None
    if not user or not cred or not auth.verify_password(body.password, cred.password_hash):
        raise HTTPException(401, "wrong email or password")
    if body.role and body.role != user.role:
        raise HTTPException(403, f"this is a {user.role} account: use the {user.role} login")
    return {"token": auth.make_token(user.id, user.role), "user": _view(user, session)}


@router.post("/auth/register", status_code=201)
def register(body: Register, session: Session = Depends(get_session)):
    email = body.email.strip().lower()
    if body.role not in ("player", "coach"):
        raise HTTPException(400, "role must be player or coach")
    if not EMAIL.match(email):
        raise HTTPException(400, "that does not look like an email address")
    if len(body.password) < 8:
        raise HTTPException(400, "the password needs at least 8 characters")
    if not body.name.strip():
        raise HTTPException(400, "a name is needed")
    if session.exec(select(User).where(User.email == email)).first():
        raise HTTPException(409, "an account with this email already exists")
    user = User(email=email, name=body.name.strip()[:60], role=body.role)
    session.add(user)
    session.flush()
    session.add(Credential(user_id=user.id, password_hash=auth.hash_password(body.password)))
    if body.role == "player":
        pid = f"p_{auth.slug(user.name)}"
        n = 1
        while session.get(Player, pid):
            n += 1
            pid = f"p_{auth.slug(user.name)}_{n}"
        session.add(Player(id=pid, user_id=user.id, name=user.name))
    session.commit()
    return {"token": auth.make_token(user.id, user.role), "user": _view(user, session)}


@router.get("/auth/me")
def me(user: User = Depends(current_user), session: Session = Depends(get_session)):
    return _view(user, session)
