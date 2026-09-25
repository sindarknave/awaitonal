"""Held-out evaluation output contains identifiers and scores, never response text."""
import json
from pathlib import Path
import statistics
import time
from .types import Event, STATES


def evaluate(classifier, fixture_path: str | Path) -> dict:
    matrix = {expected: {actual: 0 for actual in (*STATES, "ignored")} for expected in STATES}
    failures, false_attention, false_rejection, timings = [], [], [], []
    seen = set()
    for line in Path(fixture_path).read_text().splitlines():
        if not line.strip():
            continue
        case = json.loads(line)
        case_id, expected = case["id"], case["expected"]
        if not isinstance(case_id, str) or case_id in seen or expected not in STATES:
            raise ValueError("Evaluation fixture requires unique string IDs and valid expected states")
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
    count = len(seen)
    return {"cases": count, "correct": count - len(failures),
            "accuracy": (count - len(failures)) / count if count else None,
            "confusion_matrix": matrix, "failures": failures,
            "false_attention": false_attention, "false_rejection": false_rejection,
            "classification_ms": {"first": timings[0] if timings else None,
                                  "warm_median": statistics.median(timings[1:]) if len(timings) > 1 else None,
                                  "max": max(timings) if timings else None}}
