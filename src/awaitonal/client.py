"""Lightweight, bounded fire-and-forget Unix-socket client (stdlib only)."""
import json
import os
from pathlib import Path
import select
import socket
import sys
import time

from .adapter import MAX_INPUT, MAX_WIRE, adapt_claude
from .types import Event


def default_socket() -> Path:
    return Path(os.environ.get("AWAITONAL_SOCKET", f"/tmp/awaitonal-{os.getuid()}/service.sock"))


def send_event(event: Event, socket_path=None, timeout: float = 0.08) -> None:
    data = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(data) > MAX_WIRE:
        raise ValueError("notification is too large")
    deadline = time.monotonic() + timeout
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(timeout)
        connection.connect(str(socket_path or default_socket()))
        connection.settimeout(max(0.001, deadline - time.monotonic()))
        connection.sendall(data)


def read_hook_input(timeout: float = 0.15) -> bytes:
    """Bound both byte count and wall time, even if a pipe never reaches EOF."""
    fd = sys.stdin.fileno()
    chunks = bytearray()
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not select.select([fd], [], [], remaining)[0]:
            raise TimeoutError("hook input timed out")
        part = os.read(fd, min(8192, MAX_INPUT + 1 - len(chunks)))
        if not part:
            return bytes(chunks)
        chunks.extend(part)
        if len(chunks) > MAX_INPUT:
            raise ValueError("hook input is too large")


def run_hook(socket_path=None, dry_run: bool = False) -> int:
    """Never return a decision, feedback, or failure to a coding agent."""
    try:
        event = adapt_claude(json.loads(read_hook_input()))
        if dry_run:
            if event is None:
                print(json.dumps({"ignored": True, "reason": "unsupported, subagent, or malformed event"}))
            else:
                from .classify import RulesClassifier
                result = RulesClassifier().classify(event)
                print(json.dumps(result.to_dict() if result else {"ignored": True}))
        elif event is not None:
            send_event(event, socket_path)
    except Exception:
        if dry_run:
            print(json.dumps({"ignored": True, "reason": "invalid input or unavailable service"}))
    return 0
