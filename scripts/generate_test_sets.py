"""Generate multiple fixture sets with different issue densities.

Each preset writes an independent, uploadable folder under
fixtures/test_sets/<name>/ containing bank_statement.csv, ledger.csv,
razorpay_settlements.json, ground_truth.json and manifest.json.

Usage:
    python scripts/generate_test_sets.py                 # all presets
    python scripts/generate_test_sets.py --presets clean,messy
    python scripts/generate_test_sets.py --list
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.evaluation.synthetic_generator import (  # noqa: E402
    SyntheticDataGenerator,
    write_fixture_files,
)

PRESETS: dict[str, tuple[int, dict[str, int]]] = {
    #            seed  perfect  fee  refund  dup  unrec   -> issues %
    "clean":    (101, {"perfect_match": 85, "fee_deduction": 10, "partial_refund": 3, "duplicate_utr": 1, "unrecognized_credit": 1}),
    "balanced": (42,  {"perfect_match": 60, "fee_deduction": 15, "partial_refund": 10, "duplicate_utr": 5, "unrecognized_credit": 10}),
    "messy":    (202, {"perfect_match": 35, "fee_deduction": 15, "partial_refund": 15, "duplicate_utr": 15, "unrecognized_credit": 20}),
    "stress":   (303, {"perfect_match": 20, "fee_deduction": 15, "partial_refund": 20, "duplicate_utr": 20, "unrecognized_credit": 25}),
}

OUT_ROOT = REPO_ROOT / "fixtures" / "test_sets"


def issue_share(counts: dict[str, int]) -> float:
    total = sum(counts.values())
    if not total:
        return 0.0
    return sum(n for name, n in counts.items() if name != "perfect_match") / total


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate multi-difficulty test sets")
    parser.add_argument("--presets", default="all", help="comma list or 'all'")
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    parser.add_argument("--list", action="store_true", help="show presets and exit")
    args = parser.parse_args()

    if args.list:
        print(f"{'preset':<10} {'seed':<6} issues")
        for name, (_seed, counts) in PRESETS.items():
            print(f"{name:<10} {_seed:<6} {issue_share(counts):>5.0%}")
        return 0

    names = (
        list(PRESETS)
        if args.presets.strip().lower() == "all"
        else [n.strip() for n in args.presets.split(",") if n.strip()]
    )
    unknown = [n for n in names if n not in PRESETS]
    if unknown:
        parser.error(f"unknown presets: {unknown}; available: {list(PRESETS)}")

    print(f"{'set':<10} {'seed':<6} {'cases':<6} {'razorpay':<9} {'bank':<6} {'ledger':<7} {'issues':<7} out")
    for name in names:
        seed, counts = PRESETS[name]
        result = SyntheticDataGenerator(seed=seed, case_counts=counts).generate()
        out_dir = args.out / name
        write_fixture_files(result, out_dir)

        manifest_counts = result.manifest["counts"]
        print(
            f"{name:<10} {seed:<6} {manifest_counts['total_cases']:<6} "
            f"{manifest_counts['razorpay_rows']:<9} {manifest_counts['bank_rows']:<6} "
            f"{manifest_counts['ledger_rows']:<7} "
            f"{issue_share(counts):>5.0%}  {out_dir}"
        )

    print("\nUpload one set at a time. Run scripts/reset_demo_data.py between sets.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
