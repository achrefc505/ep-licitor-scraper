-- ============================================================================
-- EncheresPredict_Raw — Schema (DDL)
-- Base SQL Server SÉPARÉE pour le pipeline de scraping.
-- L'application user (EncheresPredict) ne lit JAMAIS cette base directement.
-- ============================================================================

IF DB_ID('EncheresPredict_Raw') IS NULL
BEGIN
    CREATE DATABASE EncheresPredict_Raw;
END
GO

USE EncheresPredict_Raw;
GO

-- ============================================================================
-- raw_pages : audit trail brut — chaque page HTML scrapée
-- ============================================================================
IF OBJECT_ID('dbo.raw_pages', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.raw_pages
    (
        id              BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_raw_pages PRIMARY KEY,
        source          NVARCHAR(50)     NOT NULL,    -- 'licitor'
        page_type       NVARCHAR(50)     NOT NULL,    -- 'historique_list', 'historique_detail', 'upcoming_list', 'upcoming_detail'
        url             NVARCHAR(800)    NOT NULL,
        url_hash        AS CONVERT(VARBINARY(32), HASHBYTES('SHA2_256', url)) PERSISTED,
        fetched_at      DATETIME2        NOT NULL CONSTRAINT DF_raw_pages_fetched DEFAULT (SYSUTCDATETIME()),
        http_status     INT              NOT NULL,
        html            NVARCHAR(MAX)    NULL,
        parse_status    NVARCHAR(20)     NOT NULL CONSTRAINT DF_raw_pages_parse_status DEFAULT (N'pending'),  -- pending / parsed / error / skipped
        parse_error     NVARCHAR(MAX)    NULL,
        parsed_at       DATETIME2        NULL
    );
    CREATE INDEX IX_raw_pages_url_hash       ON dbo.raw_pages(url_hash);
    CREATE INDEX IX_raw_pages_parse_status   ON dbo.raw_pages(parse_status, fetched_at);
    CREATE INDEX IX_raw_pages_page_type      ON dbo.raw_pages(page_type, fetched_at DESC);
END
GO

-- ============================================================================
-- scrape_jobs : tracking des runs (qui, quand, combien de pages, erreurs)
-- ============================================================================
IF OBJECT_ID('dbo.scrape_jobs', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.scrape_jobs
    (
        id              BIGINT IDENTITY(1,1) NOT NULL CONSTRAINT PK_scrape_jobs PRIMARY KEY,
        job_type        NVARCHAR(50)     NOT NULL,    -- 'historique', 'upcoming'
        started_at      DATETIME2        NOT NULL CONSTRAINT DF_scrape_jobs_started DEFAULT (SYSUTCDATETIME()),
        finished_at     DATETIME2        NULL,
        status          NVARCHAR(20)     NOT NULL CONSTRAINT DF_scrape_jobs_status DEFAULT (N'running'),  -- running / success / failed
        pages_fetched   INT              NOT NULL CONSTRAINT DF_scrape_jobs_pages DEFAULT 0,
        pages_failed    INT              NOT NULL CONSTRAINT DF_scrape_jobs_failed DEFAULT 0,
        error_message   NVARCHAR(MAX)    NULL,
        params_json     NVARCHAR(MAX)    NULL          -- filtres utilisés (region, tribunal, dates)
    );
END
GO

-- ============================================================================
-- adjudications : table NORMALISÉE — historique passé
-- ============================================================================
IF OBJECT_ID('dbo.adjudications', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.adjudications
    (
        id                  UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_adjudications PRIMARY KEY DEFAULT (NEWID()),
        source              NVARCHAR(50)     NOT NULL,    -- 'licitor'
        source_id           NVARCHAR(100)    NOT NULL,    -- ID Licitor (slug + numéro extrait de l'URL)
        source_url          NVARCHAR(800)    NULL,
        raw_page_id         BIGINT           NULL,        -- FK vers raw_pages.id de la page détail

        -- Localisation
        tribunal            NVARCHAR(150)    NULL,
        region              NVARCHAR(100)    NULL,
        city                NVARCHAR(100)    NULL,
        postal_code         NVARCHAR(10)     NULL,
        [address]           NVARCHAR(500)    NULL,
        latitude            DECIMAL(9,6)     NULL,        -- rempli par étape géocodage
        longitude           DECIMAL(9,6)     NULL,

        -- Bien
        property_type       NVARCHAR(80)     NULL,        -- Appartement, Maison, Local, Terrain, Immeuble...
        surface             DECIMAL(10,2)    NULL,
        rooms               INT              NULL,
        floor               NVARCHAR(50)     NULL,
        description         NVARCHAR(MAX)    NULL,

        -- Prix
        initial_price       DECIMAL(18,2)    NULL,        -- mise à prix
        adjudicated_price   DECIMAL(18,2)    NULL,        -- prix final adjudication
        currency            NVARCHAR(3)      NOT NULL CONSTRAINT DF_adj_currency DEFAULT (N'EUR'),

        -- Dates
        adjudication_date   DATE             NULL,
        published_at        DATE             NULL,

        -- Contacts (très important pour le workflow n8n)
        lawyer_name         NVARCHAR(200)    NULL,
        lawyer_email        NVARCHAR(200)    NULL,
        lawyer_phone        NVARCHAR(50)     NULL,
        lawyer_office       NVARCHAR(200)    NULL,        -- cabinet

        -- Méta
        scraped_at          DATETIME2        NOT NULL CONSTRAINT DF_adj_scraped DEFAULT (SYSUTCDATETIME()),
        updated_at          DATETIME2        NOT NULL CONSTRAINT DF_adj_updated DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT UQ_adjudications_source UNIQUE (source, source_id),
        CONSTRAINT FK_adjudications_rawpage FOREIGN KEY (raw_page_id)
            REFERENCES dbo.raw_pages(id) ON DELETE SET NULL
    );
    CREATE INDEX IX_adj_tribunal           ON dbo.adjudications(tribunal);
    CREATE INDEX IX_adj_city               ON dbo.adjudications(city);
    CREATE INDEX IX_adj_property_type      ON dbo.adjudications(property_type);
    CREATE INDEX IX_adj_adjudication_date  ON dbo.adjudications(adjudication_date DESC);
    CREATE INDEX IX_adj_lawyer_email       ON dbo.adjudications(lawyer_email) WHERE lawyer_email IS NOT NULL;
END
GO

-- ============================================================================
-- upcoming_auctions : prochaines ventes (à venir) — structure similaire
-- ============================================================================
IF OBJECT_ID('dbo.upcoming_auctions', 'U') IS NULL
BEGIN
    CREATE TABLE dbo.upcoming_auctions
    (
        id                  UNIQUEIDENTIFIER NOT NULL CONSTRAINT PK_upcoming PRIMARY KEY DEFAULT (NEWID()),
        source              NVARCHAR(50)     NOT NULL,
        source_id           NVARCHAR(100)    NOT NULL,
        source_url          NVARCHAR(800)    NULL,
        raw_page_id         BIGINT           NULL,

        tribunal            NVARCHAR(150)    NULL,
        region              NVARCHAR(100)    NULL,
        city                NVARCHAR(100)    NULL,
        postal_code         NVARCHAR(10)     NULL,
        [address]           NVARCHAR(500)    NULL,
        latitude            DECIMAL(9,6)     NULL,
        longitude           DECIMAL(9,6)     NULL,

        property_type       NVARCHAR(80)     NULL,
        surface             DECIMAL(10,2)    NULL,
        rooms               INT              NULL,
        floor               NVARCHAR(50)     NULL,
        description         NVARCHAR(MAX)    NULL,

        initial_price       DECIMAL(18,2)    NULL,
        currency            NVARCHAR(3)      NOT NULL CONSTRAINT DF_upc_currency DEFAULT (N'EUR'),

        auction_date        DATETIME2        NULL,        -- date/heure de la vente
        deposit_required    DECIMAL(18,2)    NULL,        -- consignation
        first_visit_date    DATE             NULL,
        second_visit_date   DATE             NULL,

        lawyer_name         NVARCHAR(200)    NULL,
        lawyer_email        NVARCHAR(200)    NULL,
        lawyer_phone        NVARCHAR(50)     NULL,
        lawyer_office       NVARCHAR(200)    NULL,

        -- État du workflow documents (n8n)
        documents_requested BIT              NOT NULL CONSTRAINT DF_upc_docreq DEFAULT (0),
        documents_received  BIT              NOT NULL CONSTRAINT DF_upc_docrcv DEFAULT (0),
        last_contact_at     DATETIME2        NULL,

        scraped_at          DATETIME2        NOT NULL CONSTRAINT DF_upc_scraped DEFAULT (SYSUTCDATETIME()),
        updated_at          DATETIME2        NOT NULL CONSTRAINT DF_upc_updated DEFAULT (SYSUTCDATETIME()),

        CONSTRAINT UQ_upcoming_source UNIQUE (source, source_id),
        CONSTRAINT FK_upcoming_rawpage FOREIGN KEY (raw_page_id)
            REFERENCES dbo.raw_pages(id) ON DELETE SET NULL
    );
    CREATE INDEX IX_upc_auction_date  ON dbo.upcoming_auctions(auction_date);
    CREATE INDEX IX_upc_tribunal      ON dbo.upcoming_auctions(tribunal);
    CREATE INDEX IX_upc_doc_workflow  ON dbo.upcoming_auctions(documents_requested, documents_received);
END
GO

PRINT '✓ Base EncheresPredict_Raw prête';
PRINT '  - raw_pages           : audit trail HTML brut';
PRINT '  - scrape_jobs         : tracking runs';
PRINT '  - adjudications       : historique normalisé';
PRINT '  - upcoming_auctions   : prochaines ventes';
GO
