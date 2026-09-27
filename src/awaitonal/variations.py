"""Bounded, duration-aware phrase alternation independent of session voices."""
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
import time


VARIED_GESTURES = ("answer", "done")
VARIATION_COUNT = 4
DEFAULT_GROUPS = {
    "done": {"light": (0, 2), "full": (1, 3)},
    "answer": {"light": (0, 1), "full": (2, 3)},
}


@dataclass
class PhraseCycle:
    cursors: dict[str, int] = field(default_factory=dict)
    last: int | None = None


@dataclass
class SessionCycles:
    touched: float
    gestures: dict[str, PhraseCycle] = field(default_factory=dict)


def _known_duration(seconds):
    return type(seconds) in (int, float) and math.isfinite(seconds) and seconds >= 0


class SessionVariations:
    """Alternate phrases within the group selected by measured turn duration.

    The serial playback worker alone owns this registry and calls ``choose``
    only after admitting audio. Durations below the cutoff use light phrases;
    the cutoff itself and longer turns use full phrases. Missing or unusable
    timing always uses the original phrase, without advancing either group.
    It still records that original as the last played phrase so the next timed
    cue can avoid immediately repeating it when its group offers an alternative.

    Each session/gesture/group advances independently. Explicit groups describe
    custom palette meaning; an unmapped gesture with known timing cycles through
    all its phrases. Default groups apply only to complete four-phrase palettes.
    At most 128 sessions are retained, expiring after an hour without varied
    playback. Eviction/restart begins fresh cycles without changing instruments.
    Response text, paths and model output are never retained or used as timing.
    """

    def __init__(self, counts=None, *, groups=None, full_after_seconds=120,
                 capacity=128, ttl=3600.0):
        if type(capacity) is not int or not 1 <= capacity <= 128:
            raise ValueError("variation capacity must be an integer between 1 and 128")
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("variation ttl must be finite and positive")
        if (type(full_after_seconds) not in (int, float) or not math.isfinite(full_after_seconds)
                or full_after_seconds <= 0):
            raise ValueError("variation full_after_seconds must be finite and positive")
        if counts is None:
            counts = {gesture: VARIATION_COUNT for gesture in VARIED_GESTURES}
        if (not isinstance(counts, Mapping)
                or any(gesture not in VARIED_GESTURES for gesture in counts)
                or any(type(count) is not int or not 1 <= count <= VARIATION_COUNT
                       for count in counts.values())):
            raise ValueError("variation counts must map answer/done to integers between 1 and 4")
        self.counts = {gesture: counts.get(gesture, 1) for gesture in VARIED_GESTURES}
        if groups is None:
            groups = {gesture: group for gesture, group in DEFAULT_GROUPS.items()
                      if self.counts[gesture] == VARIATION_COUNT}
        if not isinstance(groups, Mapping) or any(gesture not in VARIED_GESTURES for gesture in groups):
            raise ValueError("variation groups must map answer/done to light/full phrase groups")
        self.groups = {}
        for gesture, grouped in groups.items():
            if not isinstance(grouped, Mapping) or set(grouped) != {"light", "full"}:
                raise ValueError("variation groups require both light and full")
            copied = {}
            for name, phrases in grouped.items():
                if (not isinstance(phrases, Sequence) or isinstance(phrases, (str, bytes)) or not phrases
                        or any(type(phrase) is not int or not 0 <= phrase < self.counts[gesture]
                               for phrase in phrases)):
                    raise ValueError("variation groups require nonempty sequences of available phrase IDs")
                copied[name] = tuple(phrases)
            phrases = copied["light"] + copied["full"]
            if len(phrases) != self.counts[gesture] or set(phrases) != set(range(self.counts[gesture])):
                raise ValueError("variation groups must partition all available phrases without duplicates")
            self.groups[gesture] = copied
        self.capacity, self.ttl = capacity, ttl
        self.full_after_seconds = full_after_seconds
        self.sessions = OrderedDict()

    def supported(self, gesture):
        return self.counts.get(gesture, 1) > 1

    def group_for(self, gesture, turn_seconds):
        """Describe the selected group without allocating or changing history."""
        if not self.supported(gesture) or gesture not in self.groups or not _known_duration(turn_seconds):
            return "ordinary"
        return "full" if turn_seconds >= self.full_after_seconds else "light"

    def choose(self, session_id, gesture, now=None, *, turn_seconds=None):
        """Choose for an admitted cue; unknown duration always uses original 0."""
        if not self.supported(gesture):
            return 0
        now = time.monotonic() if now is None else now
        while self.sessions and now - next(iter(self.sessions.values())).touched >= self.ttl:
            self.sessions.popitem(last=False)
        session = self.sessions.pop(session_id, None)
        if session is None:
            session = SessionCycles(now)
        session.touched = now
        self.sessions[session_id] = session
        while len(self.sessions) > self.capacity:
            self.sessions.popitem(last=False)
        cycle = session.gestures.setdefault(gesture, PhraseCycle())
        if not _known_duration(turn_seconds):
            cycle.last = 0
            return 0
        group = self.group_for(gesture, turn_seconds)
        phrases = (tuple(range(self.counts[gesture])) if group == "ordinary"
                   else self.groups[gesture][group])
        index = cycle.cursors.get(group, 0)
        if phrases[index] == cycle.last and len(phrases) > 1:
            index = (index + 1) % len(phrases)
        cycle.last = phrases[index]
        cycle.cursors[group] = (index + 1) % len(phrases)
        return cycle.last
