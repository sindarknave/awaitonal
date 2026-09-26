# Gesture routing

Awaitonal separates the reported task outcome from the type of result and the
assistant's request for human participation. Each notification selects **one
gesture, played once**. It does not verify the work or infer success from an agent
stopping.

## Classification fields

Text classification keeps its original four outcomes. Structured API errors add
`failed`, distinct from assistant refusal, with a bounded `failure_code` field.
Delivery and expectancy metadata describe the audio choice.

| Field | Values | Meaning |
| --- | --- | --- |
| `state` | `done`, `caveats`, `needs-you`, `rejected`, `failed` | Reported outcome or structured failure; also controls queue attention. |
| `delivery_kind` | `change`, `answer`, `plan`, `artifact`, `published`, `unknown` | The kind of result the assistant reports delivering. `unknown` means no supported delivery cue was recognized. |
| `expectancy` | `none`, `review-requested`, `required-handoff` | Whether the assistant invites a response or requires participation before continuing. |
| `handoff_kind` | `decision`, `action` | Distinguishes a required choice/clarification from sign-in, approval, or another action. `action` is the neutral default outside required handoffs. |
| `gesture` | See below | The single cue selected for playback. |

For example, a delivered artifact can invite review while retaining a completed
outcome:

```json
{
  "state": "done",
  "delivery_kind": "artifact",
  "expectancy": "review-requested",
  "handoff_kind": "action",
  "gesture": "review"
}
```

`classify --json` includes these fields alongside controls, the evidence source,
the reason, and diagnostics. The plain-text command prints the gesture and
outcome. The service plays the selected gesture and logs routing metadata without
the response text.

## Selecting one cue

The selector applies these rules in order (a structured `failed` outcome always
selects the distinct `failed` cue before delivery/expectancy routing):

1. A `rejected` outcome selects `rejected`.
2. A `needs-you` outcome selects `decision` for a required choice, otherwise
   `needs-you` for the stronger action/approval cue.
3. `review-requested` selects the softer `review` cue.
4. A `caveats` outcome selects `caveats`.
5. A `done` outcome uses its delivery family; `change` and `unknown` use `done`.

| Gesture | Typical report or request |
| --- | --- |
| `done` | A change or operation is complete; also the generic completion fallback. |
| `answer` | An answer, explanation, diagnosis, or completed assessment is delivered. |
| `plan` | A plan, design, or proposal is delivered. |
| `artifact` | A concrete file, render, or other output is available. |
| `published` | A push, release, deployment, or external delivery is reported complete. |
| `review` | The assistant directly invites review or feedback without reporting a blocker. |
| `decision` | Progress requires a choice or clarification. |
| `needs-you` | Progress requires sign-in, authorization, evidence, or another user action. |
| `caveats` | Work or requested validation remains incomplete, or prose is unclear. |
| `rejected` | The assistant refuses the requested assistance. |
| `failed` | A structured API/infrastructure failure stopped the turn. |

These are eight main families plus the softer review invitation, refusal, and
infrastructure failure cues. They are not mutually exclusive claims about a response. For
example, a published change can still require authentication for the next step.
The result retains `delivery_kind = "published"`, but its required handoff chooses
the sound.

A review invitation takes precedence over the caveats sound while preserving
`state = "caveats"` when there is a reported limitation. The notification does not
combine a delivery cue, a caveat cue, and a handoff cue into a sequence.

## Contrasts that matter

| Response pattern | Intended routing |
| --- | --- |
| “Please review the draft and tell me what you think.” | Soft review invitation; routine queue priority. |
| “Please approve the preview so I can publish.” | Required action/approval; attention priority. |
| “Which version should I publish?” | Required choice when it asks for the current next step. |
| “Please complete SSO sign-in so I can continue.” | Required action; attention priority. |
| “The report is available to review whenever useful.” | Passive availability; ordinary artifact cue. |
| A finished setup document describing how users sign in | Delivered document; no current authentication handoff. |
| An earlier authentication request followed by reported successful sign-in | Resolved dependency; use the remaining outcome and delivery. |
| “The audit is complete” followed by a defect finding | Completed assessment; findings do not imply an unfinished repair. |
| A delivered plan followed by “I have not implemented the requested change” | Incomplete requested work; caveats. |
| A delivered plan followed by “I can implement it if you want” | Optional extra work; no required handoff. |

The handoff rules distinguish current requests from quoted examples, documented
instructions, optional offers, historical dependencies, and reported resolutions.
Resolving one dependency does not resolve a separate pending action or erase an
independent testing limitation. These distinctions are heuristic and depend on
explicit wording.

## Structured hooks, queueing, and compatibility

The Claude adapter sends bounded events. Optional `failure_code` carries a
normalized API error type; `kind = "turn-start"` carries timing markers with no
prompt content. It does not send gesture metadata, read a transcript, or add prior
conversation context.

- `Stop` supplies final assistant text for classification.
- `PreToolUse` for `AskUserQuestion` supplies explicit `needs-you` evidence and
  selects `decision`.
- `PermissionRequest` supplies explicit `needs-you` evidence and selects the
  stronger `needs-you` cue.
- `StopFailure` selects `failed` for ordinary API failures, or `needs-you` for
  authentication/account/billing/cloud-credential failures. Raw error text is discarded.
- `UserPromptSubmit` carries only a session/turn start marker for optional timing.

Structured evidence overrides incidental prose. The outcome remains `needs-you`
for both required cues, preserving the existing duplicate suppression and
attention handling. A soft review invitation does not set `needs_you` or receive
attention priority. Required handoffs, refusals, and infrastructure failures do.

Existing event fields, the original four `State` values, and the original `Classification`
constructor arguments remain supported. Consumers must also accept the new `failed`
state, trailing `Controls.failed` field, and failure metadata. `play` additionally accepts the new
gesture IDs; `demo` auditions the full palette. Old palette overrides merge with
the packaged defaults, so an override containing only the original four entries
does not remove the newer entries.

## Rules and optional embeddings

Both backends use the same explicit delivery and handoff routing. The optional
semantic backend reports `diagnostics.backend = "rules-routing"` when it uses
that route; otherwise it retains its four-outcome embedding comparison. The new
delivery families are not newly trained embedding classes.

The classifier sees the final response rather than the preceding user request.
It cannot always tell whether a plan fulfilled the request, whether a diagnostic
instruction is an answer or a blocker, or whether a limitation lies outside the
requested scope. English wording, Markdown extraction, and implicit dependencies
remain limitations. Code-only, quote-only, and empty prose are currently ignored;
formatting can therefore hide an otherwise meaningful delivered result. Unclear
prose still uses the original caveats fallback, which is not a calibrated
confidence estimate. No cue certifies that a build, deployment, or fix succeeded.

## Authored development coverage

[`examples/gesture-evaluation.jsonl`](../examples/gesture-evaluation.jsonl)
contains synthetic development contrasts covering all ten gestures, passive and
direct review, required and resolved authentication, mixed delivery/limitation
cases, and explicit-state overrides. Every row is marked
`"provenance": "synthetic-development"`. These are examples written during
implementation, **not held-out data or a general accuracy estimate**. A high score
shows consistency with these authored cases, not listener recognition or general
language understanding.

Run from the source checkout:

```sh
.venv/bin/awaitonal evaluate --classifier rules \
  --fixtures examples/gesture-evaluation.jsonl
```

Each row keeps the original `expected` outcome. Optional `expected_gesture`,
`expected_expectancy`, and `expected_delivery_kind` labels are scored independently
under `dimensions`, with their own case counts and confusion matrices. A missing
optional label is unscored for that dimension. A correct outcome does not excuse
an incorrect gesture or delivery tag. Reports contain case identifiers, labels,
scores, and timings, rather than response text.

The explicit-state fixture rows test generic overrides. Actual Claude
`AskUserQuestion` versus `PermissionRequest` adaptation is covered by adapter and
gesture unit tests; the fixture evaluator uses an `evaluation` evidence source and
does not simulate those hook-specific sources. Unit tests also cover ignored prose,
queue priority, selected-gesture playback, quiet hooks, and duplicate handling.
