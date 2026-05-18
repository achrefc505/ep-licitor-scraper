"""Sync ETL : EncheresPredict_Raw.upcoming_auctions → EncheresPredict.Auctions.

Idempotent : utilise une colonne SourceId qu'on ajoute à dbo.Auctions de l'app
pour matcher en upsert. Si la colonne n'existe pas, le code la crée au
premier appel (idempotent aussi).

Mapping :
  upcoming_auctions (raw)  ──▶  Auctions (app)
                           └──▶  AiAnalyses (1-1)
"""
import json
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from sqlalchemy import select, text
from sqlalchemy.exc import SQLAlchemyError

from ..db import db_session
from ..data.app_db import app_session
from ..models import UpcomingAuction
from .transform import upcoming_to_app


def ensure_app_schema_extensions():
    """Ajoute les colonnes SourceId et RawId si elles n'existent pas (idempotent).

    Permet de tracer l'origine d'une Auction côté app + upserter sur SourceId.
    """
    with app_session() as s:
        s.execute(text("""
            IF COL_LENGTH('dbo.Auctions', 'SourceId') IS NULL
                ALTER TABLE dbo.Auctions ADD SourceId NVARCHAR(100) NULL;
        """))
        s.execute(text("""
            IF COL_LENGTH('dbo.Auctions', 'RawId') IS NULL
                ALTER TABLE dbo.Auctions ADD RawId NVARCHAR(50) NULL;
        """))
        s.execute(text("""
            IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = 'IX_Auctions_SourceId')
                CREATE UNIQUE INDEX IX_Auctions_SourceId
                ON dbo.Auctions(SourceId) WHERE SourceId IS NOT NULL;
        """))
    logger.info("✓ Schéma app : colonnes SourceId/RawId vérifiées")


def _find_existing(s, source_id: str) -> Optional[str]:
    row = s.execute(
        text("SELECT CAST(Id AS NVARCHAR(50)) AS Id FROM dbo.Auctions WHERE SourceId = :sid"),
        {"sid": source_id},
    ).first()
    return row[0] if row else None


def _upsert_auction(s, mapped: dict) -> str:
    """Insert OR update une Auction selon SourceId. Retourne l'Id (Guid str)."""
    a = mapped["auction"]
    existing_id = _find_existing(s, a["source_id"])

    params = {
        "title": a["title"],
        "tribunal": a["tribunal"],
        "city": a["city"],
        "region": a["region"],
        "address": a["address"],
        "surface": a["surface"],
        "rooms": a["rooms"],
        "type": a["type"],
        "start_price": a["start_price"],
        "ai_estimate": a["ai_estimate"],
        "confidence": a["confidence"],
        "roi_value": a["roi_value"],
        "badge": a["badge"],
        "status": a["status"],
        "auction_date": a["auction_date"],
        "description": a["description"],
        "source_id": a["source_id"],
        "raw_id": mapped["raw_meta"]["raw_id"],
    }

    if existing_id:
        params["id"] = existing_id
        s.execute(text("""
            UPDATE dbo.Auctions SET
                Title=:title, Tribunal=:tribunal, City=:city, Region=:region,
                [Address]=:address, Surface=:surface, Rooms=:rooms, [Type]=:type,
                StartPriceAmount=:start_price, AiEstimateAmount=:ai_estimate,
                Confidence=:confidence, RoiValue=:roi_value,
                Badge=:badge, [Status]=:status, AuctionDate=:auction_date,
                [Description]=:description, RawId=:raw_id
            WHERE Id = :id
        """), params)
        return existing_id
    else:
        new_id = str(uuid.uuid4())
        params["id"] = new_id
        s.execute(text("""
            INSERT INTO dbo.Auctions
                (Id, Title, Tribunal, City, Region, [Address], Surface, Rooms, [Type],
                 StartPriceAmount, AiEstimateAmount, Confidence, RoiValue, Badge, [Status],
                 AuctionDate, [Description], SourceId, RawId, CreatedAt)
            VALUES
                (:id, :title, :tribunal, :city, :region, :address, :surface, :rooms, :type,
                 :start_price, :ai_estimate, :confidence, :roi_value, :badge, :status,
                 :auction_date, :description, :source_id, :raw_id, SYSUTCDATETIME())
        """), params)
        return new_id


def _upsert_ai_analysis(s, auction_id: str, mapped: dict):
    """Insert AiAnalysis si absent, sinon update."""
    ai = mapped["ai_analysis"]
    params = {
        "auction_id": auction_id,
        "price_per_sqm": ai["price_per_sqm"],
        "market_trend": ai["market_trend"],
        "renovation_cost": ai["renovation_cost"],
        "net_yield": ai["net_yield"],
        "gross_yield": ai["gross_yield"],
        "potential_resale_price": ai["potential_resale_price"],
        "risk_factors_json": json.dumps(ai["risk_factors"], ensure_ascii=False),
        "strengths_json": json.dumps(ai["strengths"], ensure_ascii=False),
        "model_version": ai["model_version"],
    }

    exists = s.execute(
        text("SELECT 1 FROM dbo.AiAnalyses WHERE AuctionId = :auction_id"),
        {"auction_id": auction_id},
    ).first()

    if exists:
        s.execute(text("""
            UPDATE dbo.AiAnalyses SET
                PricePerSqm=:price_per_sqm, MarketTrend=:market_trend,
                RenovationCost=:renovation_cost, NetYield=:net_yield, GrossYield=:gross_yield,
                PotentialResalePrice=:potential_resale_price,
                RiskFactorsJson=:risk_factors_json, StrengthsJson=:strengths_json,
                ModelVersion=:model_version, AnalyzedAt=SYSUTCDATETIME()
            WHERE AuctionId=:auction_id
        """), params)
    else:
        params["id"] = str(uuid.uuid4())
        s.execute(text("""
            INSERT INTO dbo.AiAnalyses
                (Id, AuctionId, PricePerSqm, MarketTrend, RenovationCost,
                 NetYield, GrossYield, PotentialResalePrice,
                 RiskFactorsJson, StrengthsJson, ModelVersion, AnalyzedAt, CreatedAt)
            VALUES
                (:id, :auction_id, :price_per_sqm, :market_trend, :renovation_cost,
                 :net_yield, :gross_yield, :potential_resale_price,
                 :risk_factors_json, :strengths_json, :model_version,
                 SYSUTCDATETIME(), SYSUTCDATETIME())
        """), params)


def sync_upcoming(limit: int = 500, only_after: Optional[str] = None) -> dict:
    """Sync `upcoming_auctions` (raw) → `Auctions` + `AiAnalyses` (app).

    Args:
        limit : max de lignes à traiter par run
        only_after : ne traite que les enchères avec auction_date >= 'YYYY-MM-DD'

    Returns:
        {"inserted": N, "updated": N, "errors": N}
    """
    ensure_app_schema_extensions()
    stats = {"inserted": 0, "updated": 0, "errors": 0, "skipped": 0}

    with db_session() as raw_s:
        q = select(UpcomingAuction)
        if only_after:
            q = q.where(UpcomingAuction.auction_date >= only_after)
        q = q.order_by(UpcomingAuction.auction_date.asc()).limit(limit)
        rows = raw_s.execute(q).scalars().all()

    if not rows:
        logger.info("Aucune upcoming_auction à syncer")
        return stats

    logger.info("Sync de {} upcoming → app...", len(rows))

    for row in rows:
        if not row.initial_price or row.initial_price <= 0:
            stats["skipped"] += 1
            continue

        try:
            mapped = upcoming_to_app(row)
            with app_session() as app_s:
                existed = _find_existing(app_s, mapped["auction"]["source_id"]) is not None
                auction_id = _upsert_auction(app_s, mapped)
                _upsert_ai_analysis(app_s, auction_id, mapped)
            stats["updated" if existed else "inserted"] += 1
            logger.info(
                "✓ {} {} : ROI={}% Badge={}",
                "MAJ" if existed else "NEW",
                mapped["auction"]["title"][:60],
                mapped["auction"]["roi_value"],
                mapped["auction"]["badge"],
            )
        except SQLAlchemyError as e:
            stats["errors"] += 1
            logger.error("SQL erreur pour {} : {}", row.source_id, e)
        except Exception as e:
            stats["errors"] += 1
            logger.exception("Erreur sync {} : {}", row.source_id, e)

    logger.info(
        "Sync terminé : inserted={} updated={} skipped={} errors={}",
        stats["inserted"], stats["updated"], stats["skipped"], stats["errors"],
    )
    return stats
