# Classifier tuning and public-data evaluation

September 27, 2026. Classifier tuning included in v0.7.0, evaluated against v0.6.0
(`284b7f3226a93501158380f0fd175ecc254510f1`).

The changes fix the supplied analysis's concrete regression cases. They do **not**
improve overall agreement with the prediction-blind AI-labeled public sample. The gap
between those results matters: recognizing a handful of additional phrases does
not establish broad semantic understanding.

| Evaluation | v0.6.0 | Tuned rules |
| --- | ---: | ---: |
| Supplied synthetic cases: outcome | 6/16 | **16/16** |
| Supplied synthetic cases: musical gesture | 2/16 | **16/16** |
| Existing outcome fixtures | 30/30 | 30/30 |
| Existing gesture fixtures | 35/35 | 35/35 |
| Existing expanded fixtures: outcome and gesture | 114/115 | 115/115 |
| Fresh public replies: outcome | 66/92 (71.7%) | 66/92 (71.7%) |
| Fresh public replies: musical gesture | 41/92 (44.6%) | 41/92 (44.6%) |

The one changed expectation in the existing fixtures is intentional. A prepared
email followed by “Would you like me to send it?” now requests authorization.
Previously that fixture treated it as an optional offer. Offers to prepare new
work or publish something “if useful” remain neutral.

The supplied cases were used to tune the rules; their perfect score is a
regression result, not a held-out accuracy estimate. Three supplied in-flight
cases retain Awaitonal's existing coarse `unknown` state, rather than the analysis's
proposed `done` label. Their requested in-flight activity and gesture are preserved.

Changes cover:

- Supported Business Summary verdicts, including approval and negative recommendations.
- Current artifact delivery phrased as “republished” or “fixed — same URL,” and artifact readiness.
- “PR is up” as publication, with guards against “up to date” and reference links.
- Current running work followed by a closing promise to report or read its result.
- Direct outward-action confirmations after prepared work, including later permission, publication, or cancellation resolving them.
- The assistant reporting that it was blocked from completing its own work.

Regression tests also cover hypothetical requests, documentation, negation,
historical activity, optional offers, and resolved dependencies. These classifier
changes introduce no new model or runtime dependency. The separate musical-variation
feature is described in [gesture variations](gesture-variations.md).

The public evaluation uses
[misterkerns/my-personal-claude-code-data](https://huggingface.co/datasets/misterkerns/my-personal-claude-code-data),
revision `e6aff5fa4941ef1cbfcbca7bf09ac04506d22691`. Its raw conversation file has SHA-256
`dae70421f20da2f1f68fd307a89aedca8c3f5136c21d8604037db124d854093d`.

The existing extractor produced 5,728 terminal-text candidates across 489 sessions.
We excluded the 80 sessions in our earlier development sample, then selected 100
of the remaining 409 sessions by deterministic hash ranking, with one independently
hash-ranked reply per selected session. There is no session or exact-text overlap
with the earlier sample. These are final-message boundary proxies, not recorded
Stop-hook payloads.

Two AI agents labeled separate halves using the final reply and preceding public
user context, before seeing classifier predictions. One labeler had authored the
activity-rule changes; this is prediction-blind labeling, not an independent human
annotation study or a double-label agreement study. Runtime classification sees
only the final reply. Ten preceding contexts were truncated by extraction.

The fixed sample included eight provider usage-limit/error banners without assistant
prose. They were retained in the sample metadata and excluded from prose scoring,
leaving 92 replies. Twenty-five eligible replies have explicitly recorded label
ambiguity. Neither the code nor labels changed after predictions were revealed.

| Sensitivity check, identical for both versions | Outcome | Gesture |
| --- | ---: | ---: |
| Only 67 unambiguous replies | 48/67 (71.6%) | 33/67 (49.3%) |
| Accept predeclared alternative labels on all 92 | 68/92 (73.9%) | 49/92 (53.3%) |

The sample is heavily skewed toward completed work: 85/92 outcome labels are `done`.
An always-done outcome baseline would score 92.4%; the most common gesture, also
`done`, accounts for 34/92 (37.0%). These are context for interpreting the scores,
not useful notification policies. The rules abstain to `unknown` on 21/92 replies.
There is one false attention request and no false caveat alerts. There are no
labeled required handoffs, so this sample cannot estimate handoff recall or validate
the new authorization behavior in real conversations.

The biggest remaining gesture gap is assessment language: all 21 labeled verdicts
fall back to answer/done. Four of five plans, all four artifacts, and four of five
caveat cases also miss their intended gesture. Of 85 completed outcomes, 19 become
unknown. These findings suggest broader recognition of intent and implicit completion
is the next useful experiment. Human review of the disputed labels should precede
using this benchmark to select or train a local semantic classifier.

Across all 5,728 **unlabeled** cached candidates, just one reply changes routing:
unknown/answer becomes done/published. This measures behavior change, not accuracy.
It also shows that the supplied analysis's phrases are uncommon in this different
contributor's export.

Warm classifier-only timing on this Apple M2 Pro MacBook with 16 GiB memory:

| Timing over 5,728 replies | v0.6.0 | Tuned rules |
| --- | ---: | ---: |
| Median | 1.49 ms | 1.72 ms |
| 95th percentile | 6.26 ms | 7.21 ms |
| 99th percentile | 13.02 ms | 15.31 ms |
| Maximum observed | 31.50 ms | 35.66 ms |

Each version ran in a separate interpreter with the source tree explicitly selected
and 128 warm-up calls. Timing excludes import/startup, hook transport, synthesis,
and playback; this is not an end-to-end notification benchmark or a worst-case
latency guarantee. At the classifier-only snapshot, the full Python suite passed
**1,758 tests**, with two optional local-model checks skipped, in 38.56 seconds.
Later music and packaging checks are recorded separately in
[release validation](../VALIDATION.md).

Machine-readable [comparison and frozen hashes](../artifacts/classification-v061-public-evaluation.json),
[reconstructable public labels](../artifacts/classification-v061-public-labels.json),
and [test results](../artifacts/classification-v061-validation.json) accompany this report.
The label file identifies public source row/message coordinates, text/session hashes,
eligibility, and alternatives. It contains no transcript text, prompts, or original
session IDs. Raw conversations and labeling rationales remain outside the repository.
The synthetic regressions are in [classification-v061.jsonl](../examples/classification-v061.jsonl).
