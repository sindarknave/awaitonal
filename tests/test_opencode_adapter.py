"""The native OpenCode plugin sends a strict, content-minimized protocol."""
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from awaitonal.adapter import MAX_INPUT, adapt_claude, adapt_codex, adapt_opencode, adapt_pi, event_from_wire
from awaitonal.classify import RulesClassifier
from awaitonal.client import run_hook
from awaitonal.semantic import SemanticClassifier

TURN_ID = "483427d2-fbde-42e5-a844-698a676968b7"
REQUEST_ID = "8490b860-4555-4de5-98c6-6828722cf9b5"
NEXT_TURN = "beafaf34-7b8f-4028-aaf9-2cdcb7b2e148"


def payload(name="agent_settled", **fields):
    base = {"hook_event_name": name, "session_id": "session-123", "turn_id": TURN_ID}
    if name == "agent_settled":
        outcome = fields.get("outcome", "completed")
        base["outcome"] = outcome
        if outcome == "completed":
            base["last_assistant_message"] = "Implemented the fix. All tests pass."
    elif name in ("permission_asked", "question_asked"):
        base["request_id"] = REQUEST_ID
    return {**base, **fields}


@pytest.mark.parametrize("source", [None, [], 1, "Done", True, {}])
def test_non_events_are_quiet(source):
    assert adapt_opencode(source) is None


@pytest.mark.parametrize("field,value", [
    ("session_id", None), ("session_id", []), ("session_id", " "),
    ("session_id", "s" * 257), ("session_id", "é" * 129), ("session_id", "\ud800"),
    ("turn_id", None), ("turn_id", []), ("turn_id", ""), ("turn_id", "not-a-uuid"),
    ("turn_id", "\ud800"), ("turn_id", "0" * 37),
    ("last_assistant_message", {}), ("last_assistant_message", []), ("last_assistant_message", False),
    ("last_assistant_message", "\ud800"), ("last_assistant_message", "é" * (MAX_INPUT // 2 + 1)),
    ("last_assistant_message", " " * (MAX_INPUT + 1)),
    ("outcome", None), ("outcome", []), ("outcome", "success"),
    ("hook_event_name", "session.idle"), ("hook_event_name", "Stop"), ("hook_event_name", "agent_error"),
    ("hook_event_name", "session_start"), ("hook_event_name", "tool_result"),
    ("hook_event_name", "permission_replied"), ("hook_event_name", "question_replied"),
])
def test_malformed_or_unsupported_input_is_ignored(field, value):
    assert adapt_opencode(payload(**{field: value})) is None


@pytest.mark.parametrize("field", ["session_id", "turn_id", "hook_event_name", "outcome"])
def test_required_settlement_fields_cannot_be_invented(field):
    source = payload()
    del source[field]
    assert adapt_opencode(source) is None


@pytest.mark.parametrize("name", ["agent_start", "agent_settled", "permission_asked", "question_asked"])
@pytest.mark.parametrize("field,value", [
    ("prompt", "PRIVATE PROMPT"), ("transcript_path", "PRIVATE PATH"), ("title", "PRIVATE TITLE"),
    ("error_details", "PRIVATE ERROR"), ("background_tasks", []), ("session_crons", []),
    ("evidence_source", "claude:Stop"), ("explicit_state", "needs-you"), ("duration_ms", 150000),
])
def test_unknown_metadata_is_not_part_of_the_normalized_protocol(name, field, value):
    assert adapt_opencode(payload(name, **{field: value})) is None


@pytest.mark.parametrize("source", [
    payload("agent_start", outcome="completed"), payload("agent_start", last_assistant_message="PRIVATE"),
    payload("agent_start", request_id=REQUEST_ID), payload("permission_asked", outcome="completed"),
    payload("question_asked", last_assistant_message="PRIVATE QUESTION"),
    payload(outcome="error", last_assistant_message="PRIVATE ERROR"),
    payload(outcome="aborted", last_assistant_message="PRIVATE partial output"),
    payload(outcome="error", failure_code="rate_limit"), payload(request_id=REQUEST_ID),
])
def test_inconsistent_event_fields_are_ignored(source):
    assert adapt_opencode(source) is None


def test_complete_reply_is_namespaced_bounded_and_independent_of_other_providers():
    source = payload()
    event = adapt_opencode(source)
    assert event.session_id == "opencode:session-123"
    assert event.turn_id == TURN_ID and event.event_id == "stop:" + TURN_ID
    assert event.text == source["last_assistant_message"] and event.evidence_source == "opencode:agent_settled"
    assert event.explicit_state is event.failure_code is event.background_tasks is event.session_crons is None
    common = {**source, "hook_event_name": "Stop", "prompt_id": TURN_ID}
    assert len({event.session_id, adapt_pi(source).session_id, adapt_claude(common).session_id,
                adapt_codex(common).session_id}) == 4


@pytest.mark.parametrize("session", ["s" * 247, "s" * 248, "s" * 256, "é" * 128])
def test_long_session_ids_remain_correlated_and_wire_bounded(session):
    start = adapt_opencode(payload("agent_start", session_id=session))
    stop = adapt_opencode(payload(session_id=session))
    assert start.session_id == stop.session_id and len(stop.session_id.encode()) <= 256
    assert event_from_wire(start.to_dict()) == start
    assert event_from_wire(stop.to_dict()) == stop


def test_turn_uuids_are_normalized_and_start_never_classifies():
    event = adapt_opencode(payload("agent_start", turn_id=TURN_ID.upper()))
    assert event.turn_id == TURN_ID and event.event_id == "start:" + TURN_ID
    assert event.kind == "turn-start" and event.text == ""
    assert RulesClassifier().classify(event) is None
    assert SemanticClassifier.classify(object(), event) is None


@pytest.mark.parametrize("message", [None, "", " \n"])
def test_empty_completed_settlement_is_silent_cleanup(message):
    event = adapt_opencode(payload(last_assistant_message=message))
    assert event.kind == "turn-end" and event.evidence_source == "opencode:agent_quiet"
    assert event.text == "" and event.explicit_state is event.failure_code is None
    assert RulesClassifier().classify(event) is None
    assert SemanticClassifier.classify(object(), event) is None


def test_missing_completed_prose_and_aborted_turns_end_quietly():
    source = payload()
    del source["last_assistant_message"]
    assert adapt_opencode(source).kind == "turn-end"
    assert adapt_opencode(payload(outcome="aborted")).kind == "turn-end"


def test_structured_error_has_only_generic_failure_metadata():
    event = adapt_opencode(payload(outcome="error"))
    assert event.text == "" and event.explicit_state == "failed" and event.failure_code == "unknown"
    assert RulesClassifier().classify(event).gesture == "failed"
    assert SemanticClassifier.classify(SimpleNamespace(threshold=0.5), event).gesture == "failed"


@pytest.mark.parametrize("name,gesture,prefix", [("question_asked", "decision", "question:"),
                                                 ("permission_asked", "needs-you", "permission:")])
def test_attention_is_uuid_deduplicated_and_shared_by_both_classifiers(name, gesture, prefix):
    event = adapt_opencode(payload(name, request_id=REQUEST_ID.upper()))
    assert event.event_id == prefix + REQUEST_ID and event.dedup_key == "request:" + REQUEST_ID
    assert event.text == "" and event.explicit_state == "needs-you"
    assert RulesClassifier().classify(event).gesture == gesture
    assert SemanticClassifier.classify(SimpleNamespace(threshold=0.5), event).gesture == gesture


@pytest.mark.parametrize("name", ["permission_asked", "question_asked"])
@pytest.mark.parametrize("value", [None, "", [], 1, "not-a-uuid", "0" * 37])
def test_attention_requires_request_uuid(name, value):
    assert adapt_opencode(payload(name, request_id=value)) is None


@pytest.mark.parametrize("source", [payload(), payload("agent_start"), payload("permission_asked"),
                                   payload("question_asked"), payload(outcome="error"), payload(outcome="aborted")])
def test_supported_events_round_trip_wire(source):
    event = adapt_opencode(source)
    assert event_from_wire(json.loads(json.dumps(event.to_dict()))) == event


@pytest.mark.parametrize("source,patch", [
    (payload(), {"evidence_source": "opencode:Stop"}), (payload(), {"session_id": "pi:session-123"}),
    (payload(), {"session_id": "opencode:"}), (payload(), {"session_id": "opencode: "}),
    (payload(), {"session_id": "opencode:" + "é" * 124}), (payload(), {"turn_id": ""}),
    (payload(), {"turn_id": NEXT_TURN}), (payload(), {"event_id": "stop:made-up"}),
    (payload(), {"explicit_state": "needs-you"}), (payload(), {"dedup_key": "request:spoofed"}),
    (payload(), {"background_tasks": 0}), (payload(), {"background_tasks": None}),
    (payload(), {"session_crons": 0}), (payload(), {"session_crons": None}),
    (payload(), {"kind": "turn-start"}), (payload(), {"text": "\ud800"}),
    (payload("agent_start"), {"text": "PRIVATE PROMPT"}), (payload("agent_start"), {"dedup_key": "PRIVATE"}),
    (payload("agent_start"), {"kind": "notification"}),
    (payload(outcome="aborted"), {"text": "PRIVATE partial reply"}),
    (payload(outcome="aborted"), {"failure_code": "unknown"}),
    (payload(outcome="aborted"), {"explicit_state": "failed"}),
    (payload(outcome="aborted"), {"kind": "notification"}),
    (payload(outcome="error"), {"failure_code": "rate_limit"}),
    (payload(outcome="error"), {"failure_code": None}), (payload(outcome="error"), {"text": "PRIVATE ERROR"}),
    (payload(outcome="error"), {"event_id": "failure:" + NEXT_TURN}),
    (payload("question_asked"), {"text": "PRIVATE TITLE"}),
    (payload("question_asked"), {"explicit_state": None}),
    (payload("question_asked"), {"failure_code": "unknown"}),
    (payload("question_asked"), {"event_id": "question:bad-id"}),
    (payload("question_asked"), {"dedup_key": "request:" + NEXT_TURN}),
    (payload("question_asked"), {"evidence_source": "opencode:permission_asked"}),
    (payload("permission_asked"), {"event_id": "question:" + REQUEST_ID}),
])
def test_wire_rejects_inconsistent_or_fabricated_capabilities(source, patch):
    assert event_from_wire({**adapt_opencode(source).to_dict(), **patch}) is None


def test_hook_is_quiet_and_forwards_only_the_normalized_event(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr("awaitonal.client.read_hook_input", lambda: json.dumps(payload()).encode())
    monkeypatch.setattr("awaitonal.client.send_event", lambda event, path: sent.append((event, path)))
    assert run_hook("/tmp/test.sock", adapter="opencode") == 0
    assert sent == [(adapt_opencode(payload()), "/tmp/test.sock")]
    assert capsys.readouterr() == ("", "")


def test_hook_remains_quiet_and_successful_when_service_is_unavailable(monkeypatch, capsys):
    monkeypatch.setattr("awaitonal.client.read_hook_input", lambda: json.dumps(payload()).encode())
    monkeypatch.setattr("awaitonal.client.send_event", lambda *_: (_ for _ in ()).throw(OSError("PRIVATE")))
    assert run_hook(adapter="opencode") == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize("source,expected", [(payload("agent_start"), {"recorded": "turn-start", "timing_available": True}),
                                           (payload(outcome="aborted"), {"recorded": "turn-end", "silent": True})])
def test_dry_run_reports_lifecycle_without_classification(monkeypatch, capsys, source, expected):
    monkeypatch.setattr("awaitonal.client.read_hook_input", lambda: json.dumps(source).encode())
    assert run_hook(adapter="opencode", dry_run=True) == 0
    assert json.loads(capsys.readouterr().out) == expected


def test_hot_hook_imports_no_audio_or_model_runtime():
    code = ("import json,sys; from awaitonal.client import run_hook; "
            "assert run_hook('/tmp/awaitonal-opencode-missing.sock',adapter='opencode')==0; "
            "print(json.dumps({name:name in sys.modules for name in "
            "['numpy','torch','sentence_transformers','transformers','awaitonal.synth','awaitonal.semantic']}))")
    process = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload()),
                             capture_output=True, text=True, timeout=3)
    assert process.returncode == 0 and not process.stderr
    assert not any(json.loads(process.stdout).values())
