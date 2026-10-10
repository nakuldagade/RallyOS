"""SQLModel engine, session dependency, create_all()."""
from typing import Iterator

from sqlmodel import Session, SQLModel, create_engine

from api.config import settings

_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, connect_args=_args)


def create_all() -> None:
    from api import models  # noqa: F401  (register tables)
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
