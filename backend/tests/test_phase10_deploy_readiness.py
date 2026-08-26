from pathlib import Path

import pytest

from app.config import Settings, normalize_database_url

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_normalize_database_url_variants():
    assert normalize_database_url(
        "postgresql+psycopg://u:p@h:5432/db"
    ) == "postgresql+psycopg://u:p@h:5432/db"

    assert normalize_database_url(
        "postgresql://postgres.ref:pwd@aws-0-eu.pooler.supabase.com:5432/postgres?sslmode=require"
    ) == (
        "postgresql+psycopg://postgres.ref:pwd@aws-0-eu.pooler.supabase.com:5432/postgres?sslmode=require"
    )

    assert normalize_database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert normalize_database_url("mysql://x/y") == "mysql://x/y"


def test_settings_sync_database_url_and_cors_parsing():
    settings = Settings(
        database_url="postgresql://postgres.ref:pwd@pool.supabase.com:5432/postgres",
        cors_origins="https://app.example.com, https://preview.example.com ,",
        _env_file=None,
    )
    assert settings.sync_database_url().startswith("postgresql+psycopg://")
    assert settings.cors_origin_list() == [
        "https://app.example.com",
        "https://preview.example.com",
    ]

    empty = Settings(_env_file=None)
    assert empty.cors_origin_list() == []


def test_app_entrypoint_exports_fastapi_app():
    from fastapi import FastAPI

    from app.main import app

    assert isinstance(app, FastAPI)
    schema_paths = set(app.openapi()["paths"])
    assert "/health" in schema_paths
    assert "/api/webhooks/razorpay" in schema_paths
    assert "/api/reconciliation-runs" in schema_paths
    assert "/api/exceptions/classify-pending" in schema_paths


def test_server_dependencies_declared():
    requirements = (BACKEND_DIR / "requirements.txt").read_text(encoding="utf-8")
    for package in ("uvicorn", "httpx", "psycopg", "python-multipart", "alembic"):
        assert package in requirements, f"{package} missing from requirements.txt"


def test_upload_paths_have_no_local_filesystem_writes():
    for module_path in [
        BACKEND_DIR / "app" / "routers" / "imports.py",
        BACKEND_DIR / "app" / "routers" / "webhooks.py",
        BACKEND_DIR / "app" / "services" / "ingestion" / "importers.py",
    ]:
        source = module_path.read_text(encoding="utf-8")
        assert "write_text" not in source, f"{module_path.name} writes to local disk"
        assert 'open("' not in source and "open('" not in source, (
            f"{module_path.name} opens local files"
        )


def test_groq_offline_by_default_and_enabled_by_env(monkeypatch):
    from app.services.ai.classifier import (
        FakeExceptionClassifier,
        GroqExceptionClassifier,
        get_classifier,
    )

    settings = Settings(groq_api_key="", groq_model="", _env_file=None)
    assert isinstance(get_classifier(settings, use_ai=True), FakeExceptionClassifier)

    live_settings = Settings(
        groq_api_key="key", groq_model="llama-test", _env_file=None
    )
    chosen = get_classifier(live_settings, use_ai=True)
    assert isinstance(chosen, GroqExceptionClassifier)

    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.mark.parametrize("path", ["/health"])
def test_health_smoke(client, path):
    response = client.get(path)
    assert response.status_code == 200
