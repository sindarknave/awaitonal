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

The second candidate, `1a4e700`, improved the reported random-sample gesture
agreement to 33/100 and caught 7/24 required handoffs, but played 14 attention
cues, seven incorrectly. It caught 14/39 assessments and added five assessments
absent from the labels, two on ambiguous cases. A fresh 28-case paraphrase set
improved from 8/28 to 14/28; a targeted 25-reply set improved from 3/25 to 4/25
gesture matches. These results motivated a precision pass before installation.

The precision candidate, `2dbe6b4`, met the originating environment's precision
goal: gesture agreement reached 35/100 and outcome agreement 47/100. It played
seven attention cues, five correctly, compared with three false cues in the
v0.8.0 baseline. Required handoffs fell from 7/24 to 5/24: three previously caught
handoffs were lost and one was newly caught. Assessment coverage and the same
five unlabeled assessments were unchanged. The targeted set reached 5/25 gesture
matches, and a fresh 27-case probe set reached 19/27 versus 13/27 for baseline.
All nine negatives in that fresh set were clean. These are user-reported
aggregates, not results reproduced from private replies in this checkout.

The classifier combines grammatical evidence instead of complete example
phrases:

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

The precision pass applies user ownership and assistant-dependency checks to
all textual request paths, including older choice/need patterns. Explicit
current requests and prepared-work permission questions remain supported.
Reader advice about which option to pick, what to verify with an owner, or
what to check before relying on an answer is not a gate for the assistant.
Selection prerequisites retain the decision kind rather than becoming a
generic action request.

The following recall pass separates independently addressed requests from
neighboring status, review, or limitation clauses. A genuine dependency can
therefore survive a nearby caveat or optional review invitation. Leading
optional conditions still govern their requests; unrelated process completion
does not establish a dependency on reader advice. Prepared-work authorization
also recognizes the user's judgment as a condition for execution. Questions
with an explicit assistant dependency and explicitly needed preferences retain
the decision kind. New generic interrogatives require that dependency; actor
inversion alone can introduce rhetorical or informational questions. Finite
requirements preserve their actor through adverbs, and purpose-led requests can
link supplied input to its promised use. Passive prerequisites can identify the
assistant as their beneficiary, linked to the requested input by a repeated
noun or local reference. Ordinary descriptions of sample data
do not open an indefinite document-body scope. Present process declarations do
not count as bare user commands.

`response_prose` separates explicitly presented draft/document bodies from
the response wrapper before quotation and code extraction. Body instructions
and assessments are not current requests or verdicts. Quoted/fenced body ends
and explicit returns to the conversation preserve later wrapper requests.
Artifact locations, including links on a following line, retain their evidence.
Detector callers that have already performed scope extraction must pass
`response_scoped=True` to avoid interpreting an extracted wrapper twice.

Current process waits and pending completion with a definite follow-up can
produce in-flight without inventing user involvement. Independent unverified
or unfinished work remains a caveat. Only the primary process assertion is
eligible for pending-completion normalization; multiple named work items are
treated conservatively without reliable coreference. Verdict detection also
distinguishes current assessment from procedural advice, and supports softened
stance, appearance predicates, and an assessment's main clause after its topic.

The recall pass extends current process grammar to queue states and unfinished
return/completion states, paired with a definite handback in either order.
Passive reports must be direct assertions, with negated, reported, and explicit
third-party promises excluded. A queued operation explicitly waiting for the
user remains a human dependency. Standalone future promises still do not
establish current work. End-to-end contrasts check that independent incomplete
verification remains a caveat and user gates retain priority over process waits.
An affirmative follow-up's temporal completion condition is extracted once and
shared with outcome routing. For example, pending checks within that future
condition do not independently assert omitted verification; limitations outside
the condition retain their priority. Completion-state transitions and
assistant-owned coordinated monitoring/report promises use the same scope.
Current status can precede its subject in a heading or inverted assertion.
Completion-relative follow-ups and definite promises of delivery to the user
also require current process evidence; user actions and other people's reports
do not supply that handback.

The new tests use varied subjects, verbs, clause order, morphology, and nearby
non-matches. Additional synthetic development probes were authored separately
and then used for diagnosis; scores on them are not held-out validation.
In this recall pass, the initial edits matched `2dbe6b4` at 26/48 on one
independently authored set. A second independently authored set also initially
matched baseline at 27/36. Both sets were then inspected to identify missing
grammatical roles and scopes, so they are now development inputs. They do not
provide an independent final generalization score. Local synthetic labels also
have not been adjudicated against the originating environment's label policy.
After diagnosis, the final candidate matched the specified expectations on
35/48 and 30/36 cases, respectively. All 24 negative cases remained clean.
These numbers describe development coverage only. Nonverbal progress reports
and some handoff subtypes remain incomplete; assessment coverage still needs
the originating environment's evaluation.
Negative completion alone ("hasn't finished") still does not establish current
execution without a definite pending follow-up. These remain English heuristics
with limited reference resolution and adjacent-clause context, not a general
semantic parser. Unmarked document bodies and context-dependent advice remain
ambiguous; no private false-alarm reduction is established by these tests.

The supplied `inflight-after-push` case expected a `done` outcome while checks
were still running. The regression preserves the existing `unknown` outcome
contract for ongoing work, with `published` delivery and `in-flight` activity.
The intended audible cue is unchanged. This adjustment is recorded in the case.

For the first candidate against the v0.8.0 checkout at `48ad797`, the 17 cases
improved from 3/17 to 17/17 outcome matches and 2/17 to 17/17 gesture matches.
One baseline case already had the correct cue but differed on delivery metadata. All asserted fields
matched on 1/17 cases before the change and 17/17 afterward. This synthetic
success did not predict real-reply improvement. Later candidates retain those
matches and the existing authored outcome/gesture fixture scores.

Run from the checkout:

```sh
(umask 022; HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 .venv/bin/python -m pytest -q)
.venv/bin/awaitonal evaluate --fixtures examples/classification-workflow.jsonl
```

Re-score any candidate against the original private 100-reply sample and the
separate targeted 25-reply set in their originating environment. Compare false
attention, missed handoffs, gesture errors, and ambiguous cases separately.
Score `48ad797`, `eceabb8`, `1a4e700`, `2dbe6b4`, and the new candidate against the same frozen labels
and export aggregate results only. Keep ambiguous cases distinct. The original
20-, 28-, and 27-case paraphrase sets are partially described by the feedback now; a new
unshared paraphrase set and a session-disjoint real-reply sample are needed to
measure generalization. No private-data improvement is claimed for this pass
until the originating environment re-scores it.
