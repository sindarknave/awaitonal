# Variations for repeated outcomes

`answer` and `done` each have four arrangements: the original (`0`) and three
variations (`1`–`3`). They keep their familiar shape and ending, with small changes
to voicing, register, and spacing. Done still resolves; answer keeps its open
ending. Instruments retain their existing soft attacks and note tails.

The service selects a group using matched turn-start and turn-finish timing.
Turns under two minutes use lighter arrangements; turns of two minutes or more
use fuller arrangements. Within each group, repeated outcomes alternate in a
fixed order, separately for each session and gesture.

| Gesture | Light: under 120 seconds | Full: 120 seconds or more |
| --- | --- | --- |
| `answer` | `0` Original, `1` Spaced reply | `2` Wide reply, `3` Lifted reply |
| `done` | `0` Original, `2` Upper descent | `1` Low landing, `3` Stepped landing |

This is elapsed turn time, including tools and waiting—not a measurement of
reasoning time, difficulty, or quality. Missing or unusable timing always selects
the original (`0`), even on repeated turns. Hearing an original cue therefore
does not prove the turn was short. No response-length estimate or additional
model call is used to choose an arrangement.

Only cues admitted for playback advance the alternation. Muted, suppressed,
duplicate, stale, or cancelled notifications do not. A playback failure can
consume a selected arrangement because admission precedes the audio operation.
When timed playback resumes after an untimed original, the service avoids an
immediate repeat if the selected group offers an alternative.

Session instruments stay stable. Outcome classification and other gestures
retain their existing behavior. The optional `long_turn_seconds` setting still
controls an extended ending independently; choosing a fuller arrangement does
not enable it. Long-turn versions use the selected arrangement's opening before
their extended ending. Voicings share the existing tuning and are matched to the
original cue's RMS level, subject to the peak limit.

The feature is enabled in the packaged service configuration. To change the
cutoff, pass a palette override to the service and restart it:

```toml
[notifications]
gesture_variations = true
variation_full_after_seconds = 120
```

The cutoff must be finite and positive. Set `gesture_variations = false` to keep
the original arrangements. Existing running services load changes when restarted.
Alternation history stays in memory, expires after an hour of inactivity, and
resets on service restart. It is bounded to 128 sessions; evicted sessions start
fresh when they return.

To audition an exact arrangement or export it without playback:

```sh
awaitonal play answer --voice marimba --variation 0
awaitonal play answer --voice marimba --variation 1
awaitonal play done --voice harp --variation 2 --long-turn
awaitonal play done --voice powersaw --variation 3 --out done-3.wav
```

`play` and the existing demos select the original arrangement by default. Nonzero
variations apply only to answer and done. A fixed voice and variation render
deterministically; live selection is also deterministic for the same timing and
playback history.

Download the [v0.7.0 listening preview](https://github.com/sindarknave/awaitonal/releases/download/v0.7.0/awaitonal-0.7.0-listening-preview.zip),
extract it, and open `index.html`. Or build it from the checkout:

```sh
.venv/bin/python tools/build_variation_preview.py
```

Open `artifacts/variation-preview/index.html` in a browser. It includes individual
arrangements, an eight-cue sampler, and repeated-original versus duration-guided
comparisons across the six session instruments. Each comparison turn shows its
elapsed time, group, and selected phrase. Missing-timing examples play the original.
Audio starts only when you choose Play. Comparisons use matching turn slots and
gaps so you can judge the musical change. Waveform and level checks do not
establish perceptual recognition; the preview is for listening and adjusting.

## Custom palettes

Variations are editable under `states.answer.variations` and
`states.done.variations`. Each entry supplies a complete phrase duration and
events, with an optional long-turn arrangement. Custom overrides of a base
phrase's events, duration, or long-turn settings disable inherited variations
unless the override explicitly supplies its own. Setting `variations = []`
also keeps that gesture fixed.

Timing groups belong to the phrases they describe. Changing a base phrase or
its variations removes inherited groups. To assign roles to a custom palette,
provide a complete mapping of available phrase IDs, including original `0`:

```toml
[states.done]
variation_groups = { light = [0, 2], full = [1, 3] }
```

Both groups must be nonempty, disjoint, and together contain every available ID
exactly once. An explicit mapping replaces the default as a whole. A custom
multi-phrase palette without groups cycles through its phrases when timing is
known, without labeling them light or full. Missing timing still uses original
`0`. Single-phrase palettes remain fixed.
