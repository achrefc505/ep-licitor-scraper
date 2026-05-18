"""Logique haut-niveau de scraping Licitor."""
import asyncio
import random
from typing import AsyncIterator
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_result
from loguru import logger

from ..config import settings
from .browser import browser_session, fetch_page
from .parsers import (
    parse_historique_list,
    parse_historique_pagination,
    parse_adjudication_detail,
)

# Page de résultats d'adjudications. La racine /historique-des-adjudications.html
# peut afficher des prochaines ventes selon le contexte Licitor.
HISTORIQUE_BASE = (
    "https://www.licitor.com/ventes-aux-encheres-immobilieres/"
    "paris-et-ile-de-france/historique-des-adjudications.html"
)
UPCOMING_BASE = "https://www.licitor.com/ventes-aux-encheres-immobilieres/france.html"


def _is_blocked(result):
    """Tenacity predicate : retry si HTTP 403/429/503."""
    if result is None:
        return True
    status, _ = result
    return status in (403, 429, 503)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_result(_is_blocked),
)
async def fetch_with_retry(context, url: str) -> tuple[int, str]:
    return await fetch_page(context, url)


def _is_ad_url(url: str) -> bool:
    return "/annonce/" in url


async def _scrape_ad_detail(
    context,
    item: dict,
    page_type: str,
    *,
    event_type: str,
    require_adjudicated_price: bool,
) -> AsyncIterator[dict]:
    await asyncio.sleep(
        random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
    )
    try:
        status, html = await fetch_with_retry(context, item["source_url"])
    except Exception as e:
        logger.warning("Détail KO {} : {}", item["source_url"], e)
        return

    yield {
        "_type": "raw_page",
        "page_type": page_type,
        "url": item["source_url"],
        "http_status": status,
        "html": html,
    }

    if status < 400:
        try:
            detail = parse_adjudication_detail(html, item["source_url"])
            for key, value in item.items():
                if key not in detail and key not in {"item_type", "title_preview"}:
                    detail[key] = value
            if require_adjudicated_price and detail.get("adjudicated_price") is None:
                logger.warning(
                    "Annonce ignorée en historique sans prix d'adjudication : {}",
                    item["source_url"],
                )
                return
            yield {"_type": event_type, **detail}
        except Exception as e:
            logger.error("Parse error {} : {}", item["source_url"], e)


async def scrape_historique(max_pages: int | None = None) -> AsyncIterator[dict]:
    """Scrape la liste historique + chaque détail.
    Yield un dict d'adjudication prêt à insérer.
    """
    max_pages = max_pages or settings.scraper_max_pages_per_run

    async with browser_session() as context:
        current_url = HISTORIQUE_BASE
        page_num = 1

        while current_url and page_num <= max_pages:
            logger.info("→ Page liste {} : {}", page_num, current_url)
            try:
                status, html = await fetch_with_retry(context, current_url)
            except Exception as e:
                logger.error("Échec page {} : {}", current_url, e)
                break

            if status >= 400:
                logger.error("HTTP {} sur {} — arrêt", status, current_url)
                break

            # Yield la liste pour insertion (raw)
            yield {
                "_type": "raw_page",
                "page_type": "historique_list",
                "url": current_url,
                "http_status": status,
                "html": html,
            }

            items = parse_historique_list(html)
            for item in items:
                if _is_ad_url(item["source_url"]):
                    async for event in _scrape_ad_detail(
                        context,
                        item,
                        "historique_detail",
                        event_type="adjudication",
                        require_adjudicated_price=True,
                    ):
                        yield event
                    continue

                await asyncio.sleep(
                    random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
                )
                try:
                    s2, h2 = await fetch_with_retry(context, item["source_url"])
                except Exception as e:
                    logger.warning("Audience KO {} : {}", item["source_url"], e)
                    continue

                yield {
                    "_type": "raw_page",
                    "page_type": "historique_list",
                    "url": item["source_url"],
                    "http_status": s2,
                    "html": h2,
                }

                if s2 >= 400:
                    continue

                for ad in parse_historique_list(h2):
                    if not _is_ad_url(ad["source_url"]):
                        continue
                    async for event in _scrape_ad_detail(
                        context,
                        ad,
                        "historique_detail",
                        event_type="adjudication",
                        require_adjudicated_price=True,
                    ):
                        yield event

            # Pagination
            pag = parse_historique_pagination(html)
            current_url = pag.get("next_url")
            page_num += 1

            await asyncio.sleep(
                random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
            )


async def scrape_upcoming(max_pages: int | None = None) -> AsyncIterator[dict]:
    """Scrape les ventes à venir."""
    max_pages = max_pages or settings.scraper_max_pages_per_run

    async with browser_session() as context:
        current_url = UPCOMING_BASE
        page_num = 1

        while current_url and page_num <= max_pages:
            logger.info("→ Page upcoming {} : {}", page_num, current_url)
            try:
                status, html = await fetch_with_retry(context, current_url)
            except Exception as e:
                logger.error("Échec {} : {}", current_url, e)
                break

            if status >= 400:
                logger.error("HTTP {} — arrêt", status)
                break

            yield {
                "_type": "raw_page",
                "page_type": "upcoming_list",
                "url": current_url,
                "http_status": status,
                "html": html,
            }

            items = parse_historique_list(html, archives_only=False)  # mêmes sélecteurs probablement
            for item in items:
                if _is_ad_url(item["source_url"]):
                    async for event in _scrape_ad_detail(
                        context,
                        item,
                        "upcoming_detail",
                        event_type="upcoming",
                        require_adjudicated_price=False,
                    ):
                        yield event
                    continue

                await asyncio.sleep(
                    random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
                )
                try:
                    s2, h2 = await fetch_with_retry(context, item["source_url"])
                except Exception as e:
                    logger.warning("Audience KO {} : {}", item["source_url"], e)
                    continue

                yield {
                    "_type": "raw_page",
                    "page_type": "upcoming_list",
                    "url": item["source_url"],
                    "http_status": s2,
                    "html": h2,
                }

                if s2 >= 400:
                    continue

                for ad in parse_historique_list(h2, archives_only=False):
                    if not _is_ad_url(ad["source_url"]):
                        continue
                    async for event in _scrape_ad_detail(
                        context,
                        ad,
                        "upcoming_detail",
                        event_type="upcoming",
                        require_adjudicated_price=False,
                    ):
                        yield event

            pag = parse_historique_pagination(html)
            current_url = pag.get("next_url")
            page_num += 1
            await asyncio.sleep(
                random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
            )
