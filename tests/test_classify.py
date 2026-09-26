import subprocess
import sys
import json
from pathlib import Path

import pytest
from awaitonal.classify import RulesClassifier, is_waiting
from awaitonal.text import assistant_prose
from awaitonal.types import Event


@pytest.mark.parametrize("text,expected", [
    ("Implemented the fix and all tests pass.", "done"),
    ("Implemented the fix; integration tests could not run in this environment.", "caveats"),
    ("Which database should I use? I need your choice before continuing.", "needs-you"),
    ("Which database should I use before proceeding?", "needs-you"),
    ("Done. Would you also like a CSV export?", "done"),
    ("I cannot help implement that request.", "rejected"),
    ("The first build failed, but I fixed it and the final build passes.", "done"),
    ("The first build failed. I fixed it and the final build passes.", "done"),
    ("May I run the package installer?", "needs-you"),
    ("Please approve the tool invocation.", "needs-you"),
    ("Done. Integration tests were unavailable.", "caveats"),
    ('> I cannot help with the request.\nDone.\n```python\nprint("Which option?")\n```', "done"),
    ('The log said "I cannot help". The fix is complete.', "done"),
    ("Done. If you want, I can add more examples.", "done"),
    ("Here is a description of the proposed work.", "unknown"),
    ("The work is not done.", "caveats"),
    ("I inspected the files before I fixed the bug. Done.", "done"),
    ("I am no longer waiting for your approval. Done.", "done"),
])
def test_prose_contrasts(text, expected):
    answer = RulesClassifier().classify(Event("test", "1", text))
    assert answer.state == expected
    assert answer.evidence_source == "text"
    assert answer.reason


@pytest.mark.parametrize("text", ["", "  ", "```\nI cannot help.\n```", "> Which one?", None, "a" * 131_073])
def test_no_prose_is_ignored(text):
    assert RulesClassifier().classify(Event("s", "e", text)) is None


def test_explicit_override_and_invalid():
    classifier = RulesClassifier()
    answer = classifier.classify(Event("s", "e", "I cannot help", "needs-you", "claude:PermissionRequest"))
    assert answer.state == "needs-you"
    assert answer.controls.needs_you and not answer.controls.rejected
    assert classifier.classify(Event("s", "e", "Done", "bogus")) is None
    assert classifier.classify({"text": "Done"}) is None


def test_quoted_and_unclosed_fences_are_removed():
    assert assistant_prose('Done. `raise Exception("help?")`\n~~~python\nI refuse.') == "Done."
    assert "refuse" not in assistant_prose("Done. ‘I refuse.’")


@pytest.mark.parametrize("text", [
    "The patch is not ready.",
    "This is not working.",
    "The issue is not fixed.",
    "The work isn't complete.",
    "I haven't finished the update.",
    "I have not yet implemented the migration.",
    "It doesn't work.",
    "The checks still fail.",
])
def test_negated_completion_is_not_success(text):
    assert RulesClassifier().classify(Event("s", "e", text)).state == "caveats"


@pytest.mark.parametrize("text", [
    "I was waiting for your answer. You answered and I completed the changes.",
    "I was blocked on your approval. Your approval was granted. Everything is done.",
    "I need your permission. You granted permission and the operation succeeded.",
    "I was waiting for your decision. I now have your decision and the feature is complete.",
])
def test_explicit_resolution_of_earlier_waiting(text):
    assert RulesClassifier().classify(Event("s", "e", text)).state == "done"


def test_completion_does_not_imply_permission_resolution():
    text = "I need your approval to deploy. The implementation is complete."
    assert RulesClassifier().classify(Event("s", "e", text)).state == "needs-you"


def test_temporary_inability_with_permission_is_waiting():
    text = "I cannot help because I need your approval before proceeding."
    assert RulesClassifier().classify(Event("s", "e", text)).state == "needs-you"


@pytest.mark.parametrize("text,expected", [
    ("Which option before proceeding?", True),
    ("WHAT should happen until we continue?", True),
    ("How should I proceed? Pick before continuing.", True),
    ("Which option\nbefore I continue?", True),
    ("Which option. Work before proceeding.", False),
    ("How should I proceed! Work before continuing.", False),
    ("Before proceeding, which option?", False),
    ("Somewhat before proceeding.", False),
])
def test_waiting_question_preserves_dependency_order_and_boundaries(text, expected):
    assert is_waiting(text) is expected


@pytest.mark.parametrize("text,expected", [
    ("I need your approval.\nYou have\napproved. Done.", "done"),
    ("I need your approval got your\napproval was granted. Done.", "done"),
    ("Approval was granted. I need your approval.", "needs-you"),
    ("I need your approval. Approval was granted. I need your decision.", "needs-you"),
])
def test_only_later_resolution_resolves_waiting_across_sentences(text, expected):
    assert RulesClassifier().classify(Event("s", "e", text)).state == expected


@pytest.mark.parametrize("text,expected", [
    ("which " * 21_000, "unknown"),
    ("I need your approval.\n" * 5_000 + "You approved. Done.", "done"),
    ("Previously waiting for your approval.\n" * 3_000, "unknown"),
], ids=["question-prefixes", "resolved-repeat", "historical-repeat"])
def test_adversarial_prose_finishes_promptly(text, expected):
    # A process timeout bounds failures even if quadratic scanning returns.
    # These inputs previously took seconds; allow ample headroom over the
    # corrected millisecond-scale work and interpreter startup on CI runners.
    process = subprocess.run(
        [sys.executable, "-c",
         "import sys; from awaitonal.classify import RulesClassifier; "
         "from awaitonal.types import Event; "
         "print(RulesClassifier().classify(Event('s', 'e', sys.stdin.read())).state)"],
        input=text, capture_output=True, text=True, timeout=5, check=True,
    )
    assert process.stdout.strip() == expected


_CONTRASTS = [json.loads(line) for line in
              (Path(__file__).parents[1] / "examples/classification-vNext.jsonl").read_text().splitlines()]


@pytest.mark.parametrize("case", _CONTRASTS, ids=lambda case: case["id"])
def test_classification_development_contrasts(case):
    event = Event("synthetic", case["id"], case["text"],
                  background_tasks=case.get("background_tasks"), session_crons=case.get("session_crons"))
    answer = RulesClassifier().classify(event)
    assert answer is not None
    for field in ("state", "gesture", "delivery_kind", "expectancy", "handoff_kind", "activity", "assessment_kind"):
        key = "expected" if field == "state" else "expected_" + field
        if key in case:
            assert getattr(answer, field) == case[key], field


def test_unknown_does_not_claim_completion_or_loose_ends():
    answer = RulesClassifier().classify(Event("s", "e", "Understood."))
    assert answer.state == "unknown"
    assert answer.gesture == "answer"
    assert answer.controls.loose_ends == 0
    assert not answer.attention


def test_link_queries_do_not_leak_into_diagnostics():
    answer = RulesClassifier().classify(Event("s", "e", "Here is your [report](https://claude.ai/artifacts/abc?secret=xyz#private)."))
    assert answer.gesture == "artifact"
    assert "secret" not in json.dumps(answer.to_dict())
