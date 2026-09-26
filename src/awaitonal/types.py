"""Small shared values; no audio or ML imports."""
from dataclasses import asdict, dataclass, field
import math
from typing import Literal

State = Literal["done", "caveats", "needs-you", "rejected"]
STATES = ("done", "caveats", "needs-you", "rejected")
DeliveryKind = Literal["change", "answer", "plan", "artifact", "published", "unknown"]
DELIVERY_KINDS = ("change", "answer", "plan", "artifact", "published", "unknown")
Expectancy = Literal["none", "review-requested", "required-handoff"]
EXPECTANCIES = ("none", "review-requested", "required-handoff")
HandoffKind = Literal["decision", "action"]
HANDOFF_KINDS = ("decision", "action")
Gesture = Literal["done", "answer", "plan", "artifact", "published", "review",
                  "decision", "needs-you", "caveats", "rejected"]
GESTURES = ("done", "answer", "plan", "artifact", "published", "review",
            "decision", "needs-you", "caveats", "rejected")
_DELIVERY_GESTURES = {"change": "done", "answer": "answer", "plan": "plan",
                      "artifact": "artifact", "published": "published", "unknown": "done"}


@dataclass(frozen=True)
class Controls:
    loose_ends: float = 0.0
    needs_you: bool = False
    rejected: bool = False

    def __post_init__(self):
        if isinstance(self.loose_ends, bool) or not math.isfinite(self.loose_ends) or not 0 <= self.loose_ends <= 1:
            raise ValueError("loose_ends must be finite and in [0, 1]")
        if type(self.needs_you) is not bool or type(self.rejected) is not bool:
            raise ValueError("needs_you and rejected must be booleans")


def map_controls(controls: Controls, threshold: float = 0.5) -> State:
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("threshold must be in [0, 1]")
    if controls.rejected:
        return "rejected"
    if controls.needs_you:
        return "needs-you"
    return "caveats" if controls.loose_ends >= threshold else "done"


def controls_for(state: State) -> Controls:
    if state not in STATES:
        raise ValueError("unknown state")
    return Controls(loose_ends=1.0 if state == "caveats" else 0.0,
                    needs_you=state == "needs-you", rejected=state == "rejected")


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

    @property
    def gesture(self) -> Gesture:
        """Select one cue without conflating a review invitation with a blocker."""
        if self.state == "rejected":
            return "rejected"
        if self.state == "needs-you":
            return "decision" if self.handoff_kind == "decision" else "needs-you"
        if self.expectancy == "review-requested":
            return "review"
        if self.state == "caveats":
            return "caveats"
        return _DELIVERY_GESTURES[self.delivery_kind]

    @property
    def attention(self) -> bool:
        return self.state in ("needs-you", "rejected")

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

    def to_dict(self) -> dict:
        return asdict(self)
