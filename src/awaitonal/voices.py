"""Bounded, in-memory instrument assignments for concurrent sessions."""
from collections import OrderedDict
from dataclasses import dataclass
import math


SESSION_VOICES = ("wood", "glass", "round")
VOICE_NAMES = ("default", *SESSION_VOICES)


@dataclass(frozen=True)
class SessionVoice:
    voice: str
    touched: float


class SessionVoices:
    """Give the first three active sessions distinct, stable instruments.

    Only the service listener uses this registry. Assignments retire after an
    hour with no event from that session, and disappear on service restart.
    Additional sessions use the original palette, even if an instrument becomes
    free later; an assignment changes only after that session's idle expiry.

    At most ``capacity`` IDs are retained, without paths or response text. If
    that limit is reached, keep new IDs on the original palette until all
    untracked arrivals have been idle for ``ttl``. This conservative overflow
    window preserves identity without growing an unbounded fallback cache.
    """

    def __init__(self, capacity=128, ttl=3600.0):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("voice capacity must be a positive integer")
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("voice ttl must be finite and positive")
        self.capacity, self.ttl = capacity, ttl
        self.sessions = OrderedDict()
        self._overflow_until = float("-inf")

    def assign(self, session_id, now):
        """Return a voice, refreshing that session's idle deadline."""
        while self.sessions and now - next(iter(self.sessions.values())).touched >= self.ttl:
            self.sessions.popitem(last=False)
        old = self.sessions.pop(session_id, None)
        if old is not None:
            self.sessions[session_id] = SessionVoice(old.voice, now)
            return old.voice
        if len(self.sessions) >= self.capacity:
            self._overflow_until = now + self.ttl
            return "default"
        occupied = {assignment.voice for assignment in self.sessions.values()}
        voice = (next((voice for voice in SESSION_VOICES if voice not in occupied), "default")
                 if now >= self._overflow_until else "default")
        self.sessions[session_id] = SessionVoice(voice, now)
        return voice
