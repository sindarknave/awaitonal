"""Bounded, in-memory instrument assignments for concurrent sessions."""
from collections import Counter, OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
import math


SESSION_VOICES = ("marimba", "powersaw", "harp", "clarinet", "crystal", "flute")
VOICE_NAMES = ("default", "wood", "glass", "round", *SESSION_VOICES)


@dataclass(frozen=True)
class SessionVoice:
    voice: str
    touched: float


class SessionVoices:
    """Rotate new sessions through distinct, stable instruments.

    Only the service listener uses this registry. Assignments retire after an
    hour with no event from that session, and disappear on service restart.
    Prefer an unused instrument, then the least-used instrument, with ties
    resolved in rotation order. Existing sessions retain their instrument; an
    assignment changes only after that session's idle expiry. Idle expiry does
    not reset the rotation, so a fresh session need not sound like the last one.

    At most ``capacity`` IDs are retained, without paths or response text. If
    that limit is reached, keep new IDs on the original palette until all
    untracked arrivals have been idle for ``ttl``. This conservative overflow
    window preserves identity without growing an unbounded fallback cache.
    """

    def __init__(self, capacity=128, ttl=3600.0, voice_cycle=None):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("voice capacity must be a positive integer")
        if type(ttl) not in (int, float) or not math.isfinite(ttl) or ttl <= 0:
            raise ValueError("voice ttl must be finite and positive")
        if voice_cycle is None:
            voice_cycle = SESSION_VOICES
        if (not isinstance(voice_cycle, Sequence) or isinstance(voice_cycle, (str, bytes))
                or not voice_cycle
                or any(not isinstance(voice, str) or voice not in VOICE_NAMES for voice in voice_cycle)):
            raise ValueError("voice cycle must be a nonempty sequence of known voices")
        if len(set(voice_cycle)) != len(voice_cycle):
            raise ValueError("voice cycle must not contain duplicate voices")
        self.capacity, self.ttl = capacity, ttl
        self.voice_cycle = tuple(voice_cycle)
        self.sessions = OrderedDict()
        self._cursor = 0
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
        voice = "default"
        if now >= self._overflow_until:
            counts = Counter(assignment.voice for assignment in self.sessions.values())
            order = [(self._cursor + offset) % len(self.voice_cycle)
                     for offset in range(len(self.voice_cycle))]
            # Zero-use voices come first; min preserves cursor order for ties.
            index = min(order, key=lambda index: counts[self.voice_cycle[index]])
            voice = self.voice_cycle[index]
            self._cursor = (index + 1) % len(self.voice_cycle)
        self.sessions[session_id] = SessionVoice(voice, now)
        return voice
