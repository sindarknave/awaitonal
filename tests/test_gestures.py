"""Outcome, delivery, and human expectancy choose a single playback gesture."""
import json

import pytest

from awaitonal.adapter import adapt_claude
from awaitonal.classify import RulesClassifier
from awaitonal.types import Classification, Event, GESTURES, controls_for


@pytest.mark.parametrize("text,gesture,state", [
    ("I implemented the requested interface change. All tests pass.", "done", "done"),
    ("Here is the diagnosis: the counter uses a different filter, which explains the discrepancy.", "answer", "done"),
    ("Here is the plan: first isolate the data layer, then add coverage.", "plan", "done"),
    ("I rendered the video and saved the output file. It is ready to inspect.", "artifact", "done"),
    ("I pushed the commits to the requested branch.", "published", "done"),
    ("The preview is ready. Please review it and tell me what you think.", "review", "done"),
    ("Which option should I implement? I need your choice before continuing.", "decision", "needs-you"),
    ("Please complete SSO sign-in in the browser so I can continue.", "needs-you", "needs-you"),
    ("Implemented the update. Integration tests could not run in this environment.", "caveats", "caveats"),
    ("I cannot help implement that request.", "rejected", "rejected"),
])
def test_all_palette_routes_from_prose(text, gesture, state):
    result = RulesClassifier().classify(Event("s", "e", text))
    assert result.state == state
    assert result.gesture == gesture
    assert result.to_dict()["gesture"] == gesture


def test_review_invitation_does_not_claim_a_blocking_dependency():
    result = RulesClassifier().classify(Event("s", "e", "Please review the draft and tell me what you think."))
    assert result.expectancy == "review-requested"
    assert result.gesture == "review"
    assert not result.controls.needs_you and not result.attention


@pytest.mark.parametrize("text,gesture", [
    ("The patch is complete. Please approve it so I can publish.", "authorization"),
    ("I rendered the preview. Sign in to SSO so I can continue.", "needs-you"),
    ("I pushed the code. Please run the diagnostic and send the output so I can continue.", "needs-you"),
])
def test_required_handoff_wins_over_reported_delivery(text, gesture):
    result = RulesClassifier().classify(Event("s", "e", text))
    assert result.gesture == gesture and result.attention
    assert result.expectancy == "required-handoff"


@pytest.mark.parametrize("text", [
    "The setup guide is complete. Its sign-in section explains that users authenticate through SSO during installation.",
    "The draft is available to review whenever useful; no response is needed.",
    "Authentication succeeded, and the command has finished.",
    'Done. The example says "Please approve the deployment".',
])
def test_ordinary_delivery_does_not_get_expectant_cue(text):
    result = RulesClassifier().classify(Event("s", "e", text))
    assert result.expectancy == "none"
    assert result.gesture not in ("review", "decision", "needs-you")
    assert not result.attention


def test_structured_question_and_permission_use_distinct_required_cues():
    question = adapt_claude({"session_id": "s", "hook_event_name": "PreToolUse",
                            "tool_name": "AskUserQuestion", "tool_use_id": "q",
                            "tool_input": {"questions": [{"question": "Which version?"}]}})
    permission = adapt_claude({"session_id": "s", "hook_event_name": "PermissionRequest",
                              "tool_name": "Bash", "tool_input": {"command": "private command"}})
    for event, gesture in ((question, "decision"), (permission, "needs-you")):
        result = RulesClassifier().classify(event)
        assert result.state == "needs-you" and result.gesture == gesture
        assert result.attention and result.expectancy == "required-handoff"
        assert "private command" not in json.dumps(result.to_dict())


def test_original_classification_constructor_and_gesture_precedence():
    assert Classification("done", controls_for("done"), "text", "Complete").gesture == "done"
    result = Classification("rejected", controls_for("rejected"), "text", "Declined",
                            delivery_kind="plan", expectancy="review-requested")
    assert result.gesture == "rejected"
    assert set(GESTURES) == {"done", "answer", "plan", "artifact", "published", "review",
                             "decision", "needs-you", "caveats", "rejected", "failed",
                             "verdict", "in-flight", "authorization"}


def test_uncertainty_uses_answer_without_claiming_completion():
    result = Classification("unknown", controls_for("unknown"), "text", "No clear outcome")
    assert result.gesture == "answer" and result.state == "unknown"
    assert not result.attention


@pytest.mark.parametrize("fields,gesture", [
    ({"assessment_kind": "verdict", "delivery_kind": "answer"}, "verdict"),
    ({"activity": "in-flight"}, "in-flight"),
    ({"activity": "in-flight", "expectancy": "review-requested"}, "review"),
])
def test_activity_and_assessment_have_distinct_nonblocking_gestures(fields, gesture):
    result = Classification("done", controls_for("done"), "text", "Reported result", **fields)
    assert result.gesture == gesture
    assert not result.attention


def test_authorization_remains_a_required_handoff_even_with_background_work():
    result = Classification("needs-you", controls_for("needs-you"), "text", "Awaiting approval",
                            expectancy="required-handoff", handoff_kind="authorization",
                            activity="in-flight", delivery_kind="artifact")
    assert result.gesture == "authorization"
    assert result.attention


@pytest.mark.parametrize("text,state,gesture", [
    ("Assessment: The requested security review remains unfinished.", "caveats", "caveats"),
    ("Analysis: the cause remains unverified.", "caveats", "caveats"),
    ("I failed to finish the requested migration. Here is a plan for the remaining work.", "caveats", "caveats"),
    ("I could not fix the bug. Here is my analysis: the dependency is missing.", "caveats", "caveats"),
    ("I need your approval, and integration tests remain unverified. Approval was granted. Done.", "caveats", "caveats"),
    ("I cannot proceed until you sign in. Authentication succeeded. Done.", "done", "done"),
    ("I cannot help until you sign in. Authentication succeeded. Done.", "done", "done"),
    ("I cannot provide the report because the source API is unavailable.", "caveats", "caveats"),
    ("I cannot provide the requested report yet. Please sign in so I can fetch it.", "needs-you", "needs-you"),
    ("I cannot help with this request right now because the service is offline.", "caveats", "caveats"),
    ("I cannot provide exploit code. Here is a safer plan: audit permissions and patch the server.", "rejected", "rejected"),
    ("I cannot help steal credentials. Please choose a defensive alternative.", "rejected", "rejected"),
    ("I will mark the task done tomorrow.", "unknown", "answer"),
    ("I need your approval and your choice of deployment region. Approval was granted. Done.", "needs-you", "decision"),
    ("Please review the draft and sign in. Authentication succeeded. The draft is ready.", "done", "review"),
])
def test_mixed_outcomes_preserve_unfinished_work_and_current_dependencies(text, state, gesture):
    result = RulesClassifier().classify(Event("s", "e", text))
    assert (result.state, result.gesture) == (state, gesture)
