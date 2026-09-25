"""One private local listener and one serial classification/playback worker."""
from collections import deque
from dataclasses import dataclass
import errno
import fcntl
import json
import os
from pathlib import Path
import selectors
import socket
import stat
import threading
import time

from .adapter import MAX_WIRE, event_from_wire
from .client import default_socket
from .types import Event


@dataclass
class Pending:
    event: Event
    attention: bool
    received: float


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

    def put(self, event: Event, attention=False, now=None, state=None) -> bool:
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
            self.seen[key] = (now, event.event_id, event.explicit_state == "needs-you")
            if event.dedup_key:
                self.seen[alias] = (now, event.event_id, event.explicit_state == "needs-you")
            while len(self.seen) > 512:
                self.seen.pop(next(iter(self.seen)))
            self.items.append(Pending(event, attention, now))
            self.condition.notify()
            return True

    def get(self):
        with self.condition:
            while not self.closed:
                now = time.monotonic()
                self.items = deque(p for p in self.items if now - p.received < self.ttl)
                if self.items:
                    item = next((p for p in self.items if p.attention), self.items[0])
                    self.items.remove(item)
                    return item.event
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
    def __init__(self, classifier, player, socket_path=None, queue_size=8, logger=None):
        self.classifier, self.player = classifier, player
        self.socket_path = Path(socket_path or default_socket())
        self.queue = EventQueue(queue_size)
        self.logger = logger or (lambda _record: None)
        self.ready = threading.Event()
        self._stop = threading.Event()

    def _worker(self):
        while (event := self.queue.get()) is not None:
            started = time.perf_counter()
            try:
                result = self.classifier.classify(event)
                elapsed = (time.perf_counter() - started) * 1000
                if self.queue.closed or self._stop.is_set():
                    break
                if result is not None:
                    self.logger({"state": result.state, "evidence_source": result.evidence_source,
                                 "classification_ms": round(elapsed, 3)})
                    if not self.queue.closed and not self._stop.is_set():
                        self.player(result.state, len(event.text))
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
                            connection.close()
                            del clients[connection]
                            if complete and len(buffer) <= MAX_WIRE:
                                try:
                                    payload = json.loads(bytes(buffer).split(b"\n", 1)[0])
                                    event = event_from_wire(payload)
                                    if event is not None:
                                        hint = hints.classify(event)
                                        attention = bool(hint and hint.state in ("needs-you", "rejected"))
                                        self.queue.put(event, attention, state=hint.state if hint else None)
                                except (ValueError, TypeError, UnicodeError, RecursionError):
                                    pass
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
