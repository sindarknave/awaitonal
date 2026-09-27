"""Small CLI; the hook path imports neither NumPy nor an ML runtime."""
import argparse
import json
import os
from pathlib import Path
import shlex
import signal
import sys
import tempfile
import threading
import uuid

from .types import Event, GESTURES
from .voices import VOICE_NAMES


def model_directory():
    return Path(os.environ.get("AWAITONAL_MODEL_DIR", Path.home() / ".cache/awaitonal/all-MiniLM-L6-v2"))


def make_classifier(args, threshold):
    if args.classifier == "semantic":
        from .semantic import SemanticClassifier
        return SemanticClassifier(args.model_dir, threshold=threshold, config_path=args.semantic_config)
    from .classify import RulesClassifier
    return RulesClassifier(threshold=threshold)


def parser():
    cli = argparse.ArgumentParser(prog="awaitonal", description="Hear how your agent left things.")
    sub = cli.add_subparsers(dest="command", required=True)
    for name in ("demo", "play", "ensemble-demo"):
        help_text = {"demo": "audition or render the palette", "play": "play or render one gesture",
                     "ensemble-demo": "audition rotating session voices and composed burst comparisons"}
        command = sub.add_parser(name, help=help_text[name])
        if name == "play":
            command.add_argument("state", choices=GESTURES, metavar="GESTURE")
            command.add_argument("--long-turn", action="store_true", help="audition the elapsed-time variant of a routine cue")
        if name == "ensemble-demo":
            command.add_argument("--mode", choices=("voices", "serial", "overlap", "rotation"), default="voices",
                                 help="voice comparison, new/returning sessions, or a composed burst")
        else:
            command.add_argument("--voice", choices=VOICE_NAMES, default="default",
                                 help="instrument for the gesture; default keeps the original palette")
        command.add_argument("--out", type=Path, help="write WAV without playback")
        command.add_argument("--config", type=Path, help="editable palette TOML")
    classify = sub.add_parser("classify", help="inspect a response's reported state")
    classify.add_argument("--text", required=True)
    classify.add_argument("--json", action="store_true")
    notify = sub.add_parser("notify", help="enqueue a response in the running service")
    notify.add_argument("--text", required=True)
    notify.add_argument("--session", default="cli")
    notify.add_argument("--turn", default="")
    notify.add_argument("--socket", type=Path)
    serve = sub.add_parser("serve", help="foreground private local service; Ctrl-C stops it")
    serve.add_argument("--socket", type=Path)
    serve.add_argument("--queue-size", type=int, default=8)
    serve.add_argument("--silent", action="store_true", help="classify and log diagnostics without playing (integration testing)")
    serve.add_argument("--min-turn-seconds", type=float, help="suppress short routine turns with known timing; default 0")
    hook = sub.add_parser("hook", help="quiet notification-only agent hook")
    hook.add_argument("adapter", choices=["claude", "codex", "pi"])
    hook.add_argument("--socket", type=Path)
    hook.add_argument("--dry-run", action="store_true", help="inspect fixture with rules; prints JSON, never register this mode as a hook")
    config = sub.add_parser("hook-config", help="print a hook settings fragment without editing settings")
    config.add_argument("--adapter", choices=("claude", "codex"), default="claude")
    config.add_argument("--executable", type=Path, help="absolute installed awaitonal executable")
    config.add_argument("--socket", type=Path)
    for name in ("init", "uninstall"):
        command = sub.add_parser(name, help="preview or apply owned agent hook settings changes")
        command.add_argument("--adapter", choices=("claude", "codex"), default="claude")
        command.add_argument("--settings", type=Path)
        command.add_argument("--apply", action="store_true", help="back up and apply the displayed changes")
        command.add_argument("--legacy-executable", type=Path, help="explicitly migrate exact hooks for this old executable")
        command.add_argument("--socket", type=Path)
        if name == "init":
            command.add_argument("--mode", choices=("standalone", "plugin"), default="standalone")
            command.add_argument("--executable", type=Path)
    doctor = sub.add_parser("doctor", help="inspect setup without sending response text or playing audio")
    doctor.add_argument("--adapter", choices=("claude", "codex", "pi"), default="claude")
    doctor.add_argument("--settings", type=Path)
    doctor.add_argument("--socket", type=Path)
    doctor.add_argument("--json", action="store_true")
    doctor.add_argument("--test-sound", action="store_true", help="explicitly play one cue after diagnosis")
    management = sub.add_parser("service", help="manage the resident local service")
    operations = management.add_subparsers(dest="operation", required=True)
    for name in ("start", "stop", "status", "mute", "unmute", "install", "uninstall"):
        command = operations.add_parser(name)
        command.add_argument("--socket", type=Path)
        if name in ("start", "install"):
            command.add_argument("--executable", type=Path)
            command.add_argument("--classifier", choices=("rules", "semantic"), default="rules")
            command.add_argument("--model-dir", type=Path)
            command.add_argument("--semantic-config", type=Path)
            command.add_argument("--config", type=Path)
            command.add_argument("--queue-size", type=int, default=8)
            command.add_argument("--min-turn-seconds", type=float)
            command.add_argument("--silent", action="store_true")
        if name in ("stop", "mute", "unmute", "uninstall"):
            command.add_argument("--expected-executable", type=Path)
    setup = sub.add_parser("model-setup", help="explicitly download the optional sentence encoder")
    setup.add_argument("--model-dir", type=Path, default=model_directory())
    evaluate = sub.add_parser("evaluate", help="evaluate independent labeled fixtures")
    evaluate.add_argument("--fixtures", type=Path, default=Path("examples/evaluation.jsonl"))
    for command in (classify, serve, evaluate):
        command.add_argument("--classifier", choices=("rules", "semantic"), default="rules")
        command.add_argument("--model-dir", type=Path, default=model_directory())
        command.add_argument("--semantic-config", type=Path)
        command.add_argument("--config", type=Path, help="palette and routing threshold TOML")
    return cli


def hook_configuration(executable: Path | None = None, socket_path=None, *, verify=True, adapter="claude"):
    # sys.executable lives in the active environment, so the default remains
    # valid from any project directory. No uv invocation/download on hook path.
    if adapter not in ("claude", "codex"):
        raise ValueError("unknown hook adapter")
    executable = executable or Path(sys.executable).parent / "awaitonal"
    executable = executable.absolute()
    if verify and (not executable.is_file() or not os.access(executable, os.X_OK)):
        raise ValueError(f"installed awaitonal executable not found: {executable}")
    parts = [str(executable), "hook", adapter]
    if socket_path:
        parts.extend(["--socket", str(Path(socket_path).absolute())])
    handler = {"type": "command", "command": shlex.join(parts), "timeout": 2}
    hooks = {
        "Stop": [{"hooks": [handler]}],
        "PreToolUse": [{"matcher": "AskUserQuestion" if adapter == "claude" else
                       "^(request_user_input|request_user_input_async)$", "hooks": [handler]}],
        "PermissionRequest": [{"hooks": [handler]}],
        "UserPromptSubmit": [{"hooks": [handler]}],
    }
    if adapter == "claude":
        hooks["StopFailure"] = [{"hooks": [handler]}]
    return {"hooks": hooks}


def execute(args):
    if args.command == "hook":
        from .client import run_hook
        return run_hook(args.socket, args.dry_run, adapter=args.adapter)
    if args.command == "hook-config":
        print(json.dumps(hook_configuration(args.executable, args.socket, adapter=args.adapter), indent=2))
        return 0
    if args.command in ("init", "uninstall"):
        from .setup import configure_hooks, default_settings
        mode = args.mode if args.command == "init" else "uninstall"
        fragment = hook_configuration(args.executable, args.socket, adapter=args.adapter) if mode == "standalone" else None
        legacy = hook_configuration(args.legacy_executable, args.socket, verify=False,
                                    adapter=args.adapter) if args.legacy_executable else None
        result = configure_hooks(args.settings or default_settings(args.adapter), fragment, mode=mode,
                                 apply=args.apply, legacy_fragment=legacy, adapter=args.adapter)
        if result["diff"]:
            print("Changed hook entries only; unrelated settings are preserved.")
            print(result["diff"])
        else:
            print("No hook settings changes needed.")
        if result["backup"]:
            print(f"Backup: {result['backup']}")
        print("Applied." if args.apply else "Preview only. Use --apply to write these changes.")
        if args.adapter == "codex" and args.command == "init":
            print("Codex must review and trust new or changed hooks before they run. Use /hooks in Codex CLI.")
        return 0
    if args.command == "service":
        from .lifecycle import (start_service, stop_service, service_status, set_service_muted,
                                install_launch_agent, uninstall_launch_agent)
        if args.operation in ("start", "install"):
            options = {name: getattr(args, name) for name in (
                "executable", "config", "classifier", "model_dir", "semantic_config",
                "min_turn_seconds", "queue_size", "silent")}
            options["socket_path"] = args.socket
            result = (start_service if args.operation == "start" else install_launch_agent)(**options)
        elif args.operation == "stop":
            result = stop_service(args.socket, expected_executable=args.expected_executable)
        elif args.operation == "status":
            result = service_status(args.socket)
        elif args.operation in ("mute", "unmute"):
            result = set_service_muted(args.operation == "mute", args.socket,
                                       expected_executable=args.expected_executable)
        else:
            result = uninstall_launch_agent(expected_executable=args.expected_executable)
        print(json.dumps(result, indent=2))
        return 0
    if args.command == "doctor":
        from .diagnostics import diagnose
        result = diagnose(args.settings, args.socket, adapter=args.adapter)
        if args.test_sound:
            execute(parser().parse_args(["play", "done"]))
            result["audio_tested"] = True
            result["audio_note"] = "Audio player finished; device output was not independently verified."
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            for check in result["checks"]:
                print(f"{check['status']}: {check['name']}: {check['message']}")
        return 0 if result["ok"] else 1
    if args.command == "notify":
        from .adapter import MAX_INPUT
        from .client import send_event
        if not args.text.strip() or len(args.text.encode("utf-8")) > MAX_INPUT:
            raise ValueError("text must contain 1–65536 UTF-8 bytes")
        if not args.session.strip() or len(args.session.encode("utf-8")) > 256 or len(args.turn.encode("utf-8")) > 256:
            raise ValueError("session and turn identifiers must be at most 256 UTF-8 bytes")
        send_event(Event(args.session, str(uuid.uuid4()), args.text, turn_id=args.turn), args.socket)
        print("Notification handed off.")
        return 0
    if args.command == "model-setup":
        from .semantic import setup_model
        setup_model(args.model_dir)
        print(f"Local model ready: {args.model_dir}")
        return 0
    from .config import load_config
    config = load_config(args.config)
    if args.command in ("play", "demo", "ensemble-demo"):
        from .synth import render, render_demo, write_wav
        if args.command == "ensemble-demo":
            from .audition import render_ensemble_demo
            samples, _ = render_ensemble_demo(config, mode=args.mode)
        elif args.command == "demo":
            samples = render_demo(config, voice=args.voice)
        else:
            samples = render(args.state, config, long_turn=args.long_turn, voice=args.voice)
        if args.out:
            write_wav(args.out, samples, config["synth"]["sample_rate"])
            print(args.out.absolute())
        else:
            from .playback import play_file
            with tempfile.TemporaryDirectory(prefix="awaitonal-") as directory:
                path = Path(directory) / "audition.wav"
                write_wav(path, samples, config["synth"]["sample_rate"])
                play_file(path)
        return 0
    classifier = make_classifier(args, config["classification"]["caveats_threshold"])
    if args.command == "classify":
        from .adapter import MAX_INPUT
        if len(args.text.encode("utf-8")) > MAX_INPUT:
            raise ValueError("text exceeds 65536 UTF-8 bytes")
        result = classifier.classify(Event("cli", "classification", args.text))
        if result is None:
            raise ValueError("no assistant prose to classify")
        print(json.dumps(result.to_dict(), indent=2) if args.json else
              f"{result.gesture} ({result.state}): {result.reason}")
        return 0
    if args.command == "evaluate":
        from .evaluation import evaluate
        print(json.dumps(evaluate(classifier, args.fixtures), indent=2))
        return 0
    from .service import Service
    from .client import default_socket
    from .playback import play_file
    from .synth import render, write_wav
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda *_: stop.set())
    with tempfile.TemporaryDirectory(prefix="awaitonal-audio-") as directory:
        audio_path = Path(directory) / "notification.wav"

        def player(state, response_length):
            if not args.silent:
                write_wav(audio_path, render(state, config, response_length), config["synth"]["sample_rate"])
                play_file(audio_path, stop_event=stop)

        def long_turn_player(state, response_length):
            if not args.silent:
                write_wav(audio_path, render(state, config, response_length, long_turn=True), config["synth"]["sample_rate"])
                play_file(audio_path, stop_event=stop)

        def voice_player(state, response_length, voice, long_turn):
            if not args.silent:
                write_wav(audio_path, render(state, config, response_length, voice=voice,
                                            long_turn=long_turn), config["synth"]["sample_rate"])
                play_file(audio_path, stop_event=stop)

        def logger(record):
            print(json.dumps(record), file=sys.stderr, flush=True)

        minimum = args.min_turn_seconds
        if minimum is None:
            minimum = config.get("notifications", {}).get("min_turn_seconds", 0)
        notifications = config.get("notifications", {})
        service = Service(classifier, player, args.socket, args.queue_size, logger, min_turn_seconds=minimum,
                          long_turn_seconds=notifications.get("long_turn_seconds", 0),
                          notify_in_flight=notifications.get("notify_in_flight", False),
                          long_turn_player=long_turn_player,
                          session_voices=notifications.get("session_voices", False),
                          voice_cycle=notifications.get("voice_cycle"),
                          voice_player=voice_player)
        print(f"Awaitonal starting on {args.socket or default_socket()} ({args.classifier}); Ctrl-C to stop.", file=sys.stderr, flush=True)
        service.run(stop)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Even malformed hook flags must never ask Claude to continue or print a
    # parser error. --dry-run remains an explicit diagnostic command.
    quiet_hook = bool(argv and argv[0] == "hook" and "--dry-run" not in argv)
    if quiet_hook:
        from contextlib import redirect_stdout, redirect_stderr
        with open(os.devnull, "w") as sink, redirect_stdout(sink), redirect_stderr(sink):
            try:
                return execute(parser().parse_args(argv))
            except (Exception, SystemExit):
                return 0
    try:
        return execute(parser().parse_args(argv))
    except (OSError, ValueError, RuntimeError, ImportError) as error:
        print(f"awaitonal: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
