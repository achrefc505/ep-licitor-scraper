"""Client HTTP pour ep-ml-api (prédiction prix d'adjudication)."""
from typing import Optional

import httpx
from loguru import logger

from ..config import settings


def predict_price(
    tribunal: str,
    city: str,
    region: Optional[str],
    property_type: str,
    surface: float,
    rooms: int,
    initial_price: float,
    auction_date: Optional[str] = None,
) -> Optional[dict]:
    """Appelle POST /predict de ep-ml-api.
    Retourne le dict réponse ou None si l'API est down.

    Réponse type :
        {
            "adjudicated_price_predicted": 376365.65,
            "low_estimate": 321288.46,
            "high_estimate": 447147.10,
            "confidence": 80,
            "model_used": "tribunal",
            "model_name": "TJ Paris",
            "features_version": "v1",
            "model_metrics": {...}
        }
    """
    payload = {
        "tribunal": tribunal or "Unknown",
        "city": city or "Unknown",
        "region": region or "Unknown",
        "property_type": property_type or "Appartement",
        "surface": max(1.0, float(surface or 1)),
        "rooms": int(rooms or 0),
        "initial_price": max(1.0, float(initial_price or 1)),
    }
    if auction_date:
        payload["adjudication_date"] = auction_date

    try:
        with httpx.Client(timeout=settings.ml_api_timeout) as c:
            r = c.post(f"{settings.ml_api_url}/predict", json=payload)
        if r.status_code != 200:
            logger.warning("ML API HTTP {} : {}", r.status_code, r.text[:200])
            return None
        return r.json()
    except httpx.HTTPError as e:
        logger.warning("ML API injoignable : {}", e)
        return None
