"""Regression checks for data-grounded hypothesis grades and alternatives."""

from hypothesis_engine.evidence_ladder import assess_observed_pattern, normalize
from hypothesis_engine.investigate import _assess_candidates


def test_counterevidence_downgrades_grades_without_faking_confidence():
    assert normalize("Strong evidence", 2, 0) == "Strong evidence"
    assert normalize("Strong evidence", 2, 1) == "Moderate evidence"
    assert normalize("Moderate evidence", 1, 1) == "Limited evidence"
    assert normalize("Moderate evidence", 1, 2) == "Contradictory evidence"
    assert normalize("Strong evidence", 0, 1) == "Contradictory evidence"
    assert normalize("unknown") == "Insufficient evidence"


def test_segment_details_use_measured_spread_not_schema_guess():
    flat = assess_observed_pattern("segment", {
        "series": [{"label": "A", "value": 100}, {"label": "B", "value": 99}]
    })
    assert flat["evidence_grade"] == "Contradictory evidence"
    assert flat["measured_contradictions"]
    assert flat["rivals"]
    wide = assess_observed_pattern("segment", {
        "series": [{"label": "A", "value": 100}, {"label": "B", "value": 50}]
    })
    assert wide["evidence_grade"] == "Limited evidence"
    assert not wide["measured_contradictions"]


def test_trend_grade_downgrades_when_latest_bucket_reverses():
    pattern = {"series": [
        {"label": str(i), "value": value}
        for i, value in enumerate([10, 10, 10, 25, 25, 10])
    ]}
    result = assess_observed_pattern("trend", pattern)
    assert result["evidence_grade"] == "Limited evidence"
    assert result["measured_contradictions"]
    assert result["settled_data_notes"]


def test_trend_grade_uses_observed_periods_and_zero_baseline_guard():
    rising = {"series": [
        {"label": str(i), "value": value}
        for i, value in enumerate([10, 10, 10, 20, 20, 22])
    ]}
    assert assess_observed_pattern("trend", rising)["evidence_grade"] == "Moderate evidence"
    empty_base = {"series": [
        {"label": "earlier", "value": 0}, {"label": "later", "value": 50}
    ]}
    assert assess_observed_pattern("trend", empty_base)["evidence_grade"] == "Insufficient evidence"


def test_insufficient_until_real_measurements_present():
    assert assess_observed_pattern("segment", {})["evidence_grade"] == "Insufficient evidence"
    assert assess_observed_pattern("trend", {})["evidence_grade"] == "Insufficient evidence"


def test_investigation_rivals_are_other_candidates_not_fake_causal_proofs():
    candidates = [
        {"title": "Group contribution", "strength": "Moderate evidence",
         "supporting": ["Group share was measured"], "contradictory": [],
         "metrics": {}, "limitations": []},
        {"title": "Timing shift", "strength": "Limited evidence",
         "supporting": ["Observed time change"], "contradictory": [],
         "metrics": {}, "limitations": []},
    ]
    _assess_candidates(candidates, {"text": "Sales decreased across the period."})
    assert candidates[0]["evidence_grade"] == "Moderate evidence"
    assert candidates[0]["rival_explanations"][0]["title"] == "Timing shift"
    assert candidates[0]["settled_data_notes"]


def test_unmeasured_caveat_does_not_count_as_counterevidence():
    candidates = [{
        "title": "Document mentions supplier delays",
        "strength": "Limited evidence",
        "supporting": ["Document says deliveries were delayed"],
        "contradictory": ["No causal link was measured"],
        "metrics": {},
        "limitations": ["A document is not measured causality"],
    }]
    _assess_candidates(candidates, {})
    assert candidates[0]["evidence_grade"] == "Limited evidence"
