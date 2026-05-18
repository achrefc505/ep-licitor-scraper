# 🚀 Playbook — Lancer EncheresPredict en local avec vraies données

> Tu as scrapé les données Paris ? Suis ces étapes pour les voir dans ton frontend.

## Structure attendue

```
C:\Users\a.chamekh\source\repos\
├── encherespredict\              # frontend Angular
├── encherespredict-backend\      # backend .NET 8 (a.k.a. EncheresPredict)
├── ep-licitor-scraper\           # scraper + ETL (TU ES ICI)
├── ep-ml-api\                    # API ML Python
└── ep-workflow\                  # n8n + NextCloud (optionnel)
```

## Étape par étape

### ✅ 1. Vérifier ce qui est déjà scrapé

```powershell
cd ep-licitor-scraper
.\.venv\Scripts\activate
python -m src.cli status
```

Tu dois voir :
```
Adjudications historiques : X
Ventes à venir            : Y
Pages brutes stockées     : Z
```

Si `Ventes à venir = 0` mais que tu n'as scrapé QUE l'historique, c'est normal — le sync ETL transforme `upcoming_auctions`, pas `adjudications`. Pour avoir des enchères affichées dans le frontend, il faut aussi scraper les prochaines ventes :

```powershell
python -m src.cli upcoming --max-pages 5
```

### ✅ 2. Démarrer l'API ML (terminal #1)

```powershell
cd ..\ep-ml-api
.\.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env

# A. Première fois : entraîner sur synthétique
python -m src.training.bootstrap
python -m src.training.train

# B. Si tu as >= 50 adjudications scrapées :
#    Mets DATA_SOURCE=sql dans .env puis :
# python -m src.training.train

# Démarrer l'API (laisser le terminal ouvert)
uvicorn src.api.main:app --reload --port 8000
```

→ http://localhost:8000/docs doit afficher Swagger.

### ✅ 3. Patcher la DB applicative (1 fois)

```powershell
# Depuis ep-workflow (ajoute StoragePath/ExternalRef à Documents)
sqlcmd -S "(localdb)\mssqllocaldb" -i ..\ep-workflow\db\03_documents_schema_patch.sql

# Note : le sync ETL ajoutera automatiquement SourceId / RawId à dbo.Auctions
#         lors du premier run, pas besoin de SQL manuel.
```

### ✅ 4. Lancer le pipeline ETL (terminal #2)

```powershell
cd ..\ep-licitor-scraper
.\scripts\bootstrap-local.ps1
```

Le script :
- Vérifie les bases SQL
- Affiche le compteur
- Lance `geocode` puis `sync-app`
- Montre le top 5 ROI à la fin

Ou manuellement :
```powershell
python -m src.cli pipeline --limit 500
```

### ✅ 5. Démarrer le backend .NET (terminal #3) — IMPORTANT : skip seed mock

```powershell
cd ..\encherespredict-backend
$env:EP_SKIP_SEED='true'      # ← CRITIQUE : sinon les 20 mocks reviennent

dotnet ef database update --project EncheresPredict.Infrastructure --startup-project EncheresPredict.Api
dotnet run --project EncheresPredict.Api
```

→ https://localhost:7001/swagger doit afficher l'API.

> Si tu lances sans `EP_SKIP_SEED=true` et que la table est vide, les 20 mocks seront ré-insérés. Pour les supprimer :
> ```sql
> USE EncheresPredict;
> DELETE FROM dbo.AiAnalyses WHERE AuctionId IN (SELECT Id FROM dbo.Auctions WHERE SourceId IS NULL);
> DELETE FROM dbo.Documents  WHERE AuctionId IN (SELECT Id FROM dbo.Auctions WHERE SourceId IS NULL);
> DELETE FROM dbo.Alerts     WHERE AuctionId IN (SELECT Id FROM dbo.Auctions WHERE SourceId IS NULL);
> DELETE FROM dbo.Auctions   WHERE SourceId IS NULL;
> ```

### ✅ 6. Démarrer le frontend (terminal #4)

```powershell
cd ..\encherespredict
npm install
npm start
```

→ http://localhost:4200 → Dashboard avec **tes vraies enchères Paris**.

## 🛠️ Troubleshooting

### "L'API ML est introuvable" dans les logs du sync
- Vérifie que `uvicorn` tourne sur le port 8000
- Vérifie `ML_API_URL` dans `ep-licitor-scraper/.env`
- Si tu veux skipper l'ML temporairement : laisse-la éteinte, le sync utilisera le fallback `aiEstimate = startPrice × 1.3`

### "Cannot open database EncheresPredict"
- Démarrer LocalDB : `sqllocaldb start mssqllocaldb`
- Vérifier que les migrations .NET ont créé la base : `dotnet ef database update`

### Le frontend affiche encore les 20 mocks
- Tu n'as pas mis `EP_SKIP_SEED=true` avant le `dotnet run`
- Ou tu ne les as pas supprimés manuellement (voir SQL ci-dessus)

### "Pas assez de données ML"
- Le bootstrap synthétique génère 5000 lignes → utilise-le en attendant que tu aies scrapé beaucoup
- Quand tu auras > 50 adjudications par tribunal, bascule `DATA_SOURCE=sql` et re-train

### `pyodbc` erreur d'import
- Installer ODBC Driver 17 for SQL Server : https://learn.microsoft.com/sql/connect/odbc/

### Sync skippe toutes les lignes
- Vérifier qu'au moins une `upcoming_auctions` a `initial_price > 0`
- Vérifier que `tribunal`, `city` sont remplis

## 📊 Vérifications utiles

```sql
-- Combien d'enchères vraiment importées dans l'app ?
USE EncheresPredict;
SELECT COUNT(*) AS Importees FROM dbo.Auctions WHERE SourceId IS NOT NULL;

-- Top ROI réel scrapé
SELECT TOP 10 Title, City, Tribunal, StartPriceAmount, AiEstimateAmount, RoiValue, Badge
FROM dbo.Auctions
WHERE SourceId IS NOT NULL
ORDER BY RoiValue DESC;

-- Vérifier que le géocodage a marché
USE EncheresPredict_Raw;
SELECT COUNT(*) AS Geocode_OK    FROM dbo.upcoming_auctions WHERE latitude IS NOT NULL;
SELECT COUNT(*) AS Geocode_KO    FROM dbo.upcoming_auctions WHERE latitude IS NULL AND address IS NOT NULL;
```
