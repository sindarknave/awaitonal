"""Small shared values; no audio or ML imports."""
from dataclasses import asdict, dataclass, field
import math
from typing import Literal

State = Literal["done", "caveats", "needs-you", "rejected"]
STATES = ("done", "caveats", "needs-you", "rejected")


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

    def to_dict(self) -> dict:
        return asdict(self)


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
