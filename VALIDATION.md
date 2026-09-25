# Observed validation

Run on 2026-09-25, Apple Silicon macOS 26.6, Python 3.13.1. The core environment
contains Awaitonal, NumPy, and test dependencies. A separate environment was used
for optional ML installation and explicit model setup; weights are not bundled in
the source distribution.

## Tests and integration

| Check | Observed result |
| --- | --- |
| Core suite with offline environment flags | **206 passed, 2 skipped**, 7.07 s |
| Suite with real locally downloaded MiniLM weights | **208 passed**, 15.20 s |
| Wheel installed in a fresh minimal environment | WAV rendering and JSON classification passed |
| Actual macOS `awaitonal demo` playback command | `afplay` exited successfully |
| Foreground rules and semantic services | CLI hooks from an unrelated directory, classification records, SIGINT cleanup passed |

The two core skips are the real-model offline test and the real semantic foreground
service test. Both ran in the optional environment. The real-model test blocks
socket connections while constructing and using the model. Fixture hook processes
and real local services were exercised; **hooks were not installed or fired inside
an actual Claude conversation**. Claude 2.1.158 schema compatibility was inspected
separately. Existing Claude settings were not edited.

Recorded pytest output: [core](artifacts/tests-core.txt),
[with real semantic model](artifacts/tests-semantic.txt). Tests cover hook silence
and success on failures, exact input-size limits, unfinished stdin pipes, no ML/audio
imports in hooks, service absence, no acknowledgment wait, malformed/deep JSON,
concurrent sessions, stale/duplicate events, cache/queue bounds, and shutdown.

Shutdown tests also cover inference finishing after the service stops and process
cancellation/reaping during playback. No user-session service is left running by
these tests.

## Audio

[Audition](artifacts/awaitonal-palette.wav): mono, 48,000 Hz, signed PCM16,
250,080 frames, **5.21 seconds**. Order: done, caveats, needs-you, rejected.

| State | Duration, seconds | Floating render peak | Whole-gesture RMS |
| --- | ---: | ---: | ---: |
| done | 0.92 | 0.378 | 0.0602 |
| caveats | 1.10 | 0.442 | 0.0596 |
| needs-you | 1.48 | 0.452 | 0.0557 |
| rejected | 0.66 | 0.274 | 0.0482 |

Audio tests verify deterministic samples and WAV bytes, finite values, smooth
boundaries, safe headroom, voice-energy normalization, bounded brightness, Nyquist
filtering, the late B4→D5 tail, and silence separating the two rejection taps.
These signal measurements are not a listening test or perceptual loudness study.
**No listening comparison was performed**, and no reference WAV was available.

## Held-out classification evaluation

There are 30 independently stored evaluation fixtures, separate from editable
anchor examples. They include optional offers, limited validation, permission
requests, code/quotes, recovered errors, and long responses with late or middle
waiting/refusal statements. This is a small local fixture set, not a representative
benchmark. Anchors and semantic thresholds were fixed before this evaluation and
were not tuned against its results.

Rules: **30/30** correct. No false attention or rejection cases.

Semantic: **13/30** correct (43.3%). No false attention or rejection cases, but
seven of eight expected needs-you cases fell back to caveats. Two caveat cases
were incorrectly classified as done. **Rules remains the default; the optional
semantic classifier should be treated as experimental.** Passing infrastructure
tests does not imply semantic accuracy.

Semantic confusion matrix, rows expected and columns selected:

| Expected | done | caveats | needs-you | rejected |
| --- | ---: | ---: | ---: | ---: |
| done | 5 | 7 | 0 | 0 |
| caveats | 2 | 3 | 0 | 0 |
| needs-you | 0 | 7 | 1 | 0 |
| rejected | 0 | 1 | 0 | 4 |

The full [rules report](artifacts/evaluation-rules.json) and
[semantic report](artifacts/evaluation-semantic.json) contain the confusion matrices,
failure IDs, and timing data without response text. Inspect the labeled fixtures
to see the text associated with each ID. Structured permission/question events
continue to override the encoder in both modes.

Optional runtime used here: sentence-transformers 5.7.0, torch 2.14.0,
transformers 5.17.0, CPU, model `sentence-transformers/all-MiniLM-L6-v2`.

## Actual timing measurements

`tools/benchmark.py` measures elapsed wall time with `perf_counter`. All values
below are milliseconds. First process launch is shown separately from repeated
fresh launches; it does not mean cold disk/OS caches. OS scheduling and caches are
uncontrolled, and test work may occur concurrently. No sound plays during timing.

| Operation | First | Repeated median | Repeated p95 |
| --- | ---: | ---: | ---: |
| Rules classify, new CLI process | 63.350 | 59.035 | 60.096 |
| Hook, new CLI process and socket handoff | 53.025 | 52.824 | 55.664 |
| Rules, resident classifier | 1.770 | 0.018 | 0.023 |
| Socket connect/send, resident caller | — | 0.143 | 0.357 |
| Semantic, resident classifier | 6.653 | 5.360 | 5.891 |

Semantic import, model loading, and anchor embedding took **3,114.023 ms** in a
fresh benchmark process; this happens once per service. The hook does not perform
that work. Socket timing ends after sending; it is not an acknowledgment that the
event was classified or played. Slow/absent-service paths have separate bounded
I/O tests, not benchmark-derived promises.

Raw reports: [core timing](artifacts/benchmarks-core.json),
[semantic timing](artifacts/benchmarks-semantic.json). Commands to reproduce all
checks are in [README.md](README.md).

## Remaining unverified behavior

- Human auditory quality and resemblance to the missing approved reference.
- Real hook firing in a live Claude conversation and version-specific UI behavior.
- Running the service/tests on Linux or other Python versions; implementation and
  non-playback tests avoid macOS audio dependencies, but this run was macOS only.
- Broad natural-language accuracy outside the small English fixture set.
- Perceptual volume matching across hardware and user volume settings.
