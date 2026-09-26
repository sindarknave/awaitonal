"""Small shared values; no audio or ML imports."""
from dataclasses import asdict, dataclass, field
import math
from typing import Literal

State = Literal["done", "caveats", "needs-you", "rejected", "failed"]
MODEL_STATES = ("done", "caveats", "needs-you", "rejected")
STATES = (*MODEL_STATES, "failed")
FAILURE_CODES = ("rate_limit", "overloaded", "authentication_failed", "oauth_org_not_allowed",
                 "account_on_hold", "billing_error", "invalid_request", "model_not_found",
                 "server_error", "max_output_tokens", "cloud_credential_error", "unknown")
ACTION_FAILURE_CODES = frozenset(("authentication_failed", "oauth_org_not_allowed", "account_on_hold",
                                  "billing_error", "cloud_credential_error"))
DeliveryKind = Literal["change", "answer", "plan", "artifact", "published", "unknown"]
DELIVERY_KINDS = ("change", "answer", "plan", "artifact", "published", "unknown")
Expectancy = Literal["none", "review-requested", "required-handoff"]
EXPECTANCIES = ("none", "review-requested", "required-handoff")
HandoffKind = Literal["decision", "action"]
HANDOFF_KINDS = ("decision", "action")
Gesture = Literal["done", "answer", "plan", "artifact", "published", "review",
                  "decision", "needs-you", "caveats", "rejected", "failed"]
GESTURES = ("done", "answer", "plan", "artifact", "published", "review",
            "decision", "needs-you", "caveats", "rejected", "failed")
_DELIVERY_GESTURES = {"change": "done", "answer": "answer", "plan": "plan",
                      "artifact": "artifact", "published": "published", "unknown": "done"}


@dataclass(frozen=True)
class Controls:
    loose_ends: float = 0.0
    needs_you: bool = False
    rejected: bool = False
    failed: bool = False

    def __post_init__(self):
        if isinstance(self.loose_ends, bool) or not math.isfinite(self.loose_ends) or not 0 <= self.loose_ends <= 1:
            raise ValueError("loose_ends must be finite and in [0, 1]")
        if any(type(value) is not bool for value in (self.needs_you, self.rejected, self.failed)):
            raise ValueError("needs_you, rejected and failed must be booleans")


def map_controls(controls: Controls, threshold: float = 0.5) -> State:
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be in [0, 1]")
    if controls.rejected:
        return "rejected"
    if controls.needs_you:
        return "needs-you"
    if controls.failed:
        return "failed"
    return "caveats" if controls.loose_ends >= threshold else "done"


def controls_for(state: State) -> Controls:
    if state not in STATES:
        raise ValueError("unknown state")
    return Controls(loose_ends=1.0 if state == "caveats" else 0.0,
                    needs_you=state == "needs-you", rejected=state == "rejected", failed=state == "failed")


@dataclass(frozen=True)
class Classification:
    state: State
    controls: Controls
    evidence_source: str
    reason: str
    diagnostics: dict = field(default_factory=dict)
    delivery_kind: DeliveryKind = "unknown"
    expectancy: Expectancy = "none"
    handoff_kind: HandoffKind = "action"
    failure_code: str | None = None

    @property
    def gesture(self) -> Gesture:
        """Select one cue without conflating a review invitation with a blocker."""
        if self.state == "rejected":
            return "rejected"
        if self.state == "needs-you":
            return "decision" if self.handoff_kind == "decision" else "needs-you"
        if self.state == "failed":
            return "failed"
        if self.expectancy == "review-requested":
            return "review"
        if self.state == "caveats":
            return "caveats"
        return _DELIVERY_GESTURES[self.delivery_kind]

    @property
    def attention(self) -> bool:
        return self.state in ("needs-you", "rejected", "failed")

    def to_dict(self) -> dict:
        return {**asdict(self), "gesture": self.gesture}


@dataclass(frozen=True)
class Event:
    session_id: str
    event_id: str
    text: str = ""
    explicit_state: State | None = None
    evidence_source: str = "text"
    turn_id: str = ""
    dedup_key: str = ""
    kind: Literal["notification", "turn-start"] = "notification"
    failure_code: str | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        if self.kind == "notification":
            result.pop("kind")
        if self.failure_code is None:
            result.pop("failure_code")
        return result
