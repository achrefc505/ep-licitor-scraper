# =============================================================================
# bootstrap-local.ps1
#
# Orchestrateur du pipeline complet EncheresPredict en local.
# À lancer DEPUIS le repo ep-licitor-scraper après avoir scrapé des données.
#
# Étapes :
#   1. Vérifie SQL Server LocalDB up + bases présentes
#   2. Affiche le nombre d'enchères scrapées
#   3. Lance le pipeline ETL (geocode + sync) → DB applicative
#   4. (Optionnel) ré-entraîne les modèles ML sur les vraies données
#
# Prérequis :
#   - SQL Server LocalDB démarré (sqllocaldb start mssqllocaldb)
#   - Base EncheresPredict_Raw alimentée (par le scraper)
#   - Base EncheresPredict créée (par les migrations du backend .NET)
#   - .venv Python activé avec requirements.txt installé
#   - API ML qui tourne sur http://localhost:8000 (recommandé, sinon fallback)
# =============================================================================

param(
    [int]$Limit = 500,
    [switch]$SkipGeocode = $false,
    [switch]$RetrainML = $false,
    [string]$MlApiPath = "../ep-ml-api"
)

$ErrorActionPreference = "Stop"

function Write-Step($n, $msg) {
    Write-Host ""
    Write-Host "──────────────────────────────────────────────────────────────" -ForegroundColor Cyan
    Write-Host "  Étape $n : $msg" -ForegroundColor Cyan
    Write-Host "──────────────────────────────────────────────────────────────" -ForegroundColor Cyan
}

function Test-Sqlcmd {
    try { sqlcmd -? > $null 2>&1; return $true } catch { return $false }
}

# ── Étape 1 : vérifier l'état SQL ───────────────────────────────────────────
Write-Step 1 "Vérification de SQL Server LocalDB"

if (-not (Test-Sqlcmd)) {
    Write-Host "✗ sqlcmd introuvable. Installe SQL Server Command-Line Tools." -ForegroundColor Red
    Write-Host "  https://learn.microsoft.com/sql/tools/sqlcmd-utility"
    exit 1
}

$rawCount = sqlcmd -S "(localdb)\mssqllocaldb" -d "EncheresPredict_Raw" -h -1 -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.upcoming_auctions" 2>&1
$histCount = sqlcmd -S "(localdb)\mssqllocaldb" -d "EncheresPredict_Raw" -h -1 -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.adjudications" 2>&1
$appCount = sqlcmd -S "(localdb)\mssqllocaldb" -d "EncheresPredict" -h -1 -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.Auctions" 2>&1

Write-Host "  upcoming_auctions (Raw) : $($rawCount.Trim())"
Write-Host "  adjudications     (Raw) : $($histCount.Trim())"
Write-Host "  Auctions          (App) : $($appCount.Trim())"

if ([int]($rawCount.Trim()) -eq 0 -and [int]($histCount.Trim()) -eq 0) {
    Write-Host ""
    Write-Host "✗ Aucune donnée scrapée. Lance d'abord :" -ForegroundColor Red
    Write-Host "    python -m src.cli upcoming --max-pages 5"
    Write-Host "    python -m src.cli historique --max-pages 5"
    exit 1
}

# ── Étape 2 (optionnelle) : ré-entraîner le ML sur vraies données ──────────
if ($RetrainML) {
    Write-Step 2 "Ré-entraînement des modèles ML sur données réelles"

    if (-not (Test-Path $MlApiPath)) {
        Write-Host "✗ Repo ep-ml-api introuvable à $MlApiPath" -ForegroundColor Red
        Write-Host "  Utilise -MlApiPath pour spécifier le chemin"
        exit 1
    }

    Push-Location $MlApiPath
    try {
        if (-not (Test-Path ".env")) {
            Copy-Item .env.example .env
        }
        # Force DATA_SOURCE=sql dans le .env temporaire
        $envContent = Get-Content .env -Raw
        $envContent = $envContent -replace "DATA_SOURCE=csv", "DATA_SOURCE=sql"
        Set-Content -Path .env -Value $envContent -NoNewline

        Write-Host "  Entraînement depuis EncheresPredict_Raw.adjudications..."
        python -m src.training.train
        if ($LASTEXITCODE -ne 0) {
            Write-Host "✗ Échec entraînement. Vérifie qu'il y a >= 50 lignes dans adjudications." -ForegroundColor Red
            exit 1
        }
    } finally {
        Pop-Location
    }
}

# ── Étape 3 : pipeline ETL ─────────────────────────────────────────────────
Write-Step 3 "Pipeline ETL (geocode + sync vers App)"

if ($SkipGeocode) {
    Write-Host "  (geocode skippé via -SkipGeocode)"
    python -m src.cli sync-app --limit $Limit
} else {
    python -m src.cli pipeline --limit $Limit
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "✗ Échec pipeline ETL." -ForegroundColor Red
    exit 1
}

# ── Étape 4 : vérif post-sync ───────────────────────────────────────────────
Write-Step 4 "Vérification post-sync"

$finalCount = sqlcmd -S "(localdb)\mssqllocaldb" -d "EncheresPredict" -h -1 -Q "SET NOCOUNT ON; SELECT COUNT(*) FROM dbo.Auctions WHERE SourceId IS NOT NULL" 2>&1
Write-Host "  Auctions en App (avec SourceId)  : $($finalCount.Trim())"

$topRoi = sqlcmd -S "(localdb)\mssqllocaldb" -d "EncheresPredict" -h -1 -Q @"
SET NOCOUNT ON;
SELECT TOP 5 Title, City, CAST(StartPriceAmount AS INT) AS Mise, CAST(AiEstimateAmount AS INT) AS IA, RoiValue, Badge
FROM dbo.Auctions WHERE SourceId IS NOT NULL ORDER BY RoiValue DESC
"@ 2>&1
Write-Host ""
Write-Host "Top 5 ROI :" -ForegroundColor Green
$topRoi | ForEach-Object { Write-Host "  $_" }

Write-Host ""
Write-Host "✓ Pipeline terminé." -ForegroundColor Green
Write-Host ""
Write-Host "Étapes suivantes :"
Write-Host "  1. Backend .NET : ouvrir un terminal et lancer"
Write-Host "       `$env:EP_SKIP_SEED='true'; dotnet run --project ../EncheresPredict/EncheresPredict.Api"
Write-Host "  2. Frontend Angular : ouvrir un autre terminal"
Write-Host "       cd ../encherespredict; npm start"
Write-Host "  3. Naviguer sur http://localhost:4200 — Dashboard devrait afficher tes vraies enchères Paris"
