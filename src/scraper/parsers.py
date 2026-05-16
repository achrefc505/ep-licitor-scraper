"""Parsers HTML → dict structuré.

⚠️  IMPORTANT : les sélecteurs CSS ci-dessous sont des **placeholders** raisonnables
    basés sur des conventions HTML standard. Tu DOIS les ajuster après avoir
    inspecté le vrai HTML de Licitor (script `python -m src.inspect_page <url>`).

Pour chaque type de page (liste historique, détail historique, liste upcoming,
détail upcoming) on retourne un dict ou une liste de dicts compatible avec les
modèles SQLAlchemy.
"""
import re
from datetime import datetime, date
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from loguru import logger


BASE_URL = "https://www.licitor.com"


def _clean(text: str | None) -> str | None:
    if text is None:
        return None
    return re.sub(r"\s+", " ", text).strip() or None


def _parse_price(text: str | None) -> float | None:
    """Extrait un nombre de chaînes type '185 000 €' ou '185.000,00 €'."""
    if not text:
        return None
    # Garde uniquement chiffres / , / .
    cleaned = re.sub(r"[^\d,.\-]", "", text).replace(" ", "")
    if not cleaned:
        return None
    # Heuristique : si présence de , avec . → format français '1.234,56'
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_surface(text: str | None) -> float | None:
    if not text:
        return None
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*m", text)
    return float(m.group(1).replace(",", ".")) if m else None


def _parse_rooms(text: str | None) -> int | None:
    if not text:
        return None
    m = re.search(r"(\d+)\s*pi", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _parse_date_fr(text: str | None) -> date | None:
    if not text:
        return None
    for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    # Variante "12 janvier 2024"
    months_fr = {
        "janvier": 1, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
        "juillet": 7, "août": 8, "septembre": 9, "octobre": 10,
        "novembre": 11, "décembre": 12,
    }
    m = re.match(r"(\d{1,2})\s+([a-zéû]+)\s+(\d{4})", text.strip(), re.IGNORECASE)
    if m:
        d, month_name, y = m.groups()
        mo = months_fr.get(month_name.lower())
        if mo:
            return date(int(y), mo, int(d))
    return None


def _parse_postal(text: str | None) -> tuple[str | None, str | None]:
    """Sépare '75011 Paris' en ('75011', 'Paris')."""
    if not text:
        return None, None
    m = re.match(r"\s*(\d{5})\s+(.+?)\s*$", text)
    if m:
        return m.group(1), m.group(2)
    return None, _clean(text)


# ---------------------------------------------------------------------------
# Liste historique : URL exemple https://www.licitor.com/historique-des-adjudications.html
# Retourne une liste de dict {source_id, source_url, ...champs basiques}
# ---------------------------------------------------------------------------
def parse_historique_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")

    # ⚠️  Sélecteurs à AJUSTER après inspection du vrai HTML.
    # Conventions probables Licitor : table.results, .annonce, .vente-item...
    items: list[dict] = []

    # Tentative 1 : tableau classique
    for row in soup.select("table.results tr, table.adjudications tr, table tr.annonce"):
        link = row.select_one("a[href*='adjudication'], a[href*='/vente/'], a[href*='/annonce/']")
        if not link:
            continue
        href = link.get("href", "")
        url = urljoin(BASE_URL, href)
        source_id = _extract_source_id(href)
        items.append({
            "source": "licitor",
            "source_id": source_id,
            "source_url": url,
            "title_preview": _clean(link.get_text()),
        })

    # Tentative 2 : cartes / annonces
    if not items:
        for card in soup.select("article.annonce, .vente-item, .listing-item, .item-vente"):
            link = card.select_one("a[href*='adjudication'], a[href*='/vente/'], a[href*='/annonce/']")
            if not link:
                continue
            href = link.get("href", "")
            url = urljoin(BASE_URL, href)
            items.append({
                "source": "licitor",
                "source_id": _extract_source_id(href),
                "source_url": url,
                "title_preview": _clean(link.get_text()),
            })

    logger.info("Liste historique : {} items parsés", len(items))
    return items


def parse_historique_pagination(html: str) -> dict:
    """Retourne {current_page, total_pages, next_url}."""
    soup = BeautifulSoup(html, "lxml")
    current = 1
    total = 1
    next_url = None

    # Sélecteurs probables
    pag = soup.select_one(".pagination, nav.pages, ul.pages")
    if pag:
        active = pag.select_one(".active, .current, strong")
        if active and active.get_text(strip=True).isdigit():
            current = int(active.get_text(strip=True))
        nums = [int(a.get_text(strip=True)) for a in pag.select("a, span") if a.get_text(strip=True).isdigit()]
        if nums:
            total = max(nums + [current])
        nxt = pag.select_one("a[rel=next], a.next, a:contains('»')")
        if nxt and nxt.get("href"):
            next_url = urljoin(BASE_URL, nxt["href"])

    return {"current_page": current, "total_pages": total, "next_url": next_url}


# ---------------------------------------------------------------------------
# Détail d'une adjudication
# ---------------------------------------------------------------------------
def parse_adjudication_detail(html: str, source_url: str) -> dict:
    """Parse la page détail d'une adjudication historique passée."""
    soup = BeautifulSoup(html, "lxml")
    data: dict = {
        "source": "licitor",
        "source_id": _extract_source_id(source_url),
        "source_url": source_url,
    }

    # Titre / description
    title = soup.select_one("h1, .titre-annonce, .vente-titre")
    if title:
        data["description"] = _clean(title.get_text())

    # Bloc d'infos clé-valeur — pattern courant : dl/dt/dd ou table.infos
    for dl in soup.select("dl.infos, dl.details, table.infos tr"):
        # dl avec dt/dd
        terms = dl.select("dt")
        defs = dl.select("dd")
        for k, v in zip(terms, defs):
            key = _clean(k.get_text()).lower() if k.get_text() else ""
            val = _clean(v.get_text())
            _map_field(data, key, val)
        # table tr avec th + td
        for tr in dl.select("tr") if hasattr(dl, "select") else []:
            th = tr.select_one("th")
            td = tr.select_one("td")
            if th and td:
                _map_field(data, _clean(th.get_text()).lower(), _clean(td.get_text()))

    # Adresse
    addr = soup.select_one(".adresse, .bien-adresse, [itemprop=address]")
    if addr:
        full = _clean(addr.get_text())
        data["address"] = full
        # Tente d'extraire CP + Ville sur la dernière ligne
        last_line = full.split(",")[-1] if full else None
        cp, ville = _parse_postal(last_line)
        if cp:
            data["postal_code"] = cp
        if ville and not data.get("city"):
            data["city"] = ville

    # Prix
    for el in soup.select(".prix, .price, [class*=prix]"):
        text = _clean(el.get_text()).lower() if el.get_text() else ""
        if "mise" in text or "départ" in text or "initial" in text:
            data["initial_price"] = _parse_price(el.get_text())
        elif "adjug" in text or "final" in text or "vendu" in text:
            data["adjudicated_price"] = _parse_price(el.get_text())

    # Avocat
    lawyer_block = soup.select_one(".avocat, .contact, .lawyer, [class*=avocat]")
    if lawyer_block:
        # Email
        email_link = lawyer_block.select_one("a[href^=mailto]")
        if email_link:
            data["lawyer_email"] = email_link.get("href", "").replace("mailto:", "").strip()
        # Téléphone
        tel_link = lawyer_block.select_one("a[href^=tel]")
        if tel_link:
            data["lawyer_phone"] = tel_link.get("href", "").replace("tel:", "").strip()
        # Nom probable = première ligne
        name_el = lawyer_block.select_one("h2, h3, .nom, strong")
        if name_el:
            data["lawyer_name"] = _clean(name_el.get_text())

    return data


def _map_field(data: dict, key: str, value: str | None):
    """Mappe une clé FR vers une colonne de la table."""
    if not value:
        return
    k = key.lower()
    if "tribunal" in k or "juridiction" in k:
        data["tribunal"] = value
    elif "région" in k or "region" in k:
        data["region"] = value
    elif "ville" in k or "commune" in k:
        data["city"] = value
    elif "type" in k or "nature" in k:
        data["property_type"] = value
    elif "surface" in k:
        data["surface"] = _parse_surface(value)
    elif "pièce" in k or "pieces" in k:
        data["rooms"] = _parse_rooms(value)
    elif "étage" in k or "niveau" in k:
        data["floor"] = value
    elif "mise" in k or "prix de départ" in k:
        data["initial_price"] = _parse_price(value)
    elif "adjug" in k or "vendu" in k or "prix final" in k:
        data["adjudicated_price"] = _parse_price(value)
    elif "date" in k and "adjug" in k:
        data["adjudication_date"] = _parse_date_fr(value)
    elif "date" in k and "vente" in k:
        data["adjudication_date"] = _parse_date_fr(value)


def _extract_source_id(url_or_href: str) -> str:
    """Extrait un identifiant stable depuis l'URL Licitor.
    Ex: /vente/12345-appartement-paris.html → '12345-appartement-paris'
    """
    if not url_or_href:
        return "unknown"
    last = url_or_href.rstrip("/").split("/")[-1]
    return last.replace(".html", "")
