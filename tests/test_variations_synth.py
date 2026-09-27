"""Authored phrases retain meaning, levels and safety across session voices."""

from copy import deepcopy
from itertools import combinations

import numpy as np
import pytest

from awaitonal.config import load_config
from awaitonal.synth import GESTURE_ORDER, VOICES, note_frequency, render, variation_count, variation_groups


_SESSION_VOICES = ("default", "marimba", "powersaw", "harp", "clarinet", "crystal", "flute")


def _rms(audio):
    return float(np.sqrt(np.mean(audio * audio)))


@pytest.mark.parametrize("state", ["done", "answer"])
@pytest.mark.parametrize("voice", VOICES)
@pytest.mark.parametrize("long_turn", [False, True])
def test_original_choice_is_sample_identical_with_or_without_authored_alternatives(state, voice, long_turn):
    config = load_config()
    original_only = deepcopy(config)
    del original_only["states"][state]["variations"]
    expected = render(state, original_only, voice=voice, long_turn=long_turn)
    assert np.array_equal(expected, render(state, config, voice=voice, long_turn=long_turn))
    assert np.array_equal(expected, render(state, config, voice=voice, long_turn=long_turn, variation=0))


@pytest.mark.parametrize("state", ["done", "answer"])
@pytest.mark.parametrize("voice", _SESSION_VOICES)
@pytest.mark.parametrize("long_turn", [False, True])
def test_all_four_choices_are_distinct_level_matched_and_safe_in_each_session_instrument(state, voice, long_turn):
    config = load_config()
    before = deepcopy(config)
    assert variation_count(state, config) == 4
    audio = [render(state, config, voice=voice, long_turn=long_turn, variation=i) for i in range(4)]
    rate = config["synth"]["sample_rate"]
    for index, samples in enumerate(audio):
        assert samples.ndim == 1 and np.isfinite(samples).all()
        assert .5 <= len(samples) / rate <= 2.1
        assert _rms(samples) == pytest.approx(_rms(audio[0]), rel=1e-12)
        assert np.max(np.abs(samples)) < config["synth"]["peak_limit"]
        assert not np.any(samples[:round(.01 * rate)])
        assert not np.any(samples[-round(.01 * rate):])
        assert np.array_equal(samples, render(state, config, voice=voice,
                                               long_turn=long_turn, variation=index))
    for left, right in combinations(audio, 2):
        length = max(len(left), len(right))
        difference = np.pad(left, (0, length - len(left))) - np.pad(right, (0, length - len(right)))
        assert _rms(difference) > .02
    assert config == before


def _dominant_frequency(samples, rate):
    bins = 131072
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples)), n=bins))
    return np.fft.rfftfreq(bins, 1 / rate)[np.argmax(spectrum)]


@pytest.mark.parametrize("variation", range(4))
def test_done_variations_keep_the_g_to_e_descent(variation):
    config = load_config()
    patch = config["states"]["done"] if variation == 0 else config["states"]["done"]["variations"][variation - 1]
    rate = config["synth"]["sample_rate"]
    samples = render("done", config, variation=variation)
    octave = 5 if variation == 2 else 4
    for index, pitch in enumerate((f"G{octave}", f"E{octave}")):
        start = patch["events"][index]["time"] + .025
        end = patch["events"][index + 1]["time"] - .015
        actual = _dominant_frequency(samples[round(start * rate):round(end * rate)], rate)
        assert actual == pytest.approx(note_frequency(pitch), abs=2)


@pytest.mark.parametrize("variation", range(4))
def test_answer_variations_keep_the_c_to_e_opening(variation):
    config = load_config()
    base = config["states"]["answer"]
    patch = base if variation == 0 else base["variations"][variation - 1]
    rate = config["synth"]["sample_rate"]
    audio = render("answer", config, variation=variation)
    octave = 5 if variation == 3 else 4
    for index, pitch in enumerate((f"C{octave}", f"E{octave}")):
        start = patch["events"][index]["time"] + .025
        end = patch["events"][index + 1]["time"] - .015
        segment = audio[round(start * rate):round(end * rate)]
        times = np.arange(len(segment)) / rate
        intended = abs(np.dot(segment, np.exp(-2j * np.pi * note_frequency(pitch) * times)))
        outside_key = abs(np.dot(segment, np.exp(-2j * np.pi * note_frequency("F#4") * times)))
        assert intended > 4 * outside_key


@pytest.mark.parametrize("state", ["done", "answer"])
@pytest.mark.parametrize("variation", range(4))
@pytest.mark.parametrize("long_turn", [False, True])
def test_endings_retain_resolved_major_or_open_color_without_an_attention_tail(state, variation, long_turn):
    config = load_config()
    base = config["states"][state]
    patch = base if variation == 0 else base["variations"][variation - 1]
    final = max(patch["events"], key=lambda event: event["time"])
    notes = patch["long_turn"]["chord"] if long_turn else final["notes"]
    start = final["time"] + (.36 if long_turn else 0) + .12
    rate = config["synth"]["sample_rate"]
    audio = render(state, config, variation=variation, long_turn=long_turn)
    ending = audio[round(start * rate):round((start + .25) * rate)]
    times = np.arange(len(ending)) / rate

    def energy_at(note):
        return abs(np.dot(ending, np.exp(-2j * np.pi * note_frequency(note) * times)))

    # Require the audible ending, not merely its configured note names.
    for letter in ("C", "E", "G") if state == "done" else ("D", "G"):
        intended = [note for note in notes if note.startswith(letter)]
        assert intended
        assert max(energy_at(note) for note in intended) > 3 * energy_at("F#4" if state == "done" else "B4")
    assert all(note[0] in {"C", "D", "E", "G"} for note in notes)


@pytest.mark.parametrize("variation", [None, True, False, 1.0, "1", -1, 4, 1000000])
def test_variation_selector_requires_a_bounded_integer(variation):
    with pytest.raises(ValueError, match="integer from 0 to 3"):
        render("done", variation=variation)


@pytest.mark.parametrize("state", [state for state in GESTURE_ORDER if state not in {"done", "answer"}])
def test_other_gestures_have_only_the_original_and_reject_nonzero_choices(state):
    assert variation_count(state) == 1
    with pytest.raises(ValueError, match="only for done and answer"):
        render(state, variation=1)


def test_custom_palettes_can_have_one_two_or_four_choices_and_edit_each_phrase():
    config = load_config()
    patch = config["states"]["answer"]
    original = render("answer", config)
    alternatives = patch.pop("variations")
    assert variation_count("answer", config) == 1
    with pytest.raises(ValueError, match="not configured"):
        render("answer", config, variation=1)
    patch["variations"] = []
    assert variation_count("answer", config) == 1
    patch["variations"] = [alternatives[0]]
    assert variation_count("answer", config) == 2
    before = render("answer", config, variation=1)
    patch["variations"][0]["events"][0]["notes"] = ["G3"]
    assert not np.array_equal(before, render("answer", config, variation=1))
    assert np.array_equal(original, render("answer", config))
    patch["variations"] = alternatives
    assert variation_count("answer", config) == 4


def test_missing_variation_long_turn_inherits_without_mutating_the_base():
    config = load_config()
    patch = config["states"]["done"]["variations"][0]
    patch.pop("long_turn")
    before = deepcopy(config)
    inherited = render("done", config, variation=1, long_turn=True)
    assert config == before
    patch["long_turn"] = deepcopy(config["states"]["done"]["long_turn"])
    assert np.array_equal(inherited, render("done", config, variation=1, long_turn=True))
    patch["long_turn"]["lift"] = ["E4", "G4"]
    assert not np.array_equal(inherited, render("done", config, variation=1, long_turn=True))


@pytest.mark.parametrize("change", [
    lambda state: state.update(variations=None),
    lambda state: state.update(variations={}),
    lambda state: state["variations"].append(deepcopy(state["variations"][0])),
    lambda state: state["variations"].__setitem__(0, {}),
    lambda state: state["variations"][0].update(events=[]),
    lambda state: state["variations"][0].update(events=[{}]),
    lambda state: state["variations"][0].update(long_turn=[]),
])
def test_malformed_variation_tables_fail_explicitly(change):
    config = load_config()
    change(config["states"]["done"])
    with pytest.raises(ValueError):
        variation_count("done", config)
    with pytest.raises(ValueError):
        render("done", config, variation=1)


@pytest.mark.parametrize("change", [
    lambda patch: patch.update(duration=10.1),
    lambda patch: patch.update(duration=float("nan")),
    lambda patch: patch.update(duration=.01),
    lambda patch: patch["events"][0].update(time=20),
    lambda patch: patch["events"][0].update(gain=-1),
    lambda patch: patch["events"][0].update(notes=["A20"]),
    lambda patch: patch["events"][0].update(notes=["C4"] * 17),
])
@pytest.mark.parametrize("long_turn", [False, True])
def test_variations_obey_existing_numeric_pitch_and_sample_limits(change, long_turn):
    config = load_config()
    change(config["states"]["done"]["variations"][0])
    with pytest.raises(ValueError):
        render("done", config, variation=1, long_turn=long_turn)


@pytest.mark.parametrize("state", ["done", "answer"])
def test_variation_brightness_and_long_turn_matching_use_the_original_rms(state):
    config = load_config()
    config["synth"]["brightness"]["enabled"] = True
    original = render(state, config)
    for variation in range(1, 4):
        audio = render(state, config, response_length=100000, long_turn=True,
                       voice="powersaw", variation=variation)
        assert _rms(audio) == pytest.approx(_rms(original), rel=1e-12)
        assert np.max(np.abs(audio)) <= config["synth"]["peak_limit"]


def test_zero_gain_and_emergency_peak_limit_apply_to_variations():
    config = load_config()
    for event in config["states"]["done"]["events"]:
        event["gain"] = 0
    assert not np.any(render("done", config, variation=1))
    config = load_config()
    config["synth"]["master_gain"] = 1
    config["synth"]["peak_limit"] = .1
    for variation in range(4):
        assert np.max(np.abs(render("done", config, variation=variation, voice="powersaw"))) == pytest.approx(.1)


def test_authored_groups_are_explicit_partitions_and_do_not_share_mutable_palette_lists():
    config = load_config()
    before = deepcopy(config)
    assert config["notifications"]["variation_full_after_seconds"] == 120
    assert variation_groups("done", config) == {"light": (0, 2), "full": (1, 3)}
    assert variation_groups("answer") == {"light": (0, 1), "full": (2, 3)}
    groups = variation_groups("done", config)
    groups["light"] += (1,)
    assert config == before


@pytest.mark.parametrize("state", ["done", "answer"])
def test_custom_variations_without_roles_are_not_given_inferred_groups(state):
    config = load_config()
    config["states"][state].pop("variation_groups")
    assert variation_count(state, config) == 4
    assert variation_groups(state, config) is None


@pytest.mark.parametrize("state", GESTURE_ORDER)
def test_original_only_gestures_have_no_groups_even_with_unused_metadata(state):
    config = load_config()
    config["states"][state]["variations"] = []
    config["states"][state]["variation_groups"] = {"unused": "metadata"}
    assert variation_groups(state, config) is None


@pytest.mark.parametrize("groups", [
    None, [], {}, {"light": [0, 1, 2, 3]},
    {"light": [0], "full": [1, 2, 3], "extra": []},
    {"light": [], "full": [0, 1, 2, 3]},
    {"light": [0, 1, 2, 3], "full": []},
    {"light": "01", "full": [2, 3]},
    {"light": [0, True], "full": [2, 3]},
    {"light": [0, 1.0], "full": [2, 3]},
    {"light": [0, "1"], "full": [2, 3]},
    {"light": [0, []], "full": [2, 3]},
    {"light": [-1, 0, 1], "full": [2, 3]},
    {"light": [0, 1], "full": [2, 3, 4]},
    {"light": [0, 0, 1], "full": [2, 3]},
    {"light": [0, 1], "full": [1, 2, 3]},
    {"light": [0, 1], "full": [2]},
])
def test_explicit_groups_must_partition_all_available_integer_ids(groups):
    config = load_config()
    config["states"]["done"]["variation_groups"] = groups
    with pytest.raises(ValueError, match="variation_groups"):
        variation_groups("done", config)


def test_custom_group_validation_uses_the_actual_variation_count_and_preserves_order():
    config = load_config()
    state = config["states"]["done"]
    state["variations"] = state["variations"][:2]
    state["variation_groups"] = {"light": [2, 0], "full": [1]}
    assert variation_groups("done", config) == {"light": (2, 0), "full": (1,)}
    state["variations"] = state["variations"][:1]
    with pytest.raises(ValueError, match="available integer IDs"):
        variation_groups("done", config)
    state["variation_groups"] = {"light": [0], "full": [1]}
    assert variation_groups("done", config) == {"light": (0,), "full": (1,)}
    state["variations"] = [{}]
    with pytest.raises(ValueError, match="full events list"):
        variation_groups("done", config)
    with pytest.raises(ValueError, match="Unknown gesture"):
        variation_groups("unknown", config)


@pytest.mark.parametrize("state", ["done", "answer"])
@pytest.mark.parametrize("long_turn", [False, True])
@pytest.mark.parametrize("voice", _SESSION_VOICES)
def test_group_metadata_never_changes_any_rendered_phrase(state, long_turn, voice):
    config = load_config()
    ungrouped = deepcopy(config)
    del ungrouped["states"][state]["variation_groups"]
    for variation in range(4):
        assert np.array_equal(
            render(state, config, long_turn=long_turn, voice=voice, variation=variation),
            render(state, ungrouped, long_turn=long_turn, voice=voice, variation=variation),
        )
