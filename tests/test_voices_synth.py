"""Session instruments retain gesture identity, level, and safe playback."""

from copy import deepcopy

import numpy as np
import pytest

from awaitonal.config import load_config
from awaitonal.synth import (
    GESTURE_ORDER, LONG_TURN_GESTURES, VOICES, note_frequency, render, render_demo,
)
from awaitonal.voices import SESSION_VOICES

LEGACY_VOICES = ("wood", "glass", "round")


@pytest.mark.parametrize("gesture", GESTURE_ORDER)
@pytest.mark.parametrize("voice", LEGACY_VOICES)
def test_voices_preserve_duration_level_and_headroom_with_brightness_and_long_turn(gesture, voice):
    config = load_config()
    config["synth"]["brightness"]["enabled"] = True
    before = deepcopy(config)
    reference = render(gesture, config)
    voiced = render(gesture, config, voice=voice)
    assert np.array_equal(voiced, render(gesture, config, voice=voice))
    assert len(voiced) == len(reference)
    assert not np.array_equal(voiced, reference)
    combined = render(gesture, config, response_length=100000, long_turn=True, voice=voice)
    expected_extension = .8 if gesture in LONG_TURN_GESTURES else 0
    assert len(combined) == len(reference) + round(expected_extension * config["synth"]["sample_rate"])
    for audio in (voiced, combined):
        assert audio.ndim == 1 and np.isfinite(audio).all()
        assert np.mean(audio ** 2) == pytest.approx(np.mean(reference ** 2), rel=1e-12)
        assert 0 < np.max(np.abs(audio)) < config["synth"]["peak_limit"]
        assert audio[0] == audio[-1] == 0
    if expected_extension:
        assert np.sqrt(np.mean(combined[len(reference):] ** 2)) > .008
    assert config == before


@pytest.mark.parametrize("gesture", GESTURE_ORDER)
@pytest.mark.parametrize("voice", SESSION_VOICES)
def test_compact_voices_shorten_tails_and_preserve_safe_level_and_long_turn_lift(gesture, voice):
    config = load_config()
    config["synth"]["brightness"]["enabled"] = True
    before = deepcopy(config)
    reference = render(gesture, config)
    normal = render(gesture, config, voice=voice)
    long = render(gesture, config, voice=voice, long_turn=True, response_length=100000)
    assert np.array_equal(normal, render(gesture, config, voice=voice))
    assert len(normal) < len(reference)
    if gesture in LONG_TURN_GESTURES:
        # Extra rising attacks remain, with a short final stab instead of a
        # sustained tail. The additional arrangement is still audible.
        assert len(long) - len(normal) == round(.36 * 48000)
        assert np.sqrt(np.mean(long[len(normal):] ** 2)) > .008
    else:
        assert len(long) == len(normal)
    for audio in (normal, long):
        assert np.isfinite(audio).all() and audio.ndim == 1
        assert audio[0] == audio[-1] == 0
        assert 0 < np.max(np.abs(audio)) <= config["synth"]["peak_limit"]
        assert np.mean(audio ** 2) == pytest.approx(np.mean(reference ** 2), rel=1e-12)
        assert not np.any(audio[-1200:])
    assert config == before


@pytest.mark.parametrize("voice", SESSION_VOICES)
def test_compact_single_note_keeps_pitch_with_a_short_decaying_body(voice):
    audio = _single_note(load_config(), voice)
    rate = 48000
    # The body now breathes beyond the previous 220 ms stab, then ends cleanly.
    assert not np.any(audio[round(.36 * rate):])
    early = np.sqrt(np.mean(audio[round(.01 * rate):round(.06 * rate)] ** 2))
    late = np.sqrt(np.mean(audio[round(.14 * rate):round(.19 * rate)] ** 2))
    body = np.sqrt(np.mean(audio[round(.22 * rate):round(.26 * rate)] ** 2))
    assert late < early * .6
    assert body > early * .06
    spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio)), n=131072))
    bins = np.fft.rfftfreq(131072, 1 / rate)
    assert bins[np.argmax(spectrum)] == pytest.approx(440, abs=2)


def test_compact_profiles_are_distinct_without_unrelated_pitches():
    config = load_config()
    spectra = []
    for voice in SESSION_VOICES:
        profile = config["voices"][voice]
        assert all(harmonic == int(harmonic) for harmonic in profile["harmonics"])
        audio = _single_note(config, voice)
        spectra.append(np.abs(np.fft.rfft(audio * np.hanning(len(audio)), n=32768)))
    # This protects against accidentally shipping six copies of one instrument;
    # perceptual recognizability still requires the listening comparison.
    for index, first in enumerate(spectra):
        for second in spectra[index + 1:]:
            assert np.linalg.norm(first / np.linalg.norm(first) - second / np.linalg.norm(second)) > .05


@pytest.mark.parametrize("key,value", [
    ("max_decay", 0), ("max_decay", float("nan")), ("max_note_duration", .01),
    ("max_note_duration", 100), ("detune_cents", []), ("detune_cents", "0"),
    ("detune_cents", [-13, 0, 13]), ("detune_cents", [1, 2]),
    ("detune_cents", [0, float("inf")]), ("detune_cents", [0] * 8),
])
def test_compact_profile_rejects_invalid_envelopes_and_detuning(key, value):
    config = load_config()
    config["voices"]["powersaw"][key] = value
    with pytest.raises(ValueError, match="voices.powersaw"):
        render("done", config, voice="powersaw")


@pytest.mark.parametrize("gesture", GESTURE_ORDER)
def test_default_voice_ignores_new_profiles_even_for_long_or_bright_gestures(gesture):
    config = load_config()
    original = deepcopy(config)
    # Old palettes and callers do not depend on the added voice tables.
    del original["voices"]
    config["voices"] = "not used by the default instrument"
    for bright in (False, True):
        config["synth"]["brightness"]["enabled"] = bright
        original["synth"]["brightness"]["enabled"] = bright
        for extended in (False, True):
            implicit = render(gesture, original, response_length=100000, long_turn=extended)
            explicit = render(gesture, config, response_length=100000,
                              long_turn=extended, voice="default")
            assert np.array_equal(implicit, explicit)


def _single_note(config, voice):
    config = deepcopy(config)
    event = config["states"]["done"]["events"][0]
    event.update(time=.02, notes=["A4"], duration=.6, decay=.17)
    config["states"]["done"]["events"] = [event]
    rate = config["synth"]["sample_rate"]
    return render("done", config, voice=voice)[round(.02 * rate):round(.62 * rate)]


def test_voices_have_distinct_spectral_and_decay_character_without_transposing():
    rate = 48000
    sounds = {voice: _single_note(load_config(), voice) for voice in VOICES[1:]}
    tails = {}
    for voice, audio in sounds.items():
        spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio)))) ** 2
        frequencies = np.fft.rfftfreq(len(audio), 1 / rate)
        # The strongest tone still names the same note in every instrument.
        assert frequencies[np.argmax(spectrum)] == pytest.approx(440, abs=2)
        tails[voice] = np.linalg.norm(audio[4800:]) / np.linalg.norm(audio[:4800])
    assert tails["wood"] < .6 < tails["round"] < .9 < tails["glass"]

    def band_energy(audio, ratio):
        spectrum = np.abs(np.fft.rfft(audio * np.hanning(len(audio)))) ** 2
        frequencies = np.fft.rfftfreq(len(audio), 1 / rate)
        return float(spectrum[np.abs(frequencies - 440 * ratio) < 10].sum() / spectrum.sum())

    # These identify the intended struck wood, inharmonic bell, and harmonic
    # piano colors; the profiles cannot pass by changing only volume or pitch.
    assert band_energy(sounds["wood"], 3.99) > 20 * band_energy(sounds["glass"], 3.99)
    assert band_energy(sounds["glass"], 2.76) > 20 * band_energy(sounds["round"], 2.76)
    assert band_energy(sounds["round"], 2) > 20 * band_energy(sounds["wood"], 2)
    for first, second in (("wood", "glass"), ("wood", "round"), ("glass", "round")):
        assert np.corrcoef(sounds[first], sounds[second])[0, 1] < .98


@pytest.mark.parametrize("voice", VOICES[1:])
@pytest.mark.parametrize("gesture,first,last,end", [
    ("needs-you", 1.03, 1.34, 1.76), ("review", .74, 1.04, 1.46),
    ("authorization", .56, .90, 1.32),
])
def test_session_instrument_preserves_expectant_tail_pitch_and_silent_gap(voice, gesture, first, last, end):
    audio = render(gesture, voice=voice)
    rate = 48000
    for start, length, note in ((first, .21, "A4"), (last, .42, "B4")):
        tone = audio[round(start * rate):round((start + length) * rate)]
        spectrum = np.abs(np.fft.rfft(tone * np.hanning(len(tone)), n=131072))
        frequencies = np.fft.rfftfreq(131072, 1 / rate)
        assert frequencies[np.argmax(spectrum)] == pytest.approx(note_frequency(note), abs=1)
        assert np.max(np.abs(tone[:2])) < .001
        assert np.max(np.abs(tone[-2:])) < .001
    assert not np.any(audio[round((first + .21) * rate):round(last * rate)])
    assert not np.any(audio[round(end * rate):])


def test_voice_overrides_are_editable_and_do_not_affect_other_instruments(tmp_path):
    override = tmp_path / "voices.toml"
    override.write_text("[voices.wood]\ndecay_scale = 1.4\nharmonic_weights = [1.0, 0.1, 0.05]\n")
    config = load_config(override)
    assert not np.array_equal(render("review", config, voice="wood"), render("review", voice="wood"))
    for voice in ("default", "glass", "round"):
        assert np.array_equal(render("review", config, voice=voice), render("review", voice=voice))


@pytest.mark.parametrize("key,value", [
    ("harmonics", []), ("harmonics", [1] * 33), ("harmonics", [float("nan"), 2, 3]),
    ("harmonics", [1, 2, 33]), ("harmonics", [1, .5, 3]), ("harmonics", "1,2,3"),
    ("harmonic_weights", [0, 0, 0]), ("harmonic_weights", [1, 2]),
    ("harmonic_weights", [1, -1, 1]), ("harmonic_weights", [1, float("inf"), 1]),
    ("harmonic_weights", [1, 5, 1]), ("partial_decay", float("nan")),
    ("partial_decay", -1), ("attack_scale", 0), ("decay_scale", 5),
    ("release_scale", float("inf")), ("release_scale", None),
])
def test_voice_profile_rejects_invalid_values(key, value):
    config = load_config()
    config["voices"]["wood"][key] = value
    with pytest.raises(ValueError, match=r"voices\.wood"):
        render("done", config, voice="wood")


@pytest.mark.parametrize("profiles", [None, [], {"wood": "invalid"}, {}])
def test_named_voice_needs_a_profile_table(profiles):
    config = load_config()
    config["voices"] = profiles
    with pytest.raises(ValueError, match=r"voices\.wood must be a table"):
        render("done", config, voice="wood")


@pytest.mark.parametrize("renderer,args", [(render, ("done",)), (render_demo, ())])
def test_unknown_voice_rejected(renderer, args):
    with pytest.raises(ValueError, match="Unknown voice"):
        renderer(*args, voice="oboe")


@pytest.mark.parametrize("voice", VOICES[1:])
def test_demo_uses_selected_instrument_and_preserves_gaps(voice):
    config = load_config()
    demo = render_demo(config, voice=voice)
    gap = round(config["synth"]["demo_gap"] * config["synth"]["sample_rate"])
    offset = 0
    for index, gesture in enumerate(GESTURE_ORDER):
        expected = render(gesture, config, voice=voice)
        assert np.array_equal(demo[offset:offset + len(expected)], expected)
        offset += len(expected)
        if index < len(GESTURE_ORDER) - 1:
            assert not np.any(demo[offset:offset + gap])
            offset += gap
    assert offset == len(demo)


@pytest.mark.parametrize("voice", VOICES[1:])
def test_named_voices_omit_partials_above_nyquist(voice):
    config = load_config()
    config["synth"]["sample_rate"] = 8000
    event = config["states"]["done"]["events"][0]
    event["notes"] = ["A7"]
    config["states"]["done"]["events"] = [event]
    full = render("done", config, voice=voice)
    config["voices"][voice]["harmonics"] = [1.0]
    config["voices"][voice]["harmonic_weights"] = [1.0]
    assert np.array_equal(full, render("done", config, voice=voice))


def test_named_voice_emergency_peak_limit_handles_loud_custom_events():
    config = load_config()
    config["synth"]["master_gain"] = 1
    config["states"]["done"]["events"][0]["gain"] = 4
    for voice in VOICES[1:]:
        assert np.max(np.abs(render("done", config, voice=voice))) == pytest.approx(.8)
