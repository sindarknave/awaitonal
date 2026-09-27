"""Preview timelines keep comparisons aligned even when phrase lengths differ."""
import importlib.util
import json
import wave
from html.parser import HTMLParser
from pathlib import Path

import numpy as np
import pytest

from awaitonal.config import load_config


@pytest.fixture
def preview():
    path = Path(__file__).resolve().parents[1] / "tools/build_variation_preview.py"
    spec = importlib.util.spec_from_file_location("awaitonal_variation_preview", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repeated_and_varied_sequences_share_sample_exact_turn_slots(preview):
    # Unequal phrase lengths catch accidental end-to-start spacing drift.
    clips = {(gesture, variation): np.full(31 + offset + variation * 7, (variation + 1) / 10)
             for gesture, offset in (("answer", 0), ("done", 11)) for variation in range(4)}
    original = [(gesture, 0) for gesture in preview.TURN_ORDER]
    varied = list(zip(preview.TURN_ORDER, [3, 1, 0, 2, 3, 0, 1, 2]))
    first, before = preview.make_sequence(clips, original, 100)
    second, after = preview.make_sequence(clips, varied, 100)
    assert len(first) == len(second)
    assert [row["offset_frames"] for row in before] == [row["offset_frames"] for row in after]
    assert [row["gesture"] for row in after] == list(preview.TURN_ORDER)
    for audio, timeline in ((first, before), (second, after)):
        assert not audio[:30].any()
        for index, row in enumerate(timeline):
            start = row["offset_frames"]
            stop = start + row["duration_frames"]
            assert np.array_equal(audio[start:stop], clips[row["gesture"], row["variation"]])
            assert row["offset_seconds"] == start / 100
            assert row["duration_seconds"] == (stop - start) / 100
            if index + 1 < len(timeline):
                next_start = timeline[index + 1]["offset_frames"]
                assert next_start == start + row["slot_duration_frames"] + 55
                assert not audio[stop:next_start].any()
        assert not audio[-40:].any()


def test_invalid_sequence_does_not_manufacture_an_empty_or_overlapping_clip(preview):
    clips = {("answer", 0): np.ones(20)}
    with pytest.raises(ValueError, match="Every sequence choice"):
        preview.make_sequence(clips, [("done", 0)], 100)
    with pytest.raises(ValueError, match="silence durations"):
        preview.make_sequence(clips, [("answer", 0)], 100, gap_seconds=-1)
    with pytest.raises(ValueError, match="sample_rate"):
        preview.make_sequence(clips, [("answer", 0)], True)


def test_preview_demonstrates_duration_groups_and_independent_repetition(preview):
    plan = preview.contextual_plan(load_config())
    assert [turn["variation"] for turn in plan] == [0, 0, 2, 3, 1, 3, 1, 2]
    assert [turn["selection_group"] for turn in plan] == [
        "light", "light", "full", "full", "full", "full", "light", "light"]
    assert [turn["group_occurrence"] for turn in plan] == [0, 0, 0, 1, 0, 1, 1, 1]
    assert [turn["turn_seconds"] for turn in plan] == list(preview.TURN_SECONDS)
    for gesture in preview.GESTURES:
        assert {turn["variation"] for turn in plan if turn["gesture"] == gesture} == set(range(4))
    assert "Long turn" in plan[2]["selection_reason"]
    assert "repeated gesture" in plan[3]["selection_reason"]


def test_preview_uses_configured_inclusive_cutoff_and_missing_timing_fallback(preview):
    config = load_config()
    config["notifications"]["variation_full_after_seconds"] = 20
    plan = preview.contextual_plan(config, turn_order=("answer",) * 5,
                                   elapsed_seconds=(19, 20, None, 19, 20))
    assert [turn["selection_group"] for turn in plan] == ["light", "full", "ordinary", "light", "full"]
    assert [turn["variation"] for turn in plan] == [0, 2, 0, 1, 3]
    assert plan[2]["group_occurrence"] is None
    assert "Missing matched timing" in plan[2]["selection_reason"]
    assert plan[3]["group_occurrence"] == 1
    with pytest.raises(ValueError, match="corresponding elapsed-time"):
        preview.contextual_plan(config, turn_order=("done",), elapsed_seconds=())


def test_custom_ungrouped_palette_does_not_inherit_default_group_meaning(preview):
    config = load_config()
    for gesture in preview.GESTURES:
        config["states"][gesture].pop("variation_groups")
    plan = preview.contextual_plan(config, turn_order=("answer",) * 4,
                                   elapsed_seconds=(180,) * 4)
    assert [turn["selection_group"] for turn in plan] == ["ordinary"] * 4
    assert [turn["variation"] for turn in plan] == list(range(4))
    assert all("no duration groups" in turn["selection_reason"] for turn in plan)


def test_gallery_build_preserves_matched_timelines_and_click_only_audio(preview, tmp_path):
    manifest = preview.build(tmp_path, voices=("marimba",))
    saved = json.loads((tmp_path / "manifest.json").read_text())
    assert saved["schema_version"] == 2
    assert saved["footprint"]["wav_files"] == 11
    assert len(list((tmp_path / "audio").glob("*.wav"))) == 11
    sequences = {track["kind"]: track for track in manifest["sequences"]}
    original, contextual = sequences["original"], sequences["contextual"]
    assert original["frames"] == contextual["frames"]
    assert [turn["offset_frames"] for turn in original["timeline"]] == [
        turn["offset_frames"] for turn in contextual["timeline"]]
    assert [turn["variation"] for turn in contextual["timeline"]] == [0, 0, 2, 3, 1, 3, 1, 2]
    clips = {clip["id"]: clip for clip in manifest["clips"]}
    for turn in manifest["missing_timing"]:
        assert turn["variation"] == 0
        assert turn["turn_seconds"] is None
        assert turn["clip_id"] in clips
        assert clips[turn["clip_id"]]["variation"] == 0
    for track in (*manifest["clips"], *manifest["sequences"], manifest["sampler"]):
        with wave.open(str(tmp_path / track["file"]), "rb") as source:
            assert source.getnframes() == track["frames"]
            assert source.getframerate() == manifest["sample_rate"]
            assert source.getnchannels() == 1
    html = (tmp_path / "index.html").read_text()
    assert "shuffle" not in html.lower()
    assert "seed" not in html.lower()
    assert "It is not thinking duration" in html
    assert "Play answer with missing timing" in html

    class AudioParser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.audio = []

        def handle_starttag(self, tag, attrs):
            if tag == "audio":
                self.audio.append(dict(attrs))

    parser = AudioParser()
    parser.feed(html)
    assert len(parser.audio) == 1
    assert parser.audio[0]["preload"] == "none"
    assert "src" not in parser.audio[0]
    assert "autoplay" not in parser.audio[0]
