import sys
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

TEST_DB_NAME = "recoai_test"
BASE_ADMIN_URL = "postgresql://recoai:recoai_local_dev_password@localhost:5432/postgres"


def _test_db_url() -> str:
    return f"postgresql+psycopg://recoai:recoai_local_dev_password@localhost:5432/{TEST_DB_NAME}"


@pytest.fixture(scope="session")
def test_database_url():
    with psycopg.connect(BASE_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')
        conn.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", _test_db_url())
    command.upgrade(cfg, "head")

    yield _test_db_url()

    with psycopg.connect(BASE_ADMIN_URL, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)')


@pytest.fixture(scope="session")
def engine(test_database_url):
    from app.db import make_engine

    return make_engine(test_database_url)


@pytest.fixture()
def db(engine):
    connection = engine.connect()
    session = Session(bind=connection, autoflush=False, expire_on_commit=False)
    try:
        yield session
    finally:
        session.rollback()
        session.close()
        connection.close()


@pytest.fixture()
def clean_tables(engine):
    yield
    with engine.begin() as conn:
        conn.execute(
            text(
                "TRUNCATE TABLE audit_logs, match_members, exceptions, transactions, "
                "ingestion_runs, webhook_events, match_groups, sources, "
                "evaluation_runs, reconciliation_runs, ground_truth_labels "
                "RESTART IDENTITY CASCADE"
            )
        )


@pytest.fixture()
def session_factory(engine):
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture()
def client(test_database_url, engine):
    from fastapi.testclient import TestClient

    from app.db import get_db
    from app.main import app

    test_session_factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db():
        db = test_session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
