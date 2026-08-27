from __future__ import annotations

import uuid
from decimal import Decimal

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import DEMO_ORG_ID
from app.models import (
    ExceptionRecord,
    MatchGroup,
    MatchMember,
    ReconciliationRun,
    Transaction,
)

STRATEGY_EXACT_UTR_AMOUNT = "EXACT_UTR_AMOUNT"
STRATEGY_AMOUNT_DATE_WINDOW = "AMOUNT_DATE_WINDOW"
STRATEGY_LEDGER_NET_EXACT = "LEDGER_NET_EXACT"

CATEGORY_PENDING_AI_REVIEW = "PENDING_AI_REVIEW"
CATEGORY_AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"

DATE_WINDOW_DAYS = 2

STRATEGY_SCORES = {
    STRATEGY_EXACT_UTR_AMOUNT: Decimal("1.000"),
    STRATEGY_AMOUNT_DATE_WINDOW: Decimal("0.900"),
    STRATEGY_LEDGER_NET_EXACT: Decimal("1.000"),
}

STRATEGY_EVIDENCE_ROLE = {
    STRATEGY_EXACT_UTR_AMOUNT: "razorpay_settlement",
    STRATEGY_AMOUNT_DATE_WINDOW: "razorpay_settlement",
    STRATEGY_LEDGER_NET_EXACT: "ledger_entry",
}

_COLUMNS = [
    "id",
    "external_id",
    "kind",
    "amount_paise",
    "gross_amount_paise",
    "fee_paise",
    "tax_paise",
    "currency",
    "effective_date",
    "n_utr",
]


def _normalize_utr(value: str | None) -> str:
    return (value or "").strip().upper()


def _is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and pd.isna(value))


def _money_equal(left, right) -> bool:
    left_missing = _is_missing(left)
    right_missing = _is_missing(right)
    if left_missing or right_missing:
        return left_missing and right_missing
    return int(left) == int(right)


def _load_frame(db: Session, org_id: uuid.UUID) -> pd.DataFrame:
    txns = db.execute(
        select(Transaction).where(Transaction.org_id == org_id)
    ).scalars().all()
    records = [
        {
            "id": t.id,
            "external_id": t.external_id,
            "kind": t.transaction_kind,
            "amount_paise": int(t.amount_paise),
            "gross_amount_paise": t.gross_amount_paise,
            "fee_paise": t.fee_paise,
            "tax_paise": t.tax_paise,
            "currency": (t.currency or "").strip().upper(),
            "effective_date": pd.Timestamp(t.effective_date),
            "n_utr": _normalize_utr(t.utr),
        }
        for t in txns
    ]
    return pd.DataFrame(records, columns=_COLUMNS)


def _pool(df: pd.DataFrame, kind: str, exclude: set) -> pd.DataFrame:
    frame = df[(df["kind"] == kind) & (~df["id"].isin(exclude))].copy()
    return frame.reset_index(drop=True)


def _row(frame: pd.DataFrame, txn_id) -> pd.Series:
    return frame[frame["id"] == txn_id].iloc[0]


class _RunState:
    def __init__(self):
        self.claimed_banks: set = set()
        self.used_settlements: set = set()
        self.used_ledgers: set = set()
        self.duplicate_utrs: set[str] = set()


def _create_group(
    db: Session,
    run_id: uuid.UUID,
    org_id: uuid.UUID,
    strategy: str,
    members: list[tuple[pd.Series, str]],
    rule_trace: dict,
) -> MatchGroup:
    bank_row = next(row for row, role in members if role == "bank_credit")
    expected_amount = int(bank_row["amount_paise"])

    evidence_role = STRATEGY_EVIDENCE_ROLE[strategy]
    evidence_row = next(
        (row for row, role in members if role == evidence_role),
        bank_row,
    )
    actual_amount = int(evidence_row["amount_paise"])

    group = MatchGroup(
        org_id=org_id,
        batch_id=run_id,
        strategy=strategy,
        status="matched",
        deterministic_score=STRATEGY_SCORES[strategy],
        expected_amount_paise=expected_amount,
        actual_amount_paise=actual_amount,
        delta_paise=actual_amount - expected_amount,
        rule_trace=rule_trace,
    )
    db.add(group)
    db.flush()

    for row, role in members:
        db.add(
            MatchMember(
                match_group_id=group.id,
                transaction_id=row["id"],
                role=role,
                allocated_paise=int(row["amount_paise"]),
            )
        )
    db.flush()
    return group


def _find_enrichment_ledger(
    ledger_pool: pd.DataFrame,
    used_ledgers: set,
    bank_row: pd.Series,
    settlement_row: pd.Series,
) -> pd.Series | None:
    candidates = ledger_pool[
        (~ledger_pool["id"].isin(used_ledgers))
        & (ledger_pool["amount_paise"] == int(bank_row["amount_paise"]))
        & (ledger_pool["gross_amount_paise"] == int(settlement_row["amount_paise"]))
        & (ledger_pool["currency"] == settlement_row["currency"])
    ].copy()
    if candidates.empty:
        return None
    candidates = candidates[
        candidates.apply(
            lambda l: _money_equal(l["fee_paise"], settlement_row["fee_paise"])
            and _money_equal(l["tax_paise"], settlement_row["tax_paise"]),
            axis=1,
        )
    ]
    if len(candidates) == 1:
        return candidates.iloc[0]
    return None


def _strategy_exact_utr_amount(db, run_id, org_id, banks, settlements, ledgers, state):
    created: list[uuid.UUID] = []
    usable = banks[banks["n_utr"] != ""]
    available = settlements[~settlements["id"].isin(state.used_settlements)]
    if usable.empty or available.empty:
        return created

    candidates = usable.merge(
        available, on=["n_utr", "amount_paise", "currency"], suffixes=("_bank", "_setl")
    )
    if candidates.empty:
        return created

    per_bank = candidates.groupby("id_bank")["id_setl"].transform("size")
    per_setl = candidates.groupby("id_setl")["id_bank"].transform("size")
    unique_pairs = candidates[(per_bank == 1) & (per_setl == 1)]

    for txn_id in sorted(unique_pairs["id_bank"].tolist(), key=str):
        pair = unique_pairs[unique_pairs["id_bank"] == txn_id].iloc[0]
        bank_row = _row(banks, pair["id_bank"])
        settlement_row = _row(settlements, pair["id_setl"])

        trace = {
            "candidates_considered": int((candidates["id_bank"] == pair["id_bank"]).sum()),
            "normalized_utr": str(pair["n_utr"]),
            "amount_paise": int(pair["amount_paise"]),
        }

        members = [(bank_row, "bank_credit"), (settlement_row, "razorpay_settlement")]
        used_here: list = []
        ledger_row = _find_enrichment_ledger(ledgers, state.used_ledgers, bank_row, settlement_row)
        if ledger_row is not None:
            members.append((ledger_row, "ledger_entry"))
            used_here.append(ledger_row["id"])
            trace["ledger_enrichment"] = str(ledger_row["external_id"])

        group = _create_group(db, run_id, org_id, STRATEGY_EXACT_UTR_AMOUNT, members, trace)
        created.append(group.id)
        state.claimed_banks.add(bank_row["id"])
        state.used_settlements.add(settlement_row["id"])
        state.used_ledgers.update(used_here)

    return created


def _strategy_amount_date_window(db, run_id, org_id, banks, settlements, ledgers, state):
    created: list[uuid.UUID] = []
    open_banks = banks[
        (banks["n_utr"] == "") & (~banks["id"].isin(state.claimed_banks))
    ]
    available = settlements[~settlements["id"].isin(state.used_settlements)]
    if open_banks.empty or available.empty:
        return created

    candidates = open_banks.merge(
        available, on=["amount_paise", "currency"], suffixes=("_bank", "_setl")
    )
    candidates = candidates[
        (candidates["effective_date_bank"] - candidates["effective_date_setl"]).abs()
        <= pd.Timedelta(days=DATE_WINDOW_DAYS)
    ]
    if candidates.empty:
        return created

    per_bank = candidates.groupby("id_bank")["id_setl"].transform("size")
    per_setl = candidates.groupby("id_setl")["id_bank"].transform("size")
    unique_pairs = candidates[(per_bank == 1) & (per_setl == 1)]

    for txn_id in sorted(unique_pairs["id_bank"].tolist(), key=str):
        pair = unique_pairs[unique_pairs["id_bank"] == txn_id].iloc[0]
        bank_row = _row(open_banks, pair["id_bank"])
        settlement_row = _row(available, pair["id_setl"])

        trace = {
            "candidates_considered": int((candidates["id_bank"] == pair["id_bank"]).sum()),
            "amount_paise": int(pair["amount_paise"]),
            "date_window_days": DATE_WINDOW_DAYS,
        }

        members = [(bank_row, "bank_credit"), (settlement_row, "razorpay_settlement")]
        used_here: list = []
        ledger_row = _find_enrichment_ledger(ledgers, state.used_ledgers, bank_row, settlement_row)
        if ledger_row is not None:
            members.append((ledger_row, "ledger_entry"))
            used_here.append(ledger_row["id"])
            trace["ledger_enrichment"] = str(ledger_row["external_id"])

        group = _create_group(db, run_id, org_id, STRATEGY_AMOUNT_DATE_WINDOW, members, trace)
        created.append(group.id)
        state.claimed_banks.add(bank_row["id"])
        state.used_settlements.add(settlement_row["id"])
        state.used_ledgers.update(used_here)

    return created


def _matching_settlement_ids(
    available_settlements: pd.DataFrame,
    ledger_gross: int,
    ledger_fee,
    ledger_tax,
    currency: str,
    bank_n_utr: str,
    exclude: set,
) -> list:
    rows = available_settlements[
        (~available_settlements["id"].isin(exclude))
        & (available_settlements["amount_paise"] == ledger_gross)
        & (available_settlements["currency"] == currency)
    ]
    matches = []
    for _, s in rows.iterrows():
        if not _money_equal(s["fee_paise"], ledger_fee):
            continue
        if not _money_equal(s["tax_paise"], ledger_tax):
            continue
        if bank_n_utr and s["n_utr"] and bank_n_utr != s["n_utr"]:
            continue
        matches.append(s)
    return matches


def _strategy_ledger_net_exact(db, run_id, org_id, banks, settlements, ledgers, state):
    created: list[uuid.UUID] = []
    open_banks = banks[~banks["id"].isin(state.claimed_banks)]
    available_ledgers = ledgers[~ledgers["id"].isin(state.used_ledgers)]
    available_settlements = settlements
    if open_banks.empty or available_ledgers.empty or available_settlements.empty:
        return created

    candidates = open_banks.merge(
        available_ledgers, on=["amount_paise", "currency"], suffixes=("_bank", "_ledg")
    )
    if candidates.empty:
        return created

    plans_by_bank: dict = {}
    candidate_counts: dict = {}
    for _, row in candidates.iterrows():
        candidate_counts[row["id_bank"]] = candidate_counts.get(row["id_bank"], 0) + 1
        if row["id_bank"] in state.claimed_banks:
            continue
        if row["id_ledg"] in state.used_ledgers:
            continue
        bank_n_utr = str(row["n_utr_bank"])
        if bank_n_utr and bank_n_utr in state.duplicate_utrs:
            continue
        matches = _matching_settlement_ids(
            available_settlements,
            int(row["gross_amount_paise_ledg"]),
            row["fee_paise_ledg"],
            row["tax_paise_ledg"],
            row["currency"],
            bank_n_utr,
            exclude=state.used_settlements,
        )
        if len(matches) == 1:
            plans_by_bank.setdefault(row["id_bank"], []).append((row["id_ledg"], matches[0]["id"]))

    for txn_id in sorted(plans_by_bank.keys(), key=str):
        plan = plans_by_bank[txn_id]
        ledger_ids = {ledger_id for ledger_id, _ in plan}
        settlement_ids = {sid for _, sid in plan}
        if len(plan) != 1 or len(ledger_ids) != 1 or len(settlement_ids) != 1:
            continue

        bank_row = _row(banks, txn_id)
        ledger_row = _row(ledgers, next(iter(ledger_ids)))
        settlement_row = _row(settlements, next(iter(settlement_ids)))

        trace = {
            "candidates_considered": candidate_counts.get(txn_id, 0),
            "equation": (
                "ledger_net == bank_credit AND "
                "ledger_gross/fee/tax == razorpay settlement evidence"
            ),
            "normalized_utr": str(bank_row["n_utr"]),
            "amount_paise": int(bank_row["amount_paise"]),
        }

        members = [
            (bank_row, "bank_credit"),
            (settlement_row, "razorpay_settlement"),
            (ledger_row, "ledger_entry"),
        ]
        group = _create_group(db, run_id, org_id, STRATEGY_LEDGER_NET_EXACT, members, trace)
        created.append(group.id)
        state.claimed_banks.add(bank_row["id"])
        state.used_settlements.add(settlement_row["id"])
        state.used_ledgers.add(ledger_row["id"])

    return created


def _existing_member_txn_ids(db: Session) -> set:
    return set(db.execute(select(MatchMember.transaction_id)).scalars())


def _existing_exception_txn_ids(db: Session) -> set:
    rows = db.execute(
        select(ExceptionRecord.transaction_id).where(
            ExceptionRecord.transaction_id.is_not(None)
        )
    ).scalars()
    return set(rows)


def _create_residue_exceptions(
    db: Session,
    run_id: uuid.UUID,
    df: pd.DataFrame,
    unmatched_bank_ids: list,
    skip_txn_ids: set,
) -> list[ExceptionRecord]:
    created: list[ExceptionRecord] = []
    settlements = df[df["kind"] == "settlement"]

    utr_index: dict[str, list] = {}
    for _, row in settlements.iterrows():
        if row["n_utr"]:
            utr_index.setdefault(row["n_utr"], []).append(row["id"])

    for txn_id in unmatched_bank_ids:
        if txn_id in skip_txn_ids:
            continue
        bank_row = df[df["id"] == txn_id].iloc[0]
        n_utr = str(bank_row["n_utr"])
        related = utr_index.get(n_utr, [])

        related_settlements = [
            {
                "transaction_id": str(rid),
                "external_id": str(
                    df.loc[df["id"] == rid, "external_id"].iloc[0]
                ),
                "amount_paise": int(
                    df.loc[df["id"] == rid, "amount_paise"].iloc[0]
                ),
            }
            for rid in related
        ]

        if n_utr and len(related) >= 2:
            category = CATEGORY_AMBIGUOUS_MATCH
            reason_code = "MULTIPLE_SETTLEMENT_CANDIDATES"
            reason = (
                f"UTR {n_utr} maps to {len(related)} settlements; "
                "auto-match is refused when candidates are not unique"
            )
        elif n_utr and len(related) == 1:
            category = CATEGORY_PENDING_AI_REVIEW
            reason_code = "NO_DETERMINISTIC_MATCH"
            reason = (
                "single UTR candidate found but amounts/equations did not reconcile "
                "deterministically"
            )
        else:
            category = CATEGORY_PENDING_AI_REVIEW
            reason_code = "NO_CANDIDATE"
            reason = "no settlement or ledger candidate matched this bank credit deterministically"

        record = ExceptionRecord(
            batch_id=run_id,
            transaction_id=txn_id,
            status="unresolved",
            taxonomy=category,
            evidence={
                "reason_code": reason_code,
                "explanation": reason,
                "normalized_utr": n_utr or None,
                "bank_transaction_id": str(txn_id),
                "bank_external_id": str(bank_row["external_id"]),
                "bank_amount_paise": int(bank_row["amount_paise"]),
                "bank_currency": str(bank_row["currency"]),
                "bank_effective_date": str(pd.Timestamp(bank_row["effective_date"]).date()),
                "candidate_deltas_paise": [
                    entry["amount_paise"] - int(bank_row["amount_paise"])
                    for entry in related_settlements
                ],
                "related_settlement_transaction_ids": [str(i) for i in related],
                "related_settlements": related_settlements,
            },
            model_name=None,
            prompt_version=None,
            response=None,
            confidence=None,
            retry_count=0,
        )
        db.add(record)
        created.append(record)
    db.flush()
    return created


def _summarize(db: Session, org_id: uuid.UUID, run_id: uuid.UUID) -> dict:
    total_bank_ids = set(
        db.execute(
            select(Transaction.id).where(
                Transaction.org_id == org_id,
                Transaction.transaction_kind == "bank_credit",
            )
        ).scalars()
    )

    matched_bank_ids = set(
        db.execute(
            select(MatchMember.transaction_id)
            .join(MatchGroup, MatchGroup.id == MatchMember.match_group_id)
            .join(Transaction, Transaction.id == MatchMember.transaction_id)
            .where(
                MatchGroup.batch_id == run_id,
                Transaction.org_id == org_id,
                Transaction.transaction_kind == "bank_credit",
            )
        ).scalars()
    )

    total = len(total_bank_ids)
    matched = len(matched_bank_ids & total_bank_ids)
    unmatched = total - matched
    rate = round(matched / total, 4) if total else 0.0

    strategy_rows = db.execute(
        select(MatchGroup.strategy).where(MatchGroup.batch_id == run_id)
    ).scalars().all()
    strategy_counts: dict[str, int] = {}
    for strategy in strategy_rows:
        strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

    taxonomy_rows = db.execute(
        select(ExceptionRecord.taxonomy).where(ExceptionRecord.batch_id == run_id)
    ).scalars().all()
    exceptions_by_category: dict[str, int] = {}
    for taxonomy in taxonomy_rows:
        key = taxonomy or "UNSPECIFIED"
        exceptions_by_category[key] = exceptions_by_category.get(key, 0) + 1

    exceptions_created = len(
        db.execute(
            select(ExceptionRecord.id).where(ExceptionRecord.batch_id == run_id)
        ).scalars().all()
    )
    groups_created = len(strategy_rows)

    return {
        "total_bank_transactions": total,
        "matched_bank_transactions": matched,
        "unmatched_bank_transactions": unmatched,
        "deterministic_match_rate": rate,
        "exceptions_created": exceptions_created,
        "strategy_counts": strategy_counts,
        "match_groups_created": groups_created,
        "match_groups_total": groups_created,
        "exceptions_total": sum(exceptions_by_category.values()),
        "exceptions_by_category": exceptions_by_category,
    }


def start_reconciliation_run(db: Session, org_id: uuid.UUID | None = None) -> dict:
    org = org_id or uuid.UUID(DEMO_ORG_ID)

    run = ReconciliationRun(org_id=org, status="running", summary={})
    db.add(run)
    db.flush()

    df = _load_frame(db, org)
    already_matched: set = set()
    already_exceptioned: set = set()

    state = _RunState()
    all_settlements = df[df["kind"] == "settlement"]
    if not all_settlements.empty:
        utr_counts = all_settlements["n_utr"].value_counts()
        state.duplicate_utrs = {
            str(utr) for utr, count in utr_counts.items() if utr and count >= 2
        }

    banks = _pool(df, "bank_credit", exclude=already_matched)
    settlements = _pool(df, "settlement", exclude=already_matched)
    if state.duplicate_utrs:
        settlements = settlements[
            ~settlements["n_utr"].isin(state.duplicate_utrs)
        ].reset_index(drop=True)
    ledgers = _pool(df, "ledger_entry", exclude=already_matched)

    _strategy_exact_utr_amount(db, run.id, org, banks, settlements, ledgers, state)
    _strategy_amount_date_window(db, run.id, org, banks, settlements, ledgers, state)
    _strategy_ledger_net_exact(db, run.id, org, banks, settlements, ledgers, state)

    unmatched_bank_ids = [
        txn_id for txn_id in sorted(banks["id"].tolist(), key=str)
        if txn_id not in state.claimed_banks
    ]

    _create_residue_exceptions(db, run.id, df, unmatched_bank_ids, already_exceptioned)

    summary = _summarize(db, org, run.id)
    run.status = "completed"
    run.summary = summary
    db.flush()

    return {"run_id": str(run.id), "status": run.status, "summary": summary}


def get_reconciliation_run(db: Session, run_id: uuid.UUID) -> dict | None:
    run = db.get(ReconciliationRun, run_id)
    if run is None:
        return None
    return {"run_id": str(run.id), "status": run.status, "summary": run.summary}
