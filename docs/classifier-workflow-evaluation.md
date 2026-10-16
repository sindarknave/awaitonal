# Workflow classification regressions

The cases in `examples/classification-workflow.jsonl` are authored synthetic
examples supplied alongside an aggregate evaluation of private Claude replies.
No private replies, source identifiers, or transcript-derived excerpts are
included. These cases are development regressions, not a held-out accuracy test.

The first candidate, `eceabb8`, recognized the supplied examples but did not
generalize well. The originating environment reported outcome agreement of
39/100 to 40/100, gesture agreement of 22/100 to 23/100, and required handoffs
of 2/24 to 3/24 compared with `48ad797`. No predictions changed on the separate
25-reply targeted set. On 20 unshared paraphrases, agreement was 5/20 versus
6/20. False attention remained at three. These are user-reported results; the
private data and scoring harness are unavailable in this checkout.

The next pass combines grammatical evidence instead of matching complete
example phrases:

- User-directed action plus a dependent assistant step in either clause order.
  Adjacency alone is insufficient: the dependency must refer to the action or
  its input/result. Unrelated future work does not make a request blocking.
- Preparation or pending execution plus a permission question or an agreement
  condition, including posting, committing, applying, and saving. Optional
  offers to create unrelated new work remain neutral.
- Current stance, selection, or subject/evaluative-predicate judgments. Reported
  opinions, hypothetical judgments, history, and unavailable assessments remain
  excluded. A clear affirmative go/no-go needs no minimum length or rationale.
- Present activity plus a reporting or completion-dependent follow-up promise,
  without a task-noun allowlist. Passive session monitoring alone does not
  override a delivered result. A direct pending report can override delivery.
- Completed file/draft creation in active, passive, and perfect constructions,
  with file-shaped literals and compound deliverable descriptions. Editing an
  implementation remains a code change.

An explicitly unverified side point retains the existing caveats behavior.
Quoted/code contents remain excluded from prose classification. The extractor
can preserve opaque file, code, and quoted-argument markers so that surrounding
syntax survives without exposing assertions inside a literal. Markers alone
are not evidence of delivery or a user action. Explicitly required feedback
before an assistant can continue is a required handoff, rather than soft review.

The new tests use varied subjects, verbs, clause order, morphology, and nearby
non-matches. Additional synthetic development probes were authored separately
and then used for diagnosis; scores on them are not held-out validation.
Negative completion alone ("hasn't finished") still does not establish that
execution is currently running. These remain English heuristics with limited
reference resolution and adjacent-clause context, not a general semantic parser.

The supplied `inflight-after-push` case expected a `done` outcome while checks
were still running. The regression preserves the existing `unknown` outcome
contract for ongoing work, with `published` delivery and `in-flight` activity.
The intended audible cue is unchanged. This adjustment is recorded in the case.

For the first candidate against the v0.8.0 checkout at `48ad797`, the 17 cases
improved from 3/17 to 17/17 outcome matches and 2/17 to 17/17 gesture matches. One baseline case already
had the correct cue but differed on delivery metadata. All asserted fields
matched on 1/17 cases before the change and 17/17 afterward. This synthetic
success did not predict real-reply improvement. The second candidate retains
those matches and the existing authored outcome/gesture fixture scores.

Run from the checkout:

```sh
(umask 022; HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -q)
.venv/bin/awaitonal evaluate --fixtures examples/classification-workflow.jsonl
```

Re-score any candidate against the original private 100-reply sample and the
separate targeted 25-reply set in their originating environment. Compare false
attention, missed handoffs, gesture errors, and ambiguous cases separately.
Score `48ad797`, `eceabb8`, and the new candidate against the same frozen labels
and export aggregate results only. Keep ambiguous cases distinct. The original
20 unshared paraphrases are partially described by the feedback now; a new
unshared paraphrase set and a session-disjoint real-reply sample are needed to
measure generalization. No private-data improvement is claimed for this pass
until the originating environment re-scores it.
