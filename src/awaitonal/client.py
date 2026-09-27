"""Lightweight, bounded fire-and-forget Unix-socket client (stdlib only)."""
import json
import os
from pathlib import Path
import select
import socket
import stat
import struct
import sys
import time

from .adapter import MAX_INPUT, MAX_WIRE, adapt_claude, adapt_codex, adapt_pi
from .types import Event


def default_socket() -> Path:
    return Path(os.environ.get("AWAITONAL_SOCKET", f"/tmp/awaitonal-{os.getuid()}/service.sock"))


def _endpoint_identity(path: Path) -> tuple[int, int, int, int]:
    """Reject public, foreign, or symlink endpoints without contacting them."""
    directory = path.parent.lstat()
    if (not stat.S_ISDIR(directory.st_mode) or directory.st_uid != os.getuid()
            or stat.S_IMODE(directory.st_mode) != 0o700):
        raise ValueError("socket directory must be owned by you with mode 0700")
    endpoint = path.lstat()
    if (not stat.S_ISSOCK(endpoint.st_mode) or endpoint.st_uid != os.getuid()
            or stat.S_IMODE(endpoint.st_mode) != 0o600):
        raise ValueError("socket must be owned by you with mode 0600")
    return directory.st_dev, directory.st_ino, endpoint.st_dev, endpoint.st_ino


def _peer_uid(connection: socket.socket) -> int:
    """Read kernel-supplied credentials; never ask the server to identify itself."""
    if hasattr(connection, "getpeereid"):
        return connection.getpeereid()[0]
    if sys.platform.startswith("linux"):
        credentials = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                           struct.calcsize("=iII"))
        return struct.unpack("=iII", credentials)[1]
    if sys.platform == "darwin":
        # macOS sys/ucred.h: xucred starts with uint version and uid_t uid,
        # followed by short ngroups, alignment padding and 16 gid_t entries.
        credentials = connection.getsockopt(0, socket.LOCAL_PEERCRED, 76)
        version, uid = struct.unpack_from("=II", credentials)
        if version != 0:  # XUCRED_VERSION
            raise OSError("unsupported Unix peer credential format")
        return uid
    raise OSError("Unix peer credentials are unavailable on this platform")


def _remaining_timeout(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("notification timed out")
    return remaining


def send_event(event: Event, socket_path=None, timeout: float = 0.08) -> None:
    data = json.dumps(event.to_dict(), ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
    if len(data) > MAX_WIRE:
        raise ValueError("notification is too large")
    deadline = time.monotonic() + timeout
    path = Path(socket_path or default_socket())
    identity = _endpoint_identity(path)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(_remaining_timeout(deadline))
        connection.connect(str(path))
        # Path checks alone race with pathname replacement. Authenticate the
        # connected process and recheck the endpoint before sending any bytes.
        if _peer_uid(connection) != os.getuid():
            raise ValueError("socket peer must be owned by you")
        if _endpoint_identity(path) != identity:
            raise ValueError("socket endpoint changed during connection")
        connection.settimeout(_remaining_timeout(deadline))
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


def run_hook(socket_path=None, dry_run: bool = False, *, adapter: str = "claude") -> int:
    """Never return a decision, feedback, or failure to a coding agent."""
    try:
        adapt = {"claude": adapt_claude, "codex": adapt_codex, "pi": adapt_pi}.get(adapter)
        event = adapt(json.loads(read_hook_input())) if adapt is not None else None
        if dry_run:
            if event is None:
                print(json.dumps({"ignored": True, "reason": "unsupported, subagent, or malformed event"}))
            elif event.kind == "turn-start":
                print(json.dumps({"recorded": "turn-start", "timing_available": bool(event.turn_id)}))
            elif event.kind == "turn-end":
                print(json.dumps({"recorded": "turn-end", "silent": True}))
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
