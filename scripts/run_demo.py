"""One-command Reco.ai demo.

Starts Postgres (docker compose), migrates, regenerates deterministic fixtures,
starts the backend and frontend, ingests the fixture batch, runs reconciliation,
classifies residue (Fake classifier, or Groq when GROQ_API_KEY + GROQ_MODEL are
set), prints evaluation metrics and dashboard URLs.

Usage:
    # Full demo with synthetic fixtures (default)
    python scripts/run_demo.py [--seed 42] [--preset clean|balanced|messy|stress]

    # Blank slate — upload your own files via UI
    python scripts/run_demo.py --clean --skip-docker

    # Razorpay live demo — one command, auto-fetches from API
    python scripts/run_demo.py --razorpay --skip-docker

    # Skip Docker if Postgres is already running
    python scripts/run_demo.py --skip-docker
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

import httpx
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
WEB_DIR = REPO_ROOT / "web"
FIXTURES_DIR = REPO_ROOT / "fixtures" / "synthetic"

sys.path.insert(0, str(BACKEND_DIR))

# Load .env file so Groq keys are visible to os.environ
load_dotenv(REPO_ROOT / ".env")


def wait_for(url: str, label: str, timeout_s: int = 90) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                print(f"  [ok] {label} ready ({url})")
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError(f"{label} did not become ready at {url}")


def run_step(cmd: list[str], cwd: Path | None = None, check: bool = True) -> int:
    print(f"  $ {' '.join(cmd)}" + (f"  (cwd={cwd.name})" if cwd else ""))
    result = subprocess.run(cmd, cwd=cwd)
    if check and result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}")
    return result.returncode


def reset_database() -> None:
    """Truncate all runtime tables to start fresh."""
    from sqlalchemy import text
    from app.db import make_engine

    RUNTIME_TABLES = (
        "audit_logs, match_members, exceptions, transactions, ingestion_runs, "
        "webhook_events, match_groups, sources, reconciliation_runs, evaluation_runs"
    )
    engine = make_engine()
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {RUNTIME_TABLES} RESTART IDENTITY CASCADE"))
    print("  database reset: all runtime tables cleared")


def run_razorpay_flow(base: str) -> dict:
    """Auto-fetch from Razorpay, generate sample data, run reconciliation + classification."""
    # Step 1: Fetch settlements from Razorpay API
    print("  [1/4] fetching settlements from Razorpay API...")
    resp = httpx.post(f"{base}/api/imports/razorpay-live", timeout=60)
    resp.raise_for_status()
    live = resp.json()
    settlement_count = live.get("count", len(live.get("settlements", [])))
    print(f"    fetched {settlement_count} settlements")

    if settlement_count == 0:
        print("    no settlements found — your test account may have zero transactions")
        return {
            "run_id": None,
            "matched": 0,
            "exceptions": 0,
            "classified": 0,
            "classifier": "none",
            "by_category": {},
        }

    # Step 2: Generate sample bank + ledger from settlements
    print("  [2/4] generating sample bank + ledger from settlements...")
    resp = httpx.post(f"{base}/api/imports/generate-sample", timeout=60)
    resp.raise_for_status()
    sample = resp.json()
    print(f"    bank rows: {sample['bank_rows']}, ledger rows: {sample['ledger_rows']}")

    # Step 3: Run reconciliation
    print("  [3/4] running reconciliation...")
    resp = httpx.post(f"{base}/api/reconciliation-runs", timeout=120)
    resp.raise_for_status()
    run = resp.json()
    summary = run["summary"]
    print(
        f"    matched {summary['matched_bank_transactions']}/"
        f"{summary['total_bank_transactions']} · exceptions {summary['exceptions_created']}"
    )

    # Step 4: Classify exceptions
    use_ai = bool(os.environ.get("GROQ_API_KEY")) and bool(os.environ.get("GROQ_MODEL"))
    mode = "Groq live" if use_ai else "Fake classifier (offline)"
    print(f"  [4/4] classifying exceptions — {mode}")
    resp = httpx.post(
        f"{base}/api/exceptions/classify-pending",
        json={"use_ai": use_ai, "limit": 200},
        timeout=180,
    )
    resp.raise_for_status()
    classification = resp.json()
    print(
        f"    classified={classification['classified']} "
        f"by_category={classification['by_category']}"
    )

    return {
        "run_id": run["run_id"],
        "matched": summary["matched_bank_transactions"],
        "exceptions": summary["exceptions_created"],
        "classified": classification["classified"],
        "classifier": classification["classifier"],
        "by_category": classification["by_category"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the Reco.ai end-to-end demo")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--preset",
        choices=["clean", "balanced", "messy", "stress"],
        default=None,
        help="Use a named preset (overrides --seed with preset-specific case_counts)",
    )
    parser.add_argument("--skip-docker", action="store_true", help="Postgres already running")
    parser.add_argument("--no-open", action="store_true", help="do not open the browser")
    parser.add_argument("--backend-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=3000)
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Reset database and start with blank slate (no fixtures, no ingestion)",
    )
    parser.add_argument(
        "--razorpay",
        action="store_true",
        help="Reset DB, auto-fetch from Razorpay API, generate sample data, run pipeline",
    )
    args = parser.parse_args()

    # --razorpay implies --clean
    if args.razorpay:
        args.clean = True

    base = f"http://localhost:{args.backend_port}"
    frontend_url = f"http://localhost:{args.frontend_port}"

    # ── Step 1: Docker ──────────────────────────────────────────────
    if not args.skip_docker:
        print("[1/8] docker compose up -d")
        run_step(["docker", "compose", "up", "-d"], cwd=REPO_ROOT)
    else:
        print("[1/8] skipping docker (Postgres assumed running)")

    # ── Step 2: Migrations ──────────────────────────────────────────
    print("[2/8] alembic upgrade head")
    for attempt in range(30):
        code = run_step(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=BACKEND_DIR,
            check=False,
        )
        if code == 0:
            break
        time.sleep(2)
    else:
        raise RuntimeError("database never became ready; is Docker running?")

    # ── Step 3: Reset database (if --clean or --razorpay) ───────────
    if args.clean:
        print("[3/8] resetting database (clean mode)")
        reset_database()
    elif args.preset:
        preset_dir = REPO_ROOT / "fixtures" / "test_sets" / args.preset
        if not preset_dir.exists():
            print(f"  generating preset fixtures first ({args.preset})")
            run_step(
                [sys.executable, "scripts/generate_test_sets.py", "--presets", args.preset],
                cwd=REPO_ROOT,
            )
        print(f"[3/8] copying {args.preset} preset fixtures")
        for f in preset_dir.iterdir():
            if f.is_file():
                shutil.copy2(f, FIXTURES_DIR / f.name)
    else:
        print(f"[3/8] generating fixtures (seed={args.seed}, deterministic)")
        from app.services.evaluation.synthetic_generator import (
            SyntheticDataGenerator,
            write_fixture_files,
        )

        generated = SyntheticDataGenerator(args.seed).generate()
        write_fixture_files(generated, FIXTURES_DIR)

    # ── Step 4: Start backend ───────────────────────────────────────
    print(f"[4/8] starting backend on :{args.backend_port}")
    backend_proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--port",
            str(args.backend_port),
        ],
        cwd=BACKEND_DIR,
    )
    try:
        wait_for(f"{base}/health", "backend")

        # ── Steps 5-7: Ingestion + Pipeline ────────────────────────
        if args.clean and not args.razorpay:
            # Clean mode — skip everything, user will do it from the UI
            print("[5/8] skipping ingestion (clean mode)")
            print("[6/8] skipping reconciliation (clean mode)")
            print("[7/8] skipping classification (clean mode)")
        elif args.razorpay:
            # Razorpay mode — auto-fetch + generate + run pipeline
            print("[5/8] Razorpay API flow")
            result = run_razorpay_flow(base)
            if result["run_id"]:
                print(f"\n  Pipeline complete:")
                print(f"    run_id:      {result['run_id']}")
                print(f"    matched:     {result['matched']}")
                print(f"    exceptions:  {result['exceptions']}")
                print(f"    classified:  {result['classified']} ({result['classifier']})")
                if result["by_category"]:
                    print(f"    categories:  {result['by_category']}")
            else:
                print("\n  No settlements to process.")
        else:
            # Default — synthetic fixtures
            print("[5/8] ingesting fixture sources")
            uploads = [
                ("bank", "bank_statement.csv", "text/csv"),
                ("ledger", "ledger.csv", "text/csv"),
                ("razorpay-settlements", "razorpay_settlements.json", "application/json"),
            ]
            for kind, name, mime in uploads:
                with open(FIXTURES_DIR / name, "rb") as handle:
                    response = httpx.post(
                        f"{base}/api/imports/{kind}",
                        files={"file": (name, handle, mime)},
                        timeout=60,
                    )
                response.raise_for_status()
                summary = response.json()
                print(
                    f"  {kind}: inserted={summary['inserted']} "
                    f"skipped={summary['skipped_duplicates']} failed={summary['failed_rows']}"
                )

            print("[6/8] running reconciliation")
            run = httpx.post(f"{base}/api/reconciliation-runs", timeout=120).json()
            summary = run["summary"]
            print(
                f"  matched {summary['matched_bank_transactions']}/"
                f"{summary['total_bank_transactions']} · exceptions {summary['exceptions_created']}"
            )

            use_ai = bool(os.environ.get("GROQ_API_KEY")) and bool(os.environ.get("GROQ_MODEL"))
            mode = "Groq live" if use_ai else "Fake classifier (offline)"
            print(f"[7/8] classifying residue — {mode}")
            classification = httpx.post(
                f"{base}/api/exceptions/classify-pending",
                json={"use_ai": use_ai, "limit": 200},
                timeout=180,
            ).json()
            print(
                f"  classified={classification['classified']} "
                f"pending_found={classification['pending_found']} "
                f"deferred_retry={classification['deferred_retry']} "
                f"by_category={classification['by_category']}"
            )

            result = {
                "run_id": run["run_id"],
                "matched": summary["matched_bank_transactions"],
                "exceptions": summary["exceptions_created"],
                "classified": classification["classified"],
                "classifier": classification["classifier"],
                "by_category": classification["by_category"],
            }

            metrics = httpx.get(
                f"{base}/api/reconciliation-runs/{run['run_id']}/metrics", timeout=120
            ).json()["evaluation"]["metrics"]
            print("[evaluation]")
            for key in (
                "deterministic_match_rate",
                "deterministic_coverage",
                "exception_recall",
                "ai_classification_accuracy",
                "llm_faithfulness_score",
            ):
                print(f"  {key}: {metrics[key]}")

        # ── Step 8: Start frontend ──────────────────────────────────
        print(f"[8/8] starting frontend on :{args.frontend_port}")
        npm = shutil.which("npm.cmd") or shutil.which("npm") or "npm"
        if not (WEB_DIR / ".next").exists():
            run_step([npm, "run", "build"], cwd=WEB_DIR)
        fe_command = "start" if (WEB_DIR / ".next").exists() else "dev"
        frontend_proc = subprocess.Popen(
            [npm, "run", fe_command, "--", "--port", str(args.frontend_port)],
            cwd=WEB_DIR,
        )
        wait_for(frontend_url, "frontend")

        # ── Done ────────────────────────────────────────────────────
        if args.razorpay:
            run_id = result.get("run_id")
            print("\n================ RAZORPAY DEMO READY ========")
            print(f"  Dashboard:      {frontend_url}")
            print(f"  API docs:       {base}/docs")
            if run_id:
                print(f"  Exceptions UI:  {frontend_url}/exceptions")
                print(f"  Run detail:     {frontend_url}/runs/{run_id}")
            else:
                print("  WARNING: No settlements found - open dashboard to fetch manually")
            print("============================================\n")
            if not args.no_open:
                webbrowser.open(f"{frontend_url}/runs/{run_id}" if run_id else frontend_url)
        elif args.clean:
            print("\n================ CLEAN SLATE READY ==========")
            print(f"  Dashboard:      {frontend_url}")
            print(f"  API docs:       {base}/docs")
            print("  Upload your own CSVs via the dashboard")
            print("============================================\n")
            if not args.no_open:
                webbrowser.open(frontend_url)
        else:
            print("\n================ DEMO READY ================")
            print(f"  Dashboard:      {frontend_url}")
            print(f"  Exceptions UI:  {frontend_url}/exceptions")
            print(f"  Run detail:     {frontend_url}/runs/{result['run_id']}")
            print(f"  API docs:       {base}/docs")
            print("============================================\n")
            if not args.no_open:
                webbrowser.open(frontend_url)

        print("Press Ctrl+C to stop the demo servers.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            frontend_proc.terminate()
    finally:
        backend_proc.terminate()

    return 0


if __name__ == "__main__":
    sys.exit(main())
