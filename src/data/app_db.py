"""Connexion à la base APPLICATIVE EncheresPredict (lue par le .NET).

On garde 2 sessions séparées dans tout le projet :
- src.db.db_session       → EncheresPredict_Raw  (alimentée par le scraper)
- src.data.app_db.session → EncheresPredict      (alimentée par le sync ETL)
"""
from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session

from ..config import settings


_engine = None
_SessionFactory = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(settings.app_sqlalchemy_url, pool_pre_ping=True, future=True)
    return _engine


def _factory():
    global _SessionFactory
    if _SessionFactory is None:
        _SessionFactory = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionFactory


@contextmanager
def app_session() -> Session:
    s = _factory()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
