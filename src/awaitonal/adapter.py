"""Claude's documented hook payloads -> small agent-independent events."""
import hashlib
import json

from .types import Event

MAX_INPUT = 65_536
MAX_WIRE = 131_072


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def adapt_claude(payload: object) -> Event | None:
    if not isinstance(payload, dict):
        return None
    session = payload.get("session_id")
    if not isinstance(session, str) or not session.strip() or len(session) > 256:
        return None
    # agent_type also identifies main sessions launched with --agent; only
    # agent_id is documented as identifying a subagent invocation.
    agent_id = payload.get("agent_id")
    if agent_id is not None and not isinstance(agent_id, str):
        return None
    if agent_id:
        return None
    turn = payload.get("prompt_id", "")
    if not isinstance(turn, str) or len(turn) > 256:
        return None
    name = payload.get("hook_event_name")
    if name == "Stop":
        message = payload.get("last_assistant_message")
        if not isinstance(message, str) or not message.strip() or len(message.encode("utf-8")) > MAX_INPUT:
            return None
        if "stop_hook_active" in payload and type(payload["stop_hook_active"]) is not bool:
            return None
        return Event(session, "stop:" + (turn or digest(message)), message,
                     evidence_source="claude:Stop", turn_id=turn)
    if name not in ("PreToolUse", "PermissionRequest"):
        return None
    tool = payload.get("tool_name")
    tool_input = payload.get("tool_input")
    if not isinstance(tool, str) or not tool.strip() or not isinstance(tool_input, dict):
        return None
    if name == "PreToolUse" and tool != "AskUserQuestion":
        return None
    if name == "PreToolUse":
        tool_id = payload.get("tool_use_id")
        if not isinstance(tool_id, str) or not tool_id.strip() or len(tool_id) > 256:
            return None
        questions = tool_input.get("questions")
        if not isinstance(questions, list) or not 1 <= len(questions) <= 4 or not all(
            isinstance(question, dict) and isinstance(question.get("question"), str)
            and question["question"].strip() for question in questions
        ):
            return None
    # PermissionRequest has no documented tool_use_id. The shared fingerprint
    # catches its overlap with AskUserQuestion's PreToolUse, for a short window.
    fingerprint = digest(tool + json.dumps(tool_input, sort_keys=True, ensure_ascii=False))
    event_id = "question:" + tool_id if name == "PreToolUse" else "permission:" + fingerprint
    return Event(session, event_id, explicit_state="needs-you",
                 evidence_source=f"claude:{name}", turn_id=turn,
                 dedup_key="tool:" + fingerprint)


def event_from_wire(payload: object) -> Event | None:
    """Reject malformed events instead of manufacturing a success sound."""
    if not isinstance(payload, dict):
        return None
    allowed = {"session_id", "event_id", "text", "explicit_state", "evidence_source", "turn_id", "dedup_key"}
    if set(payload) - allowed:
        return None
    for key in ("session_id", "event_id"):
        if not isinstance(payload.get(key), str) or not payload[key].strip() or len(payload[key]) > 256:
            return None
    for key in ("text", "evidence_source", "turn_id", "dedup_key"):
        value = payload.get(key, "")
        limit = MAX_INPUT if key == "text" else 256
        if not isinstance(value, str) or len(value.encode("utf-8")) > limit:
            return None
    # Structured input means waiting, not a claimed verified completion.
    if payload.get("explicit_state") not in (None, "needs-you", "rejected"):
        return None
    if payload.get("explicit_state") is None and not payload.get("text", "").strip():
        return None
    return Event(**payload)
