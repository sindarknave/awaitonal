"""Authenticated service lifecycle and explicit per-user macOS login setup."""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import plistlib
import re
import socket
import stat
import subprocess
import sys
import tempfile
import time

from . import __version__
from .client import _endpoint_identity, _peer_uid, _remaining_timeout, default_socket

PROTOCOL_VERSION = 1
SERVICE_NAME = "awaitonal"
DEFAULT_LABEL = "dev.awaitonal.service"
_MANAGED_COMMENT = "Managed by Awaitonal service lifecycle v1"
_MAX_REPLY = 4096


class LifecycleError(RuntimeError):
    """A service could not be safely identified or managed."""


def _socket_path(socket_path=None):
    return Path(socket_path or default_socket()).absolute()


def _executable(executable=None):
    path = Path(executable or Path(sys.executable).parent / "awaitonal").absolute()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise LifecycleError(f"Awaitonal executable is unavailable: {path}")
    return path.resolve()


def _same_executable(left, right):
    return Path(left).resolve() == Path(right).resolve()


def _validate_reply(reply, action):
    if (not isinstance(reply, dict) or reply.get("service") != SERVICE_NAME
            or type(reply.get("protocol")) is not int or reply["protocol"] != PROTOCOL_VERSION
            or not isinstance(reply.get("version"), str)
            or not re.fullmatch(r"[0-9][A-Za-z0-9_.+-]{0,63}", reply["version"])
            or type(reply.get("pid")) is not int or reply["pid"] <= 0
            or not isinstance(reply.get("instance_id"), str)
            or not re.fullmatch(r"[0-9a-f]{32}", reply["instance_id"])
            or reply.get("status") != ("stopping" if action == "stop" else "running")
            or not isinstance(reply.get("executable"), str)
            or not Path(reply["executable"]).is_absolute()):
        raise LifecycleError("socket did not return a valid Awaitonal service identity")
    return reply


def _control(path, action, timeout, instance_id=None):
    deadline = time.monotonic() + timeout
    identity = _endpoint_identity(path)
    request = {"awaitonal_control": action, "protocol": PROTOCOL_VERSION}
    if instance_id is not None:
        request["instance_id"] = instance_id
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(_remaining_timeout(deadline))
        connection.connect(str(path))
        if _peer_uid(connection) != os.getuid() or _endpoint_identity(path) != identity:
            raise LifecycleError("socket peer or endpoint identity is untrusted")
        connection.settimeout(_remaining_timeout(deadline))
        connection.sendall(json.dumps(request, separators=(",", ":")).encode() + b"\n")
        response = bytearray()
        while b"\n" not in response:
            connection.settimeout(_remaining_timeout(deadline))
            chunk = connection.recv(min(1024, _MAX_REPLY + 1 - len(response)))
            if not chunk:
                raise LifecycleError("service closed without an Awaitonal identity reply")
            response.extend(chunk)
            if len(response) > _MAX_REPLY:
                raise LifecycleError("service identity reply is too large")
        line, trailing = bytes(response).split(b"\n", 1)
        if trailing.strip():
            raise LifecycleError("service returned multiple identity replies")
        return _validate_reply(json.loads(line), action)


def service_status(socket_path=None, timeout=0.3):
    """Return a verified identity, or stopped for a missing/stale endpoint.

    Unsafe endpoints, other services, and timeouts raise LifecycleError. They
    must never be interpreted as an invitation to replace a live listener.
    """
    path = _socket_path(socket_path)
    try:
        reply = _control(path, "status", timeout)
    except FileNotFoundError:
        return {"service": SERVICE_NAME, "status": "stopped", "reason": "missing", "socket": str(path)}
    except ConnectionRefusedError:
        return {"service": SERVICE_NAME, "status": "stopped", "reason": "stale", "socket": str(path)}
    except LifecycleError:
        raise
    except (OSError, ValueError, TypeError, RecursionError) as error:
        raise LifecycleError(f"cannot verify service: {type(error).__name__}") from error
    return {**reply, "socket": str(path), "version_matches": reply["version"] == __version__}


def _private_directory(directory):
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = directory.lstat()
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o700):
        raise LifecycleError("service directory must be owned by you with mode 0700")


@contextmanager
def _start_lock(path, deadline):
    _private_directory(path.parent)
    fd = os.open(path.with_name(path.name + ".start.lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise LifecycleError("unsafe service start lock")
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise LifecycleError("timed out waiting for concurrent service start")
                time.sleep(0.025)
        yield
    finally:
        os.close(fd)


def service_command(*, executable=None, socket_path=None, config=None, classifier="rules",
                    model_dir=None, semantic_config=None, min_turn_seconds=None,
                    queue_size=8, silent=False):
    """Build shell-free argv shared by detached and login-managed services."""
    if classifier not in ("rules", "semantic"):
        raise LifecycleError("classifier must be rules or semantic")
    command = [str(_executable(executable)), "serve", "--socket", str(_socket_path(socket_path)),
               "--classifier", classifier, "--queue-size", str(queue_size)]
    for flag, value in (("--config", config), ("--model-dir", model_dir),
                        ("--semantic-config", semantic_config)):
        if value is not None:
            command.extend((flag, str(Path(value).absolute())))
    if min_turn_seconds is not None:
        command.extend(("--min-turn-seconds", str(min_turn_seconds)))
    if silent:
        command.append("--silent")
    return command


def start_service(*, executable=None, socket_path=None, config=None, classifier="rules",
                  model_dir=None, semantic_config=None, min_turn_seconds=None,
                  queue_size=8, silent=False, timeout=10.0):
    command = service_command(executable=executable, socket_path=socket_path, config=config,
                              classifier=classifier, model_dir=model_dir, semantic_config=semantic_config,
                              min_turn_seconds=min_turn_seconds, queue_size=queue_size, silent=silent)
    path = _socket_path(socket_path)
    deadline = time.monotonic() + timeout
    with _start_lock(path, deadline):
        current = service_status(path)
        if current["status"] == "running":
            if not _same_executable(current["executable"], command[0]):
                raise LifecycleError("service belongs to another Awaitonal installation")
            if not current["version_matches"]:
                raise LifecycleError("running service version differs; stop it before starting this version")
            return {**current, "changed": False}
        managed = _resume_login_agent(command, path, max(0.01, deadline - time.monotonic()))
        if managed is not None:
            return managed
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, start_new_session=True, close_fds=True, cwd="/")
        try:
            while time.monotonic() < deadline:
                current = service_status(path)
                if current["status"] == "running":
                    if not _same_executable(current["executable"], command[0]) or not current["version_matches"]:
                        raise LifecycleError("a different installation appeared during service start")
                    return {**current, "changed": True}
                if process.poll() is not None:
                    raise LifecycleError(f"service exited before becoming ready (exit {process.returncode})")
                time.sleep(0.025)
            raise LifecycleError("service did not become ready before the startup timeout")
        except BaseException:
            # Only terminate the exact child this call created, never a PID
            # obtained from a socket reply or an on-disk PID file.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)
            raise


def stop_service(socket_path=None, *, timeout=5.0, expected_executable=None):
    path = _socket_path(socket_path)
    current = service_status(path)
    if current["status"] == "stopped":
        return {**current, "changed": False}
    if expected_executable is not None and not _same_executable(current["executable"], expected_executable):
        raise LifecycleError("service belongs to another Awaitonal installation")
    deadline = time.monotonic() + timeout
    try:
        reply = _control(path, "stop", min(0.5, timeout), current["instance_id"])
        if reply["instance_id"] != current["instance_id"]:
            raise LifecycleError("service instance changed during stop")
        status = _wait_stopped(path, max(0.01, deadline - time.monotonic()), current["instance_id"])
        return {**status, "changed": True}
    except LifecycleError:
        raise
    except (OSError, ValueError, TypeError) as error:
        raise LifecycleError(f"could not stop verified service: {type(error).__name__}") from error
    raise LifecycleError("service did not stop before the shutdown timeout")


def _agent_path(directory, label, *, create=True):
    if sys.platform != "darwin":
        raise LifecycleError("login service installation is supported only on macOS")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,127}", label):
        raise LifecycleError("invalid LaunchAgent label")
    directory = Path(directory or Path.home() / "Library/LaunchAgents").absolute()
    if create:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        info = directory.lstat()
    except FileNotFoundError:
        if not create:
            return directory / (label + ".plist")
        raise
    if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o022):
        raise LifecycleError("LaunchAgents directory must be owned by you and not writable by others")
    return directory / (label + ".plist")


def _read_owned_agent(path, label):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return None
    except OSError as error:
        raise LifecycleError("refusing unsafe LaunchAgent file") from error
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o022 or info.st_size > 65536):
            raise LifecycleError("refusing unsafe LaunchAgent file")
        try:
            document = plistlib.loads(stream.read(65537))
        except Exception as error:
            raise LifecycleError("refusing malformed LaunchAgent file") from error
    arguments = document.get("ProgramArguments") if isinstance(document, dict) else None
    if (not isinstance(document, dict) or document.get("Comment") != _MANAGED_COMMENT
            or document.get("Label") != label or not isinstance(arguments, list)
            or len(arguments) < 2 or not all(isinstance(arg, str) for arg in arguments)
            or not Path(arguments[0]).is_absolute() or arguments[1] != "serve"):
        raise LifecycleError("LaunchAgent is not managed by Awaitonal")
    return document


def _launchctl(*arguments, check=True):
    try:
        result = subprocess.run(["/bin/launchctl", *arguments], stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise LifecycleError(f"launchctl {arguments[0]} could not finish") from error
    if check and result.returncode:
        raise LifecycleError(f"launchctl {arguments[0]} failed (exit {result.returncode})")
    return result


def _write_agent(path, document):
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".awaitonal-", suffix=".plist", dir=path.parent)
        with os.fdopen(fd, "wb") as stream:
            plistlib.dump(document, stream, fmt=plistlib.FMT_XML, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)


def _wait_running(socket_path, executable, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = service_status(socket_path)
        if status["status"] == "running":
            if not _same_executable(status["executable"], executable) or not status["version_matches"]:
                raise LifecycleError("login service returned a different installation or version")
            return status
        time.sleep(0.05)
    raise LifecycleError("login service did not become ready; use a stable installed runtime outside protected Documents/Desktop folders")


def _wait_stopped(socket_path, timeout=5.0, instance_id=None):
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            status = service_status(socket_path)
        except LifecycleError as error:
            # The known process may close a connection while shutting down.
            # Require missing/refused confirmation; never call that error a stop.
            last_error = error
        else:
            if status["status"] == "stopped":
                return status
            if instance_id is not None and status["instance_id"] != instance_id:
                raise LifecycleError("another service instance appeared while stopping")
        time.sleep(0.025)
    raise LifecycleError("service did not stop before the shutdown timeout") from last_error


def _agent_socket(document):
    arguments = document["ProgramArguments"]
    if arguments.count("--socket") != 1:
        return None
    index = arguments.index("--socket") + 1
    return Path(arguments[index]).resolve() if index < len(arguments) else None


def _resume_login_agent(command, socket_path, timeout):
    """Keep supervision and saved options when a plugin updates its runtime."""
    if sys.platform != "darwin":
        return None
    path = _agent_path(None, DEFAULT_LABEL, create=False)
    try:
        document = _read_owned_agent(path, DEFAULT_LABEL)
    except LifecycleError:
        # An unrelated or unsafe file grants no authority to control a job.
        return None
    if (document is None or not _same_executable(document["ProgramArguments"][0], command[0])
            or _agent_socket(document) != socket_path.resolve()):
        return None
    target = f"gui/{os.getuid()}/{DEFAULT_LABEL}"
    already_loaded = _launchctl("print", target, check=False).returncode == 0
    bootstrapped = False
    try:
        if not already_loaded:
            _launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
            bootstrapped = True
        # The socket can close before the previous process has fully exited.
        # A plain kickstart then succeeds without arranging a replacement.
        # Restart only this matching owned job, never a PID from the protocol.
        if already_loaded:
            _launchctl("kickstart", "-k", target)
        else:
            _launchctl("kickstart", target)
        running = _wait_running(socket_path, command[0], timeout)
        return {**running, "changed": True, "supervision": "launch_agent", "launch_agent": str(path),
                "configuration": "existing LaunchAgent arguments preserved"}
    except Exception:
        if bootstrapped:
            _launchctl("bootout", target, check=False)
        raise


def install_launch_agent(*, executable=None, socket_path=None, config=None, classifier="rules",
                         model_dir=None, semantic_config=None, min_turn_seconds=None,
                         queue_size=8, silent=False, directory=None, label=DEFAULT_LABEL,
                         load=True, timeout=10.0):
    path = _agent_path(directory, label)
    command = service_command(executable=executable, socket_path=socket_path, config=config,
                              classifier=classifier, model_dir=model_dir, semantic_config=semantic_config,
                              min_turn_seconds=min_turn_seconds, queue_size=queue_size, silent=silent)
    document = {"Label": label, "Comment": _MANAGED_COMMENT, "ProgramArguments": command,
                "RunAtLoad": True, "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 10,
                "ProcessType": "Background", "WorkingDirectory": "/", "Umask": 0o077,
                "StandardOutPath": "/dev/null", "StandardErrorPath": "/dev/null"}
    previous = _read_owned_agent(path, label)
    if previous is not None and not _same_executable(previous["ProgramArguments"][0], command[0]):
        raise LifecycleError("LaunchAgent belongs to another Awaitonal installation")
    target = f"gui/{os.getuid()}/{label}"
    was_loaded = bool(load and _launchctl("print", target, check=False).returncode == 0)
    if was_loaded and previous is None:
        raise LifecycleError("refusing to replace an unowned loaded LaunchAgent")
    if previous == document and was_loaded:
        current = service_status(socket_path)
        if (current["status"] == "running" and current["version_matches"]
                and _same_executable(current["executable"], command[0])):
            return {"path": str(path), "label": label, "changed": False, "loaded": True,
                    "service": current}
    unloaded = written = bootstrapped = False
    try:
        if was_loaded:
            _launchctl("bootout", target)
            unloaded = True
        if load:
            # A manually started instance may be transferred only when it
            # belongs to this installation, never just because its PID exists.
            stop_service(socket_path, expected_executable=command[0])
        if previous != document:
            _write_agent(path, document)
            written = True
        running = None
        if load:
            _launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
            bootstrapped = True
            _launchctl("kickstart", target)
            running = _wait_running(socket_path, command[0], timeout)
        return {"path": str(path), "label": label, "changed": previous != document or load,
                "loaded": bool(load), **({"service": running} if running else {})}
    except Exception as error:
        # Undo only the job/file this operation changed. Existing managed
        # configuration is restored if an update cannot become healthy.
        try:
            if bootstrapped:
                _launchctl("bootout", target, check=False)
            if written:
                if previous is None:
                    path.unlink(missing_ok=True)
                else:
                    _write_agent(path, previous)
            if unloaded:
                _launchctl("bootstrap", f"gui/{os.getuid()}", str(path))
        except Exception as rollback_error:
            raise LifecycleError("login service setup failed and rollback needs attention") from rollback_error
        if isinstance(error, LifecycleError):
            raise
        raise LifecycleError(f"login service setup failed: {type(error).__name__}") from error


def uninstall_launch_agent(*, directory=None, label=DEFAULT_LABEL, expected_executable=None, unload=True):
    path = _agent_path(directory, label, create=False)
    document = _read_owned_agent(path, label)
    if document is None:
        return {"path": str(path), "label": label, "changed": False, "loaded": False}
    if expected_executable is not None and not _same_executable(document["ProgramArguments"][0], expected_executable):
        raise LifecycleError("LaunchAgent belongs to another Awaitonal installation")
    target = f"gui/{os.getuid()}/{label}"
    if unload and _launchctl("print", target, check=False).returncode == 0:
        _launchctl("bootout", target)
        socket_path = _agent_socket(document)
        if socket_path is not None:
            _wait_stopped(socket_path)
    path.unlink()
    return {"path": str(path), "label": label, "changed": True, "loaded": False}
