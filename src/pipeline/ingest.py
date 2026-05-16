"""Pipeline d'ingestion : flux du scraper → base SQL Server."""
import json
from datetime import datetime
from sqlalchemy import select, update
from loguru import logger

from ..db import db_session
from ..models import RawPage, ScrapeJob, Adjudication, UpcomingAuction


def start_job(job_type: str, params: dict | None = None) -> int:
    with db_session() as s:
        job = ScrapeJob(
            job_type=job_type,
            params_json=json.dumps(params or {}, ensure_ascii=False),
        )
        s.add(job)
        s.flush()
        return job.id


def finish_job(job_id: int, status: str, pages_fetched: int, pages_failed: int, error: str | None = None):
    with db_session() as s:
        s.execute(
            update(ScrapeJob)
            .where(ScrapeJob.id == job_id)
            .values(
                finished_at=datetime.utcnow(),
                status=status,
                pages_fetched=pages_fetched,
                pages_failed=pages_failed,
                error_message=error,
            )
        )


def save_raw_page(page_type: str, url: str, http_status: int, html: str | None) -> int:
    """Insère une page brute, retourne son ID."""
    with db_session() as s:
        rp = RawPage(
            source="licitor",
            page_type=page_type,
            url=url,
            http_status=http_status,
            html=html,
            parse_status="pending" if http_status < 400 else "skipped",
        )
        s.add(rp)
        s.flush()
        return rp.id


def upsert_adjudication(data: dict) -> str:
    """Insert-or-update sur (source, source_id)."""
    with db_session() as s:
        existing = s.execute(
            select(Adjudication).where(
                Adjudication.source == data["source"],
                Adjudication.source_id == data["source_id"],
            )
        ).scalar_one_or_none()

        # Ne pas écraser avec des None
        clean = {k: v for k, v in data.items() if v is not None and not k.startswith("_")}

        if existing:
            for k, v in clean.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            existing.updated_at = datetime.utcnow()
            return str(existing.id)
        else:
            row = Adjudication(**{k: v for k, v in clean.items() if hasattr(Adjudication, k)})
            s.add(row)
            s.flush()
            return str(row.id)


def upsert_upcoming(data: dict) -> str:
    with db_session() as s:
        existing = s.execute(
            select(UpcomingAuction).where(
                UpcomingAuction.source == data["source"],
                UpcomingAuction.source_id == data["source_id"],
            )
        ).scalar_one_or_none()

        clean = {k: v for k, v in data.items() if v is not None and not k.startswith("_")}

        if existing:
            for k, v in clean.items():
                if hasattr(existing, k):
                    setattr(existing, k, v)
            existing.updated_at = datetime.utcnow()
            return str(existing.id)
        else:
            row = UpcomingAuction(**{k: v for k, v in clean.items() if hasattr(UpcomingAuction, k)})
            s.add(row)
            s.flush()
            return str(row.id)
