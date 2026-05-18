"""Géocodage via api-adresse.data.gouv.fr (BAN — Base Adresse Nationale).

Gratuit, illimité, sans API key, données officielles France.
Doc : https://adresse.data.gouv.fr/api-doc/adresse
"""
import time
from typing import Optional
from urllib.parse import urlencode

import httpx
from loguru import logger
from sqlalchemy import select, update
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings
from ..db import db_session
from ..models import Adjudication, UpcomingAuction


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
def geocode_address(query: str, postal_code: Optional[str] = None) -> Optional[dict]:
    """Renvoie {'lat', 'lng', 'score', 'city', 'postal_code'} ou None.

    L'API BAN attend la requête en `q` + filtre optionnel `postcode`.
    """
    if not query or len(query.strip()) < 3:
        return None

    params = {"q": query.strip()[:200], "limit": 1, "autocomplete": 0}
    if postal_code:
        params["postcode"] = postal_code

    url = f"{settings.geocoder_url}?{urlencode(params)}"

    with httpx.Client(timeout=settings.geocoder_timeout) as client:
        resp = client.get(url)
        if resp.status_code != 200:
            logger.warning("Geocoder HTTP {} pour {!r}", resp.status_code, query)
            return None
        data = resp.json()

    features = data.get("features") or []
    if not features:
        return None

    f = features[0]
    coords = f.get("geometry", {}).get("coordinates", [None, None])
    props = f.get("properties", {})
    return {
        "lng": float(coords[0]) if coords[0] is not None else None,
        "lat": float(coords[1]) if coords[1] is not None else None,
        "score": float(props.get("score") or 0),
        "city": props.get("city"),
        "postal_code": props.get("postcode"),
        "context": props.get("context"),  # ex: "75, Paris, Île-de-France"
    }


def geocode_table(model_cls, limit: int = 200, min_score: float = 0.3) -> dict:
    """Géocode toutes les lignes sans lat/lng pour la table donnée.

    Args:
        model_cls : Adjudication ou UpcomingAuction
        limit : nombre de lignes max par run (politesse + maîtrise du temps)
        min_score : ignore les résultats peu fiables (< 0.3 = bruit)
    """
    table = model_cls.__tablename__
    stats = {"checked": 0, "matched": 0, "skipped": 0, "errors": 0}

    with db_session() as s:
        rows = s.execute(
            select(model_cls)
            .where(model_cls.latitude.is_(None))
            .where(model_cls.address.is_not(None))
            .limit(limit)
        ).scalars().all()

    if not rows:
        logger.info("[{}] Aucune ligne à géocoder", table)
        return stats

    logger.info("[{}] Géocodage de {} lignes...", table, len(rows))

    for row in rows:
        stats["checked"] += 1
        try:
            full_addr = " ".join(
                str(x) for x in [row.address, row.postal_code, row.city] if x
            )
            result = geocode_address(full_addr, postal_code=row.postal_code)

            if result and result.get("score", 0) >= min_score and result.get("lat"):
                with db_session() as s:
                    s.execute(
                        update(model_cls)
                        .where(model_cls.id == row.id)
                        .values(
                            latitude=result["lat"],
                            longitude=result["lng"],
                            # Complète CP/ville si absents et si score >= 0.7
                            postal_code=row.postal_code or (
                                result["postal_code"] if result.get("score", 0) >= 0.7 else None
                            ),
                            city=row.city or (
                                result["city"] if result.get("score", 0) >= 0.7 else None
                            ),
                        )
                    )
                stats["matched"] += 1
            else:
                stats["skipped"] += 1

            time.sleep(0.05)  # politesse — ~20 req/s max
        except Exception as e:
            logger.error("Erreur geocode {} : {}", row.id, e)
            stats["errors"] += 1

    logger.info(
        "[{}] terminé : matched={} skipped={} errors={}",
        table, stats["matched"], stats["skipped"], stats["errors"]
    )
    return stats


def geocode_all(limit_per_table: int = 200) -> dict:
    return {
        "adjudications": geocode_table(Adjudication, limit=limit_per_table),
        "upcoming_auctions": geocode_table(UpcomingAuction, limit=limit_per_table),
    }
