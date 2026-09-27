"""Pi's extension bridge forwards only final prose or bounded lifecycle facts."""
import json
import subprocess
import sys

import pytest

from awaitonal.adapter import MAX_INPUT, adapt_claude, adapt_codex, adapt_pi, event_from_wire
from awaitonal.classify import RulesClassifier
from awaitonal.client import run_hook
from awaitonal.semantic import SemanticClassifier

REQUEST_ID = "483427d2-fbde-42e5-a844-698a676968b7"


def payload(name="agent_settled", **fields):
    base = {"session_id": "session-123", "turn_id": "turn-456", "hook_event_name": name}
    if name == "agent_settled":
        base.update(outcome="completed", last_assistant_message="Implemented the fix. All tests pass.")
    elif name == "ui_prompt_start":
        base["request_id"] = REQUEST_ID
    return {**base, **fields}


@pytest.mark.parametrize("value", [None, [], 1, "Done", True, {}])
def test_non_events_are_quiet(value):
    assert adapt_pi(value) is None


@pytest.mark.parametrize("field,value", [
    ("session_id", None), ("session_id", []), ("session_id", " "),
    ("session_id", "s" * 257), ("session_id", "é" * 129), ("session_id", "\ud800"),
    ("turn_id", None), ("turn_id", []), ("turn_id", "t" * 257),
    ("turn_id", "é" * 129), ("turn_id", "\ud800"),
    ("last_assistant_message", {}), ("last_assistant_message", []),
    ("last_assistant_message", False), ("last_assistant_message", "\ud800"),
    ("last_assistant_message", "é" * (MAX_INPUT // 2 + 1)),
    ("outcome", "success"), ("outcome", "unknown"), ("outcome", None), ("outcome", []),
    ("hook_event_name", "Stop"), ("hook_event_name", "agent_error"),
    ("hook_event_name", "agent_quiet"), ("hook_event_name", "tool_result"),
    ("hook_event_name", "ui_prompt_end"), ("hook_event_name", "turn_end"),
])
def test_malformed_or_unsupported_inputs_do_not_create_notifications(field, value):
    assert adapt_pi(payload(**{field: value})) is None


def test_only_final_text_and_pi_scoped_identity_are_retained():
    source = payload(prompt="PRIVATE PROMPT", title="PRIVATE TITLE", transcript_path="PRIVATE PATH",
                     messages=[{"text": "PRIVATE HISTORY"}], evidence_source="claude:StopFailure",
                     explicit_state="needs-you", failure_code="rate_limit", background_tasks=[], session_crons=[])
    event = adapt_pi(source)
    assert event.session_id == "pi:session-123" and event.turn_id == "turn-456"
    assert event.evidence_source == "pi:agent_settled" and event.event_id == "stop:turn-456"
    assert event.text == source["last_assistant_message"] and event.explicit_state is None
    assert event.failure_code is event.background_tasks is event.session_crons is None
    assert "PRIVATE" not in json.dumps(event.to_dict())
    common = {**source, "hook_event_name": "Stop", "prompt_id": source["turn_id"]}
    assert len({event.session_id, adapt_claude(common).session_id, adapt_codex(common).session_id}) == 3


@pytest.mark.parametrize("session", ["s" * 256, "é" * 128])
@pytest.mark.parametrize("turn", ["t" * 256, "é" * 128])
def test_long_ids_are_stable_bounded_and_round_trip(session, turn):
    start = adapt_pi(payload("agent_start", session_id=session, turn_id=turn))
    stop = adapt_pi(payload(session_id=session, turn_id=turn))
    assert start.session_id == stop.session_id and start.turn_id == stop.turn_id
    assert len(stop.session_id.encode()) <= 256
    assert len(start.event_id) <= 256 and len(stop.event_id) <= 256
    assert event_from_wire(start.to_dict()) == start
    assert event_from_wire(stop.to_dict()) == stop


def test_missing_turn_does_not_invent_correlation():
    source = payload()
    del source["turn_id"]
    event = adapt_pi(source)
    assert event.turn_id == "" and event.event_id.startswith("stop:")
    assert event == adapt_pi(source)


def test_start_discards_prompt_and_caller_timing():
    event = adapt_pi(payload("agent_start", prompt="PRIVATE", timestamp=42, duration_ms=50))
    assert event.kind == "turn-start" and event.text == "" and event.failure_code is None
    assert event.evidence_source == "pi:agent_start"
    assert "PRIVATE" not in json.dumps(event.to_dict())


def test_terminal_error_has_no_prose_or_invented_error_category():
    event = adapt_pi(payload(outcome="error", last_assistant_message="PRIVATE API ERROR",
                             error="authentication_failed", error_details="PRIVATE DETAILS"))
    assert event.evidence_source == "pi:agent_error" and event.text == ""
    assert event.explicit_state == "failed" and event.failure_code == "unknown"
    assert RulesClassifier().classify(event).gesture == "failed"
    assert "PRIVATE" not in json.dumps(event.to_dict())


@pytest.mark.parametrize("patch", [
    {"outcome": "aborted", "last_assistant_message": "PRIVATE partial output"},
    {"last_assistant_message": None}, {"last_assistant_message": ""}, {"last_assistant_message": " \n"},
])
def test_aborts_and_empty_settlements_end_timing_without_a_classification(patch):
    event = adapt_pi(payload(**patch))
    assert event.kind == "turn-end" and event.evidence_source == "pi:agent_quiet"
    assert event.text == "" and event.explicit_state is event.failure_code is None
    assert event_from_wire(event.to_dict()) == event
    assert RulesClassifier().classify(event) is None
    # Lifecycle markers cannot reach the semantic encoder either.
    assert SemanticClassifier.classify(object(), event) is None


def test_completed_settlement_without_a_message_is_a_quiet_end():
    source = payload()
    del source["last_assistant_message"]
    assert adapt_pi(source).kind == "turn-end"


def test_ui_prompt_identity_is_uuid_based_and_drops_title_and_options():
    event = adapt_pi(payload("ui_prompt_start", title="PRIVATE QUESTION", options=["PRIVATE OPTION"]))
    assert event.explicit_state == "needs-you" and event.text == ""
    assert event.evidence_source == "pi:ui_prompt_start"
    assert event.event_id == "question:" + REQUEST_ID and event.dedup_key == "ui:" + REQUEST_ID
    assert RulesClassifier().classify(event).gesture == "decision"
    assert "PRIVATE" not in json.dumps(event.to_dict())
    assert event == adapt_pi(payload("ui_prompt_start", title="Different title", request_id=REQUEST_ID.upper()))


@pytest.mark.parametrize("request_id", [None, "", " ", 1, [], "not-a-uuid", "0" * 37])
def test_ui_prompt_requires_a_valid_request_uuid(request_id):
    assert adapt_pi(payload("ui_prompt_start", request_id=request_id)) is None


@pytest.mark.parametrize("source", [payload(), payload("agent_start"), payload("ui_prompt_start"),
                                  payload(outcome="error"), payload(outcome="aborted")])
def test_supported_events_round_trip_wire(source):
    event = adapt_pi(source)
    assert event_from_wire(json.loads(json.dumps(event.to_dict()))) == event


@pytest.mark.parametrize("source,patch", [
    (payload(), {"evidence_source": "pi:Stop"}),
    (payload(), {"evidence_source": "pi:ui_prompt_end"}),
    (payload(), {"explicit_state": "needs-you"}),
    (payload(), {"kind": "turn-start"}),
    (payload(), {"kind": "turn-end"}),
    (payload(), {"dedup_key": "ui:spoofed"}),
    (payload(), {"background_tasks": 0}),
    (payload(), {"session_crons": 0}),
    (payload(), {"session_id": "another-provider"}),
    (payload(), {"session_id": "pi:"}),
    (payload(), {"session_id": "pi: "}),
    (payload(), {"text": "\ud800"}),
    (payload(outcome="error"), {"failure_code": "rate_limit"}),
    (payload(outcome="error"), {"failure_code": None}),
    (payload(outcome="error"), {"text": "PRIVATE ERROR"}),
    (payload(outcome="error"), {"dedup_key": "tool:spoofed"}),
    (payload(outcome="error"), {"explicit_state": "needs-you"}),
    (payload("ui_prompt_start"), {"text": "PRIVATE TITLE"}),
    (payload("ui_prompt_start"), {"failure_code": "unknown"}),
    (payload("ui_prompt_start"), {"explicit_state": None}),
    (payload("ui_prompt_start"), {"event_id": "question:not-a-uuid"}),
    (payload("ui_prompt_start"), {"dedup_key": "ui:different"}),
    (payload("ui_prompt_start"), {"kind": "turn-end"}),
    (payload("agent_start"), {"text": "PRIVATE PROMPT"}),
    (payload("agent_start"), {"explicit_state": "needs-you"}),
    (payload(outcome="aborted"), {"kind": "notification"}),
    (payload(outcome="aborted"), {"kind": "turn-start"}),
    (payload(outcome="aborted"), {"text": "PRIVATE partial output"}),
    (payload(outcome="aborted"), {"failure_code": "unknown"}),
    (payload(outcome="aborted"), {"explicit_state": "failed"}),
    (payload(outcome="aborted"), {"dedup_key": "tool:private"}),
    (payload(outcome="aborted"), {"evidence_source": "text"}),
    (payload(outcome="aborted"), {"background_tasks": 0}),
])
def test_wire_rejects_fabricated_pi_capabilities_or_inconsistent_fields(source, patch):
    assert event_from_wire({**adapt_pi(source).to_dict(), **patch}) is None


def test_pi_client_forwards_supported_payload_without_agent_feedback(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr("awaitonal.client.read_hook_input", lambda: json.dumps(payload()).encode())
    monkeypatch.setattr("awaitonal.client.send_event", lambda event, path: sent.append((event, path)))
    assert run_hook("/tmp/test.sock", adapter="pi") == 0
    assert sent == [(adapt_pi(payload()), "/tmp/test.sock")]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("outcome", ["aborted", "error", "completed"])
def test_pi_cli_dry_run(outcome):
    process = subprocess.run([sys.executable, "-m", "awaitonal", "hook", "pi", "--dry-run"],
                             input=json.dumps(payload(outcome=outcome)), capture_output=True, text=True, timeout=3)
    assert process.returncode == 0 and process.stderr == ""
    result = json.loads(process.stdout)
    if outcome == "aborted":
        assert result == {"recorded": "turn-end", "silent": True}
    else:
        assert result["gesture"] == ("failed" if outcome == "error" else "done")
