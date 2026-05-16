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

    @property
    def odbc_connection_string(self) -> str:
        if self.db_trusted.lower() in {"yes", "true", "1"}:
            return (
                f"DRIVER={{ODBC Driver 17 for SQL Server}};"
                f"SERVER={self.db_server};DATABASE={self.db_name};"
                f"Trusted_Connection=yes;TrustServerCertificate=yes;"
            )
        return (
            f"DRIVER={{ODBC Driver 17 for SQL Server}};"
            f"SERVER={self.db_server};DATABASE={self.db_name};"
            f"UID={self.db_user};PWD={self.db_password};TrustServerCertificate=yes;"
        )

    @property
    def sqlalchemy_url(self) -> str:
        from urllib.parse import quote_plus
        return f"mssql+pyodbc:///?odbc_connect={quote_plus(self.odbc_connection_string)}"


settings = Settings()
