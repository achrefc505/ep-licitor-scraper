"""CLI Click : commandes scrape / status / inspect."""
import asyncio
import sys
from pathlib import Path

import click
from loguru import logger

from .config import settings
from .scraper.licitor import scrape_historique, scrape_upcoming
from .pipeline.ingest import (
    start_job, finish_job, save_raw_page,
    upsert_adjudication, upsert_upcoming,
)


def _setup_logging():
    Path("logs").mkdir(exist_ok=True)
    logger.remove()
    logger.add(sys.stderr, level=settings.log_level)
    logger.add(settings.log_file, level=settings.log_level, rotation="10 MB", retention="7 days")


@click.group()
def cli():
    """ep-licitor-scraper — collecte d'adjudications immobilières."""
    _setup_logging()


@cli.command()
@click.option("--max-pages", type=int, default=None, help="Limite de pages liste à parcourir")
@click.option("--dry-run", is_flag=True, help="Ne pas écrire en DB, juste afficher")
def historique(max_pages: int | None, dry_run: bool):
    """Scrape l'historique des adjudications passées."""
    asyncio.run(_run_historique(max_pages, dry_run))


async def _run_historique(max_pages: int | None, dry_run: bool):
    job_id = None if dry_run else start_job("historique", {"max_pages": max_pages})
    fetched = failed = 0
    err = None
    last_raw_id: int | None = None

    try:
        async for item in scrape_historique(max_pages=max_pages):
            kind = item.get("_type")
            if dry_run:
                logger.info("[dry] {} : {}", kind, item.get("url") or item.get("source_url"))
                continue

            if kind == "raw_page":
                rid = save_raw_page(
                    page_type=item["page_type"],
                    url=item["url"],
                    http_status=item["http_status"],
                    html=item["html"],
                )
                last_raw_id = rid
                fetched += 1
                if item["http_status"] >= 400:
                    failed += 1
            elif kind == "adjudication":
                item["raw_page_id"] = last_raw_id
                aid = upsert_adjudication(item)
                logger.info("✓ adjudication {} : {}", aid, item.get("source_id"))
    except Exception as e:
        err = str(e)
        logger.exception("Job historique fatal")
    finally:
        if job_id:
            finish_job(job_id,
                       status="failed" if err else "success",
                       pages_fetched=fetched, pages_failed=failed, error=err)
        click.echo(f"[done] pages={fetched} failed={failed} error={err or '-'}")


@cli.command()
@click.option("--max-pages", type=int, default=None)
@click.option("--dry-run", is_flag=True)
def upcoming(max_pages: int | None, dry_run: bool):
    """Scrape les ventes à venir."""
    asyncio.run(_run_upcoming(max_pages, dry_run))


async def _run_upcoming(max_pages, dry_run):
    job_id = None if dry_run else start_job("upcoming", {"max_pages": max_pages})
    fetched = failed = 0
    err = None
    last_raw_id: int | None = None
    try:
        async for item in scrape_upcoming(max_pages=max_pages):
            kind = item.get("_type")
            if dry_run:
                logger.info("[dry] {} : {}", kind, item.get("url") or item.get("source_url"))
                continue
            if kind == "raw_page":
                last_raw_id = save_raw_page(
                    page_type=item["page_type"], url=item["url"],
                    http_status=item["http_status"], html=item["html"],
                )
                fetched += 1
                if item["http_status"] >= 400:
                    failed += 1
            elif kind == "upcoming":
                item["raw_page_id"] = last_raw_id
                uid = upsert_upcoming(item)
                logger.info("✓ upcoming {} : {}", uid, item.get("source_id"))
    except Exception as e:
        err = str(e)
        logger.exception("Job upcoming fatal")
    finally:
        if job_id:
            finish_job(job_id,
                       status="failed" if err else "success",
                       pages_fetched=fetched, pages_failed=failed, error=err)
        click.echo(f"[done] pages={fetched} failed={failed} error={err or '-'}")


@cli.command()
def status():
    """Affiche un résumé de la base."""
    from sqlalchemy import select, func
    from .db import db_session
    from .models import Adjudication, UpcomingAuction, RawPage, ScrapeJob

    with db_session() as s:
        adj = s.execute(select(func.count()).select_from(Adjudication)).scalar()
        upc = s.execute(select(func.count()).select_from(UpcomingAuction)).scalar()
        raw = s.execute(select(func.count()).select_from(RawPage)).scalar()
        jobs = s.execute(
            select(ScrapeJob).order_by(ScrapeJob.started_at.desc()).limit(5)
        ).scalars().all()

    click.echo(f"Adjudications historiques : {adj}")
    click.echo(f"Ventes à venir            : {upc}")
    click.echo(f"Pages brutes stockées     : {raw}")
    click.echo("\n5 derniers jobs :")
    for j in jobs:
        click.echo(f"  #{j.id} {j.job_type:12} {j.status:10} pages={j.pages_fetched} failed={j.pages_failed}")


@cli.command()
@click.option("--limit", type=int, default=200, help="Lignes max par table")
@click.option("--min-score", type=float, default=0.3, help="Seuil de fiabilité du géocodage")
def geocode(limit: int, min_score: float):
    """Géocode les adresses (lat/lng) via adresse.data.gouv.fr."""
    from .pipeline.geocode import geocode_all
    result = geocode_all(limit_per_table=limit)
    for table, stats in result.items():
        click.echo(f"{table:20} : {stats}")


@cli.command(name="sync-app")
@click.option("--limit", type=int, default=500, help="Enchères max à syncer par run")
@click.option("--only-after", default=None, help="Date min auction_date (YYYY-MM-DD)")
def sync_app(limit: int, only_after: str | None):
    """Sync EncheresPredict_Raw.upcoming_auctions → EncheresPredict.Auctions (App).

    Enrichit chaque enchère via l'API ML (aiEstimate, confidence, badge),
    puis upsert dans la DB applicative .NET. Idempotent.
    """
    from .pipeline.sync_to_app import sync_upcoming
    stats = sync_upcoming(limit=limit, only_after=only_after)
    click.echo(
        f"[done] inserted={stats['inserted']} updated={stats['updated']} "
        f"skipped={stats['skipped']} errors={stats['errors']}"
    )


@cli.command()
@click.option("--limit", type=int, default=500)
def pipeline(limit: int):
    """Pipeline complet : geocode + sync-app.

    À lancer après chaque run de scraping pour propager les nouvelles données
    vers la base applicative consommée par le frontend.
    """
    from .pipeline.geocode import geocode_all
    from .pipeline.sync_to_app import sync_upcoming

    click.echo("─── Étape 1/2 : géocodage ───")
    geocode_all(limit_per_table=limit)
    click.echo("─── Étape 2/2 : sync vers app ───")
    stats = sync_upcoming(limit=limit)
    click.echo(f"\n[pipeline done] {stats}")


@cli.command()
@click.argument("url")
def inspect(url: str):
    """Télécharge une page et affiche sa structure (debug sélecteurs)."""
    from .scraper.browser import browser_session, fetch_page
    from bs4 import BeautifulSoup

    async def run():
        async with browser_session() as ctx:
            status_code, html = await fetch_page(ctx, url)
            click.echo(f"HTTP {status_code} — {len(html)} bytes")
            if status_code >= 400:
                click.echo("BLOQUÉ — anti-bot probable. Augmente le délai, change l'IP, ou utilise un proxy.")
                return
            soup = BeautifulSoup(html, "lxml")
            click.echo(f"Title : {soup.title.get_text() if soup.title else '?'}")
            click.echo(f"Tables : {len(soup.find_all('table'))}")
            click.echo(f"Forms  : {len(soup.find_all('form'))}")
            click.echo(f"Articles/items : {len(soup.select('article, .annonce, .vente-item, .listing-item'))}")
            click.echo("Premiers liens contenant 'adjudication' / 'vente' :")
            for a in soup.select("a[href*='adjudication'], a[href*='vente']")[:10]:
                click.echo(f"  - {a.get('href')}")
            # Dump le HTML brut pour inspection
            Path("logs/inspect_dump.html").write_text(html, encoding="utf-8")
            click.echo("HTML dump : logs/inspect_dump.html")

    asyncio.run(run())


@cli.command(name="scrape-one")
@click.argument("url")
@click.option("--call-ml", is_flag=True, help="Appelle l'API ML et affiche aussi la prédiction")
@click.option("--ml-url", default=None, help="URL de l'API ML (défaut depuis .env)")
def scrape_one(url: str, call_ml: bool, ml_url: str | None):
    """Scrape une seule annonce Licitor et sort le JSON prêt pour /predict.

    Exemple :
      python -m src.cli scrape-one "https://www.licitor.com/.../jeudi-2-avril-2026.html#107606"
      python -m src.cli scrape-one "https://www.licitor.com/annonce/107606-xxxxx.html" --call-ml
    """
    import json
    from urllib.parse import urlparse, urlunparse
    from .scraper.browser import browser_session, fetch_page
    from .scraper.parsers import parse_adjudication_detail, parse_historique_list

    async def run():
        async with browser_session() as ctx:
            # Si l'URL est une page audience avec ancre #ID, on tente de la résoudre
            # vers l'URL d'annonce directe
            anchor = urlparse(url).fragment
            target_url = url

            status, html = await fetch_page(ctx, url)
            if status >= 400:
                click.secho(f"HTTP {status} — accès bloqué/refusé", fg="red")
                return

            # Si pas une page annonce directe, chercher l'annonce dans la liste
            if "/annonce/" not in url:
                items = parse_historique_list(html, archives_only=False)
                match = None
                for it in items:
                    if anchor and anchor in it.get("source_url", ""):
                        match = it
                        break
                if not match and items:
                    click.echo(f"Pas d'ancre #{anchor} matchée. {len(items)} annonces sur cette page :")
                    for i, it in enumerate(items[:5], 1):
                        click.echo(f"  {i}. {it['source_url']}")
                    click.echo("\nRelance avec une URL d'annonce directe.")
                    return
                if not match:
                    click.secho("Aucune annonce trouvée sur la page", fg="red")
                    return

                target_url = match["source_url"]
                click.echo(f"→ Annonce résolue : {target_url}")
                status, html = await fetch_page(ctx, target_url)
                if status >= 400:
                    click.secho(f"HTTP {status} sur la page annonce", fg="red")
                    return

            # Parse le détail
            parsed = parse_adjudication_detail(html, target_url)

            # Construit le payload /predict
            payload = {
                "tribunal": parsed.get("tribunal") or "TJ Paris",
                "city": parsed.get("city") or "Unknown",
                "region": parsed.get("region"),
                "property_type": parsed.get("property_type") or "Appartement",
                "surface": float(parsed.get("surface") or 0),
                "rooms": int(parsed.get("rooms") or 0),
                "initial_price": float(parsed.get("initial_price") or 0),
            }
            for opt in ("postal_code", "address", "description"):
                if parsed.get(opt):
                    payload[opt] = parsed[opt]
            if parsed.get("adjudication_date"):
                ad = parsed["adjudication_date"]
                payload["adjudication_date"] = ad.isoformat() if hasattr(ad, "isoformat") else str(ad)

            click.echo("")
            click.echo("─── Payload /predict ──────────────────────────")
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

            # Affichage extras utiles pour debug
            extras = {k: v for k, v in parsed.items()
                      if k not in payload and k.startswith(("adjudicated", "lawyer", "source"))}
            if extras:
                click.echo("\n─── Extras (non envoyés à /predict) ───────────")
                click.echo(json.dumps(extras, ensure_ascii=False, indent=2, default=str))

            # Optionnel : appelle l'API ML
            if call_ml:
                import httpx
                from .config import settings
                base = ml_url or settings.ml_api_url
                click.echo(f"\n─── Appel POST {base}/predict ─────────────────")
                try:
                    with httpx.Client(timeout=10) as c:
                        r = c.post(f"{base}/predict", json=payload)
                    if r.status_code == 200:
                        click.secho(json.dumps(r.json(), ensure_ascii=False, indent=2), fg="green")
                    else:
                        click.secho(f"HTTP {r.status_code} : {r.text[:300]}", fg="red")
                except Exception as e:
                    click.secho(f"API ML KO : {e}", fg="red")

    asyncio.run(run())


if __name__ == "__main__":
    cli()
