# Session voices: listening prototype

A gesture describes the reported outcome; its instrument identifies the session.
The first prototype has three instruments: `wood` (warm wooden pluck), `glass`
(soft bell), and `round` (rounded electric piano). Pitches, melodic contours,
event timing, and gesture duration stay consistent across instruments. Level is
matched by RMS, with the existing peak limit retained. The original instrument
is available as `default`.

## Listen

```sh
awaitonal play done --voice wood
awaitonal play review --voice glass
awaitonal play needs-you --voice round
awaitonal play done --voice glass --long-turn
awaitonal demo --voice wood --out wood-palette.wav
awaitonal ensemble-demo --out voice-study.wav
awaitonal ensemble-demo --mode serial --out serial.wav
awaitonal ensemble-demo --mode overlap --out overlap.wav
```

The voice study plays `done`, then `review`, then `needs-you`. Each gesture is
played in wood, glass, round order with 450 ms gaps. The burst comparisons both
contain wood/done, glass/review, and round/needs-you. Serial mode leaves 150 ms
between gestures; overlap mode starts the first two 300 ms apart and gives the
required-action cue its own space after their tails. These are composed listening
examples, not simulations of the live priority queue. Overlap is audition-only.

Try recognizing both the instrument and the outcome on laptop speakers, then
headphones. Compare spaced and overlapping versions for recognition, pleasantness,
and how quickly you notice the required-action cue. Distinct waveforms and matched
levels do not establish perceptual recognition; listener feedback is still needed.

## Enable live session voices

Add this to the TOML file supplied to the resident service:

```toml
[notifications]
session_voices = true
```

For a standalone installation, restart the service with that file:

```sh
awaitonal service stop
awaitonal service start --config /absolute/path/to/session-voices.toml
```

For the Claude plugin, use its installed `scripts/plugin-runtime.sh service`
wrapper for the same stop/start commands. The file is a partial palette override;
the rest of the defaults are inherited. See
[the example](../examples/session-voices.toml).

The first three distinct session IDs seen by that service receive wood, glass,
and round. Assignments survive mute/unmute and do not shuffle when another session
arrives. A session with no events for an hour loses its assignment; restarting
the service resets all assignments. Extra sessions use `default` rather than
sharing one of the three named instruments. Their fallback stays stable until
they expire. The registry retains at most 128 session IDs and no project paths or
response text. At registry capacity, new sessions conservatively use `default`.

Live playback stays serial. Existing attention priority and latest-per-session
queue behavior still apply. When another session is waiting, a routine result
uses its normal ending instead of the optional extended long-turn ending. A cue
already playing finishes normally. This reduces some burst backlog without
changing handoff gestures or discarding their musical content. Logs include the
instrument name and whether an extended ending was compacted, without session IDs.

The classifier and hook format are unchanged. All sessions share the same resident
model, and voice assignment adds no model calls. This first pass uses automatic
session assignments; project labels, pinned instruments, per-session solo, and a
live audio mixer would be separate extensions after listening feedback.

## Sound settings

The `[voices.wood]`, `[voices.glass]`, and `[voices.round]` tables in
[palette.toml](../src/awaitonal/palette.toml) control partial ratios, weights,
decay, and envelope scales. `default` preserves the original rendering. Named
profiles also work with the longer-turn variants and optional brightness setting.
