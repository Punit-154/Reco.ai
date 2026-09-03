from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import get_settings

_engine = None
_session_factory = None


def make_engine(database_url: str | None = None):
    url = database_url or get_settings().sync_database_url()
    return create_engine(url, pool_pre_ping=True)


def _get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        url = settings.sync_database_url()
        _engine = create_engine(url, pool_pre_ping=True)
    return _engine


def _get_session_factory():
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=_get_engine(), autoflush=False, expire_on_commit=False
        )
    return _session_factory


def get_db():
    db = _get_session_factory()()
    try:
        yield db
    finally:
        db.close()
