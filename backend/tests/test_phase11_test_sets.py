import csv
import json
from pathlib import Path

import pytest

from app.services.evaluation.synthetic_generator import (
    find_label_leaks,
)
from app.services.evaluation.synthetic_generator import (
    SyntheticDataGenerator,
    write_fixture_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

PRESETS = {
    "clean": (101, {"perfect_match": 85, "fee_deduction": 10, "partial_refund": 3, "duplicate_utr": 1, "unrecognized_credit": 1}),
    "stress": (303, {"perfect_match": 20, "fee_deduction": 15, "partial_refund": 20, "duplicate_utr": 20, "unrecognized_credit": 25}),
}


def _generate(name: str, tmp_path: Path):
    seed, counts = PRESETS[name]
    result = SyntheticDataGenerator(seed=seed, case_counts=counts).generate()
    write_fixture_files(result, tmp_path / name)
    return result


def test_custom_case_counts_are_honored(tmp_path):
    for name in PRESETS:
        result = _generate(name, tmp_path)
        counts = result.ground_truth["counts"]
        assert counts == {"total": sum(PRESETS[name][1].values()), **PRESETS[name][1]}
        assert result.manifest["counts"]["total_cases"] == sum(PRESETS[name][1].values())

    clean_rows = len(_generate("clean", tmp_path).settlements)
    stress_rows = len(_generate("stress", tmp_path).settlements)
    assert clean_rows == 85 + 10 + 3 + 2 * 1
    assert stress_rows == 20 + 15 + 20 + 2 * 20


def test_presets_deterministic_per_seed_and_counts(tmp_path):
    a = SyntheticDataGenerator(seed=101, case_counts=PRESETS["clean"][1]).generate()
    b = SyntheticDataGenerator(seed=101, case_counts=PRESETS["clean"][1]).generate()
    assert a.settlements == b.settlements
    assert a.ground_truth == b.ground_truth

    c = SyntheticDataGenerator(seed=102, case_counts=PRESETS["clean"][1]).generate()
    assert c.settlements != a.settlements


def test_preset_ids_do_not_collide_across_sets():
    ids_a = {s["id"] for s in _generate("clean", Path(__file__).parent).settlements}
    ids_b = {s["id"] for s in _generate("stress", Path(__file__).parent).settlements}
    assert ids_a.isdisjoint(ids_b)


def test_preset_outputs_stay_flat_and_leak_free(tmp_path):
    generated = _generate("stress", tmp_path)
    for settlement in generated.settlements:
        for value in settlement.values():
            assert not isinstance(value, (dict, list, tuple))
            assert value is not None
    leaks = find_label_leaks(json.loads(json.dumps(generated.bank_rows)))
    assert leaks == []


def test_invalid_preset_rejected():
    with pytest.raises(ValueError):
        SyntheticDataGenerator(case_counts={"scenario_x": 5})
    with pytest.raises(ValueError):
        SyntheticDataGenerator(case_counts={"perfect_match": -1})


def test_generated_csv_files_parse(tmp_path):
    write_fixture_files(_generate("clean", tmp_path), tmp_path / "clean")
    bank = list(csv.DictReader((tmp_path / "clean" / "bank_statement.csv").open(encoding="utf-8")))
    gt = json.loads((tmp_path / "clean" / "ground_truth.json").read_text(encoding="utf-8"))
    expected_total = sum(PRESETS["clean"][1].values())
    assert len(bank) == expected_total
    assert len(gt["cases"]) == expected_total == 100
