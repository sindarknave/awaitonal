"""Explicit adapter evidence that shares lifecycle and handoff semantics.

Keep these allowlists narrower than suffix checks: arbitrary/manual evidence
must not gain the authority to resolve attention or consume turn timing.
"""

STOP_SOURCES = frozenset(("claude:Stop", "codex:Stop", "pi:agent_settled"))
TURN_END_SOURCES = STOP_SOURCES | {"claude:StopFailure", "pi:agent_error"}
QUESTION_SOURCES = frozenset(("claude:PreToolUse", "codex:PreToolUse", "pi:ui_prompt_start"))
