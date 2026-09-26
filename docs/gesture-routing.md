# Gesture routing

Awaitonal separates reported outcome, delivery, human participation, and activity.
Each audible notification selects one gesture. It does not verify the work or
infer success simply because an agent stopped.

## Classification fields

| Field | Values | Meaning |
| --- | --- | --- |
| `state` | `done`, `caveats`, `needs-you`, `rejected`, `failed`, `unknown` | Reported outcome, structured failure, or insufficient evidence. |
| `delivery_kind` | `change`, `answer`, `plan`, `artifact`, `published`, `unknown` | Type of reported deliverable. |
| `expectancy` | `none`, `review-requested`, `required-handoff` | Whether human participation is invited or required. |
| `handoff_kind` | `decision`, `action`, `authorization` | Required choice, action, or approval of prepared outward work. The default `action` has no meaning outside a handoff. |
| `activity` | `final`, `in-flight`, `unknown` | Whether the reply reports a final result or continuing work. This does not verify execution. |
| `assessment_kind` | `none`, `verdict` | A framed assessment of an identified object. |
| `gesture` | Listed below | The selected musical cue, which may be suppressed by service settings. |

`unknown` preserves uncertainty instead of claiming a limitation or success.
Its controls are neutral; callers must retain the state field, because the older
binary controls alone cannot encode uncertainty. Existing positional constructors
remain supported; new fields are appended. Consumers must accept the new state
and gesture IDs. Optional palette overrides still merge with packaged defaults.

## Selecting one cue

Priority is refusal, required handoff, infrastructure failure, feedback request,
reported limitation, in-flight activity, neutral uncertainty, verdict, then delivery.
A required handoff is `decision`, `authorization`, or `needs-you` according to its
subtype. Feedback keeps the compatible `review` identifier and routine priority.
A review request can override the caveat sound while preserving the caveat state.

| Gesture | Meaning |
| --- | --- |
| `done` | A change or operation is reported complete. |
| `answer` | An explanation or answer; also the restrained sound for unknown outcomes. |
| `verdict` | A completed assessment, including a negative assessment. |
| `plan` | A plan or proposal is delivered. |
| `artifact` | A concrete output is delivered. |
| `published` | A successful outward delivery, push, deployment, PR opening, or review posting is reported. |
| `review` | Feedback requested, without a blocking dependency. |
| `decision` | A choice or clarification is required. |
| `authorization` | A prepared outward action currently awaits approval. |
| `needs-you` | Sign-in, evidence, or another action is required. |
| `in-flight` | Work is reported continuing with a follow-up; silent by default. |
| `caveats` | Work or requested validation is explicitly unfinished or limited. |
| `rejected` | The assistant refuses the requested assistance. |
| `failed` | A structured API/infrastructure failure stopped the turn. |

## Boundaries

The rules inspect bounded English assistant prose, excluding code and quotations
where practical. They preserve typed link evidence while removing URL destinations.
URLs are parsed locally, never fetched; query strings and fragments are not
classification evidence. An artifact/PR link needs current delivery wording.
A reference, quotation, historical action, conditional, or negated action does not
establish a new output.

Error vocabulary alone is insufficient for caveats. A completed diagnosis can
discuss failures; “the error handling is fixed” can report a completed fix.
Explicit unfinished work and validation gaps retain caveats. Final text cannot
always reveal whether diagnosing failed tests was the task, or fixing them was.
Unknown preserves that limit rather than making a correctness claim.

A verdict needs assessment framing or an identified assessed object, not a generic
“Yes,” “No,” or “Business Summary” heading. Completed “Approve” assessments must
not be confused with asking the user to approve something. “Saved locally; I can
publish if useful” is an optional offer. “The draft is ready; awaiting your approval
to publish” is a current authorization dependency.

Reported ongoing work is distinct from “I'll run CI,” which promises future work.
Bounded background counts can corroborate a present-running statement. Those counts
are session-wide, so a persistent monitor must not change a delivered artifact into
an in-flight notification. Known empty registries and missing metadata are distinct.
Handoffs and explicit limitations take precedence over a background claim.

## Hooks, timing, and playback

`Stop` supplies final prose and optional bounded active-task/cron counts.
The adapter discards task descriptions, commands, scheduled prompts, and other
free text. It never reads the transcript. `AskUserQuestion` and permission hooks
provide structured handoff evidence; `StopFailure` forwards only a normalized
failure code. `UserPromptSubmit` supplies a timing marker without prompt text.

The service suppresses duplicate waiting or contentless unknown Stop notifications
within the short session/turn deduplication window after a structured handoff.
A real result, feedback request, explicit limitation, refusal, or failure remains
eligible. Distinct questions and expired windows remain independent. This cannot
perfectly distinguish every resolved conversation without its preceding context.

The in-flight pulse is off by default. To audition it: `awaitonal play in-flight`.
Set `[notifications] notify_in_flight = true` to hear classified ongoing reports.

Both timing thresholds default to zero (disabled):

```toml
[notifications]
min_turn_seconds = 30
long_turn_seconds = 120
notify_in_flight = false
```

Pass that file using `--config` to `serve`, `service start`, or `service install`.
Only routine cues can be suppressed by the short threshold or receive the long
variant. Feedback requests, handoffs, caveats, refusals, and failures retain their
normal treatment. Long variants extend done, answer, verdict, plan, artifact, and
published cues by 0.8 seconds with two rising notes and a held, wider ending.
The opening motif stays recognizable at similar RMS level; headroom attenuation
can reduce level. Each cue's `[states.<gesture>.long_turn]` palette table sets the
two `lift` notes and final `chord`. Preview with `awaitonal play verdict --long-turn`.

Timing is matched elapsed turn time, not reasoning duration. It requires supported
prompt IDs (Claude 2.1.196+) and an observed start. Missing IDs, overlapping starts,
restarts, expired timing records, and autonomous follow-ups retain ordinary playback.
The older installed 2.1.158 schema supplies background metadata but lacks prompt IDs.

## Rules and optional embeddings

Both backends share explicit delivery, handoff, limitation, and in-flight routing.
The optional encoder still compares its four original outcome anchor classes;
these variants are not newly trained embedding classes. Ambiguous embedding
scores abstain to `unknown`, with a neutral answer cue. Cosine similarity is not
a calibrated probability. No larger model or additional runtime dependency is
introduced by these changes.

## Development evaluation

Run from the source checkout:

```sh
.venv/bin/awaitonal evaluate --fixtures examples/evaluation.jsonl
.venv/bin/awaitonal evaluate --fixtures examples/gesture-evaluation.jsonl
.venv/bin/awaitonal evaluate --fixtures examples/classification-vNext.jsonl
```

Fixtures are synthetic development examples, not private transcript excerpts or
held-out accuracy estimates. Optional `expected_gesture`, `expected_expectancy`,
`expected_delivery_kind`, `expected_activity`, `expected_assessment_kind`, and
`expected_handoff_kind` labels each have their own denominator and confusion matrix.
Fixtures can supply bounded synthetic `background_tasks` and `session_crons` counts.

Reports contain IDs, labels, scores, timings, false caveats, missed handoffs, and
unknown frequency. A changed distribution alone is not evidence of improved
accuracy. Event-sequence and audio tests cover behavior that prose fixtures cannot.
The new cue distinctions have not been validated in a blind listening study.
