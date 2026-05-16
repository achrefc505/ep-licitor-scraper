"""Wrapper Playwright avec configuration anti-détection basique.

Licitor utilise un anti-bot (403 sur requêtes simples). Playwright en mode
"navigateur réel" + en-têtes correctement configurés suffit dans la plupart
des cas. Si ça ne passe pas, ajouter playwright-stealth ou proxies résidentiels.
"""
from contextlib import asynccontextmanager
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from loguru import logger

from ..config import settings


@asynccontextmanager
async def browser_session():
    """Démarre Playwright + Chromium + un contexte avec UA/locale/timezone FR."""
    async with async_playwright() as p:
        browser: Browser = await p.chromium.launch(
            headless=settings.scraper_headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )
        context: BrowserContext = await browser.new_context(
            user_agent=settings.scraper_user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="fr-FR",
            timezone_id="Europe/Paris",
            extra_http_headers={
                "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )

        # Patch léger : masque webdriver = true
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
        )

        logger.info("Browser ready (headless={})", settings.scraper_headless)

        try:
            yield context
        finally:
            await context.close()
            await browser.close()


async def fetch_page(context: BrowserContext, url: str) -> tuple[int, str]:
    """Ouvre une page, attend le DOM ready, retourne (status, html).

    Sur 403 / Cloudflare challenge, on retourne le code reçu sans planter.
    """
    page: Page = await context.new_page()
    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=settings.scraper_timeout_ms,
        )
        status = response.status if response else 0
        # Petit délai pour laisser le JS éventuel s'exécuter
        await page.wait_for_timeout(1500)
        html = await page.content()
        logger.debug("GET {} → {}", url, status)
        return status, html
    finally:
        await page.close()
