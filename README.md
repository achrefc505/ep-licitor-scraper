# ep-licitor-scraper

Pipeline de collecte d'adjudications immobilières depuis **licitor.com** vers SQL Server.

> ⚠️ **Avertissement légal** : le scraping de Licitor n'est pas explicitement autorisé par leurs CGU. Ce projet est fourni à des fins **expérimentales/personnelles**. Pour un usage professionnel, contacte Licitor pour un partenariat (`contact@licitor.com`). Tu es responsable de l'utilisation faite de ce code (RGPD, ToS, etc.).

## Stack

- **Python 3.11+**
- **Playwright** — navigateur réel (Chromium headless) pour contourner l'anti-bot
- **SQLAlchemy + pyodbc** — connexion SQL Server LocalDB
- **BeautifulSoup + lxml** — parsing HTML
- **Click** — CLI
- **Loguru** — logs

## Architecture

```
ep-licitor-scraper/
├── db/01_raw_schema.sql      # crée la base EncheresPredict_Raw (4 tables)
├── src/
│   ├── config.py             # settings via .env
│   ├── db.py                 # session SQLAlchemy
│   ├── models.py             # ORM
│   ├── scraper/
│   │   ├── browser.py        # Playwright wrapper
│   │   ├── licitor.py        # logique de scraping (async generators)
│   │   └── parsers.py        # HTML → dict (⚠ sélecteurs à ajuster)
│   ├── pipeline/ingest.py    # upsert vers SQL Server
│   └── cli.py                # commandes
└── logs/                     # logs runtime + dumps HTML
```

**Idée clé** : 2 niveaux de stockage
1. `raw_pages` — HTML brut, traçabilité totale, on peut re-parser sans re-scraper
2. `adjudications` / `upcoming_auctions` — données normalisées prêtes pour l'ETL vers l'app

## Installation (Windows + LocalDB)

### 1. Prérequis
- Python 3.11+ : https://www.python.org/downloads/
- SQL Server LocalDB (déjà installé si tu as Visual Studio ou SQL Server Express)
- ODBC Driver 17 for SQL Server : https://learn.microsoft.com/sql/connect/odbc/

### 2. Créer la base RAW
```powershell
sqlcmd -S "(localdb)\mssqllocaldb" -i db\01_raw_schema.sql
```

### 3. Environnement Python
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Configuration
```powershell
copy .env.example .env
# Édite .env si besoin (par défaut : LocalDB Trusted Connection)
```

## Utilisation

### Inspecter une page (debug sélecteurs)
**Étape obligatoire AVANT le premier scrape** — les sélecteurs CSS dans `parsers.py` sont des **placeholders** basés sur des conventions. Tu dois vérifier qu'ils matchent le vrai HTML.

```powershell
python -m src.cli inspect https://www.licitor.com/historique-des-adjudications.html
```

Sortie :
```
HTTP 200 — 158234 bytes
Title : Historique des adjudications immobilières
Tables : 3
Forms : 2
Articles/items : 25
Premiers liens contenant 'adjudication' :
  - /vente/12345-appartement-paris-11e.html
  - /vente/12346-maison-lyon.html
  ...
HTML dump : logs/inspect_dump.html
```

→ Ouvre `logs/inspect_dump.html` dans un navigateur, inspecte avec F12, et **ajuste les sélecteurs dans `src/scraper/parsers.py`**.

### Lancer un dry-run (sans écrire en DB)
```powershell
python -m src.cli historique --max-pages 1 --dry-run
```

### Scraper l'historique (réel)
```powershell
python -m src.cli historique --max-pages 5
```

### Scraper les ventes à venir
```powershell
python -m src.cli upcoming --max-pages 5
```

### Voir le statut
```powershell
python -m src.cli status
```

## Réglage anti-bot

Si tu prends des 403 même avec Playwright, par ordre d'agressivité :

1. **Augmenter les délais** dans `.env` :
   ```
   SCRAPER_DELAY_MIN=8
   SCRAPER_DELAY_MAX=15
   ```

2. **Désactiver le headless** (un humain "voit" la page) :
   ```
   SCRAPER_HEADLESS=false
   ```

3. **Installer playwright-stealth** (déjà dans requirements.txt, à activer dans `browser.py`) :
   ```python
   from playwright_stealth import stealth_async
   await stealth_async(page)
   ```

4. **Proxies résidentiels** (Bright Data, Oxylabs, ~50€/mois) — dernier recours, à configurer dans `browser.py` via `proxy={"server": "..."}`.

5. **Solver CAPTCHA** (2Captcha, CapMonster) si vraiment nécessaire.

## Workflow complet (vision)

```
[Licitor.com]
    ↓ scraper (ce projet)
[EncheresPredict_Raw] : raw_pages + adjudications + upcoming_auctions
    ↓ ETL (à venir, dans un projet séparé ou job .NET)
[EncheresPredict] (base de l'app) : Auctions enrichies + lawyer_email
    ↓ n8n workflow
[Email avocats → réception PDF → GED NextCloud]
    ↓
[Application Angular] : utilisateurs voient les données prêtes
```

## TODO

- [ ] Inspecter Licitor + ajuster les sélecteurs dans `parsers.py`
- [ ] Ajouter `playwright-stealth` si 403 persistant
- [ ] Implémenter `pipeline/transform.py` : enrichissement géocodage + nettoyage
- [ ] Implémenter `etl/sync_to_app.py` : copie filtrée vers la base `EncheresPredict`
- [ ] Tests unitaires sur les parsers avec fixtures HTML
- [ ] Dockerfile pour exécution containerisée
- [ ] Scheduler (APScheduler) pour cron quotidien

## Licence

MIT — usage à tes risques et périls.
