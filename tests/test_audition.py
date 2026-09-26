import numpy as np
import pytest

from awaitonal.audition import render_ensemble_demo
from awaitonal.config import load_config
from awaitonal.synth import render


def test_voice_study_covers_each_identity_and_outcome_with_clear_gaps():
    audio, cues = render_ensemble_demo()
    assert {(cue.voice, cue.gesture) for cue in cues} == {
        (voice, gesture) for voice in ("wood", "glass", "round")
        for gesture in ("done", "review", "needs-you")}
    end = 0
    for cue in cues:
        start = round(cue.start * 48000)
        assert not np.any(audio[end:start])
        sound = render(cue.gesture, voice=cue.voice)
        assert np.array_equal(audio[start:start+len(sound)], sound)
        end = start + len(sound)
    assert len(audio) == end


def test_burst_comparison_changes_spacing_while_preserving_voices_and_gestures():
    serial, serial_cues = render_ensemble_demo(mode="serial")
    overlap, overlap_cues = render_ensemble_demo(mode="overlap")
    assert [(c.voice, c.gesture, c.duration) for c in serial_cues] == [
        (c.voice, c.gesture, c.duration) for c in overlap_cues]
    assert overlap_cues[1].start - overlap_cues[0].start == pytest.approx(.3)
    assert len(overlap) < len(serial)
    for cues in (serial_cues, overlap_cues):
        attention = cues[-1]
        assert attention.gesture == "needs-you"
        assert attention.start >= max(c.start+c.duration for c in cues[:-1]) + .149
    for audio in (serial, overlap):
        assert audio.ndim == 1 and np.isfinite(audio).all()
        assert np.max(np.abs(audio)) <= .8
        assert audio[0] == audio[-1] == 0


def test_overlap_mix_respects_headroom_with_loud_custom_profiles():
    config = load_config()
    config["synth"]["master_gain"] = 1
    config["synth"]["peak_limit"] = .2
    audio, _ = render_ensemble_demo(config, mode="overlap")
    assert np.max(np.abs(audio)) <= .2 + 1e-12
    assert np.any(audio)


def test_unknown_study_mode_fails_explicitly():
    with pytest.raises(ValueError, match="mode"):
        render_ensemble_demo(mode="unbounded")
