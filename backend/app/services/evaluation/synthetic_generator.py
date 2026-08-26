from __future__ import annotations

import csv
import hashlib
import io
import json
import random
import uuid
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from app.services.ingestion.money import parse_rupees_to_paise, rupees_from_paise

FIXTURE_VERSION = "synthetic-v1"
DEFAULT_SEED = 42
BASE_DATE = date(2026, 7, 1)
UTR_PREFIXES = ("AXIB", "HDFC", "ICIC", "SBIN", "UTIB")
UUID_NAMESPACE = uuid.UUID("6f1f2b0e-0f5a-4a3b-9c1d-a7b2c3d4e5f6")

CASE_COUNTS = {
    "perfect_match": 60,
    "fee_deduction": 15,
    "partial_refund": 10,
    "duplicate_utr": 5,
    "unrecognized_credit": 10,
}

CASE_ORDER = list(CASE_COUNTS)

EXPECTED_OUTCOMES = {
    "perfect_match": "auto_match",
    "fee_deduction": "auto_match",
    "partial_refund": "review_required",
    "duplicate_utr": "never_auto_match",
    "unrecognized_credit": "unresolved_exception",
}

EXPECTED_STRATEGIES = {
    "perfect_match": "UTR_EXACT",
    "fee_deduction": "LEDGER_NET_EXACT",
    "duplicate_utr": "DUPLICATE_UTR_REVIEW",
}

FORBIDDEN_LABEL_KEYS = {
    "scenario",
    "expected_class",
    "expected_outcome",
    "expected_strategy",
    "case_type",
    "ground_truth",
    "label",
    "labels",
    "duplicate_flag",
    "is_unrecognized",
}

FORBIDDEN_LABEL_TOKENS = (
    "perfect_match",
    "fee_deduction",
    "partial_refund",
    "duplicate_utr",
    "unrecognized_credit",
    "ground_truth",
    "expected_outcome",
    "expected_class",
)

SETTLEMENTS_FILE = "razorpay_settlements.json"
BANK_FILE = "bank_statement.csv"
LEDGER_FILE = "ledger.csv"
GROUND_TRUTH_FILE = "ground_truth.json"
MANIFEST_FILE = "manifest.json"

BANK_COLUMNS = [
    "txn_ref",
    "value_date",
    "description",
    "credit_amount_inr",
    "currency",
]

LEDGER_COLUMNS = [
    "ledger_entry_id",
    "invoice_ref",
    "posted_date",
    "gross_amount_inr",
    "fee_amount_inr",
    "tax_amount_inr",
    "refund_amount_inr",
    "currency",
    "narration",
]


def find_label_leaks(payload) -> list[str]:
    leaks: list[str] = []

    def walk(node, path: str) -> None:
        if isinstance(node, dict):
            for key, item in node.items():
                child_path = f"{path}.{key}"
                if isinstance(key, str) and key.lower() in FORBIDDEN_LABEL_KEYS:
                    leaks.append(child_path)
                walk(item, child_path)
        elif isinstance(node, (list, tuple)):
            for index, item in enumerate(node):
                walk(item, f"{path}[{index}]")
        elif isinstance(node, str):
            lowered = node.lower()
            for token in FORBIDDEN_LABEL_TOKENS:
                if token in lowered:
                    leaks.append(f"{path}~{token}")

    walk(payload, "$")
    return leaks


def _epoch_seconds(d: date) -> int:
    dt = datetime.combine(d, time(10, 30), tzinfo=timezone.utc)
    return int((dt - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds())


@dataclass
class GenerationResult:
    seed: int
    settlements: list[dict]
    bank_rows: list[dict]
    ledger_rows: list[dict]
    ground_truth: dict
    manifest: dict

    @property
    def cases(self) -> dict:
        return self.ground_truth["cases"]


class SyntheticDataGenerator:
    def __init__(
        self,
        seed: int = DEFAULT_SEED,
        case_counts: dict[str, int] | None = None,
    ):
        self.seed = seed
        self._rng = random.Random(seed)
        self._used_grosses: set[int] = set()
        if case_counts is None:
            self.case_counts: dict[str, int] = dict(CASE_COUNTS)
        else:
            unknown = set(case_counts) - set(CASE_COUNTS)
            if unknown:
                raise ValueError(f"unknown case types: {sorted(unknown)}")
            if any(not isinstance(n, int) or n < 0 for n in case_counts.values()):
                raise ValueError("case counts must be non-negative integers")
            self.case_counts = dict(case_counts)

    def generate(self) -> GenerationResult:
        settlements: list[dict] = []
        bank_rows: list[dict] = []
        ledger_rows: list[dict] = []
        cases: dict[str, dict] = {}
        used_utrs: set[str] = set()

        case_index = 0
        for case_type in CASE_ORDER:
            for _ in range(self.case_counts.get(case_type, 0)):
                case_id = self._stable_uuid(case_index, "case").hex
                builder = getattr(self, f"_build_{case_type}")
                built = builder(case_id, case_index, used_utrs)
                settlements.extend(built["settlements"])
                bank_rows.extend(built["bank_rows"])
                ledger_rows.extend(built["ledger_rows"])
                cases[case_id] = {
                    "case_type": case_type,
                    "expected_outcome": EXPECTED_OUTCOMES[case_type],
                    "source_ids": built["source_ids"],
                }
                strategy = EXPECTED_STRATEGIES.get(case_type)
                if strategy:
                    cases[case_id]["expected_strategy"] = strategy
                case_index += 1

        self._rng.shuffle(settlements)
        self._rng.shuffle(bank_rows)
        self._rng.shuffle(ledger_rows)

        ground_truth = {
            "fixture_version": FIXTURE_VERSION,
            "seed": self.seed,
            "counts": {"total": sum(self.case_counts.values()), **self.case_counts},
            "cases": cases,
        }

        result = GenerationResult(
            seed=self.seed,
            settlements=settlements,
            bank_rows=bank_rows,
            ledger_rows=ledger_rows,
            ground_truth=ground_truth,
            manifest={},
        )
        result.manifest = self._build_manifest(result)
        return result

    def _stable_uuid(self, index: int, tag: str) -> uuid.UUID:
        return uuid.uuid5(UUID_NAMESPACE, f"{self.seed}|{index}|{tag}")

    def _new_utr(self, used: set[str]) -> str:
        while True:
            utr = f"{self._rng.choice(UTR_PREFIXES)}{self._rng.randrange(10**9, 10**10)}"
            if utr not in used:
                used.add(utr)
                return utr

    def _settlement(self, index: int, seq: int, amount: int, fees: int, tax: int, utr: str, d: date) -> dict:
        return {
            "id": f"setl_{self._stable_uuid(index, f'settlement{seq}').hex[:16]}",
            "entity": "settlement",
            "amount": amount,
            "status": "processed",
            "currency": "INR",
            "fees": fees,
            "tax": tax,
            "utr": utr,
            "created_at": _epoch_seconds(d),
        }

    def _bank_row(self, index: int, ref_tag: str, d: date, description: str, paise: int) -> dict:
        return {
            "txn_ref": f"BNK{self._stable_uuid(index, ref_tag).hex[:14].upper()}",
            "value_date": d.isoformat(),
            "description": description,
            "credit_amount_inr": rupees_from_paise(paise),
            "currency": "INR",
        }

    def _ledger_row(
        self,
        index: int,
        gross: int,
        fees: int,
        tax: int,
        refund: int,
        d: date,
    ) -> tuple[dict, str]:
        entry_id = f"LDG{self._stable_uuid(index, 'ledger').hex[:14].upper()}"
        invoice_ref = f"INV-{self._stable_uuid(index, 'invoice').hex[:12].upper()}"
        row = {
            "ledger_entry_id": entry_id,
            "invoice_ref": invoice_ref,
            "posted_date": d.isoformat(),
            "gross_amount_inr": rupees_from_paise(gross),
            "fee_amount_inr": rupees_from_paise(fees),
            "tax_amount_inr": rupees_from_paise(tax),
            "refund_amount_inr": rupees_from_paise(refund),
            "currency": "INR",
            "narration": f"INVOICE {invoice_ref} SETTLEMENT",
        }
        return row, invoice_ref

    def _base_amounts(self) -> tuple[int, int, int, int]:
        while True:
            gross_rupees = self._rng.randrange(500, 50_001)
            gross = gross_rupees * 100
            if gross not in self._used_grosses:
                break
        self._used_grosses.add(gross)
        fees = self._rng.randrange(200, 1500)
        tax = fees * 18 // 100
        refund = 0
        return gross, fees, tax, refund

    def _dates(self, index: int) -> tuple[date, date, date]:
        settlement_date = BASE_DATE + timedelta(days=self._rng.randrange(0, 45))
        bank_offset = self._rng.choice((-1, 0, 0, 1))
        ledger_offset = self._rng.choice((-1, 0, 1))
        bank_date = settlement_date + timedelta(days=bank_offset)
        ledger_date = settlement_date + timedelta(days=ledger_offset)
        return settlement_date, bank_date, ledger_date

    def _build_perfect_match(self, case_id: str, index: int, used_utrs: set[str]) -> dict:
        gross, fees, tax, _ = self._base_amounts()
        fees, tax = 0, 0
        utr = self._new_utr(used_utrs)
        s_date, b_date, l_date = self._dates(index)
        settlement = self._settlement(index, 1, gross, fees, tax, utr, s_date)
        bank = self._bank_row(index, "bank", b_date, f"NEFT CR-{utr}", gross)
        ledger_row, _ = self._ledger_row(index, gross, fees, tax, 0, l_date)
        return {
            "settlements": [settlement],
            "bank_rows": [bank],
            "ledger_rows": [ledger_row],
            "source_ids": {
                "razorpay": [settlement["id"]],
                "bank": [bank["txn_ref"]],
                "ledger": [ledger_row["ledger_entry_id"]],
            },
        }

    def _build_fee_deduction(self, case_id: str, index: int, used_utrs: set[str]) -> dict:
        gross, fees, tax, _ = self._base_amounts()
        net = gross - fees - tax
        utr = self._new_utr(used_utrs)
        s_date, b_date, l_date = self._dates(index)
        settlement = self._settlement(index, 1, gross, fees, tax, utr, s_date)
        bank = self._bank_row(index, "bank", b_date, f"NEFT CR-{utr}", net)
        ledger_row, _ = self._ledger_row(index, gross, fees, tax, 0, l_date)
        return {
            "settlements": [settlement],
            "bank_rows": [bank],
            "ledger_rows": [ledger_row],
            "source_ids": {
                "razorpay": [settlement["id"]],
                "bank": [bank["txn_ref"]],
                "ledger": [ledger_row["ledger_entry_id"]],
            },
        }

    def _build_partial_refund(self, case_id: str, index: int, used_utrs: set[str]) -> dict:
        gross, fees, tax, _ = self._base_amounts()
        refund = gross * self._rng.randrange(20, 46) // 100
        net = gross - refund
        utr = self._new_utr(used_utrs)
        s_date, b_date, l_date = self._dates(index)
        settlement = self._settlement(index, 1, gross, fees, tax, utr, s_date)
        bank = self._bank_row(index, "bank", b_date, f"NEFT CR-{utr}", net)
        ledger_row, _ = self._ledger_row(index, gross, fees, tax, refund, l_date)
        return {
            "settlements": [settlement],
            "bank_rows": [bank],
            "ledger_rows": [ledger_row],
            "source_ids": {
                "razorpay": [settlement["id"]],
                "bank": [bank["txn_ref"]],
                "ledger": [ledger_row["ledger_entry_id"]],
            },
        }

    def _build_duplicate_utr(self, case_id: str, index: int, used_utrs: set[str]) -> dict:
        first, _, _, _ = self._base_amounts()
        delta = self._rng.randrange(1000, 50_000)
        second = max(100_00, first - delta)
        shared_utr = self._new_utr(used_utrs)
        s_date, b_date, l_date = self._dates(index)
        s2_date = s_date + timedelta(days=1)
        settlement_a = self._settlement(index, 1, first, 0, 0, shared_utr, s_date)
        settlement_b = self._settlement(index, 2, second, 0, 0, shared_utr, s2_date)
        bank = self._bank_row(index, "bank", b_date, f"NEFT CR-{shared_utr}", first)
        ledger_row, _ = self._ledger_row(index, first, 0, 0, 0, l_date)
        return {
            "settlements": [settlement_a, settlement_b],
            "bank_rows": [bank],
            "ledger_rows": [ledger_row],
            "source_ids": {
                "razorpay": [settlement_a["id"], settlement_b["id"]],
                "bank": [bank["txn_ref"]],
                "ledger": [ledger_row["ledger_entry_id"]],
            },
        }

    def _build_unrecognized_credit(self, case_id: str, index: int, used_utrs: set[str]) -> dict:
        gross, _, _, _ = self._base_amounts()
        _, b_date, _ = self._dates(index)
        digits = self._rng.randrange(10**8, 10**9)
        bank = self._bank_row(index, "bank", b_date, f"NEFT CREDIT REF {digits}", gross)
        return {
            "settlements": [],
            "bank_rows": [bank],
            "ledger_rows": [],
            "source_ids": {
                "razorpay": [],
                "bank": [bank["txn_ref"]],
                "ledger": [],
            },
        }

    def _build_manifest(self, result: GenerationResult) -> dict:
        files = {
            SETTLEMENTS_FILE: serialize_settlements(result.settlements).encode("utf-8"),
            BANK_FILE: serialize_bank_csv(result.bank_rows).encode("utf-8"),
            LEDGER_FILE: serialize_ledger_csv(result.ledger_rows).encode("utf-8"),
            GROUND_TRUTH_FILE: serialize_json(result.ground_truth).encode("utf-8"),
        }
        return {
            "fixture_version": FIXTURE_VERSION,
            "seed": self.seed,
            "synthetic": True,
            "counts": {
                **self.case_counts,
                "total_cases": sum(self.case_counts.values()),
                "razorpay_rows": len(result.settlements),
                "bank_rows": len(result.bank_rows),
                "ledger_rows": len(result.ledger_rows),
            },
            "sha256": {name: hashlib.sha256(data).hexdigest() for name, data in files.items()},
        }


def serialize_json(payload) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=True) + "\n"


def serialize_settlements(items: list[dict]) -> str:
    payload = {"entity": "collection", "count": len(items), "items": items}
    return serialize_json(payload)


def serialize_csv(rows: list[dict], columns: list[str]) -> str:
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return buffer.getvalue()


def serialize_bank_csv(rows: list[dict]) -> str:
    return serialize_csv(rows, BANK_COLUMNS)


def serialize_ledger_csv(rows: list[dict]) -> str:
    return serialize_csv(rows, LEDGER_COLUMNS)


def write_fixture_files(result: GenerationResult, out_dir: Path) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = [
        out_dir / SETTLEMENTS_FILE,
        out_dir / BANK_FILE,
        out_dir / LEDGER_FILE,
        out_dir / GROUND_TRUTH_FILE,
        out_dir / MANIFEST_FILE,
    ]
    (out_dir / SETTLEMENTS_FILE).write_text(serialize_settlements(result.settlements), encoding="utf-8", newline="\n")
    (out_dir / BANK_FILE).write_text(serialize_bank_csv(result.bank_rows), encoding="utf-8", newline="\n")
    (out_dir / LEDGER_FILE).write_text(serialize_ledger_csv(result.ledger_rows), encoding="utf-8", newline="\n")
    (out_dir / GROUND_TRUTH_FILE).write_text(serialize_json(result.ground_truth), encoding="utf-8", newline="\n")
    (out_dir / MANIFEST_FILE).write_text(serialize_json(result.manifest), encoding="utf-8", newline="\n")
    return written
