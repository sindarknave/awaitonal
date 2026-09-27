"""Documented coding-agent hook payloads -> small agent-independent events."""
import hashlib
import json
import uuid

from .types import ACTION_FAILURE_CODES, FAILURE_CODES, Event

MAX_INPUT = 65_536
MAX_WIRE = 131_072
MAX_BACKGROUND_ITEMS = 512
CODEX_QUESTION_TOOLS = frozenset(("request_user_input", "request_user_input_async"))


def _background_count(value, *, crons=False):
    """Keep only bounded counts; an unavailable or unfamiliar registry is unknown.

    These registries are session-wide, not proof that the final reply's task is
    still running. Descriptions, commands, identifiers and cron prompts never
    leave the hook. Running/pending are the statuses Claude currently emits.
    """
    if not isinstance(value, list) or len(value) > MAX_BACKGROUND_ITEMS:
        return None
    count = 0
    for entry in value:
        fields = ("id", "schedule") if crons else ("id", "type", "status")
        if not isinstance(entry, dict) or any(
            not isinstance(entry.get(key), str) or not entry[key].strip()
            or len(entry[key].encode("utf-8")) > 256 for key in fields
        ):
            return None
        if crons:
            if type(entry.get("recurring")) is not bool:
                return None
            count += 1
        elif entry["status"] in ("running", "pending"):
            count += 1
        elif entry["status"] not in ("completed", "failed", "killed", "cancelled", "canceled", "stopped"):
            return None
    return count


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def event_identifier(prefix: str, value: str) -> str:
    """Leave room for the hook prefix while preserving the original turn ID."""
    identifier = prefix + value
    return identifier if len(identifier) <= 256 else prefix + digest(value)


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
    if not isinstance(turn, str) or len(turn.encode("utf-8")) > 256:
        return None
    turn = turn if turn.strip() else ""
    name = payload.get("hook_event_name")
    if name == "UserPromptSubmit":
        # Only correlate an actual start observed by the service. The prompt,
        # transcript path and caller-supplied timestamps never leave this hook.
        return Event(session, event_identifier("start:", turn or "unidentified"),
                     evidence_source="claude:UserPromptSubmit", turn_id=turn, kind="turn-start")
    if name == "StopFailure":
        error = payload.get("error")
        if not isinstance(error, str) or not error.strip() or len(error) > 256:
            return None
        code = error if error in FAILURE_CODES else "unknown"
        state = "needs-you" if code in ACTION_FAILURE_CODES else "failed"
        # last_assistant_message is rendered error text for this hook, not prose.
        # Never send it or error_details to the service or the semantic model.
        return Event(session, event_identifier("failure:", turn or code), explicit_state=state,
                     evidence_source="claude:StopFailure", turn_id=turn, failure_code=code)
    if name == "Stop":
        message = payload.get("last_assistant_message")
        if not isinstance(message, str) or not message.strip() or len(message.encode("utf-8")) > MAX_INPUT:
            return None
        if "stop_hook_active" in payload and type(payload["stop_hook_active"]) is not bool:
            return None
        return Event(session, event_identifier("stop:", turn or digest(message)), message,
                     evidence_source="claude:Stop", turn_id=turn,
                     background_tasks=_background_count(payload.get("background_tasks")),
                     session_crons=_background_count(payload.get("session_crons"), crons=True))
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
    event_id = event_identifier("question:", tool_id) if name == "PreToolUse" else "permission:" + fingerprint
    return Event(session, event_id, explicit_state="needs-you",
                 evidence_source=f"claude:{name}", turn_id=turn,
                 dedup_key="tool:" + fingerprint)


def _bounded_string(value: object, limit: int, *, empty: bool = False) -> bool:
    if not isinstance(value, str) or (not empty and not value.strip()):
        return False
    try:
        return len(value.encode("utf-8")) <= limit
    except UnicodeError:
        return False


def adapt_codex(payload: object) -> Event | None:
    """Use final text and structured handoffs, never Codex's transcript file.

    Codex has no documented StopFailure hook. Its prompt-start and Stop hooks
    share turn_id rather than Claude's prompt_id. Namespacing the session keeps
    the two providers' timing, deduplication and assigned voices independent.
    """
    if not isinstance(payload, dict):
        return None
    session = payload.get("session_id")
    if not _bounded_string(session, 256):
        return None
    session = "codex:" + (session if len(session.encode("utf-8")) <= 250 else digest(session))
    agent_id = payload.get("agent_id")
    if agent_id is not None and (not isinstance(agent_id, str) or agent_id):
        return None
    turn = payload.get("turn_id", "")
    if not _bounded_string(turn, 256, empty=True):
        return None
    turn = turn if turn.strip() else ""
    name = payload.get("hook_event_name")
    if name == "UserPromptSubmit":
        # Prompt contents, paths and caller-supplied timestamps stay in the hook.
        return Event(session, event_identifier("start:", turn or "unidentified"),
                     evidence_source="codex:UserPromptSubmit", turn_id=turn, kind="turn-start")
    if name == "Stop":
        message = payload.get("last_assistant_message")
        if not _bounded_string(message, MAX_INPUT):
            return None
        if "stop_hook_active" in payload and type(payload["stop_hook_active"]) is not bool:
            return None
        return Event(session, event_identifier("stop:", turn or digest(message)), message,
                     evidence_source="codex:Stop", turn_id=turn)
    if name not in ("PreToolUse", "PermissionRequest"):
        return None
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input")
    if not _bounded_string(tool, 256) or not isinstance(tool_input, dict):
        return None
    try:
        serialized = json.dumps(tool_input, sort_keys=True, ensure_ascii=False, allow_nan=False)
        if len(serialized.encode("utf-8")) > MAX_INPUT:
            return None
    except (TypeError, ValueError, UnicodeError):
        return None
    if name == "PreToolUse":
        if tool not in CODEX_QUESTION_TOOLS:
            return None
        tool_id = payload.get("tool_use_id")
        if not _bounded_string(tool_id, 256):
            return None
        questions = tool_input.get("questions")
        # The synchronous tool uses question; the async tool uses title and
        # has no documented question-count limit. Its input is still byte-bound.
        question_key = "title" if tool == "request_user_input_async" else "question"
        if not isinstance(questions, list) or not questions or not all(
            isinstance(question, dict) and _bounded_string(question.get(question_key), MAX_INPUT)
            for question in questions
        ):
            return None
        if tool == "request_user_input" and len(questions) > 3:
            return None
    # Only a fingerprint leaves the hook; commands and question text do not.
    fingerprint = digest(tool + serialized)
    event_id = event_identifier("question:", tool_id) if name == "PreToolUse" else "permission:" + fingerprint
    return Event(session, event_id, explicit_state="needs-you",
                 evidence_source=f"codex:{name}", turn_id=turn,
                 dedup_key="tool:" + fingerprint)


def _request_uuid(value: object) -> str | None:
    if not _bounded_string(value, 36):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def adapt_pi(payload: object) -> Event | None:
    """Adapt the Pi extension's settled-turn and user-interface notifications.

    The extension captures the final assistant message until the agent has
    settled after any retries or compaction. Errors are structured failures;
    their text, prompt titles and other metadata never leave the hook process.
    """
    if not isinstance(payload, dict):
        return None
    session = payload.get("session_id")
    turn = payload.get("turn_id", "")
    if not _bounded_string(session, 256) or not _bounded_string(turn, 256, empty=True):
        return None
    session = "pi:" + (session if len(session.encode("utf-8")) <= 253 else digest(session))
    turn = turn if turn.strip() else ""
    name = payload.get("hook_event_name")
    if name == "agent_start":
        return Event(session, event_identifier("start:", turn or "unidentified"),
                     evidence_source="pi:agent_start", turn_id=turn, kind="turn-start")
    if name == "agent_settled":
        outcome = payload.get("outcome")
        if outcome == "error":
            return Event(session, event_identifier("failure:", turn or "unidentified"),
                         explicit_state="failed", evidence_source="pi:agent_error",
                         turn_id=turn, failure_code="unknown")
        message = payload.get("last_assistant_message")
        if outcome == "aborted" or (outcome == "completed" and (
                message is None or isinstance(message, str) and not message.strip())):
            return Event(session, event_identifier("end:", turn or "unidentified"),
                         evidence_source="pi:agent_quiet", turn_id=turn, kind="turn-end")
        if outcome != "completed":
            return None
        if not _bounded_string(message, MAX_INPUT):
            return None
        return Event(session, event_identifier("stop:", turn or digest(message)), message,
                     evidence_source="pi:agent_settled", turn_id=turn)
    if name == "ui_prompt_start":
        request = _request_uuid(payload.get("request_id"))
        if request is None:
            return None
        return Event(session, "question:" + request, explicit_state="needs-you",
                     evidence_source="pi:ui_prompt_start", turn_id=turn, dedup_key="ui:" + request)
    return None


def event_from_wire(payload: object) -> Event | None:
    """Reject malformed events instead of manufacturing a success sound."""
    if not isinstance(payload, dict):
        return None
    allowed = {"session_id", "event_id", "text", "explicit_state", "evidence_source", "turn_id", "dedup_key",
               "kind", "failure_code", "background_tasks", "session_crons"}
    if set(payload) - allowed:
        return None
    for key in ("session_id", "event_id"):
        if not isinstance(payload.get(key), str) or not payload[key].strip() or len(payload[key]) > 256:
            return None
    for key in ("text", "evidence_source", "turn_id", "dedup_key"):
        value = payload.get(key, "")
        limit = MAX_INPUT if key == "text" else 256
        if not _bounded_string(value, limit, empty=True):
            return None
    kind = payload.get("kind", "notification")
    if kind not in ("notification", "turn-start", "turn-end"):
        return None
    code = payload.get("failure_code")
    if code is not None and (not isinstance(code, str) or code not in FAILURE_CODES):
        return None
    source = payload.get("evidence_source", "")
    if source.startswith("pi:"):
        if (not payload["session_id"].startswith("pi:")
                or not _bounded_string(payload["session_id"][3:], 253)):
            return None
        if source == "pi:agent_settled":
            if (kind != "notification" or payload.get("explicit_state") is not None
                    or code is not None or payload.get("dedup_key", "")):
                return None
        elif source == "pi:agent_start":
            if kind != "turn-start":
                return None
        elif source == "pi:agent_quiet":
            if kind != "turn-end":
                return None
        elif source == "pi:agent_error":
            if (kind != "notification" or payload.get("explicit_state") != "failed"
                    or code != "unknown" or payload.get("text", "") or payload.get("dedup_key", "")):
                return None
        elif source == "pi:ui_prompt_start":
            request = _request_uuid(payload["event_id"].removeprefix("question:"))
            if (kind != "notification" or payload.get("explicit_state") != "needs-you"
                    or payload.get("text", "") or code is not None or request is None
                    or payload["event_id"] != "question:" + request or payload.get("dedup_key") != "ui:" + request):
                return None
        else:
            return None
    if source.startswith("codex:"):
        # Do not accept invented Codex failure/background signals or let a
        # structured tool event masquerade as final assistant text.
        if source == "codex:Stop":
            if kind != "notification" or payload.get("explicit_state") is not None or code is not None:
                return None
        elif source == "codex:UserPromptSubmit":
            if kind != "turn-start":
                return None
        elif source in ("codex:PreToolUse", "codex:PermissionRequest"):
            if (kind != "notification" or payload.get("explicit_state") != "needs-you"
                    or payload.get("text", "") or code is not None):
                return None
        else:
            return None
    for key in ("background_tasks", "session_crons"):
        count = payload.get(key)
        if count is not None and (
            type(count) is not int or not 0 <= count <= MAX_BACKGROUND_ITEMS
            or payload.get("evidence_source") != "claude:Stop"
            or payload.get("explicit_state") is not None or kind != "notification"
        ):
            return None
    if kind in ("turn-start", "turn-end"):
        lifecycle_sources = (("claude:UserPromptSubmit", "codex:UserPromptSubmit", "pi:agent_start")
                             if kind == "turn-start" else ("pi:agent_quiet",))
        if (payload.get("text", "") or payload.get("explicit_state") is not None or code is not None
                or payload.get("dedup_key", "")
                or source not in lifecycle_sources):
            return None
        return Event(**payload)
    # Structured input can report waiting or a failure, never verified success.
    if payload.get("explicit_state") not in (None, "needs-you", "rejected", "failed"):
        return None
    if code is not None:
        expected = "needs-you" if code in ACTION_FAILURE_CODES else "failed"
        if (payload.get("explicit_state") != expected or payload.get("text", "")
                or source not in ("claude:StopFailure", "pi:agent_error")):
            return None
    elif payload.get("explicit_state") == "failed" or source in ("claude:StopFailure", "pi:agent_error"):
        return None
    if payload.get("explicit_state") is None and not payload.get("text", "").strip():
        return None
    return Event(**payload)
