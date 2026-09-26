import json
from types import SimpleNamespace

import pytest

from awaitonal.evaluation import evaluate


class FixtureClassifier:
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.events = []

    def classify(self, event):
        self.events.append(event)
        return self.outcomes[event.event_id]


def fixtures(tmp_path, cases):
    path = tmp_path / "evaluation.jsonl"
    path.write_text("".join(json.dumps(case) + "\n" for case in cases))
    return path


def outcome(state, gesture, expectancy="none", delivery_kind="unknown"):
    return SimpleNamespace(state=state, gesture=gesture, expectancy=expectancy,
                           delivery_kind=delivery_kind,
                           activity="unknown", assessment_kind="none", handoff_kind="action",
                           reason="PRIVATE-CLASSIFIER-REASON", diagnostics={"text": "PRIVATE-DIAGNOSTICS"})


def test_uncertainty_and_action_errors_are_not_hidden_in_aggregate_score(tmp_path):
    path = fixtures(tmp_path, [
        {"id": "neutral", "expected": "unknown", "expected_activity": "unknown", "text": "PRIVATE"},
        {"id": "missed", "expected": "needs-you", "expected_handoff_kind": "authorization"},
        {"id": "false-limit", "expected": "done", "expected_assessment_kind": "verdict"},
    ])
    classifier = FixtureClassifier({"neutral": outcome("unknown", "answer"),
                                    "missed": outcome("unknown", "answer"),
                                    "false-limit": outcome("caveats", "caveats")})
    report = evaluate(classifier, path)
    assert report["quality"] == {"false_caveats": ["false-limit"], "missed_handoffs": ["missed"],
                                 "unknown_count": 2, "unknown_fraction": 2 / 3}
    assert report["dimensions"]["activity"]["correct"] == 1
    assert report["dimensions"]["assessment_kind"]["correct"] == 0
    assert report["dimensions"]["handoff_kind"]["correct"] == 0
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("value", [True, -1, 513, "running", []])
def test_invalid_background_evaluation_metadata_is_rejected(tmp_path, value):
    path = fixtures(tmp_path, [{"id": "bad", "expected": "unknown", "background_tasks": value}])
    with pytest.raises(ValueError, match="background counts"):
        evaluate(FixtureClassifier({}), path)


def test_background_context_reaches_evaluator_without_retaining_text(tmp_path):
    path = fixtures(tmp_path, [{"id": "ongoing", "expected": "unknown", "background_tasks": 2,
                                "session_crons": 0, "text": "PRIVATE"}])
    classifier = FixtureClassifier({"ongoing": outcome("unknown", "answer")})
    report = evaluate(classifier, path)
    assert classifier.events[0].background_tasks == 2
    assert classifier.events[0].session_crons == 0
    assert "PRIVATE" not in json.dumps(report)


def test_outcome_only_fixtures_preserve_original_report_shape(tmp_path):
    path = fixtures(tmp_path, [
        {"id": "right", "expected": "done", "text": "PRIVATE-RESPONSE"},
        {"id": "attention", "expected": "done", "text": "A question."},
    ])
    classifier = FixtureClassifier({
        "right": outcome("done", "artifact", delivery_kind="artifact"),
        "attention": outcome("needs-you", "decision", "required-handoff"),
    })
    report = evaluate(classifier, path)
    assert set(report) == {"cases", "correct", "accuracy", "confusion_matrix", "failures",
                           "false_attention", "false_rejection", "classification_ms", "quality"}
    assert report["cases"] == 2 and report["correct"] == 1 and report["accuracy"] == 0.5
    assert report["false_attention"] == ["attention"]
    assert report["confusion_matrix"]["done"]["needs-you"] == 1
    assert "PRIVATE" not in json.dumps(report)
    assert classifier.events[0].text == "PRIVATE-RESPONSE"


def test_gesture_expectancy_and_delivery_scores_have_independent_denominators(tmp_path):
    path = fixtures(tmp_path, [
        {"id": "review", "expected": "done", "expected_gesture": "review",
         "expected_expectancy": "review-requested", "text": "PRIVATE-RESPONSE"},
        {"id": "answer", "expected": "done", "expected_gesture": "answer",
         "expected_delivery_kind": "answer", "text": "A completed answer."},
        {"id": "legacy", "expected": "needs-you", "text": "Permission required."},
        {"id": "missing", "expected": "done", "expected_gesture": "published",
         "expected_expectancy": "none", "expected_delivery_kind": "published", "text": "An output."},
    ])
    classifier = FixtureClassifier({
        "review": outcome("done", "review", "review-requested", "artifact"),
        "answer": outcome("done", "plan", delivery_kind="plan"),
        "legacy": outcome("needs-you", "decision", "required-handoff"),
        "missing": None,
    })
    report = evaluate(classifier, path)
    assert report["cases"] == 4 and report["correct"] == 3 and report["accuracy"] == 0.75
    assert report["failures"] == [{"id": "missing", "expected": "done", "actual": "ignored"}]
    gesture = report["dimensions"]["gesture"]
    assert gesture["cases"] == 3 and gesture["correct"] == 1
    assert gesture["accuracy"] == pytest.approx(1 / 3)
    assert gesture["confusion_matrix"]["answer"]["plan"] == 1
    assert gesture["confusion_matrix"]["published"]["ignored"] == 1
    assert gesture["failures"] == [
        {"id": "answer", "expected": "answer", "actual": "plan"},
        {"id": "missing", "expected": "published", "actual": "ignored"},
    ]
    expectancy = report["dimensions"]["expectancy"]
    assert expectancy["cases"] == 2 and expectancy["correct"] == 1 and expectancy["accuracy"] == 0.5
    assert expectancy["confusion_matrix"]["none"]["ignored"] == 1
    delivery = report["dimensions"]["delivery_kind"]
    assert delivery["cases"] == 2 and delivery["correct"] == 0 and delivery["accuracy"] == 0.0
    assert delivery["confusion_matrix"]["answer"]["plan"] == 1
    assert "PRIVATE" not in json.dumps(report)


@pytest.mark.parametrize("dimension,value", [
    ("gesture", "decision"),
    ("expectancy", "required-handoff"),
    ("delivery_kind", "unknown"),
])
def test_only_labeled_extra_dimension_appears(tmp_path, dimension, value):
    path = fixtures(tmp_path, [{"id": "one", "expected": "needs-you", "expected_" + dimension: value}])
    classifier = FixtureClassifier({"one": outcome("needs-you", "decision", "required-handoff")})
    report = evaluate(classifier, path)
    assert set(report["dimensions"]) == {dimension}
    assert report["dimensions"][dimension]["cases"] == 1
    assert report["dimensions"][dimension]["accuracy"] == 1.0


@pytest.mark.parametrize("field,value", [
    ("expected_gesture", "not-a-gesture"),
    ("expected_gesture", None),
    ("expected_expectancy", "needs-you"),
    ("expected_expectancy", []),
    ("expected_delivery_kind", "review"),
    ("expected_delivery_kind", False),
])
def test_invalid_extra_labels_are_rejected_before_classification(tmp_path, field, value):
    path = fixtures(tmp_path, [{"id": "bad", "expected": "done", field: value}])
    classifier = FixtureClassifier({})
    with pytest.raises(ValueError, match=field):
        evaluate(classifier, path)
    assert not classifier.events


def test_empty_fixture_has_no_unlabeled_dimension_scores(tmp_path):
    report = evaluate(FixtureClassifier({}), fixtures(tmp_path, []))
    assert report["cases"] == 0 and report["correct"] == 0 and report["accuracy"] is None
    assert "dimensions" not in report
