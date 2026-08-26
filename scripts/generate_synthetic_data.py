import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.evaluation.synthetic_generator import (  # noqa: E402
    DEFAULT_SEED,
    SyntheticDataGenerator,
    write_fixture_files,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the synthetic 100-case reconciliation fixture set"
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "fixtures" / "synthetic",
    )
    args = parser.parse_args()

    result = SyntheticDataGenerator(args.seed).generate()
    written = write_fixture_files(result, args.out)

    counts = result.manifest["counts"]
    print(f"seed={args.seed} out={args.out}")
    print(
        f"cases={counts['total_cases']} "
        f"razorpay_rows={counts['razorpay_rows']} "
        f"bank_rows={counts['bank_rows']} "
        f"ledger_rows={counts['ledger_rows']}"
    )
    for path in written:
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
