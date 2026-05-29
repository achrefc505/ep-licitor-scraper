import uuid
from datetime import datetime, date
from sqlalchemy import (
    Column, BigInteger, Integer, String, DateTime, Date, Text, Boolean,
    Numeric, ForeignKey
)
from sqlalchemy.dialects.mssql import UNIQUEIDENTIFIER
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class RawPage(Base):
    __tablename__ = "raw_pages"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    source = Column(String(50), nullable=False)
    page_type = Column(String(50), nullable=False)
    url = Column(String(800), nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    http_status = Column(Integer, nullable=False)
    html = Column(Text, nullable=True)
    parse_status = Column(String(20), default="pending", nullable=False)
    parse_error = Column(Text, nullable=True)
    parsed_at = Column(DateTime, nullable=True)


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    job_type = Column(String(50), nullable=False)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at = Column(DateTime, nullable=True)
    status = Column(String(20), default="running", nullable=False)
    pages_fetched = Column(Integer, default=0, nullable=False)
    pages_failed = Column(Integer, default=0, nullable=False)
    error_message = Column(Text, nullable=True)
    params_json = Column(Text, nullable=True)


class Adjudication(Base):
    __tablename__ = "adjudications"

    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    source = Column(String(50), nullable=False)
    source_id = Column(String(100), nullable=False)
    source_url = Column(String(800), nullable=True)
    raw_page_id = Column(BigInteger, ForeignKey("raw_pages.id"), nullable=True)

    tribunal = Column(String(150), nullable=True)
    region = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    postal_code = Column(String(10), nullable=True)
    address = Column(String(500), nullable=True)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)

    property_type = Column(String(80), nullable=True)
    surface = Column(Numeric(10, 2), nullable=True)
    rooms = Column(Integer, nullable=True)
    floor = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)

    initial_price = Column(Numeric(18, 2), nullable=True)
    adjudicated_price = Column(Numeric(18, 2), nullable=True)
    currency = Column(String(3), default="EUR", nullable=False)

    adjudication_date = Column(Date, nullable=True)
    published_at = Column(Date, nullable=True)

    lawyer_name = Column(String(200), nullable=True)
    lawyer_email = Column(String(200), nullable=True)
    lawyer_phone = Column(String(50), nullable=True)
    lawyer_office = Column(String(200), nullable=True)

    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class UpcomingAuction(Base):
    __tablename__ = "upcoming_auctions"

    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    source = Column(String(50), nullable=False)
    source_id = Column(String(100), nullable=False)
    source_url = Column(String(800), nullable=True)
    raw_page_id = Column(BigInteger, ForeignKey("raw_pages.id"), nullable=True)

    tribunal = Column(String(150), nullable=True)
    region = Column(String(100), nullable=True)
    city = Column(String(100), nullable=True)
    postal_code = Column(String(10), nullable=True)
    address = Column(String(500), nullable=True)
    latitude = Column(Numeric(9, 6), nullable=True)
    longitude = Column(Numeric(9, 6), nullable=True)

    property_type = Column(String(80), nullable=True)
    surface = Column(Numeric(10, 2), nullable=True)
    rooms = Column(Integer, nullable=True)
    floor = Column(String(50), nullable=True)
    description = Column(Text, nullable=True)

    initial_price = Column(Numeric(18, 2), nullable=True)
    currency = Column(String(3), default="EUR", nullable=False)

    auction_date = Column(DateTime, nullable=True)
    deposit_required = Column(Numeric(18, 2), nullable=True)
    first_visit_date = Column(Date, nullable=True)
    second_visit_date = Column(Date, nullable=True)

    lawyer_name = Column(String(200), nullable=True)
    lawyer_email = Column(String(200), nullable=True)
    lawyer_phone = Column(String(50), nullable=True)
    lawyer_office = Column(String(200), nullable=True)

    documents_requested = Column(Boolean, default=False, nullable=False)
    documents_received = Column(Boolean, default=False, nullable=False)
    last_contact_at = Column(DateTime, nullable=True)

    scraped_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class DocumentSummary(Base):
    __tablename__ = "document_summaries"

    id = Column(UNIQUEIDENTIFIER, primary_key=True, default=uuid.uuid4)
    auction_id = Column(String(36), nullable=False, index=True)
    summary_json = Column(Text, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    model_version = Column(String(50), nullable=True)
    pdf_url = Column(String(800), nullable=True)
