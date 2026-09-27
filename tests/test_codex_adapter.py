"""Codex hooks preserve outcomes and timing without exposing tool/prompt data."""
import json

import pytest

from awaitonal.adapter import MAX_INPUT, adapt_claude, adapt_codex, event_from_wire
from awaitonal.client import run_hook


def payload(name="Stop", **fields):
    return {"session_id": "thread-123", "hook_event_name": name, "turn_id": "turn-456",
            "stop_hook_active": False, "last_assistant_message": "Implemented it. All tests pass.",
            **fields}


def question_payload(*, asynchronous=False, **fields):
    tool = "request_user_input_async" if asynchronous else "request_user_input"
    questions = ([{"title": "Which database?", "options": ["Postgres", "SQLite"]}]
                 if asynchronous else [{"id": "database", "header": "Database",
                                       "question": "Which database?",
                                       "options": [{"label": "Postgres", "description": "Shared database."},
                                                   {"label": "SQLite", "description": "Local database."}]}])
    return payload("PreToolUse", tool_name=tool, tool_use_id="call-123",
                   tool_input={"questions": questions}, **fields)


@pytest.mark.parametrize("value", [None, [], 1, "Done", True, {}])
def test_non_events_are_quiet(value):
    assert adapt_codex(value) is None


@pytest.mark.parametrize("field,value", [
    ("session_id", None), ("session_id", []), ("session_id", " "),
    ("session_id", "s" * 257), ("session_id", "é" * 129), ("session_id", "\ud800"),
    ("turn_id", None), ("turn_id", []), ("turn_id", "t" * 257),
    ("turn_id", "é" * 129), ("turn_id", "\ud800"),
    ("last_assistant_message", None), ("last_assistant_message", {}),
    ("last_assistant_message", ""), ("last_assistant_message", " \n"),
    ("last_assistant_message", "é" * (MAX_INPUT // 2 + 1)),
    ("last_assistant_message", "\ud800"),
    ("stop_hook_active", None), ("stop_hook_active", "false"), ("stop_hook_active", 0),
    ("agent_id", True), ("agent_id", 0), ("agent_id", []), ("agent_id", "child-123"),
    ("hook_event_name", "StopFailure"), ("hook_event_name", "SubagentStop"),
    ("hook_event_name", "SubagentStart"), ("hook_event_name", "PostToolUse"),
    ("hook_event_name", "Interrupt"), ("hook_event_name", "Notification"),
    ("hook_event_name", "SessionStart"), ("hook_event_name", "SessionEnd"),
])
def test_malformed_and_unsupported_events_are_quiet(field, value):
    assert adapt_codex(payload(**{field: value})) is None


def test_final_text_only_and_provider_scoped_identity():
    source = payload(prompt_id="claude-only-id", prompt="PRIVATE PROMPT",
                     transcript_path="PRIVATE PATH", messages=[{"text": "PRIVATE TEXT"}],
                     agent_type="reviewer", background_tasks=[], session_crons=[])
    event = adapt_codex(source)
    assert event.text == source["last_assistant_message"]
    assert event.session_id == "codex:thread-123"
    assert event.turn_id == "turn-456"
    assert event.event_id == "stop:turn-456"
    assert event.evidence_source == "codex:Stop"
    assert event.explicit_state is None
    assert event.background_tasks is event.session_crons is None
    assert "PRIVATE" not in json.dumps(event.to_dict())
    assert event.session_id != adapt_claude(source).session_id


def test_null_final_text_never_reads_transcript(tmp_path, monkeypatch):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text('{"role":"assistant","content":"Done."}\n')
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: pytest.fail("must not open a transcript"))
    assert adapt_codex(payload(last_assistant_message=None, transcript_path=str(transcript))) is None


@pytest.mark.parametrize("session", ["s" * 256, "é" * 128])
def test_long_session_identity_stays_bounded_and_stable(session):
    first = adapt_codex(payload(session_id=session))
    second = adapt_codex(payload("UserPromptSubmit", session_id=session))
    assert first.session_id == second.session_id
    assert first.session_id.startswith("codex:")
    assert len(first.session_id.encode()) <= 256
    assert event_from_wire(first.to_dict()) == first


def test_prompt_and_stop_correlate_using_codex_turn_id_only():
    start = adapt_codex(payload("UserPromptSubmit", prompt="PRIVATE PROMPT", prompt_id="wrong-start"))
    stop = adapt_codex(payload(prompt_id="wrong-stop"))
    other = adapt_codex(payload(turn_id="next-turn"))
    assert start.kind == "turn-start"
    assert start.text == "" and start.explicit_state is None
    assert start.evidence_source == "codex:UserPromptSubmit"
    assert start.session_id == stop.session_id
    assert start.turn_id == stop.turn_id
    assert start.event_id != stop.event_id != other.event_id
    assert "PRIVATE" not in json.dumps(start.to_dict())


def test_missing_turn_id_does_not_invent_timing_or_use_claude_prompt_id():
    source = payload(prompt_id="wrong-provider")
    del source["turn_id"]
    stop = adapt_codex(source)
    start = adapt_codex({**source, "hook_event_name": "UserPromptSubmit"})
    assert stop.turn_id == start.turn_id == ""
    assert "wrong-provider" not in stop.event_id
    assert stop.event_id == adapt_codex(source).event_id


@pytest.mark.parametrize("asynchronous", [False, True])
def test_documented_question_shapes_request_attention_without_retaining_questions(asynchronous):
    source = question_payload(asynchronous=asynchronous)
    event = adapt_codex(source)
    assert event.explicit_state == "needs-you"
    assert event.text == "" and event.event_id == "question:call-123"
    assert event.evidence_source == "codex:PreToolUse"
    assert event.dedup_key.startswith("tool:")
    assert "database" not in json.dumps(event.to_dict())
    assert event_from_wire(event.to_dict()) == event


@pytest.mark.parametrize("asynchronous,questions", [
    (False, []), (False, None), (False, "Which?"), (False, [None]),
    (False, [{"question": " "}]), (False, [{"question": "x"}] * 4),
    (False, [{"title": "Which?"}]),
    (True, []), (True, [{"title": " "}]), (True, [{"question": "Which?"}]),
])
def test_empty_or_wrong_question_shapes_do_not_request_attention(asynchronous, questions):
    source = question_payload(asynchronous=asynchronous)
    source["tool_input"] = {"questions": questions}
    assert adapt_codex(source) is None


def test_async_questions_have_no_synchronous_three_question_limit():
    source = question_payload(asynchronous=True)
    source["tool_input"]["questions"] *= 4
    assert adapt_codex(source).explicit_state == "needs-you"


@pytest.mark.parametrize("field,value", [
    ("tool_name", "Bash"), ("tool_name", "AskUserQuestion"),
    ("tool_name", "request_user_input_extra"), ("tool_name", "functions.request_user_input"),
    ("tool_name", None), ("tool_name", []), ("tool_name", "t" * 257),
    ("tool_use_id", None), ("tool_use_id", " "), ("tool_use_id", "t" * 257),
    ("tool_input", None), ("tool_input", []), ("tool_input", "Which?"),
    ("tool_input", {"questions": [{"question": "x" * MAX_INPUT}]}),
    ("tool_input", {"questions": [{"question": "Which?"}], "invalid": float("nan")}),
])
def test_malformed_question_fields_are_quiet(field, value):
    source = question_payload()
    source[field] = value
    assert adapt_codex(source) is None


def test_permission_needs_no_tool_use_id_and_does_not_forward_commands():
    event = adapt_codex(payload("PermissionRequest", tool_name="Bash",
                               tool_input={"command": "PRIVATE COMMAND", "description": "PRIVATE REASON"}))
    assert event.explicit_state == "needs-you" and event.text == ""
    assert event.evidence_source == "codex:PermissionRequest"
    assert "PRIVATE" not in json.dumps(event.to_dict())
    assert event_from_wire(event.to_dict()) == event


def test_question_and_permission_for_same_tool_share_fingerprint():
    source = question_payload()
    question = adapt_codex(source)
    permission = adapt_codex({**source, "hook_event_name": "PermissionRequest"})
    assert question.dedup_key == permission.dedup_key
    assert question.event_id != permission.event_id


@pytest.mark.parametrize("event", [payload(), payload("UserPromptSubmit"), question_payload(),
                                 question_payload(asynchronous=True)])
def test_supported_events_round_trip_wire(event):
    adapted = adapt_codex(event)
    assert event_from_wire(json.loads(json.dumps(adapted.to_dict()))) == adapted


@pytest.mark.parametrize("source,patch", [
    ("codex:StopFailure", {"explicit_state": "failed", "failure_code": "rate_limit", "text": ""}),
    ("codex:SubagentStop", {}), ("codex:Interrupt", {}),
    ("codex:Stop", {"explicit_state": "needs-you"}),
    ("codex:Stop", {"background_tasks": 0}), ("codex:Stop", {"session_crons": 1}),
    ("codex:Stop", {"text": "", "kind": "turn-start"}),
    ("codex:UserPromptSubmit", {}),
    ("codex:PreToolUse", {}), ("codex:PermissionRequest", {}),
    ("codex:PermissionRequest", {"explicit_state": "needs-you"}),
])
def test_wire_rejects_unsupported_codex_signal_combinations(source, patch):
    event = adapt_codex(payload()).to_dict()
    event.update(evidence_source=source, **patch)
    assert event_from_wire(event) is None


def test_client_routes_codex_without_output_or_response(monkeypatch, capsys):
    sent = []
    monkeypatch.setattr("awaitonal.client.read_hook_input", lambda: json.dumps(payload()).encode())
    monkeypatch.setattr("awaitonal.client.send_event", lambda event, path: sent.append((event, path)))
    assert run_hook("/tmp/example.sock", adapter="codex") == 0
    assert sent == [(adapt_codex(payload()), "/tmp/example.sock")]
    assert capsys.readouterr() == ("", "")


def test_client_unknown_adapter_is_quiet(monkeypatch, capsys):
    monkeypatch.setattr("awaitonal.client.send_event", lambda *args: pytest.fail("must not send"))
    assert run_hook(adapter="unknown") == 0
    assert capsys.readouterr() == ("", "")
