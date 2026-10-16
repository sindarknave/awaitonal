"""Synthetic delivery contrasts; these fixtures do not estimate model quality."""
import subprocess
import sys

import pytest

from awaitonal.delivery import detect_assessment, detect_delivery
from awaitonal.text import assistant_prose


@pytest.mark.parametrize("prose,expected", [
    ("I fixed the focus bug.", "change"),
    ("I've now refactored the parser and updated its tests.", "change"),
    ("Added a missing import.", "change"),
    ("The migration is complete.", "change"),
    ("The query has been corrected.", "change"),
    ("The issue is fixed.", "change"),
    ("Summary of changes:\nAdded error handling and a retry limit.", "change"),
    ("I created a helper for reading reports.", "change"),
    ("Here is my analysis: the cache uses a stale key.", "answer"),
    ("The root cause is a missing event listener.", "answer"),
    ("The parser returns a separate result for each input.", "answer"),
    ("I found a mismatch between the two signatures.", "answer"),
    ("The audit is complete. Findings include three access-control gaps.", "answer"),
    ("No, this setting only affects local rendering.", "answer"),
    ("Here is the plan: add a checksum, validate it, then deploy.", "plan"),
    ("I recommend a shared cache with a bounded lifetime.", "plan"),
    ("Implementation plan:\n1. Add a converter.\n2. Test the output.", "plan"),
    ("I wrote a proposal for the migration.", "plan"),
    ("The plan is ready for review.", "plan"),
    ("I exported the spreadsheet.", "artifact"),
    ("Saved the CSV for download.", "artifact"),
    ("Your presentation is ready.", "artifact"),
    ("Here is the PDF with the requested comparisons.", "artifact"),
    ("I created a diagram of the architecture.", "artifact"),
    ("The requested video has been rendered and opened.", "artifact"),
    ("The spreadsheet has been generated.", "artifact"),
    ("The report has been written.", "artifact"),
    ("The chart has been saved.", "artifact"),
    ("The archive was exported.", "artifact"),
    ("The images were rendered.", "artifact"),
    ("Requested video output:\nRendered and opened.", "artifact"),
    ("Requested spreadsheet output:\nGenerated and saved.", "artifact"),
    ("Rendered and opened the requested video.", "artifact"),
    ("I deployed the service.", "published"),
    ("Pushed the reviewed commits.", "published"),
    ("The release is now live.", "published"),
    ("The package has been published.", "published"),
    ("v2.3.0 is live.", "published"),
    ("I updated the parser and published the release.", "published"),
    ("Authentication succeeded, and I implemented the fix.", "change"),
    ("Authentication succeeded, and we exported the spreadsheet.", "artifact"),
    ("Authentication succeeded, and I've pushed the commits.", "published"),
    ("I fixed the query. I exported the CSV.", "artifact"),
    ("I rendered the video. I uploaded it to the release.", "published"),
])
def test_positive_delivery_cues(prose, expected):
    assert detect_delivery(prose) == expected


@pytest.mark.parametrize("prose", [
    "I plan to deploy the service.",
    "I will publish the release.",
    "I have not deployed the service.",
    "I never pushed those commits.",
    "The package has not been published.",
    "The release is not live.",
    "If the release is published, users can install it.",
    "Once the service is deployed, the endpoint will work.",
    "The docs say the release is live.",
    "This example says I published a package.",
    "I deployed the service yesterday.",
    "Previously I published the release.",
    "I pushed this branch last week.",
    "I published the package in 2023.",
    "I deployed the service on Monday.",
    "No release has been published.",
    "I published no release.",
    "Published packages include metadata.",
    "Released versions are supported for a year.",
    "Updated docs explain the publication process.",
    "The proposed release is live in the example.",
    "The release is live in the example.",
    "Example:\nI deployed the service.",
    "Expected output:\nThe release is now live.",
    "I created a report in the previous session.",
    "I will generate a spreadsheet.",
    "The spreadsheet is not ready.",
    "The video has not been rendered.",
    "The report will be written.",
    "The images were rendered last week.",
    "Rendered and opened.",
    "Planned video output:\nRendered and opened.",
    "Example:\nThe requested video has been rendered and opened.",
    "Analysis is unavailable because the tool failed.",
    "The review is incomplete because a dependency is missing.",
    "Analysis failed because the input was missing.",
    "I should update the configuration.",
    "I have not fixed the parser.",
    "The migration will be completed tomorrow.",
    "The issue is not fixed.",
    "The problem is still not resolved.",
    "Would you like me to publish the package?",
    "I can create a PDF if you want.",
    "If authentication succeeds and I pushed the commits, the endpoint would work.",
    "The example says authentication succeeded and I published the package.",
    "Authentication succeeded and I will publish the package.",
    "Authentication succeeded and I have not published the package.",
    "Yesterday authentication succeeded and I published the package.",
    "A deployment, a report, and a patch.",
    "Done.",
    "Interesting.",
])
def test_mentions_promises_history_and_negation_are_not_delivery(prose):
    assert detect_delivery(prose) == "unknown"


@pytest.mark.parametrize("prose,expected", [
    ("I fixed the parser. Would you like me to publish the package?", "change"),
    ("I recommend deploying after tests pass.", "plan"),
    ("Here is the deployment plan. No release has been published.", "plan"),
    ("The root cause is a stale cache. I can prepare a patch if you want.", "answer"),
    ("I updated the docs to explain how to deploy the service.", "change"),
    ("I fixed the config. The previous release was published last week.", "change"),
    ("Earlier I published a preview, but I now fixed the final issue.", "change"),
    ("I had not deployed the service, but now I deployed the corrected build.", "published"),
    ("Example:\nI published the release.\nActual result:\nI fixed the parser.", "change"),
    ("The issue is not a race condition; the cache uses the wrong key.", "answer"),
    ("Analysis:\nThree workers failed because they used different keys.", "answer"),
])
def test_current_result_wins_without_promoting_optional_or_historical_actions(prose, expected):
    assert detect_delivery(prose) == expected


def test_quoted_claims_are_removed_by_the_callers_prose_extractor():
    prose = assistant_prose('The log said "I published the release".\n> I exported a PDF.\nI fixed the parser.')
    assert detect_delivery(prose) == "change"


_ARTIFACT_URL = "https://claude.ai/code/artifact/00000000-0000-4000-8000-000000000001"
_PR_URL = "https://github.com/example/widgets/pull/42"


@pytest.mark.parametrize("text,expected", [
    (f"Republished to the same URL — {_ARTIFACT_URL} The table now includes both runs.", "artifact"),
    (f"Fixed — same URL: {_ARTIFACT_URL}", "artifact"),
    (f"I've updated the artifact: {_ARTIFACT_URL}", "artifact"),
    (f"The artifact is ready: {_ARTIFACT_URL}", "artifact"),
    ("The artifacts are ready.", "artifact"),
    ("I created an artifact with the requested comparisons.", "artifact"),
    ("Here is the artifact with the requested comparisons.", "artifact"),
    (f"Here is the revised table: {_ARTIFACT_URL}", "artifact"),
    (f"PR is up: {_PR_URL}", "published"),
    (f"The pull request is now up at {_PR_URL}", "published"),
    ("Our PR is up on GitHub.", "published"),
    (f"Fixed — same URL: {_ARTIFACT_URL}\nI published the package.", "published"),
])
def test_presented_artifacts_and_pull_requests(text, expected):
    assert detect_delivery(assistant_prose(text, link_types=True)) == expected


@pytest.mark.parametrize("text,expected", [
    (_ARTIFACT_URL, "unknown"),
    (f"Same URL: {_ARTIFACT_URL}", "unknown"),
    (f"For reference, the previous comparison is at {_ARTIFACT_URL}", "unknown"),
    (f"Here is the source: {_ARTIFACT_URL}", "unknown"),
    (f"If I republished to the same URL — {_ARTIFACT_URL} — it would replace the draft.", "unknown"),
    (f"I will update the artifact: {_ARTIFACT_URL}", "unknown"),
    (f"I have not updated the artifact: {_ARTIFACT_URL}", "unknown"),
    (f"Yesterday I republished to the same URL: {_ARTIFACT_URL}", "unknown"),
    (f"Example:\nFixed — same URL: {_ARTIFACT_URL}", "unknown"),
    (f'The log said "Republished to the same URL: {_ARTIFACT_URL}".', "unknown"),
    (f"> The artifact is ready: {_ARTIFACT_URL}", "unknown"),
    ("The artifact is not ready.", "unknown"),
    (f"I fixed the parser using this reference: {_ARTIFACT_URL}", "change"),
    (f"I updated the docs with a link to {_ARTIFACT_URL}", "change"),
    (f"I published the site with an image from {_ARTIFACT_URL}", "published"),
    (f"PR is not up: {_PR_URL}", "unknown"),
    (f"If the PR is up: {_PR_URL}", "unknown"),
    (f"The docs say the PR is up: {_PR_URL}", "unknown"),
    (f"Yesterday the PR was up: {_PR_URL}", "unknown"),
    ("The PR is up to date.", "unknown"),
    ("The PR is up next.", "unknown"),
    ("The PR count is up.", "unknown"),
])
def test_references_and_non_delivery_status_do_not_inherit_link_type(text, expected):
    assert detect_delivery(assistant_prose(text, link_types=True)) == expected


@pytest.mark.parametrize("text", [
    "## Business Summary\n\nApprove. The change does what the ticket asked and the tests cover the new branch.",
    "**Business Summary** Don't build it. The dashboards look broken, but the pipeline is behaving correctly.",
    "## Business Summary\n\nSafe, but not doing anything we can measure yet. The new setting has not moved the error rate.",
    "**Business Summary** **Safe**, but the new setting has not moved the error rate.",
    "Business Summary:\nRequest changes. The handler still loses the cancellation signal during retry.",
])
def test_summary_bottom_line_with_supporting_prose_is_a_verdict(text):
    prose = assistant_prose(text, link_types=True)
    assert detect_assessment(prose) == "verdict"
    assert detect_delivery(prose) == "answer"


@pytest.mark.parametrize("text", [
    "## Business Summary\nThe incident lasted four minutes.",
    "## Business Summary\nApprove.",
    "## Business Summary\nSafe.",
    "## Business Summary\nApprove the access request so the tool can continue.",
    "## Business Summary\nSafe. I will inspect the patch after the next run.",
    "## Business Summary\nDon't build it.\nExample:\nThe pipeline is behaving correctly and the labels are stale.",
    "## Business Summary\nYes, the output directory contains the requested files.",
    "## Business Summary\nDon't panic. The files remain available in the previous location.",
    "## Business Summary\nDon't build it if the experiment later shows no improvement.",
    "## Business Summary\nSafe if the missing checks eventually pass on the new branch.",
    "## Business Summary\nEarlier I recommended not building it because the pipeline was working.",
    "Example:\n## Business Summary\nDon't build it. The dashboards look broken but the pipeline is behaving correctly.",
    '## Business Summary\nThe comment said "Don\'t build it. The pipeline is behaving correctly."',
    "> ## Business Summary\n> Don't build it. The pipeline is behaving correctly and the gap is a labeling issue.",
    "Here is a sample response:\n## Business Summary\nDon't build it. The dashboards are only displaying stale labels.",
])
def test_summary_headings_quotes_and_conditional_advice_are_not_verdicts(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "none"


@pytest.mark.parametrize("text", [
    "My call: enable it for the first group now and hold the second for a week.",
    "Our call: keep the existing handler and skip the rewrite.",
    "I'd go with the smaller migration because rollback is simpler.",
    "Yes, ship it. The downside is small and it's one command to undo.",
    "Yes, do it. The change preserves existing callers and the tests cover the new branch.",
    "**Verdict:** the patch is correct. Approve once the config default is updated.",
    "__Verdict__: do not ship this patch because it drops cancellation.",
    "## **Review verdict:** the migration preserves existing records.",
    "This isn't a blocker; I wouldn't delay the release for it.",
    "Safe to ship. The patch is reversible and the checks cover the changed behavior.",
    "Yes, ship it.",
    "Yes, ship it. I will inspect the patch tomorrow.",
    "Yes, keep the smaller deployment.",
    "Safe to ship.",
    "Unsafe to deploy.",
])
def test_explicit_current_recommendations_deliver_an_assessment(text):
    prose = assistant_prose(text, link_types=True)
    assert detect_assessment(prose) == "verdict"
    assert detect_delivery(prose) == "answer"


@pytest.mark.parametrize("text", [
    "Yes, the output directory contains the requested files.",
    "Ship it after the next review.",
    "Yes, ship it if the next check passes. The patch is reversible.",
    "Safe to ship if the missing check passes. The branch is reversible.",
    "My call: if the next check passes, enable the new path.",
    "My call: I'll inspect the handler in the next session.",
    "My call: pending review of the new handler.",
    "My call: I can't tell yet without logs.",
    "My call: no decision until we get results.",
    "My call: I don't know which migration preserves the records.",
    "Yesterday my call: enable the new path now.",
    "The docs say My call: enable the new path now.",
    "I'd go with the smaller migration if the old database were still available.",
    "**Verdict:** pending review of the new handler.",
    "**Verdict:** I'll inspect the handler in the next session.",
    "**Verdict:** not available because the input is missing.",
    "**Verdict:** I cannot assess the patch without the test results.",
    "The docs say **Verdict:** the patch is correct.",
    "Example:\n**Verdict:** the patch is correct.",
    "> **Verdict:** the patch is correct.",
    'The reviewer said "My call: enable the first group now."',
    "This isn't a blocker; I wouldn't delay the release if the next test passes.",
    "Previously this wasn't a blocker; I wouldn't delay the release for it.",
])
def test_recommendation_mentions_promises_and_conditions_are_not_assessments(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "none"


@pytest.mark.parametrize("text", [
    "I recommend the smaller of the two options because it is easier to reverse.",
    "We favor the existing design over another layer of coordination.",
    "Personally, I prefer the second vendor: its failure behavior is predictable.",
    "I'd choose the staged rollout rather than moving every account together.",
    "Overall, I would keep the current arrangement for this release.",
    "I wouldn't build another index; the current lookup already meets the limit.",
    "My recommendation is the incremental route rather than a clean replacement.",
    "Our preference: retain the smaller configuration and retire the extra layer.",
    "The current choice is the hosted version because maintenance matters most.",
    "I suggest keeping the original mapping, which matches every supported client.",
    "I'd stick with the simpler alternative because it is reversible.",
    "We recommend that you keep the old endpoint during the transition.",
    "The proposed allocation is too risky for this workload.",
    "This arrangement looks sensible given the measured traffic.",
    "The replacement remains unnecessary: the existing worker clears the queue.",
    "A second cache is overkill for the volume we measured.",
    "That tradeoff seems reasonable for a short migration.",
    "The first supplier is the better choice on reliability.",
    "This design is not safe to deploy because retries can duplicate writes.",
    "The fallback is sufficient for the current constraints.",
    "This is worth doing because the reduction in error rate is measurable.",
    "The revised build is ready to ship with the existing checks.",
    "I do not recommend a second index for this workload.",
    "I would not deploy this version: the retry loop duplicates writes.",
    "The safer alternative is to keep the old route.",
    "This patch makes sense for the current workload.",
    "Option two is my recommendation.",
    "I think the rewrite is worth considering.",
    "I recommend the extra queue because the service loses messages when traffic spikes.",
    "I prefer the documentation over the examples for this audience.",
    "My recommendation is to keep the smaller worker pool.",
    "After measuring both configurations, I recommend the simpler layout.",
    "Given the current constraints, I'd choose the slower but safer route.",
    "The better choice for the upcoming trial: a single regional worker.",
    "For this migration, retain the existing mapping; it preserves every supported client.",
    "Go ahead with the smaller trial. The measured error rate is within the agreed limit.",
    "On balance, I would not deploy the rewrite because it loses cancellation.",
])
def test_current_stances_and_evaluated_subjects_do_not_require_literal_verdict_framing(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "verdict"


@pytest.mark.parametrize("text", [
    "I recommend adding instrumentation before we investigate the latency.",
    "I suggest reviewing the database logs next.",
    "I'll choose the smaller option after inspecting the traces.",
    "We will assess whether the new approach is safe.",
    "I don't know whether this design is correct.",
    "I cannot determine which option is better without the measurements.",
    "My recommendation is pending the load test.",
    "Our preference is unavailable until the review is complete.",
    "The recommendation is to investigate the remaining reports.",
    "We discussed whether this choice is appropriate.",
    "I would prefer the second vendor if it supported the current format.",
    "The fallback is sufficient when all workers share a region.",
    "Assuming the cache is warm, this arrangement is safe.",
    "Yesterday I recommended the staged rollout.",
    "The documentation says the replacement is unnecessary.",
    "The example describes which option is better.",
    "Is this configuration safe to deploy?",
    'The reviewer wrote "The fallback is sufficient for the current constraints."',
    "> I recommend the smaller of the two options.",
    "The question is which choice is better for the target workload.",
    "I have not made a recommendation because the measurements are incomplete.",
    "The cursor is right now positioned at the first record.",
    "The deployment is ready to test locally.",
    "It is worth noting that the deployment has three replicas.",
    "The documentation recommends the old route over the new one.",
    "The reviewer thinks this implementation is correct.",
    "Ada believes this version is safe.",
    "The compliance bot thinks this design is sound.",
    "Several operators recommend the larger instance.",
    "The best option is not available yet.",
    "The safer approach is not ready for use.",
    "After measuring both configurations, I'll recommend a layout next week.",
    "For this migration, retain the mapping if the old clients cannot be updated.",
    "A safer choice: pending the next load measurement.",
])
def test_structural_verdict_rules_require_asserted_current_advice_or_judgment(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "none"


@pytest.mark.parametrize("text", [
    "I saved the summary to findings.md, including the table and the open questions.",
    "Saved the comparison as output/comparison.txt.",
    "I wrote the summary to /tmp/findings.md.",
    "Here's the reply, ready to paste:\n\n> Thanks, this is live now; let me know if anything looks off.",
    "Here is my draft, ready to paste into the discussion.",
    "Here's the ready-to-paste email with the requested wording.",
])
def test_saved_files_and_explicit_paste_ready_drafts_are_artifacts(text):
    assert detect_delivery(assistant_prose(text, link_types=True)) == "artifact"


@pytest.mark.parametrize("text", [
    "I assembled the requested notes in a single document.",
    "I've drafted a reply for the discussion below.",
    "We composed the email with the requested explanation.",
    "Saved the comparison to output/weekly-results.json.",
    "I wrote the findings to /tmp/review-summary.rst.",
    "I prepared a checklist covering each remaining decision.",
    "The draft has been assembled for your review.",
    "The memo is written and ready for you to read.",
    "I saved awaitonalfile containing the complete comparison.",
    "We generated the complete comparison at awaitonalfile.",
    "I assembled the result as awaitonalfile.",
    "The awaitonalfile has been saved for download.",
    "I saved the write-up as HANDOFF.",
    "I saved the file as NOTES.",
    "The draft has been put in the shared folder.",
    "The file was placed in the review directory.",
    "The write-up has been stored in the shared folder.",
    "I've written the complete brief and saved a copy in the shared folder.",
    "I finished the requested draft for the onboarding discussion.",
    "The comparison is assembled and saved in awaitonalfile.",
    "I've assembled an audit packet with the source notes and the timeline.",
    "We created a comparison table containing the relevant tradeoffs.",
])
def test_completed_artifact_reports_support_drafts_generic_paths_and_opaque_file_markers(text):
    # File markers represent already-sanitized prose; raw marker text is never
    # trusted by the caller's extractor.
    assert detect_delivery(text) == "artifact"


@pytest.mark.parametrize("text,expected", [
    ("I will assemble a draft for the discussion.", "unknown"),
    ("I haven't saved awaitonalfile yet.", "unknown"),
    ("The memo is not written yet.", "unknown"),
    ("The draft has not been assembled.", "unknown"),
    ("Yesterday I assembled the requested notes.", "unknown"),
    ("If I saved awaitonalfile, the tool would load it.", "unknown"),
    ("The documentation says I saved awaitonalfile.", "unknown"),
    ("Example:\nI assembled a draft for your review.", "unknown"),
    ("I wrote a parser to load the comparison from awaitonalfile.", "change"),
    ("I updated awaitonalfile to correct the parser.", "change"),
    ("I created a helper that saves reports to output/results.json.", "change"),
    ("I prepared a plan to generate the comparison file.", "plan"),
    ("I created an implementation plan for the remaining work.", "plan"),
    ("I wrote a comparison of the existing files.", "answer"),
    ("I have not finished the requested draft.", "unknown"),
    ("The comparison will be saved in awaitonalfile.", "unknown"),
    ("The comparison was assembled in the previous session.", "unknown"),
    ("The previous draft was assembled last week.", "unknown"),
])
def test_artifact_reports_preserve_future_negation_context_and_implementation_changes(text, expected):
    assert detect_delivery(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("I saved the summary as `quarterly findings.md`.", "artifact"),
    ('I assembled "handover notes.txt" for your review.', "artifact"),
    ("I wrote the comparison to [this file](sandbox:/tmp/full-comparison.txt).", "artifact"),
    ("We have saved `/tmp/notes` for download.", "artifact"),
    ("I wrote the parser in `src/parser.py`.", "change"),
    ("I updated `src/parser.py` to correct the loader.", "change"),
    ("I reviewed `src/parser.py` and found a mismatch.", "answer"),
    ("I will save the summary as `quarterly findings.md`.", "unknown"),
    ('The docs say "I saved handover notes.txt for your review."', "unknown"),
])
def test_file_delivery_uses_sanitized_shape_without_filename_contents(text, expected):
    prose = assistant_prose(text, link_types=True, typed_code=True)
    assert detect_delivery(prose) == expected


@pytest.mark.parametrize("text,expected", [
    ("I will save the summary to findings.md.", "unknown"),
    ("I have not saved the summary to findings.md.", "unknown"),
    ("I saved no summary to findings.md.", "unknown"),
    ("Yesterday I saved the summary to findings.md.", "unknown"),
    ("The docs say I saved the summary to findings.md.", "unknown"),
    ("Example:\nI saved the summary to findings.md.", "unknown"),
    ("I wrote a helper to export data as findings.md.", "change"),
    ("I saved the summary to the database.", "unknown"),
    ("Here is a reply that will be ready to paste later.", "unknown"),
    ("Here's the reply, not ready to paste yet.", "unknown"),
    ("Here's an example reply, ready to paste.", "unknown"),
    ("Here's the reply, ready to paste last week.", "unknown"),
])
def test_file_mentions_and_undelivered_drafts_do_not_become_artifacts(text, expected):
    assert detect_delivery(assistant_prose(text, link_types=True)) == expected


@pytest.mark.parametrize("text", [
    "Found it. The scheduler reads the timezone from the server instead of the user's profile, so evening jobs run an hour early.",
    "I found it. The parser returns an empty list because it receives the wrong key.",
    "Found it. The cause is the upstream rate limiter, not our code.",
])
def test_found_it_with_a_current_explanation_delivers_a_diagnosis(text):
    assert detect_delivery(assistant_prose(text, link_types=True)) == "answer"


@pytest.mark.parametrize("text", [
    "Found it.",
    "Found it. Please confirm the target branch before I continue.",
    "Found it. The summary will be available after the next run.",
    "Found it. The documentation says the patch is fixed.",
    "Found it yesterday. The scheduler reads the timezone from the server.",
    "Example:\nFound it. The scheduler reads the timezone from the server.",
])
def test_found_it_without_a_current_explanation_is_not_a_delivered_diagnosis(text):
    assert detect_delivery(assistant_prose(text, link_types=True)) == "unknown"


@pytest.mark.parametrize("prose", [None, {}, "", "  ", "x" * 131_073])
def test_invalid_or_oversized_input_is_unknown(prose):
    assert detect_delivery(prose) == "unknown"


@pytest.mark.parametrize("prose,expected", [
    ("which " * 20_000, "unknown"),
    ("and " * 30_000, "unknown"),
    ("[" * 131_072, "unknown"),
    ("I fixed the code and " * 5_000, "change"),
], ids=["question-prefixes", "conjunction-prefixes", "unmatched-brackets", "repeated-actions"])
def test_adversarial_input_finishes_promptly(prose, expected):
    # Short IDs also bound the inherited PYTEST_CURRENT_TEST environment value;
    # Linux limits each argv/environment string even when prose uses stdin.
    process = subprocess.run(
        [sys.executable, "-c", "import sys; from awaitonal.delivery import detect_delivery; "
         "print(detect_delivery(sys.stdin.read()))"],
        input=prose, capture_output=True, text=True, timeout=5, check=True,
    )
    assert process.stdout.strip() == expected


@pytest.mark.parametrize("text", [
    "I lean toward the regional rollout: it limits the recovery cost.",
    "I'm leaning towards the smaller design because it has fewer failure modes.",
    "I'd lean to the existing worker rather than add coordination.",
    "We vote for the hosted alternative because maintenance is the main constraint.",
    "My vote goes to the gradual migration, which preserves rollback.",
    "The staged alternative gets my vote on reversibility.",
    "I'd rank the incremental option first on reliability.",
    "I would place the existing approach above the replacement.",
    "The local option comes first on both latency and recovery cost.",
    "The second alternative outperforms the first on every relevant constraint.",
    "No-go for this deployment: it silently drops writes.",
    "I don't see a case to replace the worker while it meets the target.",
    "We don't see a reason to ship this version with the known data loss.",
    "The smaller pool is our pick for this release.",
    "Don't ship this.",
    "Do not merge this patch.",
])
def test_current_selection_and_withheld_endorsement_generalize_across_wording(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "verdict"


@pytest.mark.parametrize("text", [
    "The analysis is complete. I recommend you verify the totals with the owner.",
    "The comparison has one limitation. I suggest someone check the live setting.",
    "The result depends on the local configuration. I advise asking the maintainer.",
    "The audit found two gaps. My recommendation is to inspect the logs next.",
    "The cause is the cache key. It is sensible to ask the operator to verify the setting.",
    "You should verify that the fallback is sufficient for the current constraints.",
    "Check that the chosen supplier is the best option for the region.",
    "I recommend confirming which configuration is safer before changing anything.",
    "The comment says the first option gets my vote on reliability.",
    "Yesterday I leaned toward the regional rollout because rollback was simpler.",
    "I'd rank the incremental option first if the old format were still supported.",
    "My vote goes to investigating the missing records next.",
    "If the retry loop loses writes, this deployment is a no-go.",
    "The competitor's model outperforms the previous release on the published benchmark.",
    "The first record comes first in the sorted result.",
    "I will place the existing approach above the replacement after inspecting both.",
    "The election report says the regional option gets my vote.",
    "Go ahead and verify the configuration with the owner.",
    "My call: keep the existing route if the client format cannot be changed.",
    "**Verdict:** the alternative is safer if the legacy client is still supported.",
    "Safe to ship if the next check passes. The patch is reversible.",
])
def test_procedural_advice_and_reported_comparisons_are_not_current_verdicts(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "none"


@pytest.mark.parametrize("text", [
    "Here is the draft:",
    "Here's my reply.",
    "Here is the assembled document:",
    "Here are the requested notes.",
])
def test_presented_document_wrapper_is_an_artifact_without_its_body(text):
    assert detect_delivery(assistant_prose(text, link_types=True)) == "artifact"


@pytest.mark.parametrize("text", [
    "Here is the drafted email:\nThe smaller plan is the best option. I recommend it to the team.",
    "I assembled the report below:\n## Recommendation\nThe safer alternative is to keep the old route.",
    "I assembled the memo below:\n## Next steps\nDo not publish this version. It is unsafe.",
    "Here is the draft: I would rank the incremental option first on reliability.",
    "I wrote the requested letter:\nMy vote goes to the local candidate, who has my full backing.",
])
def test_evaluative_sentences_in_presented_documents_are_not_response_verdicts(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "none"
    assert detect_delivery(assistant_prose(text, link_types=True)) == "artifact"


@pytest.mark.parametrize("text", [
    "Here is the draft:\nThe incumbent is our strongest choice.\n\nOutside the draft, I would choose the shorter version because it explains the risk clearly.",
    "I saved the email. My vote goes to the shorter version because its request is clearer.",
    "My assessment: the staged option is preferable because rollback is simpler.",
    "## Analysis\nThe incremental option is my recommendation for this release.",
])
def test_response_assessments_remain_available_around_delivered_documents(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "verdict"


def test_already_scoped_prose_preserves_the_wrapper_after_a_quoted_document():
    from awaitonal.text import response_prose

    text = "Here is the draft:\n> The incumbent has my full backing.\nMy vote goes to the shorter version because it is clearer."
    scoped = assistant_prose(response_prose(text), link_types=True)
    assert detect_assessment(scoped, response_scoped=True) == "verdict"
    assert detect_delivery(scoped, response_scoped=True) == "artifact"


@pytest.mark.parametrize("text", [
    "Here is your report:",
    "Here is your report: awaitonalreferencelink",
    "Here is your report: https://claude.ai.evil.example/artifacts/report-123",
    "Here is your report: awaitonalartifactlink",
])
def test_bare_report_wrapper_without_a_valid_destination_does_not_report_a_file(text):
    assert detect_delivery(assistant_prose(text, link_types=True)) == "unknown"


@pytest.mark.parametrize("text", [
    "On balance, this looks like a reasonable approach. The fallback covers the failure case.",
    "The staged option seems like the safer alternative for this workload.",
    "Our assessment of the proposed design: I lean toward keeping it because recovery is simpler.",
    "My judgment on the competing routes: I'd place the regional option first.",
])
def test_evaluative_similes_and_personal_assessment_frames_preserve_the_main_assertion(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "verdict"


@pytest.mark.parametrize("text", [
    "On balance, this looks like a reasonable approach if the missing fallback is implemented.",
    "The record seems like the first row in the sorted result.",
    "My assessment of the design: I'll recommend a route after checking the measurements.",
    "Our judgment of the routes: I lean toward the second one if the old client remains supported.",
    "My earlier assessment of the design: I lean toward keeping it.",
])
def test_assessment_frame_does_not_override_future_conditional_or_historical_scope(text):
    assert detect_assessment(assistant_prose(text, link_types=True)) == "none"


def test_personal_assessment_after_a_quoted_draft_is_a_response_level_judgment():
    from awaitonal.text import response_prose

    raw = ("Here is the draft reply:\n> Thanks for explaining the available options.\n"
           "My assessment of your proposed plan: I lean toward accepting it, because the risk is small.")
    prose = assistant_prose(response_prose(raw), link_types=True)
    assert detect_assessment(prose, response_scoped=True) == "verdict"
