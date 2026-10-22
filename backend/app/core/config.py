from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = (
        "postgresql+psycopg://recallops:recallops@127.0.0.1:55432/recallops"
    )
    environment: str = "development"
    operator_token: str = ""
    demo_enabled: bool = True
    public_demo: bool = False
    llm_api_key: str = Field(
        default="", validation_alias=AliasChoices("LLM_API_KEY", "OPENAI_API_KEY")
    )
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4.1-mini"
    source_url: str = (
        "https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/rappelconso-v2-gtin-trie/records"
    )
    source_refresh_seconds: int = 3600
    source_max_records: int = 1000
    worker_enabled: bool = True
    mutation_limit_per_minute: int = Field(default=120, ge=1)
    allowed_origins: str = ""
    fixture_dir: Path = Path(__file__).resolve().parents[3] / "data" / "fixtures"
    frontend_dist: Path = Path(__file__).resolve().parents[3] / "frontend" / "dist"

    @property
    def db_url(self) -> str:
        return self.database_url.replace(
            "postgres://", "postgresql+psycopg://", 1
        ).replace("postgresql://", "postgresql+psycopg://", 1)


settings = Settings()
# Installed monorepo has data next to backend, container sets FIXTURE_DIR explicitly.
if not settings.fixture_dir.exists():
    settings.fixture_dir = Path(__file__).resolve().parents[4] / "data" / "fixtures"
