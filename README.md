# Awaitonal

**Hear how your agent left things.**

A small local musical notification engine for coding agents. Composed gestures
distinguish changes, answers, plans, artifacts, publication, and human handoffs.
This does not verify the agent's work, generate music
from text, or send response text to a cloud service.

## Hear it

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/). macOS uses the built-in
`afplay`; rendering, classification, and tests require no audio device. The only
core runtime dependency is NumPy.

From this directory:

```sh
uv sync --dev
uv run awaitonal demo
uv run awaitonal demo --out palette.wav
uv run awaitonal play done
uv run awaitonal play answer
uv run awaitonal play plan
uv run awaitonal play artifact
uv run awaitonal play published
uv run awaitonal play review
uv run awaitonal play decision
uv run awaitonal play caveats
uv run awaitonal play needs-you
uv run awaitonal play rejected
uv run awaitonal play verdict
uv run awaitonal play authorization
uv run awaitonal play in-flight
uv run awaitonal play answer --long-turn
```

`--out` renders without playback; `play` accepts it too. Neither audition command
requires a service or classifier. A ready-made [audition WAV](artifacts/awaitonal-palette.wav)
plays the gestures in this order with 350 ms gaps:

| Gesture ID | Meaning and sound | Duration |
| --- | --- | --- |
| `done` | Change/completion: descending notes settle into a chord | 1.08 s |
| `answer` | Answer, finding, or assessment: a quick upward figure | 0.95 s |
| `plan` | Plan/proposal: four measured steps | 1.10 s |
| `artifact` | Output ready to inspect: an arpeggio blooms | 1.12 s |
| `published` | Result delivered externally: two broad chord strikes | 1.12 s |
| `review` | Feedback requested: a suspended opening and hanging A4 → B4 | 1.52 s |
| `decision` | Required choice/clarification: taps and a rising question | 1.13 s |
| `needs-you` | Sign-in, approval, or needed action: knocks, a pause, then A4 → B4 | 1.82 s |
| `caveats` | Partial result/limitation: an uneven unresolved descent | 1.10 s |
| `rejected` | C4–F♯4, two dry taps | 0.66 s |
| `failed` | API/infrastructure failure: three low descending dyad pulses | 1.02 s |
| `verdict` | Completed assessment: a compact, firm ending | 0.98 s |
| `in-flight` | Continuing work: a very quiet unresolved pulse (silent by default) | 0.54 s |
| `authorization` | Prepared outward action awaits approval: an expectant tail | 1.38 s |

In-flight notifications are silent by default; `play` and
`demo` let you audition them. Each audible notification plays one gesture once.

All sound settings live in [palette.toml](src/awaitonal/palette.toml): pitches,
timings, envelopes, partials, headroom, gain, and routing threshold. Use
`--config my-palette.toml` on `demo`, `play`, `classify`, or `serve` for a partial
override. Tables merge; event arrays replace the entire state's event list. For
example:

```toml
[synth]
master_gain = 0.18

[synth.brightness]
enabled = true
```

Brightness is disabled by default. When enabled in the service, response character
count increases upper partials with a bounded, saturating curve. Duration stays
fixed and energy is matched to the unmodified gesture; emergency peak attenuation
may reduce level. Rich chords use voice-energy normalization. All oscillators are
deterministic, partials above Nyquist are omitted, and cosine ramps prevent hard
onsets and releases. WAV output is mono PCM16 at 48 kHz by default.

The palette follows the auditioned gesture sketches, including the expectant review
and authentication revision. Distinguishability has not been measured in a blinded
listening study.

## Classify and run

```sh
uv run awaitonal classify --text "Done. Integration tests were unavailable." --json
uv run awaitonal classify --text "Please review the draft and tell me what you think." --json
uv run awaitonal classify --text "Please complete SSO sign-in so I can continue." --json
uv run awaitonal serve --classifier rules
```

For a managed background process, use:

```sh
uv run awaitonal service start
uv run awaitonal service status
uv run awaitonal doctor
uv run awaitonal service stop
```

On macOS, `awaitonal service install` enables a per-user login service;
`awaitonal service uninstall` removes it. Use a stable installed executable, such
as the plugin runtime below, before enabling login startup. `serve` remains the
foreground mode; Ctrl-C stops it. In another terminal:

```sh
uv run awaitonal notify --text "Which database should I use before proceeding?"
```

`notify` reports errors when the service is absent. Normal hooks silently return
success instead. `serve --silent` exercises classification and diagnostics without
playing audio. Setup is explicit; notification hooks never install dependencies
or start the service. The listener remains local to your account.

The core controls are `loose_ends` in [0,1], `needs_you`, `rejected`, and `failed`.
Known outcomes route deterministically: rejection first, then waiting, failure,
then caveats at or above the configured threshold (default 0.5), otherwise done.
Text classifiers use coarse
loose-end values 0 or 1; neither similarities nor controls claim calibrated
probability. Text outcomes include `done`, `caveats`, `needs-you`, `rejected`,
and `unknown`; structured infrastructure errors add `failed`. `unknown` is
uncertainty, not a claim of success, and uses the neutral `answer` cue.
Classification also returns `delivery_kind`, `expectancy`, `handoff_kind`,
`assessment_kind`, `activity`, and the selected `gesture`.
Playback uses `gesture`; queue attention uses the outcome. A direct review request
gets `review-requested` and the softer cue without claiming a blocking dependency.
Required sign-in, approval, choices, and needed evidence get `required-handoff`.

Structured question/permission evidence bypasses textual inference. Rules examine
only the assistant's current prose, filtering Markdown code and quotes where
practical. Passive review availability and completed guides describing login steps
do not imply a current handoff. An explicit request to review and respond does,
even when work is not blocked. A pending approval still matters after tests pass.
Completed assessments can report defects without becoming unfinished repairs.
Optional offers do not imply waiting, and recovered failures do not imply refusal.
Unclear prose retains `state = "unknown"`; empty/code-only input and malformed events
are ignored. Discussing an error does not itself establish unfinished work.
Delivered artifact and PR links require current delivery wording, not just a URL.
A verdict requires an assessment frame or assessed object; an ordinary yes/no
answer is not enough. Ongoing work is separate from a future plan or optional offer. Rules are intentionally small English-language heuristics; Markdown
extraction and semantic interpretation are imperfect. The classifier sees the final
response, not the preceding user request, so task scope and implicit dependencies
can remain ambiguous. This update adds a deterministic baseline, not a trained
classifier or a claim of general accuracy. See [routing details](docs/gesture-routing.md).

The listener uses a private Unix socket at `/tmp/awaitonal-<uid>/service.sock`, a
0700 directory, a 0600 socket, and a single-instance lock. Override with
`--socket PATH` on service/client/hook or `AWAITONAL_SOCKET`; a custom parent
directory must also be owned by you and mode 0700. Hook input is capped at 64 KiB
and 150 ms. Before sending response text, the client verifies the private directory,
socket ownership and permissions, and connected peer's user ID. Symlinked endpoints
and untrusted listeners are rejected; normal hooks discard those notifications
silently. This boundary separates OS users, not processes under your own account.
Socket connect/send has an 80 ms total deadline. The hook never waits
for classification or playback. These are I/O bounds, not guarantees about OS
process-start latency.

Playback is serialized. The default queue holds eight events, drops notifications
older than eight seconds, coalesces obsolete events, and favors attention over
routine completion. Duplicate suppression lasts two seconds and includes session
and available turn identifiers. On older Claude versions without prompt IDs, very
rapid identical turns cannot always be distinguished; this limitation never becomes
permanent suppression. No queue or response text is persisted. Default service
stderr contains outcome/gesture metadata, evidence sources, timings, and error class
names only. Soft review invitations have routine queue priority; required handoffs
and refusals have attention priority. Longer cues can increase delay during bursts.

## Elapsed-time and background treatments

These optional settings work with the resident service:

```toml
[notifications]
min_turn_seconds = 30
long_turn_seconds = 120
notify_in_flight = false
```

Pass the file with `serve --config PATH` or `service start --config PATH`.
Defaults are zero for both thresholds and false for the background pulse.
Short-turn suppression keeps handoffs, feedback requests, caveats, refusals, and
failures audible. The long-turn variant slightly fills out a routine result's
existing motif at matched energy and unchanged duration. Preview it with
`awaitonal play verdict --long-turn`. The in-flight pulse is independent of timing.

Timing means elapsed user-waited time, **not model thinking duration**. It requires
matching prompt-start/stop IDs (Claude 2.1.196+); missing or ambiguous timing leaves
the ordinary treatment intact. Autonomous follow-ups cannot inherit an old wait.
The installed 2.1.158 schema supports background-task metadata but lacks prompt IDs.

Stop metadata contributes only bounded background-task and scheduled-task counts;
commands, task descriptions, and scheduled prompts are discarded. Counts corroborate
an ongoing-work reply, rather than turning every result with a background monitor
into a waiting cue. No hooks are added to every tool call.

## Connect Claude Code

The Claude Code plugin and marketplace live in this repository:

```sh
claude plugin marketplace add sindarknave/awaitonal
claude plugin install awaitonal@awaitonal
```

Then run `/awaitonal:setup` in Claude Code to install the runtime and start the
service. `/awaitonal:status` diagnoses setup; `/awaitonal:uninstall` removes the
plugin-owned runtime. See [plugin setup and migration](docs/plugin.md), including
how to remove old manual hooks without duplicate sounds. Updating the plugin
requires rerunning setup to update its stable Python runtime.

For standalone hooks, `awaitonal init` previews the settings diff;
`awaitonal init --apply` backs up and installs owned handlers. `awaitonal uninstall
--apply` removes only those handlers. Both accept `--settings PATH` for an explicit
Claude settings scope. Existing manually pasted snippets need an explicit
`--legacy-executable /absolute/path/to/awaitonal` to migrate them.

Installed Claude **2.1.158** and the current [official hook reference](https://code.claude.com/docs/en/hooks)
were checked on 2026-09-25. The adapter handles:

- `Stop`: classify `last_assistant_message` if supplied; never infer success from stopping.
- `PreToolUse` matched to `AskUserQuestion`: explicit `needs-you`, `decision` gesture.
- `PermissionRequest`: explicit `needs-you`, stronger waiting gesture.
- `StopFailure`: structured API failure; account/authentication problems need user
  action, other errors play a distinct `failed` cue. Error prose is discarded.
- `UserPromptSubmit`: timing metadata only; prompt text is discarded.

It suppresses `agent_id` subagent events and installs no `SubagentStop` hook. Missing
final text is ignored; transcripts are never opened. `prompt_id` is used when
present, but requires Claude 2.1.196+ and is absent on the installed version.

```sh
uv run awaitonal hook claude --dry-run < examples/claude-stop.json
uv run awaitonal hook claude --dry-run < examples/claude-question.json
uv run awaitonal hook claude < examples/claude-stop.json
uv run awaitonal hook-config > examples/claude-hooks.local.json
```

Optional short-turn suppression uses `[notifications] min_turn_seconds = 30` in a
TOML config, or `serve/service start --min-turn-seconds 30`. It is off by default.
Only routine completed-result cues are suppressed; review, caveats, handoffs,
refusals, and failures remain audible. Timing must match a known turn ID. Missing
or ambiguous timing, including older Claude versions without `prompt_id`, plays
normally. Restarting the service loses its bounded in-memory timing map.

The generated `examples/claude-hooks.local.json` settings fragment uses the
installed executable's absolute, shell-quoted path, so it works from another
project. **Review and manually merge** the five groups into your chosen Claude
settings' `hooks` object. Do not overwrite existing settings. Regenerate after
moving the checkout or its environment. A [portable template](examples/claude-hooks.template.json)
and [detailed installation/removal notes](docs/claude-hooks.md) are included.
The generated local fragment is intentionally excluded from version control and packages.

Normal hook execution has empty stdout/stderr and exits 0 even for invalid input
or a missing service. It emits no permissions, decisions, prompts, or feedback.
`--dry-run` is explicitly diagnostic and must never appear in installed hooks.
The settings omit `async`: only the short handoff runs in the hook; the service
does the work separately.

## Optional local embeddings

**Experimental:** use rules for the initial installation. The original v0.1 encoder
scored 13/30 on the included fixtures, and a later exploratory real-conversation
sample exposed substantial classification errors in both backends. Those historical
scores do not describe the updated router. The fixtures are now regression material,
not a fresh held-out accuracy estimate. Historical [encoder results](artifacts/evaluation-semantic.json)
are retained for reference.

Both backends now share explicit delivery and handoff rules. The semantic backend
uses these recognized routes first (`diagnostics.backend = "rules-routing"`), then
falls back to its original four-outcome embedding comparison for unrecognized prose.
It still requires local model weights and loads them once at startup.

Install optional dependencies, then explicitly download weights once:

```sh
uv sync --dev --extra semantic
uv run --extra semantic awaitonal model-setup --model-dir .models/all-MiniLM-L6-v2
```

The model is [`sentence-transformers/all-MiniLM-L6-v2`](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2),
distributed under Apache-2.0 by the Sentence Transformers project. It uses a
384-dimensional sentence representation and a 256-word-piece default context
window. See the [Sentence Transformers documentation](https://sbert.net/docs/sentence_transformer/usage/efficiency.html)
for runtime options. This implementation uses PyTorch on CPU with
`trust_remote_code=False`. Optional dependencies include Sentence Transformers,
Transformers, and PyTorch; they are not required by rules, hooks, demos, or rendering.

After setup, use the already-installed environment directly for guaranteed offline
startup (no package-manager resolution on hooks):

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/awaitonal serve \
  --classifier semantic --model-dir .models/all-MiniLM-L6-v2

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/awaitonal classify \
  --classifier semantic --model-dir .models/all-MiniLM-L6-v2 \
  --text "I need your approval before continuing." --json
```

The constructor requires a local model directory and uses `local_files_only=True`.
Missing weights produce an explicit setup error. The service loads and embeds
anchors once, keeping the model warm. The hook has no model download or ML import
path. Without `--model-dir`, the default is
`~/.cache/awaitonal/all-MiniLM-L6-v2`, overridable with `AWAITONAL_MODEL_DIR`.

Editable [anchors.json](src/awaitonal/anchors.json) has multiple positive and
negative examples per class, separate from [evaluation fixtures](examples/evaluation.jsonl).
[semantic.toml](src/awaitonal/semantic.toml) controls thresholds and margins; pass
`--semantic-config PATH` to override it. Its `anchors` path is relative to that file.

The backend tokenizes without truncation, reserves conclusion windows, selects
salient contexts with neighboring recovery clauses, then fills remaining slots
with coverage windows. Each selected window is rechecked against the encoder's
word-piece limit. Selection is capped at eight windows of 224 tokens by default;
diagnostics disclose omitted-token counts. It does not embed an entire transcript.

For each class, a window score is 75% best-anchor similarity plus 25% mean of the
top three. The class score is 65% conclusion score plus 35% strongest-window score.
The winner must exceed an absolute threshold and runner-up margin. Attention and
rejection additionally need stricter thresholds and a margin over negative anchors.
Uncertain results retain `unknown` and use the neutral answer cue. Cosine similarity measures resemblance to examples,
not probability or whether the coding agent is correct.

## Tests, evaluation, and timings

Core install, no ML weights or audio device:

Run evaluation from the source checkout, or supply `--fixtures PATH` when using a
standalone installed wheel; evaluation fixtures are distributed with the source.

```sh
uv sync --dev
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -q
.venv/bin/awaitonal evaluate --classifier rules
.venv/bin/awaitonal evaluate --fixtures examples/gesture-evaluation.jsonl
.venv/bin/awaitonal evaluate --fixtures examples/classification-vNext.jsonl
.venv/bin/python tools/benchmark.py
```

After the explicit semantic setup:

```sh
HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  AWAITONAL_TEST_MODEL="$PWD/.models/all-MiniLM-L6-v2" \
  .venv/bin/python -m pytest -q

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/awaitonal evaluate \
  --classifier semantic --model-dir .models/all-MiniLM-L6-v2

HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python tools/benchmark.py \
  --model-dir .models/all-MiniLM-L6-v2
```

Tests cover routing precedence, prose contrasts, model input budgets, explicit-event
overrides, malformed input, quiet notification-only hooks, blocked stdin, absent
service, concurrent sessions, bounded queues, duplicates, safe shutdown, real
offline encoder loading when weights exist, and audio properties. The real-model
test blocks network connections. Without its dependencies/weights it is explicitly
skipped; stubbed encoder tests alone do not validate model quality.

Gesture fixtures are authored development contrasts, including direct versus passive
review, active versus documented authentication, delivery types, and explicit-state overrides.
Optional gesture, expectancy, delivery, activity, assessment, and handoff labels
get separate evaluation denominators and confusion matrices. Reports also identify
false caveats, missed handoffs, and the fraction of unknown outcomes. A correct outcome alone
does not count as a correct gesture. Evaluation output contains IDs and labels only.

[VALIDATION.md](VALIDATION.md) records observed runs, audio properties, confusion
matrices, timing reports, and unverified behavior. Benchmarks distinguish fresh
process launches, warm resident classification, and socket connect/send. Semantic
timings identify shared-rule routing separately from encoder fallback. Cache state
and OS scheduling are uncontrolled; measurements are not latency promises.

## Disable and remove

Stop the foreground service with Ctrl-C to silence Awaitonal. To disconnect Claude,
remove only the handlers invoking `awaitonal hook claude`, preserving other hooks,
then restart the Claude session. Delete the checkout/virtual environment and any
model directory when no longer needed. The private socket directory may retain an
empty lock file; it can be removed after the service has stopped. Nothing is added
to startup settings or installed globally.

## Small code map

- `adapter.py` and `client.py`: bounded event adaptation and quiet hook handoff.
- `text.py`, `classify.py`, `semantic.py`: prose extraction and outcome classification.
- `delivery.py`, `handoff.py`: reported delivery and conversational expectancy.
- `types.py`: semantic controls and deterministic state mapping.
- `palette.toml`, `config.py`, `synth.py`, `playback.py`: instrument and local audio.
- `service.py`, `cli.py`: serial worker, private socket, and commands.
- `evaluation.py`, `tools/benchmark.py`: independent evaluation and actual timing.

Only the Claude adapter is implemented. There is no browser UI,
cloud account, API key requirement, or GPU requirement. The same-repository Claude
plugin and optional managed background service are installed explicitly.

## License

Awaitonal's code, documentation, and included audio assets are available under
the [MIT License](LICENSE). Third-party dependencies and optional model weights
retain their own licenses.
