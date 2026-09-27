# Observed validation

## v0.7.0 release checks

The implementation suite reports [2,069 Python tests passed, with two optional-model
skips](artifacts/tests-contextual-variations.txt). After synchronizing the package
and plugin versions to 0.7.0, [130 packaging, lifecycle, diagnostics, and CLI checks
passed](artifacts/tests-v0.7.0-packaging.txt), along with all
[23 Pi extension tests](artifacts/tests-v0.7.0-pi.txt).

A [fresh-wheel smoke check](artifacts/package-v0.7.0-smoke.json) installed only
Awaitonal 0.7.0 and NumPy into a disposable Python 3.13 environment. Imports and
CLI calls ran outside the checkout. Claude, Codex, and Pi adapters delivered
synthetic lifecycle events to a private socket; the service rendered 15 finite,
peak-limited PCM cues with the expected duration choices and stable voices.
Missing timing, shared mute, cancellation before admission, recovery, and socket
cleanup passed. Long durations used test-only clock injection. No user service,
settings, model, or audio device was exercised.

[Variation validation](artifacts/gesture-variations-validation.json) records the
source hashes and duration policy. Tests cover the inclusive 120-second cutoff,
missing/ambiguous timing, independent session/gesture/group histories, bounded
retention, mute and cancellation admission, custom palette overrides, and the
independent optional extended ending. Grouping metadata does not change rendered
samples. Audio checks cover finite output, distinct phrases, RMS matching, peak
limits, and motif direction; they do not establish human recognition or preference.

The downloadable offline preview contains 61 WAVs. All 48 individual phrases,
six original comparisons, and the sampler match the preceding gallery. Six
duration-guided comparisons use the real selector with synthetic turn durations;
their phrase samples and A/B onset positions match exactly. All WAV URLs returned
HTTP 200, and the browser gallery was checked for roles, selection explanations,
missing-timing examples, and click-only audio. The release ZIP was extracted and
all audio hashes and headers matched its manifest.

The [classifier evaluation](docs/classification-v061-evaluation.md) is a separate,
frozen classifier-only study. Its 16 targeted regression cases improve, while
agreement on 92 eligible public replies is unchanged. AI labeling, ambiguity,
completion-heavy sampling, and the absence of required handoffs limit what that
sample can establish. No raw conversations or labeling rationales are published.
The earlier evaluation's timing and source hashes remain historical measurements.

## v0.6.0 release checks

The final release suite reports [1,603 Python tests passed, with two optional-model
skips](artifacts/tests-v0.6.0-core.txt), and [23 Pi extension tests
passed](artifacts/tests-v0.6.0-pi.txt). All package and plugin manifests use 0.6.0.

A fresh 0.6.0 wheel installed with NumPy only passes the
[Claude/Codex transport and shared-service smoke check](artifacts/codex-v0.6.0-smoke.json)
and the [native Pi 0.87.1 package/lifecycle smoke check](artifacts/pi-v0.6.0-smoke.json).
These isolated checks render WAVs without playing audio, preserve user settings,
exercise shared mute and distinct session voices, and check metadata-only logs.
The timing observations below describe earlier integration runs; the new smoke
reports record the release-build measurements separately.

## Pi integration, v0.6.0

The [full core suite](artifacts/tests-pi-core.txt) reports **1,603 passed,
2 optional-model skips**. The [Pi extension suite](artifacts/tests-pi-extension.txt)
reports **23 passed**. Strict TypeScript checking against the installed Pi
`0.87.1` declarations also passes. Python checks cover existing Claude/Codex
behavior, Pi wire validation, privacy filtering, timing, global mute, voice
isolation, and quiet cancellation before classification or playback admission.
The extension suite covers automatic continuations, retries, cancellation during
retry backoff, final outcomes, idle versus active dialogs, size limits, session
replacement, subprocess deadlines, and explicit service commands.

The [native Pi smoke check](artifacts/pi-integration-smoke.json) installs, lists,
and removes the local package through Pi `0.87.1` in an isolated temporary
profile. Pi's resource loader discovers exactly one extension and all four
commands, without importing the other apps' skills. Its native extension runner
dispatches fixture lifecycle events to real hook subprocesses and a private
service installed from a fresh wheel with NumPy only. The service renders PCM
WAVs without invoking an audio player. Tests verify final-only notifications,
dialog attention, generic errors, quiet cancellation, preserved timing after
abort, distinct Pi/Claude/Codex session voices, shared mute/unmute, no replay,
and logs without response text or fixture identities.

On this arm64 Mac, 20 sequential Pi settlements reached a synthesized WAV in
**63.1 ms median / 64.4 ms p95** using the resident rules classifier. Timing
starts at the extension's settlement callback and excludes model execution,
Pi scheduling before that callback, playback contention, player startup, and
audio-device latency. No live model request or audible Pi session was exercised.
User configuration, credentials, and the existing service were untouched.

The source distribution contains the extension, Pi manifest, setup script,
documentation, and fixtures. The npm package file list excludes Python caches
and unrelated host plugins. Pi integration requires the settlement APIs available
in the tested release; no early `agent_end` fallback is registered. Pi's final
event lacks an outcome field, so late cancellation by another pre-settlement
handler remains a documented upstream API limitation in [the Pi guide](docs/pi.md).

## Codex integration, v0.6.0

The [full local core suite](artifacts/tests-codex-core.txt) reports **1,446 passed,
2 optional-model skips**. Coverage includes Codex final replies, synchronous and
asynchronous questions, approvals, malformed and oversized input, quiet hook
processes, provider-specific setup/removal, turn timing, long endings, handoff
deduplication, queued-attention resolution, and shared session voices. Existing
Claude behavior remains covered by the same suite.

[Native Codex configuration validation](artifacts/codex-standalone-validation.json)
uses Codex CLI `0.155.0-alpha.16.4` with an isolated temporary configuration.
`awaitonal init --adapter codex --apply` generates four handlers which Codex's
app-server `hooks/list` discovers, all enabled and untrusted, with no errors or
warnings. No model is called and no trust setting is changed.

The Codex plugin installs, lists, and removes successfully in an isolated profile,
but this build does not expose its bundled hooks through the native inventory.
Putting Codex handlers in the default plugin hook file or removing the Claude
manifest did not resolve that gap. Codex plugin setup therefore registers tracked
user hooks pointing at the stable runtime. Its manifests disable bundled hooks
to avoid duplicate registration on builds that load them. Claude still uses
native bundled hooks. Plugin-only removal includes a Codex detach step; shared
runtime removal and global mute affect Claude, Codex, and Pi.

A [fresh-wheel smoke and timing check](artifacts/codex-integration-smoke.json)
uses a separate Python 3.13 environment with only the wheel and NumPy. It runs
real Claude and Codex hook subprocesses against a private service, synthesizes
PCM WAVs, checks all six initial voice assignments and returning identities,
exercises Codex plugin wrappers for completion/questions/approval, and verifies
shared mute/unmute without restarting the service or replaying muted events.
Logs exclude fixture identities, commands, questions, and final response text.

On this arm64 Mac, 20 measured Codex hook launches reached a synthesized WAV in
**61.5 ms median / 74.4 ms p95**, compared with **61.5 / 74.8 ms** for Claude.
Providers were alternated against the same warm rules service, with one event at
a time. This includes hook process startup, transport, classification, synthesis,
and WAV writing. It excludes Codex's hook scheduling, competing queued cues,
audio-player startup, and device onset. OS caches and scheduling are uncontrolled.

These checks do not play audio, change user settings, or invoke a live Codex model
turn. Hook trust still requires user review in Codex. Structured API-failure
notifications are supported by Claude and Pi; Codex has no documented
`StopFailure` equivalent. Pi reports generic terminal failure without raw error details.

## Rotating voices, v0.5.0 release

The [full local core suite](artifacts/tests-v0.5.0-rotation-core.txt) reports
**1,269 passed, 2 optional-model skips**. It covers six-way rotation, stable
returning sessions, idle expiry without resetting the cursor, least-used reuse,
bounded overflow, custom cycles, captured queued identities, and mute/unmute.
Audio checks cover every gesture and voice, optional brightness and long-turn
arrangements, deterministic output, common pitches, bounded short envelopes,
RMS matching, headroom, zero endpoints, and CLI/listening exports.

An independent direct comparison against the preceding prototype commit checked
224 default/wood/glass/round renders: fourteen gestures, normal and long-turn,
brightness off and on. Every sample was identical. Only the new six compact
profiles use the revised 105–135 ms maximum decay constants and 360 ms note caps.

A [fresh-wheel smoke check](artifacts/rotation-v0.5.0-smoke.json), run from an
unrelated directory with only the installed package and NumPy, verifies real
silent service startup and hook transport, all six initial assignments,
seventh-session reuse, stable returning identities, and CLI forwarding of a
custom two-voice cycle. Mute/unmute preserves the process and service instance,
drops muted hooks without replay, and excludes fixture IDs and response text
from logs. All six CLI WAV exports and four audition modes pass; shutdown is
clean. No audio is played and no user service or settings are changed.

[Installed-wheel audio measurements](artifacts/rotation-v0.5.0-audio.json) record
the shipped profiles, all 84 voice/gesture combinations, and rotation cue sheet.
The exported six-voice comparison is byte-identical to the final local audition.
Across 56 warm renders per voice on this Mac, median synthesis time ranged from
6.40 to 19.44 ms and p95 from 11.04 to 30.00 ms. This excludes hook transport,
classification, queue wait, WAV writing, player startup, and audible device onset.

Live playback remains serial; overlap demos are composed listening examples.
Six voices necessarily repeat beyond six active sessions. Instrument recognition
and perceived loudness across listening devices have not been measured in a
blinded study. The following prototype records describe the earlier three-voice
iteration, before the final listening revisions.

## Session voice prototype, before the v0.5.0 release

The [full core suite](artifacts/tests-v0.5.0-core.txt) reports **1,113 passed,
2 optional-model skips**. Synthesis checks cover all fourteen gestures in wood,
glass, and round, including long-turn and brightness combinations, validated
configuration, level matching, headroom, deterministic output, and unchanged note
and event timing. A direct comparison to v0.4.3 confirms default rendering is
sample-identical across all 56 gesture/brightness/long-turn combinations.

Registry and service checks cover distinct initial assignments, stable fallback,
idle expiry, bounded saturation, voice capture across queued work, burst
compaction, and existing mute generation guards. A
[fresh-wheel integration check](artifacts/ensemble-v0.5.0-smoke.json) runs real
plugin hooks and mute/unmute wrappers against a private silent service. It verifies
three instruments, fourth-session fallback, stable identity on later turns,
no muted replay, unchanged process/instance, no private IDs or reply text in
logs, and byte-identical CLI audio exports. No user service or settings were changed.

[Audio measurements](artifacts/session-voices-v0.5.0.json) record all named voices'
levels and the composed demo cue sheets. In a warm local process with loaded
configuration, 30 renders per voice across done/review/needs-you measured median
9.86–12.03 ms and p95 10.41–12.64 ms for the named voices. This excludes hook,
queue, file writing, player startup, and device onset. These are observations,
not end-to-end latency guarantees.

The demos compare three voices and three outcomes; the overlapping example is
composed offline. Live playback remains serial. No listener recognition study
has been performed, and instrument distinguishability still needs listening
feedback on laptop speakers and headphones.

## Mute controls and skills, v0.4.3

The [full core suite](artifacts/tests-v0.4.3-core.txt) reports **988 passed,
2 optional-model skips**. Deterministic checks cover queued and in-progress
classification, muting between logging and playback, controls during a blocked
player, and notification/unmute ordering in the same socket-read batch. Lifecycle
tests cover instance and executable guards, idempotence, older services, and
malformed or unconfirmed state replies.

An isolated Claude plugin install discovers all five skills, including `mute`
and `unmute`; both new skill files pass frontmatter validation. The plugin
wrappers target only their stable runtime, require no uv/dependency setup, reject
unsupported arguments, and propagate failures.

A [fresh-wheel smoke check](artifacts/mute-v0.4.3-smoke.json) uses a private silent
service from an unrelated directory. Mute, repeated mute, unmute, and repeated
unmute preserve the same PID and authenticated instance. A muted hook is dropped;
a fresh notification after unmute is processed without replaying the old one.
Doctor reports intentional mute as informational. Unmuting a stopped service
fails without starting anything. No real user settings or audio output are used.

Mute is in memory for the current service and permits one cue already admitted
to synthesis/playback to finish. It does not cancel playback or claim to measure
device-level silence.

## Intake deadline race, v0.4.2

The v0.4.1 Linux/Python3.13 CI run exposed a scheduling-dependent notification
loss. A 64 KiB repeated-question input took about 205 ms to classify locally, while
accepted peers had a 150 ms intake deadline. If another peer's complete message
arrived during that classification, the listener could expire it before reading.
The natural test passed on rerun, but the controlled sequence reproduced the drop.

The listener now drains bounded ready messages, handles incomplete-client expiry,
and then performs intake classification. Two deterministic regressions advance
the service clock during a paused hint and deliver a small message or a 12 KB
message. Both fail against the previous service and pass with the fix. The
service/security/control group reports **81 passed**. An explicit EOF assertion
confirms incomplete clients still expire; client and message-size limits are
unchanged. The full suite reports **952 passed, 2 optional-model skips**; see
[full core output](artifacts/tests-v0.4.2-core.txt).

## Extended endings, v0.4.1

Following listening feedback, all six elapsed-turn variants now add **0.80 seconds**
with two rising notes and a wider, held final chord. Their durations are 1.75–1.92
seconds. The familiar opening is retained, RMS level stays matched to the short
cue, and the extra time contains audible music rather than trailing silence.
Editable lift/chord voicings live in each state's `long_turn` table.

The focused synthesis and CLI suite reports **59 passed, 1 optional-model skip**.
Tests cover extension length, musical energy beyond the original ending, retained
opening shape, level/headroom, deterministic rendering, configurable voicing,
independent character brightness, and the exported CLI WAV's length. A direct
comparison with the previous renderer confirms all fourteen normal cues remain
sample-identical, both with and without optional brightness. Attention, caveat,
failure, and in-flight cues keep their existing behavior.

[Measured durations and levels](artifacts/long-turn-v0.4.1.json) show RMS near
0.065 and peaks below 0.431 full scale. No blinded perceptual study is claimed.
The service remains opt-in for elapsed-time treatment; no classification or
hook changes are part of this revision.

## Classification boundaries and elapsed-time voicing, v0.4.0

Checked on 2026-09-26 on the same M2 Pro/macOS/Python environment below.
The core suite reports **949 passed, 2 optional-model skips**; see
[core output](artifacts/tests-v0.4-core.txt). A separate offline MiniLM run passes all **13 semantic/CLI integration tests**,
including real model loading and service integration; see
[semantic output](artifacts/tests-v0.4-semantic.txt).

All **115 new synthetic development contrasts** pass, along with all 30 outcome
and 35 existing gesture cases. One existing approval-to-publish gesture label
was deliberately updated to the new authorization subtype; outcomes are unchanged.
The fixtures were written during implementation, not sampled or held out from
private history. No private transcripts were read or included. On these targeted
contrasts the previous rules matched 41/115 outcome labels and 33/115 gesture
labels, with 63 false caveats; current rules match all labels with no false
caveats or missed handoffs. New uncertainty/activity concepts were not supported
by the old classifier. These figures demonstrate development coverage, not
population accuracy or an unbiased estimate of improvement.

Reports: [previous baseline](artifacts/classification-v0.4-baseline.json),
[current comparison](artifacts/classification-v0.4-current.json),
[new fixture evaluation](artifacts/v0.4-classification-vNext.json),
[legacy outcome evaluation](artifacts/v0.4-evaluation.json), and
[legacy gesture evaluation](artifacts/v0.4-gesture-evaluation.json).
The [optional semantic evaluation](artifacts/v0.4-semantic-evaluation.json) matches
110/115 outcomes and gestures, with one false caveat and no false or missed
handoffs. Model-quality limitations are not hidden by passing infrastructure
tests. Rules remains the default.

Current rule classification measured 0.190 ms median and 0.345 ms p95 across the
115 contrasts. A separate 25-notification measurement exercised fresh Python hook
processes, the private socket, warm rules service, and synthesis to samples:
**56.4 ms median, 59.0 ms p95, 62.0 ms maximum**. It excludes WAV writing, audio
player/device onset, and competing traffic; no sound was played. See the
[notification timing report](artifacts/notification-latency-v0.4.json). These are
observations on this Mac, not latency guarantees.

The old eleven cues remain sample-identical under default and optional character
brightness rendering. New verdict and authorization cues have the existing
approximately 0.065 RMS level; in-flight is deliberately quieter at approximately
0.0123 RMS. Longer-turn variants preserve duration and RMS while adding a fuller
voicing; handoffs, feedback, caveats, refusals, and failures remain unchanged.
Headroom, finite samples, deterministic rendering, and quiet endpoints are tested.
The complete demo is now 20.07 seconds. No blind recognition or device-level
loudness study was performed.

Regression checks cover current versus cited links, URL-target exclusion, explicit
verification gaps, optional offers, framed verdicts, background registry presence
and limits, future versus running work, default-silent activity preserving queued
results, duplicate Stop timing, subsequent clean turns, and handoff/result sequences.
A [fresh-wheel smoke check](artifacts/wheel-v0.4-smoke.json) runs from an unrelated
directory using only the installed wheel and NumPy. It covers real quiet hooks,
long-turn config forwarding, suppressed in-flight output, neutral uncertainty,
private-data exclusion from logs, WAV rendering, version identity, and shutdown.
Existing hook input limits, private peer checks, bounded queues, and resident
service behavior remain in place. No per-tool hooks or model dependency were added.

The following sections describe earlier releases and historical measurements.

## Plugin, service management, and failure handling, v0.3.0

Checked on 2026-09-26 on the same M2 Pro/macOS/Python environment as below.
The final core run reports **713 passed, 2 optional-model skips**;
see [test output](artifacts/tests-v0.3-core.txt). A separate run of all seven
semantic tests with the existing offline MiniLM environment passed, including
structured-failure/start-marker bypass checks against the real model.

The installed Claude Code 2.1.158 validated both plugin manifests. An isolated
Claude configuration exercised marketplace installation, a plugin version/cache
update, disable/enable, uninstall, and marketplace removal. It discovered exactly
five hooks and three skills. The real uv bootstrap installed and updated a stable
runtime, and that runtime restarted successfully after its plugin source/cache
directory was deleted. Test paths included spaces. No real Claude settings or
existing service were changed.

A fresh wheel in a separate NumPy-only environment passed detached service
start/status/repeated-start/stop, quiet hook execution, structured failure routing,
demo rendering, and settings init/doctor/uninstall. The macOS LaunchAgent was
also installed and verified through an authenticated socket, reinstalled, and
uninstalled using a unique temporary job and non-editable runtime. Temporary
jobs, files, and processes were cleaned up.

A separate real managed stop/start check confirmed that launchd supervised the
new service instance and its PID matched the authenticated reply. Saved arguments
were unchanged, including a 19-second timing threshold. This caught and fixed a
shutdown race where a plain kickstart could return before scheduling a replacement.

Regression coverage includes private peer authentication, service instance and
executable ownership, refusing other installations, startup readiness/rollback,
saved LaunchAgent configuration, settings backups and exact hook ownership,
credential-free displayed diffs, failure/retry priority, bounded timing state,
threshold boundaries, uncertain timing, and attention-cue exemptions.

Short-turn suppression is opt-in and requires matching prompt IDs; the installed
Claude 2.1.158 lacks them, so it conservatively keeps playing. No live Claude API
failure was induced, no audible device output was measured, and the earlier
latency figures below were not remeasured for 0.3. The updated demo has eleven
cues, 773,760 frames at 48 kHz (16.12 seconds). The added `failed` cue passes the
same deterministic rendering, smooth-envelope, headroom, and level checks.

The remaining sections describe historical releases and measurements.

## Publication hardening, v0.2.0

On 2026-09-26 the client was hardened against an impostor local Unix socket.
Before sending text it validates the direct parent and socket type, owner, and
private permissions, authenticates the connected peer UID, and rechecks endpoint
identity. Rejection tests prove that permissive, foreign, symlinked, replaced, and
unauthenticated endpoints receive no notification payload. The original send
deadline remains shared across validation, connection, and transmission. Processes
running as the same OS user remain inside the trust boundary.

The final local suite reports **560 passed, 2 optional-model skips** in 10.56 s;
the environment with local MiniLM weights reports **562 passed** in 19.73 s.
See [core](artifacts/tests-publication-core.txt) and
[semantic](artifacts/tests-publication-semantic.txt) output. The macOS kernel peer
credential path was exercised against real listeners; the cross-platform CI runs
exercise the matching Linux path as well.

After hardening, 20 fresh hook processes had median 53.55 ms and p95 58.77 ms
through handoff, with no audio playback. The resident socket connect/send p95 was
0.569 ms. These are send-completion timings, not playback acknowledgments; see
[the benchmark](artifacts/benchmarks-publication-core.json). The broader 150-response
palette timings below were recorded before endpoint hardening and retain their
original runtime fingerprint. Classification and synthesis were unchanged.

## Full palette, v0.2.0

Checked on 2026-09-26, Apple M2 Pro, 16 GiB RAM, macOS 26.6 arm64,
Python 3.13.1. The tests and measurements below describe the expanded palette;
sections further down are historical records.

### Tests and package

| Check | Observed result |
| --- | --- |
| Offline core suite | **540 passed, 2 skipped**, 9.88 s |
| Same suite with the existing local MiniLM model | **542 passed**, 16.86 s |
| v0.2.0 wheel in a fresh NumPy-only runtime, from another directory | Demo, review/auth WAVs, classification JSON, structured question dry-run, and gesture evaluation passed |

Recorded outputs: [core tests](artifacts/tests-palette-core.txt),
[optional model tests](artifacts/tests-palette-semantic.txt),
[installed-package smoke checks](artifacts/package-v0.2-smoke.json).
The optional tests include network-blocked real model loading and a foreground
semantic service. New tests cover all gestures, review queue priority, required
actions versus decisions, compound/resolved dependencies, unfinished assessments,
temporary inability versus refusal, and retained validation caveats. Adversarial
long-input tests remain in the suite.

### Development evaluations

| Fixture set and dimension | Rules | Optional semantic frontend |
| --- | ---: | ---: |
| Original 30 outcome fixtures | 30/30 | 24/30 |
| New 35 development outcomes | 35/35 | 34/35 |
| New gesture labels | 35/35 | 34/35 |
| New expectancy labels | 35/35 | 35/35 |
| New delivery labels | 34/34 | 34/34 |

These are regression/development fixtures, **not a fresh held-out accuracy estimate**.
The rules remain the default. The semantic frontend now shares explicit routes,
but its older encoder fallback still calls bare “Done.” a caveat, and misses six
legacy outcomes, including one false completion. Both fixture sets had zero false
attention or refusal selections. Passing them does not establish broad accuracy.

Reports: [rules, legacy](artifacts/evaluation-v0.2-rules-legacy.json),
[rules, gestures](artifacts/evaluation-v0.2-rules-gestures.json),
[semantic, legacy](artifacts/evaluation-v0.2-semantic-legacy.json), and
[semantic, gestures](artifacts/evaluation-v0.2-semantic-gestures.json).

### Latency on this Mac

Measured on the same 150 deterministically selected real assistant responses,
with 40 sequential hook subprocesses per backend against an idle service.
Only aggregate timings are included; raw conversation data is not packaged.

| Measurement | Rules median / p95 | Semantic median / p95 |
| --- | ---: | ---: |
| Resident classification | 1.37 / 4.50 ms | 5.16 / 46.36 ms |
| Hook launch through WAV ready | 58.61 / 69.34 ms | 69.01 / 110.16 ms |

The semantic sample used shared rules for 77 responses and the encoder for 73.
Encoder-only classification p95 was 51.07 ms. Local model construction and anchor
embedding took 4.16 s, excluding module import; this occurs once per service and
is not a cold process-start measurement. Rules require no model setup.

A useful target is under one second to have an idle-service notification ready,
comfortably inside the requested few seconds. These measurements meet that target.
They exclude audio-player launch and audible device latency. No v0.2 audio playback
or burst-load timing was performed. Serialized playback and the eight-second
queue expiry still permit delays/drops in a burst; the longest cue now lasts 1.82 s.
The [full benchmark](artifacts/benchmarks-palette-v0.2.json) records sample sizes,
method, limitations, and an identical runtime/palette fingerprint for both runs.

### Audio

The updated [demo WAV](artifacts/awaitonal-palette.wav) is mono PCM16 at 48 kHz,
708,000 frames, **14.75 seconds**, with ten cues and 350 ms gaps. Cue durations
range from 0.66 to 1.82 seconds. The nine auditioned/revised cues have RMS near
0.065; the retained refusal cue is 0.0482. The largest floating render peak is
0.4084. [Signal measurements](artifacts/palette-v0.2.json) include every cue.

The user auditioned the category sketches and requested the expectant review/auth
revision. This is not a blinded recognition test or a perceptual loudness study.
The integration uses the selected sketches' pitch/timing design. Live hooks have
still not been tested inside an actual Claude conversation, and this work did not
edit Claude settings or install a background service.

## Reliability fix validation

The long-input parsing fix was checked on 2026-09-25, on the same macOS/Python
environment described below. The offline core suite now reports **243 passed,
2 skipped** in 7.95 s; the skips require the optional real model. Rules evaluation
remains **30/30** with no false attention or rejection cases. The older reports
below describe the original v0.1.0 release.

Regression tests cover unmatched link brackets and curly quotation marks,
repeated question prefixes, and long histories of resolved or historical waiting
statements. Extraction/classification tests run adversarial inputs up to the
131,072-character prose limit in subprocesses with a five-second timeout.
Service tests send near-limit 65,536-byte events and verify both their processing
and a subsequent notification from another session within three seconds.

Measured medians of five resident calls, in milliseconds:

| Input | UTF-8 bytes | Prose extraction | Full rules classification |
| --- | ---: | ---: | ---: |
| Unmatched `[` | 65,536 | 2.307 | 11.342 |
| Repeated `which ` | 49,152 | 2.377 | 16.680 |
| Unmatched curly opening quotes | 65,535 | 4.371 | 7.993 |
| Repeated waiting statements, followed by explicit resolution | 63,832 | 3.111 | 13.047 |

The audit measured 10.759 seconds for bracket extraction and 2.794 seconds for
waiting detection on the corresponding inputs before the fix. These are local
wall-clock observations, not latency guarantees. Prose content and existing
priority/deduplication behavior are preserved; no service scheduling changes were
needed.

Run the regressions with `python -m pytest -q tests/test_text.py
tests/test_classify.py tests/test_service.py`.

## Original release validation

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

[Original audition](https://github.com/sindarknave/awaitonal/blob/d031245577834e2b639e03cc8d7989d40daa49c4/artifacts/awaitonal-palette.wav): mono, 48,000 Hz, signed PCM16,
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
