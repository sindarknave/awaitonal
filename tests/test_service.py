from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import wave

import pytest

from awaitonal.adapter import MAX_INPUT, adapt_claude
from awaitonal.classify import RulesClassifier
from awaitonal.client import send_event
from awaitonal.service import EventQueue, Service
from awaitonal.types import Classification, Controls, Event, controls_for, map_controls


@contextmanager
def running_service(player=None, classifier=None, queue_size=32, min_turn_seconds=0, **options):
    with tempfile.TemporaryDirectory(prefix="at-", dir="/tmp") as directory:
        path = Path(directory) / "s.sock"
        played, logs, failures = [], [], []
        stop = threading.Event()
        service = Service(classifier or RulesClassifier(), player or (lambda state, length: played.append(state)),
                          path, queue_size, logs.append, min_turn_seconds=min_turn_seconds, **options)

        def run():
            try:
                service.run(stop)
            except Exception as error:
                failures.append(error)

        thread = threading.Thread(target=run)
        thread.start()
        assert service.ready.wait(3), failures
        try:
            yield service, path, played, logs
        finally:
            stop.set()
            thread.join(4)
            assert not thread.is_alive()
            assert not path.exists()
            assert not failures


def eventually(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert predicate()


@pytest.mark.parametrize("loose,needs,rejected,expected", [
    (0, False, False, "done"), (0.49, False, False, "done"),
    (0.5, False, False, "caveats"), (1, True, False, "needs-you"),
    (1, True, True, "rejected"), (0, False, True, "rejected"),
])
def test_state_precedence(loose, needs, rejected, expected):
    assert map_controls(Controls(loose, needs, rejected)) == expected


def test_control_validation_and_configurable_threshold():
    assert map_controls(Controls(0.6), 0.7) == "done"
    for value in (float("nan"), float("inf"), -0.1, 1.1):
        with pytest.raises(ValueError):
            Controls(value)
    with pytest.raises(ValueError):
        Controls(needs_you="true")


def test_duplicates_sessions_turns_and_expiry():
    queue = EventQueue()
    event = Event("one", "same", "Done.", turn_id="turn-a")
    now = time.monotonic()
    assert queue.put(event, now=now)
    assert not queue.put(event, now=now + 0.1)
    assert queue.put(Event("two", "same", "Done.", turn_id="turn-a"), now=now + 0.1)
    assert queue.put(Event("one", "same", "Done.", turn_id="turn-b"), now=now + 0.1)
    assert queue.put(event, now=now + 2.1)


def test_question_permission_alias_does_not_hide_distinct_questions():
    queue = EventQueue()
    for event_id, expected in (("question:tool1", True), ("permission:hash", False),
                               ("question:tool2", True)):
        assert queue.put(Event("s", event_id, explicit_state="needs-you", dedup_key="tool:hash"), True) is expected


def test_queue_prefers_attention_and_removes_obsolete_routine():
    queue = EventQueue(capacity=2)
    assert queue.put(Event("a", "1", "Done."))
    assert queue.put(Event("a", "2", "Fixed."))
    assert len(queue.items) == 1
    assert queue.put(Event("b", "3", explicit_state="needs-you"), True)
    assert queue.put(Event("c", "4", explicit_state="needs-you"), True)
    assert not queue.put(Event("d", "5", "Done."))
    assert queue.get().session_id == "b"
    assert queue.get().session_id == "c"
    queue.close()
    assert queue.get() is None


def test_queue_expires_old_notifications():
    queue = EventQueue(ttl=0.01)
    queue.put(Event("old", "1", "Done."), now=time.monotonic() - 1)
    queue.put(Event("new", "1", "Done."))
    assert queue.get().session_id == "new"
    queue.close()


def test_concurrent_sessions_serial_playback_and_safe_logs():
    active, played = 0, []
    lock = threading.Lock()

    def player(state, length):
        nonlocal active
        with lock:
            active += 1
            assert active == 1
        time.sleep(0.005)
        played.append(state)
        with lock:
            active -= 1

    with running_service(player=player) as (service, path, _, logs):
        events = [Event(f"session-{i}", "turn-1", "Implemented the fix and all tests pass. PRIVATE-MARKER") for i in range(12)]
        with ThreadPoolExecutor(max_workers=12) as pool:
            list(pool.map(lambda event: send_event(event, path), events))
        eventually(lambda: len(played) == 12)
        assert all(state == "done" for state in played)
        assert "PRIVATE-MARKER" not in json.dumps(logs)
        assert path.stat().st_mode & 0o777 == 0o600


def test_handoff_does_not_wait_for_classification_or_playback():
    entered, release = threading.Event(), threading.Event()

    class SlowClassifier:
        def classify(self, event):
            entered.set()
            assert release.wait(2)
            return RulesClassifier().classify(event)

    with running_service(classifier=SlowClassifier()) as (_, path, played, _):
        try:
            send_event(Event("s", "1", "Done."), path)
            assert entered.wait(1)
            # Both sends complete while classification is still blocked.
            send_event(Event("s2", "1", "Done."), path)
            assert not played
        finally:
            release.set()
        eventually(lambda: len(played) == 2)


def test_slow_incomplete_client_does_not_block_others():
    with running_service() as (_, path, played, _):
        with socket.socket(socket.AF_UNIX) as slow:
            slow.connect(str(path))
            slow.sendall(b'{"session_id":')
            send_event(Event("ok", "1", "Done."), path)
            eventually(lambda: len(played) == 1)
            slow.settimeout(1)
            assert slow.recv(1) == b""  # Incomplete clients still expire.


@pytest.mark.parametrize("text", ["Done.", "Done. " * 2000], ids=["small", "multiple-reads"])
def test_ready_peer_is_not_expired_during_intake_classification(monkeypatch, text):
    from types import SimpleNamespace
    import awaitonal.service as service_module

    accepted, entered, release = threading.Event(), threading.Event(), threading.Event()
    clock = [time.monotonic()]
    monkeypatch.setattr(service_module, "time", SimpleNamespace(
        monotonic=lambda: clock[0], perf_counter=time.perf_counter))
    original_accept = socket.socket.accept
    original_classify = RulesClassifier.classify

    def accept(connection):
        result = original_accept(connection)
        if not accepted.is_set():
            result[0].setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 32768)
        accepted.set()
        return result

    def classify(classifier, event):
        if event.session_id == "first" and not entered.is_set():
            entered.set()
            assert release.wait(3)
        return original_classify(classifier, event)

    monkeypatch.setattr(socket.socket, "accept", accept)
    monkeypatch.setattr(RulesClassifier, "classify", classify)
    played = []
    with running_service(player=lambda state, length: played.append((state, length))) as (_, path, _, logs):
        with socket.socket(socket.AF_UNIX) as peer:
            peer.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 32768)
            peer.connect(str(path))
            assert accepted.wait(3)
            try:
                send_event(Event("first", "1", "Done."), path)
                assert entered.wait(3)
                peer.sendall(json.dumps(Event("peer", "1", text).to_dict()).encode() + b"\n")
                # Advance the service clock beyond its 150 ms intake deadline
                # while classification is blocked, with the full peer message
                # already buffered in the socket. No real-time race is needed.
                clock[0] += 0.2
            finally:
                release.set()
            eventually(lambda: len(played) == 2)
            assert sorted(played) == sorted([("done", 5), ("done", len(text))])
            assert not any("error" in record for record in logs)


def test_live_short_turn_suppression_and_failure_remain_private_and_responsive():
    with running_service(min_turn_seconds=60) as (service, path, played, logs):
        start = adapt_claude({"hook_event_name": "UserPromptSubmit", "session_id": "short", "prompt_id": "t",
                             "prompt": "PRIVATE PROMPT"})
        send_event(start, path)
        eventually(lambda: "short" in service.timings.sessions)
        send_event(adapt_claude({"hook_event_name": "Stop", "session_id": "short", "prompt_id": "t",
                                "last_assistant_message": "Implemented the fix and all tests pass."}), path)
        eventually(lambda: any(row.get("suppressed") == "short-turn" for row in logs))
        assert not played
        send_event(adapt_claude({"hook_event_name": "StopFailure", "session_id": "other", "error": "server_error",
                                "error_details": "PRIVATE KEY", "last_assistant_message": "PRIVATE ERROR"}), path)
        eventually(lambda: played == ["failed"])
        # Without matching timing, even an immediate routine completion plays.
        send_event(Event("unknown", "stop", "Implemented the fix and all tests pass.", evidence_source="claude:Stop"), path)
        eventually(lambda: played == ["failed", "done"])
        assert "PRIVATE" not in json.dumps(logs)


def test_retry_start_supersedes_a_failure_waiting_behind_another_session():
    entered, release = threading.Event(), threading.Event()

    class PausedClassifier:
        def classify(self, event):
            if event.session_id == "busy":
                entered.set()
                assert release.wait(2)
            return RulesClassifier().classify(event)

    with running_service(classifier=PausedClassifier()) as (service, path, played, _):
        try:
            send_event(Event("busy", "1", "Done."), path)
            assert entered.wait(1)
            send_event(adapt_claude({"hook_event_name": "StopFailure", "session_id": "retry",
                                    "error": "server_error"}), path)
            eventually(lambda: any(p.event.failure_code for p in service.queue.items))
            send_event(adapt_claude({"hook_event_name": "UserPromptSubmit", "session_id": "retry",
                                    "prompt": "PRIVATE RETRY"}), path)
            eventually(lambda: not service.queue.items)
            send_event(adapt_claude({"hook_event_name": "Stop", "session_id": "retry",
                                    "last_assistant_message": "Implemented the fix and all tests pass."}), path)
            eventually(lambda: len(service.queue.items) == 1)
        finally:
            release.set()
        eventually(lambda: played == ["done", "done"])


@pytest.mark.parametrize("text", [
    "[" * MAX_INPUT,
    "which " * (MAX_INPUT // len("which ")),
    "I need your approval. " * ((MAX_INPUT - 40) // len("I need your approval. "))
    + "Your approval was granted. Done.",
], ids=["unmatched-links", "question-prefixes", "resolved-waiting-history"])
def test_near_limit_adversarial_prose_keeps_other_sessions_responsive(text):
    played = []
    assert MAX_INPUT - 100 < len(text.encode("utf-8")) <= MAX_INPUT
    with running_service(player=lambda state, length: played.append((state, length))) as (_, path, _, logs):
        started = time.monotonic()
        send_event(Event("long-input", "1", text), path, timeout=1)
        send_event(Event("another-session", "1", "Done."), path, timeout=1)
        # Exercise both the intake priority hint and the playback classifier.
        # Three seconds is generous for bounded text processing, but catches
        # the multi-second stalls caused by repeated scans of adversarial text.
        eventually(lambda: len(played) == 2, timeout=3)
        # Regex work can hold the GIL, so an eventual check alone might resume
        # only after a long stall and then incorrectly succeed.
        assert time.monotonic() - started < 3
        assert ("done", len("Done.")) in played
        assert any(length == len(text) for _, length in played)
        assert not any("error" in record for record in logs)


def test_bad_wire_and_player_failure_leave_service_available():
    attempts = []

    def broken_player(state, length):
        attempts.append(state)
        raise RuntimeError("PRIVATE-TEXT")

    with running_service(player=broken_player) as (_, path, _, logs):
        for data in (b"garbage\n", b'{"text":"Done."}\n', b"[]\n"):
            with socket.socket(socket.AF_UNIX) as connection:
                connection.connect(str(path))
                connection.sendall(data)
        send_event(Event("a", "1", "Done."), path)
        send_event(Event("b", "1", "Done."), path)
        eventually(lambda: len(attempts) == 2)
        assert "PRIVATE-TEXT" not in json.dumps(logs)
        assert any(record.get("error") == "RuntimeError" for record in logs)


def test_live_duplicate_suppression():
    with running_service() as (_, path, played, _):
        event = Event("a", "1", "Done.")
        send_event(event, path)
        send_event(event, path)
        send_event(Event("b", "1", "Done."), path)
        eventually(lambda: len(played) == 2)
        time.sleep(0.05)
        assert len(played) == 2


def test_service_plays_selected_gesture_and_logs_only_routing_metadata():
    with running_service() as (_, path, played, logs):
        send_event(Event("review-session", "1", "PRIVATE-MARKER. Please review the preview and tell me what you think."), path)
        eventually(lambda: played == ["review"])
        send_event(Event("auth-session", "1", "Please complete SSO sign-in in the browser so I can continue."), path)
        eventually(lambda: played == ["review", "needs-you"])
        send_event(Event("artifact-session", "1", "I rendered the video and saved the output file."), path)
        eventually(lambda: played == ["review", "needs-you", "artifact"])
        assert logs[0]["expectancy"] == "review-requested"
        assert logs[1]["state"] == "needs-you"
        assert logs[2]["delivery_kind"] == "artifact"
        assert "PRIVATE-MARKER" not in json.dumps(logs)


def test_required_auth_has_priority_over_soft_review_invitation():
    classifier = RulesClassifier()
    queue = EventQueue()
    review = Event("review", "1", "Please review the draft and tell me what you think.")
    auth = Event("auth", "1", "Please sign in to SSO so I can continue.")
    for event in (review, auth):
        result = classifier.classify(event)
        queue.put(event, attention=result.attention, state=result.state)
    assert queue.get() == auth
    assert queue.get() == review
    queue.close()


def test_second_server_does_not_unlink_running_socket():
    with running_service() as (_, path, played, _):
        with pytest.raises(RuntimeError, match="already serving"):
            Service(RulesClassifier(), lambda *_: None, path).run()
        assert path.exists()
        send_event(Event("a", "1", "Done."), path)
        eventually(lambda: len(played) == 1)


def test_refuse_nonprivate_directory_and_nonsocket(tmp_path):
    directory = tmp_path / "public"
    directory.mkdir(mode=0o755)
    with pytest.raises(ValueError, match="0700"):
        Service(RulesClassifier(), lambda *_: None, directory / "socket").run()
    directory.chmod(0o700)
    target = directory / "socket"
    target.write_text("do not replace")
    with pytest.raises(ValueError, match="non-socket"):
        Service(RulesClassifier(), lambda *_: None, target).run()
    assert target.read_text() == "do not replace"


@pytest.mark.parametrize("old_turn,new_turn,source", [
    ("old", "new", "text"),
    ("", "", "claude:Stop"),
    ("same", "same", "claude:Stop"),
])
def test_newer_session_state_removes_obsolete_queued_attention(old_turn, new_turn, source):
    queue = EventQueue()
    queue.put(Event("a", "question:old", explicit_state="needs-you", turn_id=old_turn), True)
    queue.put(Event("b", "question:other", explicit_state="needs-you"), True)
    queue.put(Event("a", "stop:new", "Done.", turn_id=new_turn, evidence_source=source))
    assert queue.get().session_id == "b"
    assert queue.get().event_id == "stop:new"
    assert not queue.items
    queue.close()


@pytest.mark.parametrize("turn", ["", "known-turn"])
def test_stop_waiting_does_not_repeat_structured_attention_but_new_questions_do(turn):
    queue = EventQueue()
    now = time.monotonic()
    explicit = Event("s", "question:one", explicit_state="needs-you", turn_id=turn,
                     dedup_key="tool:identical")
    assert queue.put(explicit, True, now=now)
    assert queue.get() == explicit  # Already played; dedup must still apply.
    stopped = Event("s", "stop:one", "I need your choice before continuing.",
                    evidence_source="claude:Stop", turn_id=turn)
    assert not queue.put(stopped, True, now=now + 0.1, state="needs-you")
    distinct = Event("s", "question:two", explicit_state="needs-you", turn_id=turn,
                     dedup_key="tool:identical")
    assert queue.put(distinct, True, now=now + 0.2)
    assert queue.put(Event("s", "stop:refusal", "I cannot help with that request.",
                           evidence_source="claude:Stop", turn_id=turn), True,
                     now=now + 0.3, state="rejected")
    assert queue.put(stopped, True, now=now + 2.3, state="needs-you")
    queue.close()


@pytest.mark.parametrize("turn", ["", "known-turn"])
@pytest.mark.parametrize("already_played", [False, True])
def test_ambiguous_stop_does_not_replace_or_repeat_recent_question(turn, already_played):
    queue = EventQueue()
    now = time.monotonic()
    question = Event("s", "question:one", explicit_state="needs-you", turn_id=turn)
    assert queue.put(question, True, now=now)
    if already_played:
        assert queue.get() == question
    result = Classification("unknown", controls_for("unknown"), "test", "test")
    closing = Event("s", "stop:one", "Okay.", evidence_source="claude:Stop", turn_id=turn)
    assert not queue.put(closing, now=now + 0.1, state=result.state, classification=result)
    assert [p.event for p in queue.items] == ([] if already_played else [question])
    # Missing IDs and known IDs both fail open after the short overlap window.
    assert queue.put(closing, now=now + 2.1, state=result.state, classification=result)
    if not already_played:
        assert queue.get() == question  # Unknown prose cannot resolve queued attention.
    assert queue.get() == closing
    queue.close()


@pytest.mark.parametrize("result", [
    Classification("done", controls_for("done"), "test", "test", delivery_kind="artifact"),
    Classification("caveats", controls_for("caveats"), "test", "test"),
    Classification("done", controls_for("done"), "test", "test", expectancy="review-requested"),
])
def test_a_real_final_report_after_question_remains_audible_and_resolves_queued_question(result):
    queue = EventQueue()
    now = time.monotonic()
    question = Event("s", "question:one", explicit_state="needs-you", turn_id="t")
    assert queue.put(question, True, now=now)
    report = Event("s", "stop:one", "Report.", evidence_source="claude:Stop", turn_id="t")
    assert queue.put(report, result.attention, now=now + 0.1, state=result.state, classification=result)
    assert [p.event for p in queue.items] == [report]
    queue.close()


def test_unknown_stop_for_another_turn_or_session_does_not_collide_with_question():
    queue = EventQueue()
    now = time.monotonic()
    assert queue.put(Event("s", "question:one", explicit_state="needs-you", turn_id="old"), True, now=now)
    result = Classification("unknown", controls_for("unknown"), "test", "test")
    for session, turn in (("other", "old"), ("s", "new"), ("s", "")):
        event = Event(session, f"stop:{turn}", "Okay.", evidence_source="claude:Stop", turn_id=turn)
        assert queue.put(event, now=now + 0.1, state=result.state, classification=result)
    queue.close()


def test_stop_failure_is_preserved_after_question_even_when_both_need_attention():
    queue = EventQueue()
    now = time.monotonic()
    assert queue.put(Event("s", "question:one", explicit_state="needs-you", turn_id="t"), True, now=now)
    failure = adapt_claude({"session_id": "s", "prompt_id": "t", "hook_event_name": "StopFailure",
                           "error": "authentication_failed"})
    result = RulesClassifier().classify(failure)
    assert queue.put(failure, result.attention, now=now + 0.1, state=result.state, classification=result)
    assert any(p.event == failure for p in queue.items)
    queue.close()


@pytest.mark.parametrize("contextual_player", [False, True])
def test_live_long_turn_routes_to_optional_player_and_keeps_two_argument_players(contextual_player):
    long_played = []
    options = {"long_turn_player": lambda gesture, length: long_played.append((gesture, length))} if contextual_player else {}
    with running_service(long_turn_seconds=120, **options) as (service, _, played, logs):
        now = time.monotonic()
        rules = RulesClassifier()
        start = adapt_claude({"session_id": "long", "prompt_id": "t", "hook_event_name": "UserPromptSubmit",
                              "prompt": "PRIVATE PROMPT"})
        stop = adapt_claude({"session_id": "long", "prompt_id": "t", "hook_event_name": "Stop",
                             "last_assistant_message": "Implemented the fix and all tests pass. PRIVATE RESULT"})
        service._intake(start, rules, now - 150)
        service._intake(stop, rules, now)
        eventually(lambda: bool(long_played if contextual_player else played))
        assert long_played == ([("done", len(stop.text))] if contextual_player else [])
        assert played == ([] if contextual_player else ["done"])
        assert logs[0]["long_turn"] is True and logs[0]["turn_seconds"] == 150
        assert "PRIVATE" not in json.dumps(logs)


@pytest.mark.parametrize("enabled", [False, True])
def test_live_in_flight_notification_default_and_opt_in(enabled):
    class InFlightClassifier:
        def classify(self, event):
            return Classification("unknown", controls_for("unknown"), "test", "test", activity="in-flight")

    with running_service(classifier=InFlightClassifier(), notify_in_flight=enabled) as (_, path, played, logs):
        send_event(Event("s", "1", "PRIVATE RESULT"), path)
        eventually(lambda: bool(logs))
        assert logs[0]["suppressed"] == (None if enabled else "in-flight")
        if enabled:
            eventually(lambda: played == ["in-flight"])
        else:
            assert not played
        assert "PRIVATE" not in json.dumps(logs)


@pytest.mark.parametrize("queue_size,expected_count", [(1, 1), (2, 2)])
def test_default_silent_activity_cannot_evict_an_unplayed_artifact(queue_size, expected_count):
    class Hints:
        def classify(self, event):
            if event.event_id == "artifact":
                return Classification("done", controls_for("done"), "test", "test", delivery_kind="artifact")
            return Classification("unknown", controls_for("unknown"), "test", "test", activity="in-flight")

    hints = Hints()
    service = Service(hints, lambda *_: None, queue_size=queue_size)
    now = time.monotonic()
    artifact = Event("s", "artifact", "Report.", evidence_source="claude:Stop")
    background = Event("s", "activity", "Monitoring.", evidence_source="claude:Stop")
    service._intake(artifact, hints, now)
    service._intake(background, hints, now + 0.1)
    assert len(service.queue.items) == expected_count
    assert service.queue.get() == artifact
    if expected_count == 2:
        assert service.queue.get() == background  # The worker can still log its suppression.
    service.queue.close()


def test_explicit_ongoing_work_is_not_deduped_as_ambiguous_question_closing():
    queue = EventQueue()
    now = time.monotonic()
    assert queue.put(Event("s", "question:one", explicit_state="needs-you", turn_id="t"), True, now=now)
    result = Classification("unknown", controls_for("unknown"), "test", "test", activity="in-flight")
    event = Event("s", "stop:one", "CI is running. I'll report back.", evidence_source="claude:Stop", turn_id="t")
    assert queue.put(event, now=now + 0.1, state=result.state, classification=result)
    assert queue.get() == event
    queue.close()


def test_attention_alias_cache_stays_bounded_under_burst():
    queue = EventQueue()
    now = time.monotonic()
    for index in range(700):
        event = Event("s", f"question:{index}", explicit_state="needs-you",
                      dedup_key=f"tool:{index}")
        assert queue.put(event, True, now=now)
        assert len(queue.seen) <= 512
    assert not queue.put(event, True, now=now + 0.1)
    queue.close()


def test_deeply_nested_wire_is_ignored_without_stopping_service():
    with running_service() as (_, path, played, _):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.connect(str(path))
            connection.sendall(b"[" * 10000 + b"0" + b"]" * 10000 + b"\n")
        send_event(Event("valid", "1", "Done."), path)
        eventually(lambda: played == ["done"])


def test_shutdown_never_plays_late_classification_result():
    entered, release, classified = threading.Event(), threading.Event(), threading.Event()
    played, logs = [], []

    class BlockedClassifier:
        def classify(self, event):
            entered.set()
            release.wait(10)
            result = RulesClassifier().classify(event)
            classified.set()
            return result

    with tempfile.TemporaryDirectory(prefix="at-stop-", dir="/tmp") as directory:
        path = Path(directory) / "s.sock"
        stop = threading.Event()
        service = Service(BlockedClassifier(), lambda *args: played.append(args), path, logger=logs.append)
        runner = threading.Thread(target=service.run, args=(stop,))
        runner.start()
        try:
            assert service.ready.wait(1)
            send_event(Event("s", "1", "Done."), path)
            assert entered.wait(1)
            stop.set()
            runner.join(4)
            assert not runner.is_alive()
            assert not path.exists()
            release.set()
            assert classified.wait(1)
            time.sleep(0.025)
            assert not played and not logs
        finally:
            stop.set()
            release.set()
            runner.join(4)


def test_cancellable_player_terminates_its_process(monkeypatch, tmp_path):
    from awaitonal import playback
    destination = tmp_path / "silent.wav"
    with wave.open(str(destination), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(48000)
        stream.writeframes(b"\0\0" * 480)
    monkeypatch.setattr(playback.platform, "system", lambda: "Darwin")
    real_popen = subprocess.Popen
    spawned, failures = [], []
    ready, stop = threading.Event(), threading.Event()

    def fake_player_process(args, **kwargs):
        assert args == ["/usr/bin/afplay", str(destination.resolve())]
        process = real_popen([sys.executable, "-c", "import time; time.sleep(30)"], **kwargs)
        spawned.append(process)
        ready.set()
        return process

    monkeypatch.setattr(playback.subprocess, "Popen", fake_player_process)

    def play():
        try:
            playback.play_file(destination, stop_event=stop)
        except Exception as error:
            failures.append(error)

    thread = threading.Thread(target=play)
    thread.start()
    try:
        assert ready.wait(1)
        stop.set()
        thread.join(1.5)
        assert not thread.is_alive()
        assert spawned[0].poll() is not None
        assert not failures
    finally:
        stop.set()
        for process in spawned:
            if process.poll() is None:
                process.kill()
                process.wait()
        thread.join(2)
