from contextlib import contextmanager
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from .config import settings

_engine = create_engine(settings.sqlalchemy_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


@contextmanager
def db_session() -> Session:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def get_engine():
    return _engine
