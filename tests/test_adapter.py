"""Documented Claude inputs must never manufacture completion or attention."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from awaitonal.adapter import MAX_INPUT, adapt_claude, event_from_wire
from awaitonal.classify import RulesClassifier


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def fixture(name):
    return json.loads((EXAMPLES / f"claude-{name}.json").read_text())


@pytest.mark.parametrize("payload", [None, [], "Done.", 42, True, {}])
def test_non_events_are_ignored(payload):
    assert adapt_claude(payload) is None


@pytest.mark.parametrize("field,value", [
    ("session_id", None), ("session_id", []), ("session_id", ""),
    ("session_id", "  "), ("session_id", "s" * 257),
    ("hook_event_name", None), ("hook_event_name", "PostToolUse"),
    ("hook_event_name", "SubagentStop"), ("hook_event_name", "StopFailure"),
    ("hook_event_name", "Notification"), ("hook_event_name", "stop"),
    ("last_assistant_message", None), ("last_assistant_message", {}),
    ("last_assistant_message", ""), ("last_assistant_message", " \n "),
    ("last_assistant_message", "é" * (MAX_INPUT // 2 + 1)),
    ("stop_hook_active", "false"), ("stop_hook_active", 0),
    ("prompt_id", None), ("prompt_id", 1), ("prompt_id", "p" * 257),
    ("agent_id", False), ("agent_id", 0), ("agent_id", []),
])
def test_malformed_stop_fields_are_ignored(field, value):
    payload = fixture("stop")
    payload[field] = value
    assert adapt_claude(payload) is None


def test_missing_final_text_does_not_read_transcript(tmp_path):
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text('{"role":"assistant","content":"Done. All tests pass."}\n')
    payload = fixture("missing-text")
    payload["transcript_path"] = str(transcript)
    assert adapt_claude(payload) is None


def test_stop_uses_only_final_assistant_text():
    payload = fixture("stop")
    payload["original_user_message"] = "I cannot help implement that request."
    payload["messages"] = [{"role": "user", "content": "Which database?"}]
    event = adapt_claude(payload)
    assert event is not None
    assert event.text == payload["last_assistant_message"]
    assert event.explicit_state is None
    result = RulesClassifier().classify(event)
    assert result.state == "done"
    assert result.evidence_source == "claude:Stop"


@pytest.mark.parametrize("name", ["stop", "question", "permission"])
def test_subagent_suppression_and_main_agent_persona(name):
    payload = fixture(name)
    payload["agent_type"] = "code-reviewer"
    assert adapt_claude(payload) is not None
    payload["agent_id"] = "worker-123"
    assert adapt_claude(payload) is None


def test_documented_subagent_fixture_is_ignored():
    assert adapt_claude(fixture("subagent")) is None


@pytest.mark.parametrize("name", ["question", "permission"])
def test_structured_wait_overrides_refusal_text(name):
    payload = fixture(name)
    payload["last_assistant_message"] = "I cannot help implement that request."
    event = adapt_claude(payload)
    assert event.explicit_state == "needs-you"
    assert event.text == ""
    result = RulesClassifier().classify(event)
    assert result.state == "needs-you"
    assert result.controls.needs_you is True
    assert result.controls.rejected is False


@pytest.mark.parametrize("name,field,value", [
    ("question", "tool_name", "Bash"),
    ("question", "tool_name", "AskUserQuestionExtra"),
    ("question", "tool_use_id", None), ("question", "tool_use_id", ""),
    ("question", "tool_use_id", []), ("question", "tool_use_id", "t" * 257),
    ("question", "tool_input", None), ("question", "tool_input", []),
    ("permission", "tool_name", ""), ("permission", "tool_name", 1),
    ("permission", "tool_input", "npm test"),
])
def test_malformed_tool_event_fields_are_ignored(name, field, value):
    payload = fixture(name)
    payload[field] = value
    assert adapt_claude(payload) is None


@pytest.mark.parametrize("tool_input", [{}, {"questions": []}, {"questions": "Which?"},
                                        {"questions": [None]}, {"questions": [{"question": ""}]}])
def test_malformed_questions_do_not_request_attention(tool_input):
    payload = fixture("question")
    payload["tool_input"] = tool_input
    assert adapt_claude(payload) is None


def test_permission_requires_no_tool_use_id():
    payload = fixture("permission")
    assert "tool_use_id" not in payload
    event = adapt_claude(payload)
    assert event is not None
    assert event.explicit_state == "needs-you"


def test_same_question_and_permission_share_fingerprint():
    question = fixture("question")
    permission = deepcopy(question)
    permission["hook_event_name"] = "PermissionRequest"
    del permission["tool_use_id"]
    first, second = adapt_claude(question), adapt_claude(permission)
    assert first.dedup_key
    assert first.dedup_key == second.dedup_key
    assert first.event_id != second.event_id


def test_prompt_ids_preserve_distinct_turns():
    payload = fixture("stop")
    payload["prompt_id"] = "prompt-1"
    first = adapt_claude(payload)
    payload["prompt_id"] = "prompt-2"
    second = adapt_claude(payload)
    assert first.text == second.text
    assert first.turn_id != second.turn_id
    assert first.event_id != second.event_id


@pytest.mark.parametrize("name", ["stop", "question", "permission"])
def test_adapted_event_round_trips_wire(name):
    event = adapt_claude(fixture(name))
    assert event_from_wire(json.loads(json.dumps(event.to_dict()))) == event


@pytest.mark.parametrize("patch", [
    {"session_id": None}, {"session_id": " "}, {"event_id": []},
    {"text": 123}, {"text": "x" * (MAX_INPUT + 1)},
    {"explicit_state": "done"}, {"explicit_state": "unknown"},
    {"text": "", "explicit_state": None}, {"turn_id": 1},
    {"dedup_key": "d" * 257}, {"evidence_source": []},
    {"decision": "allow"}, {"hookSpecificOutput": {}},
])
def test_wire_rejects_malformed_and_decision_fields(patch):
    payload = adapt_claude(fixture("stop")).to_dict()
    payload.update(patch)
    assert event_from_wire(payload) is None
