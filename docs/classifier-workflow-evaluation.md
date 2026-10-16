# Workflow classification regressions

The cases in `examples/classification-workflow.jsonl` are authored synthetic
examples supplied alongside an aggregate evaluation of private Claude replies.
No private replies, source identifiers, or transcript-derived excerpts are
included. These cases are development regressions, not a held-out accuracy test.

The rules now recognize:

- A user instruction followed by an explicit assistant continuation, including
  requests whose command contents are removed during prose extraction.
- Permission questions about prepared work as authorization, including posting,
  committing, and applying. Optional offers of unprepared work remain neutral.
- Current recommendations and verdicts, including formatted verdict headings.
- Running imports, timers, and a closing report of checks still being watched.
- Saved named files, paste-ready drafts, and a diagnosis following “Found it.”

An explicitly unverified side point retains the existing caveats behavior.
Quoted/code content remains excluded from prose classification; the handoff
rules use the surrounding instruction and dependency rather than inspect the
command itself. Inline-code filenames still require other artifact evidence.

The supplied `inflight-after-push` case expected a `done` outcome while checks
were still running. The regression preserves the existing `unknown` outcome
contract for ongoing work, with `published` delivery and `in-flight` activity.
The intended audible cue is unchanged. This adjustment is recorded in the case.

Against the v0.8.0 checkout at `48ad797`, the new 17 cases improve from 3/17 to
17/17 outcome matches and 2/17 to 17/17 gesture matches. One baseline case already
had the correct cue but differed on delivery metadata. All asserted fields
match on 1/17 cases before the change and 17/17 afterward. Existing authored
outcome/gesture fixtures retain their previous scores.

Run from the checkout:

```sh
(umask 022; HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -q)
.venv/bin/awaitonal evaluate --fixtures examples/classification-workflow.jsonl
```

Re-score any candidate against the original private 100-reply sample and the
separate targeted 25-reply set in their originating environment. Compare false
attention, missed handoffs, gesture errors, and ambiguous cases separately.
The original report used v0.6.0, so score `48ad797` as a baseline too. Keep labels
frozen and export aggregate results only. A new session-disjoint held-out sample
is needed to measure whether changes generalize beyond the supplied examples.
