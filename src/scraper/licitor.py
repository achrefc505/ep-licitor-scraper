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

HISTORIQUE_BASE = "https://www.licitor.com/historique-des-adjudications.html"
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


async def scrape_historique(max_pages: int | None = None) -> AsyncIterator[dict]:
    """Scrape la liste historique + chaque détail.
    Yield un dict d'adjudication prêt à insérer.
    """
    max_pages = min(max_pages or settings.scraper_max_pages_per_run,
                    settings.scraper_max_pages_per_run)

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
                # Politesse : délai entre chaque détail
                await asyncio.sleep(
                    random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
                )
                try:
                    s2, h2 = await fetch_with_retry(context, item["source_url"])
                except Exception as e:
                    logger.warning("Détail KO {} : {}", item["source_url"], e)
                    continue

                yield {
                    "_type": "raw_page",
                    "page_type": "historique_detail",
                    "url": item["source_url"],
                    "http_status": s2,
                    "html": h2,
                }

                if s2 < 400:
                    try:
                        detail = parse_adjudication_detail(h2, item["source_url"])
                        yield {"_type": "adjudication", **detail}
                    except Exception as e:
                        logger.error("Parse error {} : {}", item["source_url"], e)

            # Pagination
            pag = parse_historique_pagination(html)
            current_url = pag.get("next_url")
            page_num += 1

            await asyncio.sleep(
                random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
            )


async def scrape_upcoming(max_pages: int | None = None) -> AsyncIterator[dict]:
    """Scrape les ventes à venir."""
    max_pages = min(max_pages or settings.scraper_max_pages_per_run,
                    settings.scraper_max_pages_per_run)

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

            items = parse_historique_list(html)  # mêmes sélecteurs probablement
            for item in items:
                await asyncio.sleep(
                    random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
                )
                try:
                    s2, h2 = await fetch_with_retry(context, item["source_url"])
                except Exception as e:
                    logger.warning("Détail KO {} : {}", item["source_url"], e)
                    continue

                yield {
                    "_type": "raw_page",
                    "page_type": "upcoming_detail",
                    "url": item["source_url"],
                    "http_status": s2,
                    "html": h2,
                }

                if s2 < 400:
                    try:
                        detail = parse_adjudication_detail(h2, item["source_url"])
                        yield {"_type": "upcoming", **detail}
                    except Exception as e:
                        logger.error("Parse error {} : {}", item["source_url"], e)

            pag = parse_historique_pagination(html)
            current_url = pag.get("next_url")
            page_num += 1
            await asyncio.sleep(
                random.uniform(settings.scraper_delay_min, settings.scraper_delay_max)
            )
