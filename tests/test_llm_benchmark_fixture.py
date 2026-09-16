"""Integrity checks for the hand-reviewed live-model benchmark fixture."""

import json
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "llm_benchmark_cases.json"


def test_benchmark_fixture_is_complete_and_policy_versioned():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    cases = data["cases"]

    assert data["version"] == 2
    assert len(cases) == 41
    assert len({case["id"] for case in cases}) == 41
    assert sum(case["expected"]["is_job"] for case in cases) == 29
    assert all(case["raw_text"].strip() for case in cases)
    assert all(case["metadata_text"].strip() for case in cases)

    for case in cases:
        if case["expected"]["is_job"]:
            assert case["expected"]["country"]
            assert case["expected"]["position"]


def test_current_policy_excludes_student_award_and_future_opening_cases():
    cases = {
        case["id"]: case
        for case in json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    }

    assert cases[7]["expected"]["is_job"] is False
    assert cases[16]["expected"]["is_job"] is False
    assert "label_note" in cases[7]
    assert "label_note" in cases[16]
