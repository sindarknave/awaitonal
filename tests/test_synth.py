"""Audio tests measure rendered behavior without requiring an audio device."""

import subprocess
import wave
from copy import deepcopy

import numpy as np
import pytest

from awaitonal.config import load_config
from awaitonal import playback
from awaitonal.synth import LONG_TURN_GESTURES, STATE_ORDER, note_frequency, render, render_demo, write_wav


@pytest.mark.parametrize("state", STATE_ORDER)
def test_render_is_deterministic_safe_and_smooth(state, tmp_path):
    config = load_config()
    rate = config["synth"]["sample_rate"]
    audio = render(state, config)
    assert audio.ndim == 1 and np.isfinite(audio).all()
    assert len(audio) == round(config["states"][state]["duration"] * rate)
    assert 0.5 <= len(audio) / rate <= 2.0
    assert 0.01 < np.max(np.abs(audio)) < 0.5
    assert np.array_equal(audio, render(state, config))
    assert np.count_nonzero(audio[:int(0.01 * rate)]) == 0
    assert np.count_nonzero(audio[-int(0.01 * rate):]) == 0
    # A click would produce an abrupt boundary jump. Every isolated event has
    # sub-milliscale neighboring samples, including the deliberately dry taps.
    for event in config["states"][state]["events"]:
        isolated = deepcopy(config)
        isolated["states"][state]["events"] = [event]
        voice = render(state, isolated)
        start = round(event["time"] * rate)
        end = start + round(event["duration"] * rate)
        assert np.max(np.abs(voice[start - 1:start + 2])) < 0.001
        assert np.max(np.abs(voice[end - 2:end + 1])) < 0.001
    destination = tmp_path / f"{state}.wav"
    write_wav(destination, audio, rate)
    with wave.open(str(destination), "rb") as stream:
        assert stream.getnchannels() == 1
        assert stream.getsampwidth() == 2
        assert stream.getframerate() == 48000
        assert stream.getnframes() == len(audio)
        decoded = np.frombuffer(stream.readframes(stream.getnframes()), dtype="<i2")
    assert decoded[0] == decoded[-1] == 0
    assert np.max(np.abs(decoded.astype(np.int32))) < 16384
    assert np.allclose(decoded / 32767, audio, atol=0.5 / 32767 + 1e-12)


def test_richer_chords_do_not_simply_get_louder():
    levels = {state: np.sqrt(np.mean(render(state) ** 2))
              for state in STATE_ORDER if state != "in-flight"}
    assert max(levels.values()) / min(levels.values()) < 1.4
    assert 0.85 < levels["caveats"] / levels["done"] < 1.1
    assert levels["rejected"] <= levels["done"]


def test_continuing_work_pulse_is_short_and_deliberately_quiet():
    pulse = render("in-flight")
    answer = render("answer")
    assert len(pulse) / 48000 < 0.6
    assert 0.1 < np.sqrt(np.mean(pulse ** 2) / np.mean(answer ** 2)) < 0.25
    # A small pair of pulses, with neither a held chord nor an attention tail.
    assert not np.any(pulse[round(.2 * 48000):round(.28 * 48000)])
    assert not np.any(pulse[round(.46 * 48000):])


def test_new_gestures_have_distinct_audio_from_each_existing_cue():
    sounds = {state: render(state) for state in STATE_ORDER}
    for added in ("verdict", "in-flight", "authorization"):
        for other, audio in sounds.items():
            if other != added:
                size = max(len(sounds[added]), len(audio))
                left = np.pad(sounds[added], (0, size - len(sounds[added])))
                right = np.pad(audio, (0, size - len(audio)))
                assert np.sqrt(np.mean((left - right) ** 2)) > 0.01


def _dominant_frequency(samples, rate):
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)), n=131072))
    return np.fft.rfftfreq(131072, 1 / rate)[np.argmax(spectrum)]


@pytest.mark.parametrize("gesture,first,last,end", [
    ("needs-you", 1.03, 1.34, 1.76), ("review", .74, 1.04, 1.46),
    ("authorization", .56, .90, 1.32),
])
def test_expectant_tail_leaves_space_before_unresolved_rising_notes(gesture, first, last, end):
    audio = render(gesture)
    rate = 48000
    early_tail = audio[round(first * rate):round((first + .21) * rate)]
    late_tail = audio[round(last * rate):round(end * rate)]
    assert _dominant_frequency(early_tail, rate) == pytest.approx(note_frequency("A4"), abs=1)
    assert _dominant_frequency(late_tail, rate) == pytest.approx(note_frequency("B4"), abs=1)
    assert not np.any(audio[round((first + .21) * rate):round(last * rate)])
    assert not np.any(audio[round(end * rate):])


def test_rejection_contains_two_identical_short_taps_with_silent_gap():
    audio = render("rejected")
    rate = 48000
    first = audio[round(0.025 * rate):round(0.195 * rate)]
    second = audio[round(0.30 * rate):round(0.47 * rate)]
    assert np.array_equal(first, second)
    assert np.sqrt(np.mean(first ** 2)) > 0.05
    assert not np.any(audio[round(0.195 * rate):round(0.30 * rate)])
    assert not np.any(audio[round(0.47 * rate):])
    # Both fundamentals in the tritone must be present in each tap.
    times = np.arange(len(first)) / rate
    c_power = abs(np.dot(first, np.exp(-2j * np.pi * note_frequency("C4") * times)))
    fs_power = abs(np.dot(first, np.exp(-2j * np.pi * note_frequency("F#4") * times)))
    e_power = abs(np.dot(first, np.exp(-2j * np.pi * note_frequency("E4") * times)))
    assert min(c_power, fs_power) > 5 * e_power


def test_demo_preserves_each_gesture_in_order_with_silence():
    config = load_config()
    audio = render_demo(config)
    gap = round(config["synth"]["demo_gap"] * config["synth"]["sample_rate"])
    offset = 0
    for index, state in enumerate(STATE_ORDER):
        expected = render(state, config)
        assert np.array_equal(audio[offset:offset + len(expected)], expected)
        offset += len(expected)
        if index < len(STATE_ORDER) - 1:
            assert not np.any(audio[offset:offset + gap])
            offset += gap
    assert offset == len(audio)


def test_brightness_is_opt_in_bounded_and_volume_neutral():
    original = render("caveats")
    assert np.array_equal(original, render("caveats", response_length=100000))
    config = load_config()
    config["synth"]["brightness"]["enabled"] = True
    short = render("caveats", config, response_length=100)
    long = render("caveats", config, response_length=100000)
    saturated = render("caveats", config, response_length=10**12)
    assert not np.array_equal(short, long)
    for bright in (short, long, saturated):
        assert len(bright) == len(original)
        assert np.mean(bright ** 2) == pytest.approx(np.mean(original ** 2), rel=1e-12)
        assert np.max(np.abs(bright)) < config["synth"]["peak_limit"]
    assert np.sqrt(np.mean((long - saturated) ** 2)) < 0.001


@pytest.mark.parametrize("state", STATE_ORDER)
def test_elapsed_turn_treatment_extends_result_ending_at_similar_level(state):
    config = load_config()
    before = deepcopy(config)
    fixed = render(state, config)
    fuller = render(state, config, long_turn=True)
    assert config == before
    assert np.array_equal(fixed, render(state, config, long_turn=False))
    assert np.isfinite(fuller).all()
    assert np.mean(fuller ** 2) == pytest.approx(np.mean(fixed ** 2), rel=1e-12)
    assert np.max(np.abs(fuller)) < config["synth"]["peak_limit"]
    assert fuller[0] == fuller[-1] == 0
    if state in LONG_TURN_GESTURES:
        assert len(fuller) - len(fixed) == round(.8 * config["synth"]["sample_rate"])
        # The added time contains music, not silence appended to the old cue.
        assert np.sqrt(np.mean(fuller[len(fixed):] ** 2)) > .01
        final_start = max(event["time"] for event in config["states"][state]["events"])
        opening = round(final_start * config["synth"]["sample_rate"])
        # Global level matching may scale the opening, but its notes/rhythm stay.
        assert np.allclose(fixed[:opening] / np.max(np.abs(fixed[:opening])),
                           fuller[:opening] / np.max(np.abs(fuller[:opening])), atol=1e-12)
    else:
        assert np.array_equal(fixed, fuller)


@pytest.mark.parametrize("state", sorted(LONG_TURN_GESTURES))
def test_elapsed_turn_and_character_brightness_remain_independent_and_bounded(state):
    config = load_config()
    config["synth"]["brightness"]["enabled"] = True
    fixed = render(state, config)
    bright = render(state, config, response_length=100000)
    both = render(state, config, response_length=100000, long_turn=True)
    assert not np.array_equal(both, bright)
    assert not np.array_equal(both, render(state, config, long_turn=True))
    assert len(both) - len(fixed) == round(.8 * config["synth"]["sample_rate"])
    assert np.mean(both ** 2) == pytest.approx(np.mean(fixed ** 2), rel=1e-12)
    assert np.max(np.abs(both)) < config["synth"]["peak_limit"]


def test_long_turn_voicing_is_editable_without_changing_the_short_cue():
    config = load_config()
    normal = render("done", config)
    extended = render("done", config, long_turn=True)
    config["states"]["done"]["long_turn"]["lift"] = ["D4", "E4"]
    assert np.array_equal(normal, render("done", config))
    assert not np.array_equal(extended, render("done", config, long_turn=True))
    config["states"]["done"]["long_turn"]["lift"] = []
    with pytest.raises(ValueError, match="two notes"):
        render("done", config, long_turn=True)


def test_partials_above_nyquist_are_omitted():
    config = load_config()
    config["synth"]["sample_rate"] = 8000
    config["states"]["done"]["events"] = config["states"]["done"]["events"][:1]
    config["states"]["done"]["events"][0]["notes"] = ["A7"]
    config["synth"]["harmonics"] = [1, 2, 3]
    config["synth"]["harmonic_weights"] = [1, 1, 1]
    filtered = render("done", config)
    config["synth"]["harmonic_weights"] = [1, 0, 0]
    fundamental = render("done", config)
    assert np.array_equal(filtered, fundamental)
    config["states"]["done"]["events"][0]["notes"] = ["A8"]
    with pytest.raises(ValueError, match="Nyquist"):
        render("done", config)


def test_custom_gain_still_has_headroom():
    config = load_config()
    config["synth"]["master_gain"] = 1.0
    config["states"]["caveats"]["events"][0]["gain"] = 4.0
    assert np.max(np.abs(render("caveats", config))) == pytest.approx(0.8)


def test_config_overrides_merge_without_mutating_defaults(tmp_path):
    override = tmp_path / "quiet.toml"
    override.write_text("[synth]\nmaster_gain = 0.12\n[classification]\ncaveats_threshold = 0.7\n")
    config = load_config(override)
    assert config["classification"]["caveats_threshold"] == 0.7
    assert config["synth"]["sample_rate"] == 48000
    assert np.allclose(render("done", config), 0.5 * render("done"))
    config["states"]["done"]["events"][0]["notes"] = ["A4"]
    assert load_config()["states"]["done"]["events"][0]["notes"] == ["G4"]


@pytest.mark.parametrize("samples", [[], [float("nan")], [float("inf")], [1.1], [[0.0]]])
def test_wav_writer_rejects_invalid_audio(samples, tmp_path):
    with pytest.raises(ValueError):
        write_wav(tmp_path / "invalid.wav", np.asarray(samples), 48000)


def test_playback_uses_argument_array_and_timeout(monkeypatch, tmp_path):
    destination = tmp_path / "sound ; $(no-command).wav"
    write_wav(destination, render("done"), 48000)
    monkeypatch.setattr(playback.platform, "system", lambda: "Darwin")
    calls = []
    monkeypatch.setattr(playback.subprocess, "run", lambda args, **kwargs: calls.append((args, kwargs)))
    playback.play_file(destination)
    args, kwargs = calls[0]
    assert args == ["/usr/bin/afplay", str(destination.resolve())]
    assert "shell" not in kwargs
    assert kwargs["check"] is True and 5 <= kwargs["timeout"] < 10


def test_playback_reports_missing_platform_and_player_failure(monkeypatch, tmp_path):
    destination = tmp_path / "done.wav"
    write_wav(destination, render("done"), 48000)
    monkeypatch.setattr(playback.platform, "system", lambda: "Linux")
    with pytest.raises(RuntimeError, match="macOS"):
        playback.play_file(destination)
    monkeypatch.setattr(playback.platform, "system", lambda: "Darwin")

    def fail(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(playback.subprocess, "run", fail)
    with pytest.raises(RuntimeError, match="timed out"):
        playback.play_file(destination)
