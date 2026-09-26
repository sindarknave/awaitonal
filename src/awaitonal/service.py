"""One private local listener and one serial classification/playback worker."""
from collections import OrderedDict, deque
from dataclasses import dataclass
import errno
import fcntl
import json
import math
import os
from pathlib import Path
import selectors
import socket
import stat
import sys
import threading
import time
import uuid

from . import __version__
from .adapter import MAX_WIRE, event_from_wire
from .client import _peer_uid, default_socket
from .types import Event


@dataclass
class Pending:
    event: Event
    attention: bool
    received: float
    turn_seconds: float | None = None
    mute_generation: int = 0


@dataclass
class TurnTiming:
    turn_id: str
    started: float | None
    touched: float
    ambiguous: bool = False


class TurnTimings:
    """Bounded in-memory correlation; uncertain timing always permits sound.

    A duplicate or overlapping start quarantines that session until inactivity
    expires it. A fresh start must not manufacture a shorter elapsed duration.
    Only the listener accesses this object; no transcript or prompt is retained.
    """
    def __init__(self, capacity=512, ttl=3600.0):
        self.capacity, self.ttl = capacity, ttl
        self.sessions = OrderedDict()

    def _prune(self, now):
        while self.sessions and now - next(iter(self.sessions.values())).touched >= self.ttl:
            self.sessions.popitem(last=False)

    def start(self, event, now):
        self._prune(now)
        old = self.sessions.pop(event.session_id, None)
        ambiguous = not event.turn_id.strip() or bool(old and (old.ambiguous or old.started is not None))
        self.sessions[event.session_id] = TurnTiming(event.turn_id, None if ambiguous else now, now, ambiguous)
        while len(self.sessions) > self.capacity:
            self.sessions.popitem(last=False)

    def finish(self, event, now):
        self._prune(now)
        timing = self.sessions.pop(event.session_id, None)
        if timing is None:
            return None
        if (not timing.ambiguous and timing.started is None and event.turn_id
                and event.turn_id == timing.turn_id):
            # Duplicate terminal delivery consumes no timing and must not poison
            # the next fresh prompt. A different unmatched terminal stays unknown.
            self.sessions[event.session_id] = TurnTiming(timing.turn_id, None, now)
            return None
        valid = (not timing.ambiguous and bool(event.turn_id.strip()) and event.turn_id == timing.turn_id
                 and timing.started is not None and now >= timing.started)
        elapsed = now - timing.started if valid else None
        # Keep the ambiguity marker through subsequent starts, but release a
        # clean completed turn so a normal next turn can be measured.
        ambiguous = timing.ambiguous or not valid
        self.sessions[event.session_id] = TurnTiming(event.turn_id if valid else "", None, now, ambiguous)
        return elapsed


class EventQueue:
    """Bounded latest-per-session routine queue, with attention preference."""
    def __init__(self, capacity=8, ttl=8.0, dedup_seconds=2.0):
        if capacity < 1 or ttl <= 0 or dedup_seconds <= 0:
            raise ValueError("queue limits must be positive")
        self.capacity, self.ttl, self.dedup_seconds = capacity, ttl, dedup_seconds
        self.items = deque()
        self.seen = {}
        self.condition = threading.Condition()
        self.closed = False

    def begin_turn(self, event: Event):
        """A retry makes any still-queued failure and its dedup entry obsolete."""
        with self.condition:
            self.items = deque(p for p in self.items if not (
                p.event.session_id == event.session_id and p.event.failure_code is not None))
            self.seen = {k: v for k, v in self.seen.items() if not (k[0] == event.session_id and v[3])}

    def put(self, event: Event, attention=False, now=None, state=None, turn_seconds=None,
            classification=None, supersede=True, mute_generation=0) -> bool:
        now = time.monotonic() if now is None else now
        with self.condition:
            if self.closed:
                return False
            self.seen = {k: v for k, v in self.seen.items() if now - v[0] < self.dedup_seconds}
            uninformative = (classification is not None and classification.state == "unknown"
                             and classification.delivery_kind == "unknown"
                             and classification.expectancy == "none" and classification.activity == "unknown")
            if event.evidence_source == "claude:Stop" and (state == "needs-you" or uninformative):
                # A question or permission hook already announced this waiting
                # state. An ambiguous closing sentence is not a second outcome.
                # Keep the window short even with prompt IDs: a later question
                # in the same prompt may be a new dependency. A real delivery,
                # caveat, review request, refusal or failure is never collapsed.
                if any(k[:2] == (event.session_id, event.turn_id) and v[2]
                       for k, v in self.seen.items()):
                    return False
            key = (event.session_id, event.turn_id, event.event_id)
            if key in self.seen:
                return False
            alias = (event.session_id, event.turn_id, event.dedup_key)
            if event.dedup_key and alias in self.seen:
                previous_id = self.seen[alias][1]
                # Distinct known tool IDs represent distinct questions; only
                # cross-hook aliases (question vs permission) are collapsed.
                if previous_id.split(":", 1)[0] != event.event_id.split(":", 1)[0]:
                    return False
            self.items = deque(p for p in self.items if now - p.received < self.ttl)
            resolves_attention = (event.evidence_source == "claude:Stop" and not attention
                                  and not uninformative)
            if supersede:
                self.items = deque(p for p in self.items if not (
                    p.event.session_id == event.session_id and (
                        not p.attention or resolves_attention or
                        (event.evidence_source == "claude:Stop" and p.event.failure_code is not None) or
                        (event.turn_id and p.event.turn_id and event.turn_id != p.event.turn_id))))
            if len(self.items) >= self.capacity:
                if not supersede:
                    return False
                routine = next((p for p in self.items if not p.attention), None)
                if routine is not None:
                    self.items.remove(routine)
                elif not attention:
                    return False
                else:
                    self.items.popleft()
            # Limit duplicate-cache memory independently of queue occupancy.
            seen = (now, event.event_id, event.explicit_state == "needs-you" and event.failure_code is None,
                    event.failure_code is not None)
            self.seen[key] = seen
            if event.dedup_key:
                self.seen[alias] = seen
            while len(self.seen) > 512:
                self.seen.pop(next(iter(self.seen)))
            self.items.append(Pending(event, attention, now, turn_seconds, mute_generation))
            self.condition.notify()
            return True

    def get(self):
        item = self.get_pending()
        return item.event if item is not None else None

    def get_pending(self):
        with self.condition:
            while not self.closed:
                now = time.monotonic()
                self.items = deque(p for p in self.items if now - p.received < self.ttl)
                if self.items:
                    item = next((p for p in self.items if p.attention), self.items[0])
                    self.items.remove(item)
                    return item
                self.condition.wait(0.2)
            return None

    def close(self):
        with self.condition:
            self.closed = True
            self.items.clear()
            self.condition.notify_all()

    def discard(self):
        with self.condition:
            self.items.clear()
            self.seen.clear()


def private_directory(directory: Path):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError(f"socket directory must be owned by you with mode 0700: {directory}")


class Service:
    def __init__(self, classifier, player, socket_path=None, queue_size=8, logger=None, min_turn_seconds=0,
                 long_turn_seconds=0, notify_in_flight=False, long_turn_player=None):
        for name, value in (("min_turn_seconds", min_turn_seconds), ("long_turn_seconds", long_turn_seconds)):
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if type(notify_in_flight) is not bool:
            raise ValueError("notify_in_flight must be a boolean")
        if long_turn_player is not None and not callable(long_turn_player):
            raise ValueError("long_turn_player must be callable")
        self.classifier, self.player = classifier, player
        self.socket_path = Path(socket_path or default_socket())
        self.queue = EventQueue(queue_size)
        self.logger = logger or (lambda _record: None)
        self.ready = threading.Event()
        self._stop = threading.Event()
        self.min_turn_seconds = min_turn_seconds
        self.long_turn_seconds = long_turn_seconds
        self.notify_in_flight = notify_in_flight
        self.long_turn_player = long_turn_player
        self.timings = TurnTimings()
        self.instance_id = uuid.uuid4().hex
        self.muted = False
        self._mute_generation = 0
        self._mute_lock = threading.Lock()

    def _suppress(self, result, turn_seconds):
        return (self.min_turn_seconds > 0 and turn_seconds is not None
                and 0 <= turn_seconds < self.min_turn_seconds
                and result.gesture in ("done", "answer", "verdict", "plan", "artifact", "published"))

    def _long_turn(self, result, turn_seconds):
        return (self.long_turn_seconds > 0 and turn_seconds is not None
                and turn_seconds >= self.long_turn_seconds
                and result.gesture in ("done", "answer", "verdict", "plan", "artifact", "published"))

    def _suppression_reason(self, result, turn_seconds):
        if result.gesture == "in-flight" and not self.notify_in_flight:
            return "in-flight"
        return "short-turn" if self._suppress(result, turn_seconds) else None

    def _control(self, payload, connection, stop):
        """Handle authenticated lifecycle requests before the connection closes."""
        if not isinstance(payload, dict) or "awaitonal_control" not in payload:
            return False
        verb = payload.get("awaitonal_control")
        guarded = verb in ("stop", "mute", "unmute")
        allowed = {"awaitonal_control", "protocol"} | ({"instance_id"} if guarded else set())
        if (verb not in ("status", "stop", "mute", "unmute") or type(payload.get("protocol")) is not int
                or payload["protocol"] != 1 or set(payload) != allowed
                or (guarded and payload.get("instance_id") != self.instance_id)):
            return True
        try:
            if _peer_uid(connection) != os.getuid():
                return True
            changed = False
            if verb in ("mute", "unmute"):
                with self._mute_lock:
                    muted = verb == "mute"
                    changed = self.muted != muted
                    self.muted = muted
                    if muted and changed:
                        self._mute_generation += 1
                        self.queue.discard()
                        self.timings.sessions.clear()
            response = {"service": "awaitonal", "protocol": 1, "version": __version__, "pid": os.getpid(),
                        "instance_id": self.instance_id, "status": "stopping" if verb == "stop" else "running",
                        "executable": str(Path(sys.argv[0]).resolve()), "muted": self.muted}
            if verb in ("mute", "unmute"):
                response["changed"] = changed
            connection.settimeout(0.05)
            connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
            if verb == "stop":
                stop.set()
        except (OSError, ValueError):
            pass
        return True

    def _intake(self, event, hints, now, mute_generation=None):
        with self._mute_lock:
            if mute_generation is None:
                mute_generation = self._mute_generation
            if self.muted or mute_generation != self._mute_generation:
                return
        if event.kind == "turn-start":
            self.queue.begin_turn(event)
            if self.min_turn_seconds > 0 or self.long_turn_seconds > 0:
                self.timings.start(event, now)
            return
        turn_seconds = None
        if ((self.min_turn_seconds > 0 or self.long_turn_seconds > 0)
                and event.evidence_source in ("claude:Stop", "claude:StopFailure")):
            turn_seconds = self.timings.finish(event, now)
        hint = hints.classify(event)
        # A default-silent activity update must not erase an unplayed delivery
        # or question. Queue it only when there is room so suppression still logs.
        silent_activity = hint and hint.gesture == "in-flight" and not self.notify_in_flight
        with self._mute_lock:
            if not self.muted and mute_generation == self._mute_generation:
                self.queue.put(event, bool(hint and hint.attention), state=hint.state if hint else None,
                               now=now, turn_seconds=turn_seconds, classification=hint,
                               supersede=not silent_activity, mute_generation=mute_generation)

    def _worker(self):
        while (pending := self.queue.get_pending()) is not None:
            with self._mute_lock:
                if self.muted or pending.mute_generation != self._mute_generation:
                    continue
            event = pending.event
            started = time.perf_counter()
            try:
                result = self.classifier.classify(event)
                elapsed = (time.perf_counter() - started) * 1000
                if self.queue.closed or self._stop.is_set():
                    break
                if result is not None:
                    suppressed = self._suppression_reason(result, pending.turn_seconds)
                    with self._mute_lock:
                        if self.muted or pending.mute_generation != self._mute_generation:
                            suppressed = "muted"
                    long_turn = not suppressed and self._long_turn(result, pending.turn_seconds)
                    self.logger({"state": result.state, "gesture": result.gesture,
                                 "expectancy": result.expectancy, "delivery_kind": result.delivery_kind,
                                 "evidence_source": result.evidence_source,
                                 "classification_ms": round(elapsed, 3), "failure_code": result.failure_code,
                                 "activity": result.activity,
                                 "turn_seconds": (round(pending.turn_seconds, 3)
                                                  if pending.turn_seconds is not None else None),
                                 "long_turn": long_turn, "suppressed": suppressed})
                    if not suppressed and not self.queue.closed and not self._stop.is_set():
                        player = self.long_turn_player if long_turn and self.long_turn_player else self.player
                        # Admission is atomic with mute. At most this one
                        # already-admitted cue may finish after mute replies;
                        # synthesis/playback never holds the listener's lock.
                        with self._mute_lock:
                            admitted = not self.muted and pending.mute_generation == self._mute_generation
                        if admitted:
                            player(result.gesture, len(event.text))
            except Exception as error:
                # Don't log exception strings: third-party errors may quote input.
                if not self.queue.closed and not self._stop.is_set():
                    self.logger({"error": type(error).__name__})

    def run(self, stop: threading.Event | None = None):
        from .classify import RulesClassifier
        hints = RulesClassifier()
        stop = stop or threading.Event()
        self._stop = stop
        private_directory(self.socket_path.parent)
        lock_path = self.socket_path.with_suffix(".lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        bound = False
        worker = None
        selector = selectors.DefaultSelector()
        clients = {}
        try:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                if error.errno in (errno.EACCES, errno.EAGAIN):
                    raise RuntimeError("Awaitonal is already serving this socket") from error
                raise
            if self.socket_path.exists() or self.socket_path.is_symlink():
                info = self.socket_path.lstat()
                if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.getuid():
                    raise ValueError("refusing to replace a non-socket or foreign socket")
                self.socket_path.unlink()
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(self.socket_path))
                bound = True
                os.chmod(self.socket_path, 0o600)
                listener.listen(32)
                listener.setblocking(False)
                selector.register(listener, selectors.EVENT_READ)
                worker = threading.Thread(target=self._worker, daemon=True)
                worker.start()
                self.ready.set()
                while not stop.is_set():
                    completed = []
                    for selected, _ in selector.select(0.05):
                        connection = selected.fileobj
                        if connection is listener:
                            connection, _ = listener.accept()
                            if len(clients) >= 32:
                                connection.close()
                                continue
                            connection.setblocking(False)
                            clients[connection] = (bytearray(), time.monotonic())
                            selector.register(connection, selectors.EVENT_READ)
                            continue
                        buffer, received = clients[connection]
                        complete = closed = False
                        # Drain already available bytes before applying the
                        # deadline. A full message may span several reads.
                        while len(buffer) <= MAX_WIRE:
                            try:
                                chunk = connection.recv(min(8192, MAX_WIRE + 1 - len(buffer)))
                            except BlockingIOError:
                                break
                            except OSError:
                                closed = True
                                break
                            if not chunk:
                                closed = True
                                break
                            buffer.extend(chunk)
                            if b"\n" in chunk:
                                complete = True
                                break
                        if len(buffer) > MAX_WIRE or complete or closed:
                            selector.unregister(connection)
                            del clients[connection]
                            try:
                                if complete and len(buffer) <= MAX_WIRE:
                                    payload = json.loads(bytes(buffer).split(b"\n", 1)[0])
                                    if not self._control(payload, connection, stop):
                                        event = event_from_wire(payload)
                                        if event is not None and not self.muted:
                                            completed.append((event, time.monotonic(), self._mute_generation))
                            except (ValueError, TypeError, UnicodeError, RecursionError):
                                pass
                            finally:
                                connection.close()
                    for connection, (_, received) in list(clients.items()):
                        if time.monotonic() - received > 0.15:
                            selector.unregister(connection)
                            connection.close()
                            del clients[connection]
                    # Classification can exceed a client's intake deadline.
                    # Always give ready peers another I/O pass before expiring
                    # them after time spent on our own classification work.
                    for event, received, mute_generation in completed:
                        if stop.is_set():
                            break
                        try:
                            self._intake(event, hints, received, mute_generation)
                        except (ValueError, TypeError, UnicodeError, RecursionError):
                            pass
        finally:
            self.queue.close()
            for connection in clients:
                connection.close()
            selector.close()
            if worker is not None:
                worker.join(timeout=3.0)
            if bound:
                self.socket_path.unlink(missing_ok=True)
            os.close(lock_fd)
