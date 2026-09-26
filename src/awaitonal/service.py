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
        valid = (not timing.ambiguous and bool(event.turn_id.strip()) and event.turn_id == timing.turn_id
                 and timing.started is not None and now >= timing.started)
        elapsed = now - timing.started if valid else None
        # Keep the ambiguity marker through subsequent starts, but release a
        # clean completed turn so a normal next turn can be measured.
        ambiguous = timing.ambiguous or not valid
        self.sessions[event.session_id] = TurnTiming("", None, now, ambiguous)
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

    def put(self, event: Event, attention=False, now=None, state=None, turn_seconds=None) -> bool:
        now = time.monotonic() if now is None else now
        with self.condition:
            if self.closed:
                return False
            self.seen = {k: v for k, v in self.seen.items() if now - v[0] < self.dedup_seconds}
            if event.evidence_source == "claude:Stop" and state == "needs-you":
                # A question or permission hook already announced this waiting
                # state. Missing prompt IDs get only the short dedup window.
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
            resolves_attention = event.evidence_source == "claude:Stop" and not attention
            self.items = deque(p for p in self.items if not (
                p.event.session_id == event.session_id and (
                    not p.attention or resolves_attention or
                    (event.evidence_source == "claude:Stop" and p.event.failure_code is not None) or
                    (event.turn_id and p.event.turn_id and event.turn_id != p.event.turn_id))))
            if len(self.items) >= self.capacity:
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
            self.items.append(Pending(event, attention, now, turn_seconds))
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


def private_directory(directory: Path):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o700:
        raise ValueError(f"socket directory must be owned by you with mode 0700: {directory}")


class Service:
    def __init__(self, classifier, player, socket_path=None, queue_size=8, logger=None, min_turn_seconds=0):
        if (type(min_turn_seconds) not in (int, float) or not math.isfinite(min_turn_seconds)
                or min_turn_seconds < 0):
            raise ValueError("min_turn_seconds must be finite and nonnegative")
        self.classifier, self.player = classifier, player
        self.socket_path = Path(socket_path or default_socket())
        self.queue = EventQueue(queue_size)
        self.logger = logger or (lambda _record: None)
        self.ready = threading.Event()
        self._stop = threading.Event()
        self.min_turn_seconds = min_turn_seconds
        self.timings = TurnTimings()
        self.instance_id = uuid.uuid4().hex

    def _suppress(self, result, turn_seconds):
        return (self.min_turn_seconds > 0 and turn_seconds is not None
                and 0 <= turn_seconds < self.min_turn_seconds
                and result.gesture in ("done", "answer", "plan", "artifact", "published"))

    def _control(self, payload, connection, stop):
        """Handle authenticated lifecycle requests before the connection closes."""
        if not isinstance(payload, dict) or "awaitonal_control" not in payload:
            return False
        verb = payload.get("awaitonal_control")
        allowed = {"awaitonal_control", "protocol"} | ({"instance_id"} if verb == "stop" else set())
        if (verb not in ("status", "stop") or type(payload.get("protocol")) is not int
                or payload["protocol"] != 1 or set(payload) != allowed
                or (verb == "stop" and payload.get("instance_id") != self.instance_id)):
            return True
        try:
            if _peer_uid(connection) != os.getuid():
                return True
            response = {"service": "awaitonal", "protocol": 1, "version": __version__, "pid": os.getpid(),
                        "instance_id": self.instance_id, "status": "stopping" if verb == "stop" else "running",
                        "executable": str(Path(sys.argv[0]).resolve())}
            connection.settimeout(0.05)
            connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
            if verb == "stop":
                stop.set()
        except (OSError, ValueError):
            pass
        return True

    def _intake(self, event, hints, now):
        if event.kind == "turn-start":
            self.queue.begin_turn(event)
            if self.min_turn_seconds > 0:
                self.timings.start(event, now)
            return
        turn_seconds = None
        if self.min_turn_seconds > 0 and event.evidence_source in ("claude:Stop", "claude:StopFailure"):
            turn_seconds = self.timings.finish(event, now)
        hint = hints.classify(event)
        self.queue.put(event, bool(hint and hint.attention), state=hint.state if hint else None,
                       now=now, turn_seconds=turn_seconds)

    def _worker(self):
        while (pending := self.queue.get_pending()) is not None:
            event = pending.event
            started = time.perf_counter()
            try:
                result = self.classifier.classify(event)
                elapsed = (time.perf_counter() - started) * 1000
                if self.queue.closed or self._stop.is_set():
                    break
                if result is not None:
                    suppressed = self._suppress(result, pending.turn_seconds)
                    self.logger({"state": result.state, "gesture": result.gesture,
                                 "expectancy": result.expectancy, "delivery_kind": result.delivery_kind,
                                 "evidence_source": result.evidence_source,
                                 "classification_ms": round(elapsed, 3), "failure_code": result.failure_code,
                                 "suppressed": "short-turn" if suppressed else None})
                    if not suppressed and not self.queue.closed and not self._stop.is_set():
                        self.player(result.gesture, len(event.text))
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
                        try:
                            chunk = connection.recv(8192)
                        except (ConnectionError, OSError):
                            chunk = b""
                        buffer.extend(chunk)
                        complete = b"\n" in buffer
                        if len(buffer) > MAX_WIRE or complete or not chunk:
                            selector.unregister(connection)
                            del clients[connection]
                            try:
                                if complete and len(buffer) <= MAX_WIRE:
                                    payload = json.loads(bytes(buffer).split(b"\n", 1)[0])
                                    if not self._control(payload, connection, stop):
                                        event = event_from_wire(payload)
                                        if event is not None:
                                            self._intake(event, hints, time.monotonic())
                            except (ValueError, TypeError, UnicodeError, RecursionError):
                                pass
                            finally:
                                connection.close()
                    for connection, (_, received) in list(clients.items()):
                        if time.monotonic() - received > 0.15:
                            selector.unregister(connection)
                            connection.close()
                            del clients[connection]
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
