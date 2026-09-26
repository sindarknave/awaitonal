# Rotating session voices

A gesture describes the reported outcome; its instrument identifies the session.
New sessions rotate through six contrasting instruments: `marimba`, `powersaw`,
`harp`, `clarinet`, `crystal`, and `flute`. Each session keeps its assigned voice.
The new profiles use 105–135 ms maximum exponential decay constants and 360 ms
maximum note bodies, with softer attacks and typically 85–100 ms release ramps.
Phrase pitches and note onset times are preserved, while
trailing silence is trimmed. Level is matched by RMS with the existing peak
limit retained. The original `default`, `wood`, `glass`, and `round` instruments
remain available with their previous sound and duration.

The compact set uses harmonic partials at the same concert tuning, rather than
putting each session in a different key. Powersaw has only +/-5 cents of detuning
around an unshifted oscillator. There is no reverb. This reduces lingering
clashes; it does not make all outcome chords consonant together. In particular,
the refusal cue keeps its deliberate dissonance. Live playback remains serial.

## Listen

```sh
awaitonal play done --voice marimba
awaitonal play review --voice powersaw
awaitonal play needs-you --voice clarinet
awaitonal play done --voice harp --long-turn
awaitonal demo --voice crystal --out crystal-palette.wav
awaitonal ensemble-demo --out voice-study.wav
awaitonal ensemble-demo --mode rotation --out rotation.wav
awaitonal ensemble-demo --mode serial --out serial.wav
awaitonal ensemble-demo --mode overlap --out overlap.wav
```

The voice study plays `done`, then `review`, then `needs-you`. Each gesture is
played through the configured cycle with 450 ms gaps. Rotation mode plays the
same `done` phrase for six new sessions, then returns to sessions 1 and 2 and
introduces session 7, which reuses marimba. This uses the live voice allocator.
The burst comparisons contain marimba/done, powersaw/review, and harp/needs-you.
Serial mode leaves 150 ms
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
voice_cycle = ["marimba", "powersaw", "harp", "clarinet", "crystal", "flute"]
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

The first six distinct session IDs receive the six voices in that order. New
sessions prefer an unused instrument, then the least-used instrument, with ties
resolved in rotation order. Beyond six simultaneous sessions, voices are shared;
six sounds cannot uniquely identify an unlimited number of sessions. Returning
sessions keep their assignment, including across mute/unmute. A session with no
events for an hour loses its assignment; expiry frees its voice without resetting
the rotation cursor. Restarting the service resets assignments and the cursor.
The registry retains at most 128 session IDs and no project paths or response
text. At registry capacity, new sessions conservatively use `default` until the
overflow arrivals have been idle for an hour.

`voice_cycle` is optional. Supply any nonempty list of distinct supported voice
names to change its order or size, including the original voices if preferred.
Both the resident service and audition commands use this list. Restart the
service after changing it; the feature remains opt-in via `session_voices`.

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

The `[voices.<name>]` tables in
[palette.toml](../src/awaitonal/palette.toml) control partial ratios, weights,
decay, and envelope scales. Compact profiles additionally set `max_decay` and
`max_note_duration` in seconds. The latter trims playback to the last note's end
plus 25 ms. `detune_cents` optionally layers up to seven oscillators within
+/-12 cents and must include zero. Partials beyond Nyquist are omitted.
`default` preserves the original rendering. The optional long-turn arrangement
still adds two rising attacks; with compact instruments its final chord remains
a stab, making the phrase 360 ms longer rather than adding a sustained tail.
The optional brightness setting works with every voice.
