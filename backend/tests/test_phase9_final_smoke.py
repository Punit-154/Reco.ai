import json
import subprocess
import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, select, text

from app.models import (
    AuditLog,
    ExceptionRecord,
    MatchGroup,
)
from app.services.ai.classifier import FakeExceptionClassifier
from app.services.ai.triage import classify_pending_exceptions
from app.services.evaluation.metrics import run_evaluation
from app.services.ingestion.importers import (
    ingest_bank_csv,
    ingest_ledger_csv,
    ingest_razorpay_settlements,
)
from app.services.matching.deterministic import start_reconciliation_run

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "fixtures" / "synthetic"
BACKEND_DIR = REPO_ROOT / "backend"
DEMO_ACTOR_UUID = uuid.UUID("7fa528e3-07b7-5613-b90d-e89b562882a3")

SECRET_PATTERNS = ["rzp_live_", "gsk_", "AKIA", "BEGIN PRIVATE KEY", "ghp_", "xoxb-"]

TEXT_SUFFIXES = {
    ".py", ".ts", ".tsx", ".md", ".json", ".csv", ".yml", ".yaml",
    ".toml", ".ini", ".txt", ".mjs", ".css", ".mako", ".example",
}

EXPECTED_TABLES = {
    "sources", "ingestion_runs", "webhook_events", "transactions",
    "match_groups", "match_members", "exceptions", "audit_logs",
    "evaluation_runs", "ground_truth_labels", "reconciliation_runs", "actors",
}


def _alembic_config(test_database_url: str) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", test_database_url)
    return cfg


def test_migration_cycle_base_to_head(test_database_url):
    cfg = _alembic_config(test_database_url)

    try:
        command.downgrade(cfg, "base")
        probe = create_engine(test_database_url)
        with probe.connect() as conn:
            user_tables_after_downgrade = conn.execute(
                text(
                    "select tablename from pg_tables "
                    "where schemaname='public' and tablename <> 'alembic_version'"
                )
            ).scalars().all()
        assert user_tables_after_downgrade == []

        command.upgrade(cfg, "head")

        with probe.connect() as conn:
            tables_after = {
                row[0]
                for row in conn.execute(
                    text(
                        "select tablename from pg_tables where schemaname='public'"
                    )
                ).fetchall()
            }
            actor = conn.execute(text("select name from actors")).scalar()
        probe.dispose()

        assert EXPECTED_TABLES <= tables_after
        assert actor == "demo_finance_controller"
    finally:
        command.upgrade(_alembic_config(test_database_url), "head")


def json_dumps(value) -> str:
    return json.dumps(value, sort_keys=True)


@pytest.mark.usefixtures("clean_tables")
def test_end_to_end_pipeline_metrics_and_audit(session_factory):
    with session_factory() as db:
        ingest_bank_csv(db, (FIXTURES_DIR / "bank_statement.csv").read_bytes())
        ingest_ledger_csv(db, (FIXTURES_DIR / "ledger.csv").read_bytes())
        ingest_razorpay_settlements(
            db, (FIXTURES_DIR / "razorpay_settlements.json").read_bytes()
        )
        run = start_reconciliation_run(db)
        db.commit()

        classify_pending_exceptions(db, FakeExceptionClassifier(), limit=200)
        db.commit()

        output = run_evaluation(
            db,
            FIXTURES_DIR / "ground_truth.json",
            reconciliation_run_id=uuid.UUID(run["run_id"]),
        )
        db.commit()

    metrics = output.metrics
    for rate_key in (
        "deterministic_match_rate",
        "deterministic_coverage",
        "exception_recall",
        "ai_classification_accuracy",
        "llm_faithfulness_score",
    ):
        assert metrics[rate_key] == 1.0, f"{rate_key}={metrics[rate_key]}"

    with session_factory() as db:
        target = db.execute(
            select(ExceptionRecord).where(ExceptionRecord.response.is_not(None))
        ).scalars().first()
        groups_before = len(db.execute(select(MatchGroup)).scalars().all())
        hypothesis_before = json_dumps(target.response)

        audit = AuditLog(
            actor_id=DEMO_ACTOR_UUID,
            action="exception_approve",
            entity_type="exception",
            entity_id=str(target.id),
            previous_state={"status": target.status},
            new_state={"status": "approved"},
            ai_hypothesis=target.response,
            reason="final smoke approval",
        )
        db.add(audit)
        target.status = "approved"
        db.commit()
        db.refresh(audit)

        hypothesis_after = json_dumps(audit.ai_hypothesis)
        groups_after = len(db.execute(select(MatchGroup)).scalars().all())

    assert hypothesis_after == hypothesis_before
    assert groups_before == groups_after == 75


def test_readme_and_judge_defense_present():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "run_demo.py" in readme
    assert "synthetic" in readme.lower()

    defense = (REPO_ROOT / "docs" / "judge_defense.md").read_text(encoding="utf-8")
    lowered = defense.lower()
    assert "deterministic first" in lowered or "why deterministic" in lowered
    assert "hallucinated" in lowered
    assert "auditability" in lowered or "failure recovery" in lowered


def _git_available() -> bool:
    try:
        return (
            subprocess.run(["git", "--version"], capture_output=True).returncode == 0
        )
    except OSError:
        return False


@pytest.mark.skipif(not _git_available(), reason="git not available")
def test_no_secrets_committed():
    git_output = subprocess.run(
        ["git", "ls-files"], cwd=REPO_ROOT, capture_output=True, text=True
    )
    tracked = git_output.stdout.splitlines()

    assert ".env" not in tracked
    gitignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".env" in gitignore

    violations = []
    for rel_path in tracked:
        path = REPO_ROOT / rel_path
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern in content:
                violations.append(f"{rel_path}: {pattern}")

    assert violations == [], f"potential secrets committed: {violations}"


@pytest.mark.skipif(not _git_available(), reason="git not available")
def test_git_status_has_no_sensitive_files():
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    ).stdout

    sensitive = []
    for line in status.splitlines():
        lowered = line.lower()
        if ".env" in line and ".env.example" not in line:
            sensitive.append(line)
        elif "secret" in lowered and "no secret" not in lowered:
            sensitive.append(line)

    assert sensitive == [], f"sensitive files appear in git status: {sensitive}"
