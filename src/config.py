from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=Path(__file__).parent.parent / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    db_server: str = "(localdb)\\mssqllocaldb"
    db_name: str = "EncheresPredict_Raw"
    db_trusted: str = "yes"
    db_user: str | None = None
    db_password: str | None = None

    # Base applicative (alimentée par le sync ETL)
    app_db_server: str = "(localdb)\\mssqllocaldb"
    app_db_name: str = "EncheresPredict"
    app_db_trusted: str = "yes"
    app_db_user: str | None = None
    app_db_password: str | None = None

    # API ML
    ml_api_url: str = "http://localhost:8000"
    ml_api_timeout: int = 10

    # Géocodage
    geocoder_url: str = "https://api-adresse.data.gouv.fr/search/"
    geocoder_timeout: int = 10

    scraper_user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    scraper_delay_min: float = 3.0
    scraper_delay_max: float = 7.0
    scraper_timeout_ms: int = 30000
    scraper_headless: bool = True
    scraper_max_retries: int = 3
    scraper_max_pages_per_run: int = 20
    scraper_respect_robots: bool = True

    log_level: str = "INFO"
    log_file: str = "logs/scraper.log"

    @staticmethod
    def _build_odbc(server, db, trusted, user, password):
        if trusted.lower() in {"yes", "true", "1"}:
            return (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={server};DATABASE={db};"
                f"Trusted_Connection=yes;TrustServerCertificate=yes;"
            )
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={server};DATABASE={db};"
            f"UID={user};PWD={password};TrustServerCertificate=yes;"
        )

    @property
    def odbc_connection_string(self) -> str:
        return self._build_odbc(self.db_server, self.db_name, self.db_trusted, self.db_user, self.db_password)

    @property
    def app_odbc_connection_string(self) -> str:
        return self._build_odbc(self.app_db_server, self.app_db_name, self.app_db_trusted, self.app_db_user, self.app_db_password)

    @property
    def sqlalchemy_url(self) -> str:
        from urllib.parse import quote_plus
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(self.odbc_connection_string)}"

    @property
    def app_sqlalchemy_url(self) -> str:
        from urllib.parse import quote_plus
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(self.app_odbc_connection_string)}"


settings = Settings()
