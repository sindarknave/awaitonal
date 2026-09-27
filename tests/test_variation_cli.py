"""The authored palette, custom overrides, and CLI reach the live player."""
import wave

import numpy as np
import pytest

from awaitonal.cli import execute, parser
from awaitonal.config import load_config
from awaitonal.synth import render, variation_count, variation_groups


def test_custom_phrase_does_not_inherit_unrelated_packaged_variations(tmp_path):
    palette = tmp_path / "custom.toml"
    palette.write_text('''
[states.done]
duration = 0.4
events = [{ time = 0.01, notes = ["C3"], duration = 0.3, attack = 0.02, decay = 0.15, release = 0.07, gain = 0.6 }]
''')
    config = load_config(palette)
    assert variation_count("done", config) == 1
    assert variation_count("answer", config) == 4
    assert variation_groups("done", config) is None
    assert variation_groups("answer", config) == {"light": (0, 1), "full": (2, 3)}
    assert len(render("done", config)) == 19200
    with pytest.raises(ValueError):
        render("done", config, variation=1)
    assert variation_count("done", load_config()) == 4


@pytest.mark.parametrize("custom", [
    '[states.answer]\nduration = 1.2\n',
    '[states.answer.long_turn]\nlift = ["C5", "E5"]\n',
])
def test_custom_phrase_timing_also_disables_inherited_variations(tmp_path, custom):
    path = tmp_path / "palette.toml"
    path.write_text(custom)
    config = load_config(path)
    assert variation_count("answer", config) == 1
    assert variation_count("done", config) == 4


def test_custom_variations_are_explicitly_editable(tmp_path):
    path = tmp_path / "palette.toml"
    path.write_text('''
[states.answer]
duration = 1.2
[[states.answer.variations]]
duration = 0.4
events = [{ time = 0.01, notes = ["G3", "D4"], duration = 0.3, attack = 0.02, decay = 0.15, release = 0.07, gain = 0.6 }]
[states.done]
variations = []
''')
    config = load_config(path)
    assert variation_count("answer", config) == 2
    assert variation_count("done", config) == 1
    assert variation_groups("answer", config) is None
    assert variation_groups("done", config) is None
    assert len(render("answer", config, variation=1)) == 19200


def test_play_renders_selected_variation_and_rejects_attention_variation(tmp_path, capsys):
    path = tmp_path / "variation.wav"
    args = parser().parse_args(["play", "answer", "--variation", "2", "--voice", "harp", "--out", str(path)])
    assert execute(args) == 0
    with wave.open(str(path)) as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2")
    expected = np.rint(render("answer", variation=2, voice="harp") * 32767).astype("<i2")
    assert np.array_equal(samples, expected)
    args = parser().parse_args(["play", "needs-you", "--variation", "1", "--out", str(path)])
    with pytest.raises(ValueError):
        execute(args)


@pytest.mark.parametrize("enabled,silent", [(True, False), (False, False), (True, True)])
def test_service_cli_wires_variations_and_preserves_voice_and_long_turn(tmp_path, monkeypatch, enabled, silent):
    import awaitonal.playback
    import awaitonal.service

    palette = tmp_path / "palette.toml"
    palette.write_text(f"[notifications]\ngesture_variations = {str(enabled).lower()}\nvariation_full_after_seconds = 90\n")
    captured, playback = {}, []

    class FakeService:
        def __init__(self, *_args, **kwargs):
            captured.update(kwargs)

        def run(self, stop):
            captured["variation_player"]("done", 500, "marimba", True, 3 if enabled else 0)

    def read_playback(path, **_kwargs):
        with wave.open(str(path)) as wav:
            playback.append(np.frombuffer(wav.readframes(wav.getnframes()), dtype="<i2"))

    monkeypatch.setattr(awaitonal.service, "Service", FakeService)
    monkeypatch.setattr(awaitonal.playback, "play_file", read_playback)
    monkeypatch.setattr("awaitonal.cli.signal.signal", lambda *_: None)
    args = parser().parse_args(["serve", "--config", str(palette), *(["--silent"] if silent else [])])
    assert execute(args) == 0
    assert captured["gesture_variations"] is (enabled and not silent)
    assert captured["variation_counts"] == ({"answer": 4, "done": 4} if enabled and not silent else None)
    assert captured["variation_groups"] == ({"answer": {"light": (0, 1), "full": (2, 3)},
                                             "done": {"light": (0, 2), "full": (1, 3)}}
                                            if enabled and not silent else None)
    assert captured["variation_full_after_seconds"] == 90
    if silent:
        assert not playback
    else:
        expected = np.rint(render("done", voice="marimba", long_turn=True, variation=3 if enabled else 0) * 32767).astype("<i2")
        assert np.array_equal(playback[0], expected)


def test_invalid_variation_flag_fails_even_in_silent_mode(tmp_path, monkeypatch):
    path = tmp_path / "palette.toml"
    path.write_text('[notifications]\ngesture_variations = "true"\n')
    monkeypatch.setattr("awaitonal.cli.signal.signal", lambda *_: None)
    args = parser().parse_args(["serve", "--silent", "--config", str(path)])
    with pytest.raises(ValueError, match="gesture_variations"):
        execute(args)


def test_custom_group_mapping_is_complete_and_never_merges_hidden_defaults(tmp_path):
    path = tmp_path / "palette.toml"
    path.write_text('[states.done]\nvariation_groups = { light = [0, 1], full = [2, 3] }\n')
    assert variation_groups("done", load_config(path)) == {"light": (0, 1), "full": (2, 3)}
    path.write_text('[states.done]\nvariation_groups = { light = [0, 2] }\n')
    with pytest.raises(ValueError):
        variation_groups("done", load_config(path))


def test_overriding_only_variations_removes_inherited_timing_groups(tmp_path):
    path = tmp_path / "palette.toml"
    path.write_text('''
[[states.answer.variations]]
duration = 0.4
events = [{ time = 0.01, notes = ["G3", "D4"], duration = 0.3, attack = 0.02, decay = 0.15, release = 0.07, gain = 0.6 }]
''')
    config = load_config(path)
    assert variation_count("answer", config) == 2
    assert variation_groups("answer", config) is None
    assert variation_groups("done", config) == {"light": (0, 2), "full": (1, 3)}
