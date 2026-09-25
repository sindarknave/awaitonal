"""macOS playback with explicit errors, bounded execution, and no shell."""

from pathlib import Path
import platform
import subprocess
import threading
import time
import wave


def play_file(path: str | Path, stop_event: threading.Event | None = None) -> None:
    """Play a locally rendered WAV using afplay; callers decide error policy."""
    if stop_event is not None and stop_event.is_set():
        return
    target = Path(path).expanduser().resolve(strict=True)
    if platform.system() != "Darwin":
        raise RuntimeError("Playback requires macOS afplay; use demo --out to render a WAV")
    with wave.open(str(target), "rb") as stream:
        duration = stream.getnframes() / stream.getframerate()
    timeout = min(120.0, max(5.0, duration + 5.0))
    try:
        args = ["/usr/bin/afplay", str(target)]
        if stop_event is None:
            subprocess.run(
                args, check=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, timeout=timeout,
            )
        else:
            process = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            deadline = time.monotonic() + timeout
            try:
                while process.poll() is None:
                    if stop_event.wait(0.025):
                        process.terminate()
                        try:
                            process.wait(timeout=0.5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait(timeout=0.5)
                        return
                    if time.monotonic() >= deadline:
                        raise subprocess.TimeoutExpired(args, timeout)
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, args)
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait(timeout=0.5)
    except FileNotFoundError as exc:
        raise RuntimeError("macOS audio player /usr/bin/afplay is unavailable") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Audio playback timed out") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"Audio playback failed (afplay exit {exc.returncode})") from exc
