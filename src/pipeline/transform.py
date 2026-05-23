"""Mapping Raw → App.

Convertit une `upcoming_auctions` (DB raw scrapée) en dict prêt à insérer
dans la table `dbo.Auctions` de la DB applicative .NET, en enrichissant :

- aiEstimate, confidence, low/high : via appel ML API
- ROI %, Badge : calculés selon la même formule que Domain/RoiScore.cs
- AiAnalysis : pricePerSqm, marketTrend, etc.

Reste agnostique de la DB cible — la couche sync_to_app gère l'insertion.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from loguru import logger

from .ml_client import predict_price


# ---------------------------------------------------------------------------
# Helpers métier (équivalents des Value Objects côté .NET)
# ---------------------------------------------------------------------------
def compute_roi_pct(start_price: float, ai_estimate: float) -> float:
    if not start_price:
        return 0.0
    return round((ai_estimate - start_price) / start_price * 100, 2)


def roi_to_badge(roi_pct: float) -> str:
    """Doit MATCHER la logique de Domain/ValueObjects/RoiScore.cs"""
    if roi_pct >= 30: return "TresBonneAffaire"
    if roi_pct >= 15: return "BonneAffaire"
    if roi_pct >= 0:  return "Neutre"
    return "Risque"


def status_from_date(auction_date) -> str:
    """Active si dans 14 jours, sinon Upcoming."""
    if not auction_date:
        return "Upcoming"
    if isinstance(auction_date, str):
        try:
            auction_date = datetime.fromisoformat(auction_date.replace("Z", ""))
        except ValueError:
            return "Upcoming"
    delta = (auction_date - datetime.utcnow()).days
    return "Active" if 0 <= delta <= 14 else "Upcoming"


def build_title(row) -> str:
    """Génère un titre lisible : 'Appartement T3 — Paris'."""
    parts = []
    if row.property_type:
        parts.append(row.property_type)
    if row.rooms and row.rooms > 0:
        parts.append(f"T{row.rooms}")
    if row.city:
        parts.append(f"— {row.city}")
    return " ".join(parts) or f"Adjudication {row.source_id}"


# ---------------------------------------------------------------------------
# Mapping principal
# ---------------------------------------------------------------------------
def upcoming_to_app(row) -> dict:
    """Transforme une UpcomingAuction (raw) en dict pour la table Auctions de l'app."""
    surface = float(row.surface or 0)
    initial = float(row.initial_price or 0)

    # Appel API ML (peut être None si l'API est down → fallback)
    # v2 : on passe postal_code + lat/lng pour des prédictions intra-ville précises
    pred = predict_price(
        tribunal=row.tribunal or "",
        city=row.city or "",
        region=row.region or "",
        property_type=row.property_type or "Appartement",
        surface=surface,
        rooms=int(row.rooms or 0),
        initial_price=initial,
        auction_date=row.auction_date.isoformat() if row.auction_date else None,
        postal_code=row.postal_code,
        latitude=float(row.latitude) if row.latitude is not None else None,
        longitude=float(row.longitude) if row.longitude is not None else None,
        address=row.address,
        description=row.description,
        floor=row.floor,
    )

    if pred:
        ai_estimate = float(pred["adjudicated_price_predicted"])
        ai_low = float(pred["low_estimate"])
        ai_high = float(pred["high_estimate"])
        confidence = int(pred["confidence"])
        model_version = pred.get("features_version", "v1")
        model_name = pred.get("model_name", "global")
    else:
        # Fallback : estimation grossière initial * 1.3
        logger.warning("Fallback prédiction pour {}", row.source_id)
        ai_estimate = round(initial * 1.30, 2) if initial else 0
        ai_low = round(ai_estimate * 0.85, 2)
        ai_high = round(ai_estimate * 1.15, 2)
        confidence = 50
        model_version = "fallback"
        model_name = "none"

    roi = compute_roi_pct(initial, ai_estimate)
    badge = roi_to_badge(roi)
    status = status_from_date(row.auction_date)

    price_per_sqm = round(ai_estimate / surface, 2) if surface else 0

    return {
        "auction": {
            "source_id": row.source_id,
            "title": build_title(row),
            "tribunal": row.tribunal or "Tribunal inconnu",
            "city": row.city or "Inconnu",
            "region": row.region or "Inconnu",
            "address": row.address or "",
            "surface": int(surface),
            "rooms": int(row.rooms or 0),
            "type": row.property_type or "Appartement",
            "start_price": initial,
            "ai_estimate": ai_estimate,
            "confidence": confidence,
            "roi_value": roi,
            "badge": badge,
            "status": status,
            "auction_date": row.auction_date,
            "description": (row.description or "")[:1900],
        },
        "ai_analysis": {
            "price_per_sqm": price_per_sqm,
            "market_trend": "stable",  # ne nécessite pas la DVF pour le MVP
            "renovation_cost": 0,
            "net_yield": 0,
            "gross_yield": 0,
            "potential_resale_price": ai_high,
            "model_version": model_version,
            "risk_factors": [],
            "strengths": [],
        },
        "raw_meta": {
            "raw_id": str(row.id),
            "source_url": row.source_url,
            "ai_low": ai_low,
            "ai_high": ai_high,
            "ml_model_name": model_name,
        },
    }
