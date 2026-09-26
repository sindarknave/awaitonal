"""Labeled-fixture evaluation reports identifiers and scores, never response text."""
import json
from pathlib import Path
import statistics
import time
from .types import DELIVERY_KINDS, EXPECTANCIES, Event, GESTURES, STATES


# These annotations are optional: outcome-only fixtures keep their original
# report and each new dimension is scored only where it has its own label.
DIMENSIONS = {
    "gesture": GESTURES,
    "expectancy": EXPECTANCIES,
    "delivery_kind": DELIVERY_KINDS,
}


def _dimension_report(values):
    return {
        "cases": 0,
        "correct": 0,
        "accuracy": None,
        "confusion_matrix": {expected: dict.fromkeys((*values, "ignored"), 0) for expected in values},
        "failures": [],
    }


def evaluate(classifier, fixture_path: str | Path) -> dict:
    matrix = {expected: {actual: 0 for actual in (*STATES, "ignored")} for expected in STATES}
    failures, false_attention, false_rejection, timings = [], [], [], []
    dimensions = {}
    seen = set()
    for line in Path(fixture_path).read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        case_id, expected = case["id"], case["expected"]
        if not isinstance(case_id, str) or case_id in seen or expected not in STATES:
            raise ValueError("Evaluation fixture requires unique string IDs and valid expected states")
        for name, values in DIMENSIONS.items():
            if "expected_" + name in case and case["expected_" + name] not in values:
                raise ValueError(f"Evaluation fixture requires a valid expected_{name}")
        seen.add(case_id)
        event = Event("evaluation", case_id, case.get("text", ""), case.get("explicit_state"), "evaluation")
        start = time.perf_counter()
        outcome = classifier.classify(event)
        timings.append((time.perf_counter() - start) * 1000)
        actual = outcome.state if outcome else "ignored"
        matrix[expected][actual] += 1
        if expected != actual:
            failures.append({"id": case_id, "expected": expected, "actual": actual})
        if actual == "needs-you" and expected != actual:
            false_attention.append(case_id)
        if actual == "rejected" and expected != actual:
            false_rejection.append(case_id)
        for name, values in DIMENSIONS.items():
            label = "expected_" + name
            if label not in case:
                continue
            if name not in dimensions:
                dimensions[name] = _dimension_report(values)
            report = dimensions[name]
            wanted = case[label]
            observed = getattr(outcome, name) if outcome is not None else "ignored"
            report["cases"] += 1
            report["confusion_matrix"][wanted][observed] += 1
            if wanted == observed:
                report["correct"] += 1
            else:
                report["failures"].append({"id": case_id, "expected": wanted, "actual": observed})
    count = len(seen)
    report = {"cases": count, "correct": count - len(failures),
              "accuracy": (count - len(failures)) / count if count else None,
              "confusion_matrix": matrix, "failures": failures,
              "false_attention": false_attention, "false_rejection": false_rejection,
              "classification_ms": {"first": timings[0] if timings else None,
                                    "warm_median": statistics.median(timings[1:]) if len(timings) > 1 else None,
                                    "max": max(timings) if timings else None}}
    if dimensions:
        for dimension in dimensions.values():
            dimension["accuracy"] = dimension["correct"] / dimension["cases"]
        report["dimensions"] = dimensions
    return report
