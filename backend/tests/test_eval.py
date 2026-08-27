"""The eval harness's refusals.

Section 6.5 says build this before the pilot; Section 15 says cite these numbers
rather than projections. The most important property of this harness is
therefore what it *won't* say: it must be impossible to get an accuracy figure
out of it that isn't backed by labelled field data.
"""

from __future__ import annotations

import json

import pytest

from app.eval import golden, metrics
from app.eval.metrics import UNVALIDATED


def _report(**overrides):
    kwargs = dict(
        truth_codes=[],
        predicted_ranked=[],
        portion_pairs=[],
        calorie_pairs=[],
        compliance_truth=[],
        compliance_pred=[],
        is_mock=False,
        weighed_only=True,
        uncalibrated_dishes=set(),
    )
    kwargs.update(overrides)
    return metrics.build_report(**kwargs)


# --------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------


def test_an_empty_golden_set_reports_unvalidated_not_zero() -> None:
    """A 0% would read as a failing model. The honest answer is 'not measured'."""
    report = _report()
    assert all(m.status == UNVALIDATED for m in report.metrics)
    assert all(m.value is None for m in report.metrics)
    assert report.any_validated is False


def test_the_mock_provider_blocks_every_accuracy_claim() -> None:
    """The offline provider validates plumbing, not recognition. Scoring against
    it would manufacture exactly the false number Section 6.5 warns about."""
    report = _report(
        is_mock=True,
        truth_codes=[{"dal"}],
        predicted_ranked=[["dal"]],
        portion_pairs=[(120.0, 118.0)],
    )
    assert report.blockers, "a mock run must be blocked"
    assert "mock" in report.blockers[0].lower()
    assert report.any_validated is False


def test_real_data_on_a_real_provider_does_report() -> None:
    report = _report(truth_codes=[{"dal"}], predicted_ranked=[["dal"]])
    assert not report.blockers
    assert report.any_validated is True


# --------------------------------------------------------------------------
# Metric behaviour
# --------------------------------------------------------------------------


def test_recognition_is_measured_per_item_not_per_plate() -> None:
    """A model that finds rice and misses three other dishes must not score the
    same as one that found everything."""
    value, n = metrics.top_k_recognition([{"dal", "rice", "sabzi", "banana"}], [["rice"]])
    assert n == 4
    assert value == pytest.approx(0.25)


def test_recognition_respects_the_top_k_cut() -> None:
    value, _ = metrics.top_k_recognition([{"banana"}], [["dal", "rice", "sabzi", "banana"]], k=3)
    assert value == 0.0  # banana was ranked fourth


def test_portion_error_only_scores_items_the_model_found() -> None:
    """A missed item is a recognition failure. Charging it to portion error too
    would penalise one mistake twice and make the metrics move together."""
    value, n = metrics.portion_mae([(120.0, 100.0), (150.0, 160.0)])
    assert n == 2
    assert value == pytest.approx(15.0)


def test_calorie_error_ignores_zero_truth_plates() -> None:
    value, n = metrics.calorie_mape([(0.0, 50.0), (400.0, 440.0)])
    assert n == 1
    assert value == pytest.approx(0.10)


def test_ground_truth_energy_uses_the_deterministic_path() -> None:
    """Calorie MAPE must isolate vision error. Ground truth goes through the
    same recipe and IFCT arithmetic as the prediction, so a recipe correction
    does not read as a model regression."""
    assert metrics.truth_energy_kcal([("rice", 150.0), ("dal", 120.0)]) == pytest.approx(
        300.8, abs=1.0
    )


def test_precision_and_recall_are_reported_separately() -> None:
    """They fail differently. A false positive wastes a block officer's trip; a
    false negative lets a non-compliant kitchen pass. Section 6.5 sets both."""
    precision, recall, n = metrics.precision_recall(
        truth=[True, True, False, False], predicted=[True, False, True, False]
    )
    assert n == 4
    assert precision == pytest.approx(0.5)
    assert recall == pytest.approx(0.5)


def test_precision_and_recall_are_none_when_nothing_was_flagged() -> None:
    precision, recall, _ = metrics.precision_recall([False, False], [False, False])
    assert precision is None and recall is None


# --------------------------------------------------------------------------
# Targets and caveats
# --------------------------------------------------------------------------


def test_targets_match_the_section_6_5_table() -> None:
    assert metrics.TARGETS == {
        "recognition_top3": 0.80,
        "portion_mae_g": 25.0,
        "calorie_mape": 0.15,
        "compliance_precision": 0.85,
        "compliance_recall": 0.85,
    }


def test_error_metrics_pass_when_low_and_accuracy_metrics_when_high() -> None:
    good_error = metrics.Metric("portion", 10.0, 5, 25.0, higher_is_better=False)
    bad_error = metrics.Metric("portion", 40.0, 5, 25.0, higher_is_better=False)
    good_acc = metrics.Metric("reco", 0.9, 5, 0.8, higher_is_better=True)
    bad_acc = metrics.Metric("reco", 0.5, 5, 0.8, higher_is_better=True)
    assert good_error.status == "meets target" and bad_error.status == "above target"
    assert good_acc.status == "meets target" and bad_acc.status == "below target"


def test_unweighed_plates_caveat_the_portion_metric() -> None:
    """Section 6.5's portion target assumes dietitian-weighed reference plates."""
    report = _report(portion_pairs=[(120.0, 118.0)], weighed_only=False)
    portion = next(m for m in report.metrics if "Portion" in m.name)
    assert portion.caveats and "weighed" in portion.caveats[0]


def test_weighed_plates_carry_no_such_caveat() -> None:
    report = _report(portion_pairs=[(120.0, 118.0)], weighed_only=True)
    portion = next(m for m in report.metrics if "Portion" in m.name)
    assert portion.caveats == ()


def test_uncalibrated_recipes_caveat_the_calorie_metric() -> None:
    """A systematic yield error moves truth and prediction together and would
    not show up in MAPE at all. Saying so is the only defence."""
    report = _report(calorie_pairs=[(400.0, 420.0)], uncalibrated_dishes={"dal", "rice"})
    calorie = next(m for m in report.metrics if "Calorie" in m.name)
    assert calorie.caveats and "yield factors" in calorie.caveats[0]
    assert "dal" in calorie.caveats[0]


def test_unvalidated_metrics_render_without_a_number() -> None:
    rendered = metrics.Metric("x", None, 0, 0.8, True).render()
    assert UNVALIDATED in rendered and "n=0" in rendered


# --------------------------------------------------------------------------
# Golden set loading
# --------------------------------------------------------------------------


def test_the_shipped_golden_set_is_empty_and_says_so() -> None:
    """Section 15: no labelled dataset exists for these dishes yet."""
    assert golden.load().is_empty is True


def test_a_label_outside_the_pm_poshan_vocabulary_is_rejected(tmp_path, monkeypatch) -> None:
    """Otherwise the metrics would compare against something the pipeline can
    never produce, and recognition accuracy would be permanently capped."""
    bad = tmp_path / "plates.jsonl"
    bad.write_text('{"image": "x.jpg", "items": [{"dish_code": "pizza", "cooked_grams": 100}]}\n')
    monkeypatch.setattr(golden, "PLATES_FILE", bad)
    with pytest.raises(golden.GoldenSetError, match="PM POSHAN"):
        golden.load()


def test_malformed_jsonl_names_the_offending_line(tmp_path, monkeypatch) -> None:
    bad = tmp_path / "plates.jsonl"
    bad.write_text('{"image": "a.jpg", "items": []}\nnot json at all\n')
    monkeypatch.setattr(golden, "PLATES_FILE", bad)
    with pytest.raises(golden.GoldenSetError, match="line 2"):
        golden.load()


def test_weighed_and_estimated_plates_are_separable(tmp_path, monkeypatch) -> None:
    path = tmp_path / "plates.jsonl"
    rows = [
        {"image": "a.jpg", "items": [{"dish_code": "dal", "cooked_grams": 120}],
         "weighed": True},
        {"image": "b.jpg", "items": [{"dish_code": "dal", "cooked_grams": 110}],
         "weighed": False},
    ]
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))
    monkeypatch.setattr(golden, "PLATES_FILE", path)
    data = golden.load()
    assert len(data.plates) == 2 and len(data.weighed_plates) == 1


def test_missing_image_files_are_detected_not_ignored(tmp_path, monkeypatch) -> None:
    """A silently skipped plate makes a partial run look like a complete one."""
    path = tmp_path / "plates.jsonl"
    path.write_text('{"image": "nope.jpg", "items": [{"dish_code": "dal", "cooked_grams": 1}]}\n')
    monkeypatch.setattr(golden, "PLATES_FILE", path)
    assert golden.load().missing_images() == ["nope.jpg"]
