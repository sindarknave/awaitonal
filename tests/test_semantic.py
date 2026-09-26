"""Infrastructure tests use a fake encoder; actual model smoke is opt-in offline."""
import json
import os
from pathlib import Path
import socket
import sys
import types

import numpy as np
import pytest

from awaitonal.evaluation import evaluate
from awaitonal.semantic import SemanticClassifier
from awaitonal.text import select_chunks
from awaitonal.types import Event


class Tokenizer:
    def __init__(self):
        self.words = []
    def encode(self, text, **kwargs):
        words = text.split()
        result = []
        for word in words:
            if word not in self.words:
                self.words.append(word)
            result.append(self.words.index(word))
        return result
    def decode(self, ids, **kwargs):
        return " ".join(self.words[i] for i in ids)
    def num_special_tokens_to_add(self, **kwargs):
        return 2


def test_long_selection_retains_conclusion_and_waiting_context():
    tokenizer = Tokenizer()
    text = "General details. " * 800 + "I am waiting for your decision. This is still necessary. " + "More details. " * 800 + "The final conclusion is that your answer is required."
    chunks, diagnostics = select_chunks(text, tokenizer, 64, 8)
    selected = " ".join(chunk.text for chunk in chunks)
    assert "waiting for your decision" in selected
    assert "This is still necessary" in selected
    assert "your answer is required" in selected
    assert len(chunks) <= 8 and diagnostics["omitted_tokens"] > 0
    assert all(len(tokenizer.encode(chunk.text)) <= 64 for chunk in chunks)
    assert any(chunk.conclusion for chunk in chunks)


def test_recovery_context_is_retained():
    tokenizer = Tokenizer()
    text = "Background information. " * 200 + "The build failed. I fixed the issue and the final build passes. " + "Other details. " * 200
    chunks, _ = select_chunks(text, tokenizer, 64, 8)
    assert any("build failed" in chunk.text and "build passes" in chunk.text for chunk in chunks)


def test_missing_weights_never_import_or_download(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(RuntimeError, match="No local sentence model"):
        SemanticClassifier(tmp_path / "missing")


def test_model_loaded_once_offline_and_structured_override(tmp_path, monkeypatch):
    calls = []
    encodings = []
    class FakeModel:
        tokenizer = Tokenizer()
        max_seq_length = 256
        def __init__(self, *args, **kwargs):
            calls.append(kwargs)
        def eval(self):
            return self
        def encode(self, texts, **kwargs):
            encodings.append(texts)
            return np.tile([1.0, 0.0], (len(texts), 1))
    (tmp_path / "modules.json").write_text("[]")
    monkeypatch.setitem(sys.modules, "sentence_transformers", types.SimpleNamespace(SentenceTransformer=FakeModel))
    classifier = SemanticClassifier(tmp_path)
    assert calls == [{"device": "cpu", "local_files_only": True, "trust_remote_code": False}]
    assert classifier.classify(Event("s", "1", "I refuse.", "needs-you")).state == "needs-you"
    from awaitonal.adapter import adapt_claude
    for code, expected in (("server_error", "failed"), ("authentication_failed", "needs-you")):
        failure = adapt_claude({"session_id": "s", "hook_event_name": "StopFailure", "error": code,
                               "last_assistant_message": "PRIVATE ERROR"})
        outcome = classifier.classify(failure)
        assert outcome.gesture == expected and outcome.failure_code == code
    assert classifier.classify(Event("s", "start", kind="turn-start")) is None
    assert len(encodings) == 1  # Structured failures/start markers never reach the encoder.
    # Known delivery/handoff routes share the rules palette and skip encoding.
    for text, gesture in (
        ("Please review the draft and tell me what you think.", "review"),
        ("Please sign in through SSO so I can continue.", "needs-you"),
        ("Which option should I implement? I need your choice before continuing.", "decision"),
        ("I rendered the video and saved the output file.", "artifact"),
        ("I pushed the commits to the requested branch.", "published"),
        ("Review verdict: request changes. The patch loses writes.", "verdict"),
        ("The draft is ready. I need your approval to publish.", "authorization"),
        ("CI is running. I will report back when it finishes.", "in-flight"),
        ("I could not verify the fix.", "caveats"),
        ("The error handling is fixed and all tests passed.", "done"),
    ):
        outcome = classifier.classify(Event("s", gesture, text))
        assert outcome.gesture == gesture
        assert outcome.diagnostics["backend"] == "rules-routing"
        if gesture == "verdict":
            assert outcome.assessment_kind == "verdict"
        if gesture == "in-flight":
            assert outcome.activity == "in-flight" and outcome.state == "unknown"
        if gesture == "authorization":
            assert outcome.handoff_kind == "authorization" and outcome.attention
    assert len(encodings) == 1  # Anchors only; prose went through shared routing.
    contradictory = classifier.classify(Event("s", "empty-registry", "CI is running. I will report back.",
                                               background_tasks=0, session_crons=0))
    assert contradictory.state == "unknown" and contradictory.activity == "unknown"
    assert contradictory.diagnostics["backend"] == "rules-routing"
    assert len(encodings) == 1  # The encoder must not override structured contradiction.
    # Equal similarities must abstain to the non-attention fallback.
    for number in range(3):
        outcome = classifier.classify(Event("s", str(number), "The work is described."))
        assert outcome.state == "unknown"
        assert outcome.gesture == "answer"
        assert outcome.diagnostics["accepted"] is False
        assert "The work" not in json.dumps(outcome.to_dict())
    outcome = classifier.classify(Event("s", "url", "See https://example.com/?status=done&token=PRIVATE-URL-TARGET"))
    assert outcome.state == "unknown"
    assert "PRIVATE-URL-TARGET" not in json.dumps(encodings[-1])
    assert len(calls) == 1


def test_evaluation_reports_ids_without_text(tmp_path):
    from awaitonal.classify import RulesClassifier
    path = tmp_path / "fixture.jsonl"
    path.write_text(json.dumps({"id": "secret-1", "text": "Private words. I need your approval.", "expected": "done"}) + "\n")
    report = evaluate(RulesClassifier(), path)
    assert report["false_attention"] == ["secret-1"]
    assert report["confusion_matrix"]["done"]["needs-you"] == 1
    assert "Private words" not in json.dumps(report)


@pytest.mark.semantic
def test_real_model_offline(monkeypatch):
    path = os.getenv("AWAITONAL_TEST_MODEL")
    if not path:
        pytest.skip("Set AWAITONAL_TEST_MODEL to explicitly downloaded local weights")
    def no_network(*args, **kwargs):
        raise AssertionError("Offline model attempted a network connection")
    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    classifier = SemanticClassifier(Path(path))
    result = classifier.classify(Event("offline", "1", "The work is described."))
    assert result is not None and result.diagnostics["backend"] == "sentence-transformers"
    assert all(np.isfinite(value) for value in result.diagnostics["scores"].values())
    def no_encoding(*args, **kwargs):
        raise AssertionError("Structured hook data reached the encoder")
    monkeypatch.setattr(classifier.model, "encode", no_encoding)
    from awaitonal.adapter import adapt_claude
    for code, expected in (("server_error", "failed"), ("billing_error", "needs-you")):
        failure = adapt_claude({"session_id": "offline", "hook_event_name": "StopFailure", "error": code,
                               "last_assistant_message": "PRIVATE RENDERED ERROR"})
        assert classifier.classify(failure).gesture == expected
    assert classifier.classify(Event("offline", "start", kind="turn-start")) is None


def test_reencode_expansion_preserves_final_tokens():
    class ExpandingTokenizer(Tokenizer):
        def decode(self, ids, **kwargs):
            return "prefix " + super().decode(ids, **kwargs)
    tokenizer = ExpandingTokenizer()
    prose = " ".join(f"word{i}" for i in range(40))
    chunks, _ = select_chunks(prose, tokenizer, 16, 2)
    final = chunks[-1]
    assert final.conclusion and final.end == 40
    assert final.text.endswith("word39")
    assert all(len(tokenizer.encode(chunk.text)) <= 16 for chunk in chunks)
