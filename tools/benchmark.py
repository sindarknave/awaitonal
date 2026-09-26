"""Reproducible real timings; no audio, no raw text in results."""
import argparse
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid

from awaitonal.classify import RulesClassifier
from awaitonal.client import send_event
from awaitonal.service import Service
from awaitonal.types import Event


def ms(call):
    start = time.perf_counter()
    call()
    return (time.perf_counter() - start) * 1000


def summary(values):
    values = sorted(values)
    return {"n": len(values), "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(values[min(len(values) - 1, int(len(values) * .95))], 3)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path)
    args = parser.parse_args()
    text = "Implemented the update; integration tests were unavailable."
    event = Event("benchmark", "one", text)
    report = {"platform": platform.platform(), "machine": platform.machine(),
              "python": platform.python_version(), "units": "milliseconds",
              "notes": "First process launch is measured before repeated launches; OS caches uncontrolled. Handoff is connect/send, not a processing acknowledgement. No audio."}
    classify_command = [sys.executable, "-m", "awaitonal", "classify", "--text", text, "--json"]
    def process_classify():
        subprocess.run(classify_command, check=True, capture_output=True, timeout=10)
    report["rules_first_process_ms"] = round(ms(process_classify), 3)
    report["rules_repeated_new_process"] = summary([ms(process_classify) for _ in range(10)])
    rules = RulesClassifier()
    report["rules_first_resident_classification_ms"] = round(ms(lambda: rules.classify(event)), 3)
    report["rules_warm_resident"] = summary([ms(lambda: rules.classify(event)) for _ in range(200)])
    with tempfile.TemporaryDirectory(prefix="at-bench-", dir="/tmp") as directory:
        socket_path = Path(directory) / "s.sock"
        service = Service(rules, lambda *_: None, socket_path)
        stop = threading.Event()
        thread = threading.Thread(target=service.run, args=(stop,), daemon=True)
        thread.start()
        if not service.ready.wait(3):
            raise RuntimeError("benchmark service did not start")
        try:
            payload = json.dumps({"session_id": "bench", "hook_event_name": "Stop", "last_assistant_message": text}).encode()
            command = [sys.executable, "-m", "awaitonal", "hook", "claude", "--socket", str(socket_path)]
            def hook():
                outcome = subprocess.run(command, input=payload, capture_output=True, timeout=2)
                assert outcome.returncode == 0 and not outcome.stdout and not outcome.stderr
            report["hook_first_process_ms"] = round(ms(hook), 3)
            report["hook_repeated_new_process"] = summary([ms(hook) for _ in range(20)])
            report["socket_warm_connect_send"] = summary([
                ms(lambda: send_event(Event("bench", str(uuid.uuid4()), text), socket_path)) for _ in range(100)])
        finally:
            stop.set()
            thread.join(4)
    if args.model_dir:
        start = time.perf_counter()
        from awaitonal.semantic import SemanticClassifier
        semantic = SemanticClassifier(args.model_dir)
        report["semantic_import_load_anchors_ms"] = round((time.perf_counter() - start) * 1000, 3)
        report["semantic_first_classification_ms"] = round(ms(lambda: semantic.classify(event)), 3)
        report["semantic_warm_resident"] = summary([ms(lambda: semantic.classify(event)) for _ in range(20)])
        report["semantic_measured_backend"] = semantic.classify(event).diagnostics["backend"]
        # Explicit deliveries use shared rules. Measure unrecognized prose
        # separately so the fast route does not masquerade as encoder latency.
        fallback = Event("benchmark", "fallback", "The work is described.")
        report["semantic_fallback_measured_backend"] = semantic.classify(fallback).diagnostics["backend"]
        report["semantic_fallback_warm_resident"] = summary([
            ms(lambda: semantic.classify(fallback)) for _ in range(20)])
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
