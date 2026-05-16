"""Tests unitaires des helpers de parsing.
Lance avec : pytest tests/
"""
from datetime import date
from src.scraper.parsers import (
    _parse_price, _parse_surface, _parse_rooms, _parse_date_fr, _parse_postal,
    _extract_source_id,
)


def test_parse_price_simple():
    assert _parse_price("185 000 €") == 185000.0
    assert _parse_price("1.234,56 €") == 1234.56
    assert _parse_price("450000") == 450000.0
    assert _parse_price(None) is None
    assert _parse_price("") is None


def test_parse_surface():
    assert _parse_surface("68 m²") == 68.0
    assert _parse_surface("145,5 m2") == 145.5
    assert _parse_surface("environ 100m²") == 100.0
    assert _parse_surface("pas de surface") is None


def test_parse_rooms():
    assert _parse_rooms("3 pièces") == 3
    assert _parse_rooms("4 pieces principales") == 4
    assert _parse_rooms("studio") is None


def test_parse_date_fr():
    assert _parse_date_fr("12/01/2024") == date(2024, 1, 12)
    assert _parse_date_fr("2024-03-15") == date(2024, 3, 15)
    assert _parse_date_fr("15 mars 2024") == date(2024, 3, 15)
    assert _parse_date_fr("invalide") is None


def test_parse_postal():
    assert _parse_postal("75011 Paris") == ("75011", "Paris")
    assert _parse_postal("69006 Lyon 6e") == ("69006", "Lyon 6e")
    cp, ville = _parse_postal("Paris")
    assert cp is None and ville == "Paris"


def test_extract_source_id():
    assert _extract_source_id("/vente/12345-appartement-paris.html") == "12345-appartement-paris"
    assert _extract_source_id("https://www.licitor.com/vente/99-test.html") == "99-test"
    assert _extract_source_id("") == "unknown"
