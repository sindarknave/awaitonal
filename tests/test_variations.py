import pytest

from awaitonal.variations import SessionVariations


@pytest.mark.parametrize("gesture,seconds,expected", [
    ("done", 0, [0, 2, 0, 2]), ("done", 119.999, [0, 2, 0, 2]),
    ("done", 120, [1, 3, 1, 3]), ("done", 900, [1, 3, 1, 3]),
    ("answer", 30, [0, 1, 0, 1]), ("answer", 120, [2, 3, 2, 3]),
])
def test_duration_selects_group_and_repetition_alternates_inside_it(gesture, seconds, expected):
    variations = SessionVariations()
    assert [variations.choose("s", gesture, turn_seconds=seconds) for _ in range(4)] == expected


def test_interleaved_light_and_full_groups_advance_independently():
    variations = SessionVariations()
    elapsed = [10, 120, 20, 130, 30, 140, 40, 150]
    assert [variations.choose("s", "done", turn_seconds=seconds) for seconds in elapsed] == [0, 1, 2, 3, 0, 1, 2, 3]
    assert [variations.choose("s", "answer", turn_seconds=seconds) for seconds in elapsed] == [0, 2, 1, 3, 0, 2, 1, 3]


def test_sessions_and_gestures_have_independent_deterministic_history():
    variations = SessionVariations()
    assert variations.choose("a", "done", turn_seconds=50) == 0
    assert variations.choose("b", "done", turn_seconds=50) == 0
    assert variations.choose("a", "answer", turn_seconds=50) == 0
    assert variations.choose("a", "done", turn_seconds=50) == 2
    assert variations.choose("b", "done", turn_seconds=50) == 2
    assert variations.choose("a", "answer", turn_seconds=50) == 1


@pytest.mark.parametrize("seconds", [None, True, False, "150", -1, float("nan"), float("inf"), float("-inf")])
def test_missing_or_unusable_timing_uses_original_and_preserves_group_cursor(seconds):
    variations = SessionVariations()
    assert variations.group_for("done", seconds) == "ordinary"
    assert not variations.sessions
    assert variations.choose("s", "done", turn_seconds=150) == 1
    assert [variations.choose("s", "done", turn_seconds=seconds) for _ in range(3)] == [0, 0, 0]
    assert variations.choose("s", "done", turn_seconds=150) == 3
    # Unknown timing recorded original0; the first timed light phrase avoids it.
    assert variations.choose("s", "done", turn_seconds=seconds) == 0
    assert variations.choose("s", "done", turn_seconds=20) == 2


def test_group_lookup_is_pure_and_custom_cutoff_is_inclusive():
    variations = SessionVariations(full_after_seconds=60)
    for _ in range(5):
        assert variations.group_for("answer", 59.999) == "light"
        assert variations.group_for("answer", 60) == "full"
        assert variations.group_for("plan", 300) == "ordinary"
    assert not variations.sessions
    assert variations.choose("s", "answer", turn_seconds=60) == 2


@pytest.mark.parametrize("count", [2, 3, 4])
def test_unmapped_custom_palette_has_an_ordinary_cycle_only_when_timing_is_known(count):
    variations = SessionVariations({"done": count}, groups={})
    assert variations.group_for("done", 300) == "ordinary"
    chosen = [variations.choose("s", "done", turn_seconds=300) for _ in range(count * 3)]
    assert chosen == list(range(count)) * 3
    assert variations.choose("s", "done") == 0
    # Fallback0 is audible history, so the next timed cue starts at its alternative.
    assert variations.choose("s", "done", turn_seconds=30) == 1


def test_incomplete_counts_do_not_inherit_packaged_group_meaning():
    variations = SessionVariations({"done": 3, "answer": 4})
    assert variations.group_for("done", 300) == "ordinary"
    assert variations.group_for("answer", 300) == "full"
    assert [variations.choose("s", "done", turn_seconds=300) for _ in range(4)] == [0, 1, 2, 0]


def test_custom_groups_are_copied_and_single_phrase_groups_can_repeat():
    counts = {"done": 3}
    groups = {"done": {"light": [2, 0], "full": [1]}}
    variations = SessionVariations(counts, groups=groups)
    counts["done"] = 4
    groups["done"]["light"].clear()
    assert [variations.choose("s", "done", turn_seconds=10) for _ in range(4)] == [2, 0, 2, 0]
    assert [variations.choose("s", "done", turn_seconds=150) for _ in range(2)] == [1, 1]
    assert not variations.supported("answer")


def test_unsupported_or_single_phrase_cues_do_not_allocate_or_refresh_history():
    variations = SessionVariations({"done": 4, "answer": 1}, ttl=10)
    variations.choose("a", "done", 0, turn_seconds=10)
    for gesture in ("answer", "plan", "decision", "failed", "unrecognized"):
        assert variations.choose("other", gesture, 9, turn_seconds=150) == 0
        assert variations.choose("a", gesture, 9) == 0
    assert list(variations.sessions) == ["a"]
    variations.choose("b", "done", 10, turn_seconds=10)
    assert list(variations.sessions) == ["b"]


def test_lru_bounds_history_and_preserves_a_refreshed_sessions_next_phrase():
    variations = SessionVariations(capacity=2, ttl=100)
    assert variations.choose("a", "done", 0, turn_seconds=10) == 0
    variations.choose("b", "done", 1, turn_seconds=10)
    assert variations.choose("a", "done", 2, turn_seconds=10) == 2
    variations.choose("c", "done", 3, turn_seconds=10)
    assert list(variations.sessions) == ["a", "c"]
    assert variations.choose("a", "done", 4, turn_seconds=10) == 0
    assert variations.choose("b", "done", 5, turn_seconds=10) == 0
    assert list(variations.sessions) == ["a", "b"]
    for now in range(6, 300):
        variations.choose(str(now), "done", now)
        assert len(variations.sessions) == 2


def test_ttl_expiry_restarts_idle_history_while_preserving_active_history():
    variations = SessionVariations(ttl=10)
    assert variations.choose("idle", "done", 0, turn_seconds=10) == 0
    assert variations.choose("active", "done", 9, turn_seconds=10) == 0
    assert variations.choose("idle", "done", 10, turn_seconds=10) == 0
    assert variations.choose("active", "done", 11, turn_seconds=10) == 2


@pytest.mark.parametrize("options", [
    {"capacity": 0}, {"capacity": 129}, {"capacity": True}, {"capacity": 2.5},
    {"ttl": 0}, {"ttl": -1}, {"ttl": True}, {"ttl": float("inf")}, {"ttl": float("nan")},
    {"counts": []}, {"counts": "done"}, {"counts": {"plan": 4}},
    {"counts": {"done": 0}}, {"counts": {"done": 5}}, {"counts": {"done": True}},
    {"counts": {"answer": 2.5}}, {"counts": {"answer": None}},
    {"full_after_seconds": 0}, {"full_after_seconds": -1}, {"full_after_seconds": True},
    {"full_after_seconds": float("nan")}, {"full_after_seconds": float("inf")},
    {"groups": []}, {"groups": {"plan": {"light": [0], "full": [1]}}},
    {"groups": {"done": None}}, {"groups": {"done": {"light": [0, 1, 2, 3]}}},
    {"groups": {"done": {"light": [], "full": [0, 1, 2, 3]}}},
    {"groups": {"done": {"light": "01", "full": [2, 3]}}},
    {"groups": {"done": {"light": [False, 1], "full": [2, 3]}}},
    {"groups": {"done": {"light": [0, 1], "full": [2, 4]}}},
    {"groups": {"done": {"light": [0, 1], "full": [1, 3]}}},
    {"groups": {"done": {"light": [0], "full": [1]}}},
])
def test_invalid_configuration_is_rejected(options):
    with pytest.raises(ValueError):
        SessionVariations(**options)
