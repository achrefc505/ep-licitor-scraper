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
    postal_code: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    address: Optional[str] = None,
    description: Optional[str] = None,
    floor: Optional[str] = None,
) -> Optional[dict]:
    """Appelle POST /predict de ep-ml-api. Retourne dict réponse ou None si KO.

    Les nouveaux champs postal_code/lat/lng (v2) discriminent fortement les
    prédictions intra-ville (Paris 16e vs 11e, etc.). Toujours les passer
    quand on les a.
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
    if postal_code:
        payload["postal_code"] = str(postal_code)
    if latitude is not None:
        payload["latitude"] = float(latitude)
    if longitude is not None:
        payload["longitude"] = float(longitude)
    if address:
        payload["address"] = address
    if description:
        payload["description"] = description
    if floor:
        payload["floor"] = str(floor)

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
