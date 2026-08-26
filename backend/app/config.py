from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

DEMO_ORG_ID = "891aaba9-43e1-59c2-b4b9-ee28ca88ed7d"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "development"
    database_url: str = (
        "postgresql+psycopg://recoai:recoai_local_dev_password@localhost:5432/recoai"
    )
    cors_origins: str = ""
    groq_api_key: str = ""
    groq_model: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""

    demo_actor_id: str = "demo_finance_controller"
    demo_actor_uuid: str = "7fa528e3-07b7-5613-b90d-e89b562882a3"
    ground_truth_path: str = str(REPO_ROOT / "fixtures" / "synthetic" / "ground_truth.json")

    def sync_database_url(self) -> str:
        return normalize_database_url(self.database_url)

    def cors_origin_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]


def normalize_database_url(url: str) -> str:
    if url.startswith("postgresql+psycopg://"):
        return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


@lru_cache
def get_settings() -> Settings:
    return Settings()
