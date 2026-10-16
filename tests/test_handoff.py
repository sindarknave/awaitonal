"""Authored behavioral contrasts, not measured classifier-evaluation data."""
import time
import subprocess
import sys

import pytest

from awaitonal.handoff import Handoff, analyze_handoff, detect_handoff, handoff_kind
from awaitonal.text import assistant_prose, response_prose


def test_nested_address_headings_do_not_recurse_or_become_requests():
    subprocess.run([
        sys.executable, "-c",
        "from awaitonal.handoff import analyze_handoff; "
        "assert analyze_handoff('you: ' * 20000 + 'Done.').expectancy == 'none'",
    ], check=True, capture_output=True, text=True, timeout=5)


@pytest.mark.parametrize("text", [
    "Your session token has expired, so I can't query the warehouse. Run `! examplectl auth login` and I'll carry on.",
    "Run:\n```sh\nexamplectl auth login\n```\nThen I'll resume the query.",
    "After you finish the test, export the request from the browser's network tab and drop it into request.txt. Then I'll wire it into the script.",
    "Export the browser request. Then I'll reproduce the error.",
])
def test_user_action_with_assistant_continuation_is_required(text):
    assert analyze_handoff(assistant_prose(text)) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "Run `examplectl auth login` to try the demo.",
    "If you want, run the example. Then I'll explain the output.",
    "The documentation says: run the command. Then I'll explain the example.",
    "Setup instructions:\nRun the command. Then I'll explain the result.",
    "```sh\nexamplectl auth login\n```\nThen I'll continue.",
    "The instructions say \"Run the command and I'll continue.\"",
    "I exported the browser request. Then I'll reproduce the error.",
])
def test_continuation_does_not_promote_optional_documented_or_completed_actions(text):
    assert analyze_handoff(assistant_prose(text)).expectancy == "none"


@pytest.mark.parametrize("text", [
    "The review comments are written up above; none are on the PR yet. Should I post them?",
    "The change is ready locally and the tests pass; nothing is committed. Shall I commit and open the pull request?",
    "The two config rules are listed above. OK to apply them as written?",
    "The change is ready. Should I commit it or leave it for you?",
    "The change is ready. Would you like me to commit it?",
    "The config rules are listed above. Want me to apply them?",
    "I committed the changes. Want me to push them?",
    "I committed the changes. Should I push them?",
])
def test_explicit_permission_for_prepared_work_is_authorization(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "authorization")


@pytest.mark.parametrize("text", [
    "Should I post a review?",
    "Shall I commit and open a pull request?",
    "The change is not ready. Shall I commit it?",
    "The config rules will be listed above. OK to apply them?",
    "The change is ready. If you want, I can also commit it.",
    "The change is ready. Shall I commit it? I committed it.",
    "The config rules are listed above. OK to apply them? I applied them.",
    "The config rules are listed above. OK to apply them? No need to apply them.",
    "The documentation says: the config rules are listed above. OK to apply them?",
])
def test_unprepared_optional_and_resolved_permission_questions_stay_neutral(text):
    assert analyze_handoff(text).expectancy == "none"


def test_explicit_alternative_question_is_a_decision():
    text = "I'd enable it for both groups. Should I set it to half the traffic or all of it?"
    assert analyze_handoff(text) == Handoff("required-handoff", "decision")
    assert analyze_handoff(text + " Your choice was received.").expectancy == "none"


@pytest.mark.parametrize("text", [
    "The branch is ready. Say the word and I'll push it and open the PR.",
    "The review is written. I haven't posted it; want me to submit it as an approval?",
    "The draft reply is above. Want me to post it to the thread?",
    "The email is prepared. Would you like me to send it?",
    "The email draft is ready, would you like me to send it?",
    "The branch is ready. Want me to push it? The tests pass.",
])
def test_prepared_outward_confirmations_are_authorization(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "authorization")


@pytest.mark.parametrize("text", [
    "Want me to post a reply?",
    "If the branch is ready, say the word and I'll push it.",
    "The branch is not ready. Want me to push it?",
    "The branch will be ready tomorrow. Want me to push it?",
    "The patch is ready. Happy to open a follow-up ticket if you want.",
    "The draft reply is above. If you want, I can also post an example.",
    "Previously the branch was ready. Say the word and I'll push it.",
    "The documentation says: the branch is ready. Say the word and I'll push it.",
    "The branch is ready. Want me to push it? You approved. I pushed it.",
    "The draft reply is above. Want me to post it? I posted it.",
    "The branch is ready. Say the word and I'll push it, and I just pushed it.",
    "The review is written. Want me to submit it? No approval is needed.",
    "The email draft is ready. Want me to send it? I have already sent it.",
    "The email draft is ready. Want me to send it? I've sent it.",
    "The email draft is ready. Want me to send it? No need to send it.",
    "The email draft is ready. Want me to send it? No response is needed.",
    "The draft is ready. Someone might want me to send it later.",
    "The draft is ready. The template asks whether you want me to send it.",
])
def test_optional_and_resolved_outward_confirmations_stay_neutral(text):
    assert analyze_handoff(text).expectancy == "none"


def test_outward_confirmation_does_not_hide_an_unresolved_user_action():
    text = "The branch is ready. Want me to push it? Please sign in to SSO."
    assert analyze_handoff(text) == Handoff("required-handoff", "action")
    assert analyze_handoff(text + " Authentication succeeded.") == Handoff("required-handoff", "authorization")


def test_up_to_date_does_not_resolve_outward_confirmation():
    text = "The draft is ready. Want me to post it? The PR is up to date."
    assert analyze_handoff(text) == Handoff("required-handoff", "authorization")


@pytest.mark.parametrize("text,expected", [
    ("The patch is ready. Please review and approve it so I can merge.", "required-handoff"),
    ("The patch is merged and the checks pass. You can review the diff whenever convenient.", "none"),
    ("The draft is ready. Please review it and tell me what you think.", "review-requested"),
    ("The draft is available to review whenever useful; no response is needed.", "none"),
    ("The browser is at the SSO screen. Sign in there, and I will resume the deployment when authentication completes.", "required-handoff"),
    ("The setup guide is complete. Its sign-in section explains that users authenticate through SSO during installation.", "none"),
    ("The command is paused at authentication. Approve the device sign-in in your browser to continue.", "required-handoff"),
    ("Authentication succeeded, and the command has finished.", "none"),
    ("Please authorize repository access in the browser. I cannot inspect the requested files until access is granted.", "required-handoff"),
    ("The current setup is complete. On future machines, authorize repository access before first use.", "none"),
    ("Please reproduce the crash once and send the sanitized console output. I need that evidence to continue diagnosing it.", "required-handoff"),
    ("The fix is installed and the regression test passes. I included reproduction steps in case you want to verify it yourself.", "none"),
    ("Please restart the local service now. I am waiting for it to reconnect before running the remaining checks.", "required-handoff"),
    ("I wrote the quick-start sheet: start the local service, then sign in. The requested instructions are ready.", "none"),
    ("All checks pass, but publication still needs your go-ahead. Please review the preview and confirm whether to publish.", "required-handoff"),
    ("Your review is in. I applied the requested corrections and published the approved version.", "none"),
])
def test_synthetic_design_contrasts(text, expected):
    assert detect_handoff(text) == expected


@pytest.mark.parametrize("text,expectancy,kind", [
    ("Please choose the deployment region.", "required-handoff", "decision"),
    ("Which database should I use?", "required-handoff", "decision"),
    ("Could you clarify what you mean by a workspace?", "required-handoff", "decision"),
    ("I need your input before I can continue.", "required-handoff", "decision"),
    ("Please approve the deployment.", "required-handoff", "action"),
    ("May I install the dependency?", "required-handoff", "action"),
    ("Please do auth in the browser.", "required-handoff", "action"),
    ("Could you sign in to SSO?", "required-handoff", "action"),
    ("Please paste the error output.", "required-handoff", "action"),
    ("Can you check the console for errors?", "required-handoff", "action"),
    ("Could you look over this draft?", "review-requested", "action"),
    ("Please take a look at the changes.", "review-requested", "action"),
    ("Let me know what you think.", "review-requested", "action"),
    ("I'd appreciate your feedback.", "review-requested", "action"),
    ("Done. Would you like me to review the tests next?", "none", "action"),
    ("The guide is complete. Please review it.", "review-requested", "action"),
    ("Restart the service to apply the configuration.", "none", "action"),
    ("The service is down; I will restart it.", "none", "action"),
])
def test_handoff_flavors(text, expectancy, kind):
    assert analyze_handoff(text) == Handoff(expectancy, kind)
    assert handoff_kind(text) == kind


@pytest.mark.parametrize("text,expected", [
    ("Please sign in. Authentication succeeded. Done.", "none"),
    ("Please approve this. Your approval was received.", "none"),
    ("Please choose a region. You have selected a region.", "none"),
    ("Please review this. I incorporated your feedback.", "none"),
    ("Please paste the logs. I received the logs.", "none"),
    ("Please restart it now. The service reconnected.", "none"),
    ("Please sign in. Authentication has not succeeded.", "required-handoff"),
    ("Please approve it. Approval has not been received.", "required-handoff"),
    ("Please sign in. Once authentication is complete, I can continue.", "required-handoff"),
    # Explicit cross-sentence workflow gates make the review required.
    ("Please review it. Once your feedback is in, I can continue.", "required-handoff"),
    ("Please sign in. The implementation and tests are complete.", "required-handoff"),
    ("The tests pass, but I need your approval.", "required-handoff"),
    ("I don't need your approval, but please review the draft.", "review-requested"),
    ("I was initially waiting for your approval. Everything is complete.", "none"),
    ("Earlier I needed your approval, but now please sign in.", "required-handoff"),
    ("Please sign in. I no longer need you to sign in.", "none"),
    ("Please review. No review is needed.", "none"),
    ("Please approve. I no longer need your approval. Please approve the next operation.", "required-handoff"),
])
def test_current_dependency_and_resolution_order(text, expected):
    assert detect_handoff(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("Please sign in. Please review the draft. Authentication succeeded.", "review-requested"),
    ("Please sign in. Please review the draft. I received your feedback.", "required-handoff"),
    ("Please approve publishing. Please sign in. Your approval was received.", "required-handoff"),
    ("Please choose a region. Please sign in. Authentication succeeded.", "required-handoff"),
    ("Please send the logs. Authentication succeeded.", "required-handoff"),
    ("Please sign in. The upload is complete.", "required-handoff"),
])
def test_resolution_clears_only_related_dependency(text, expected):
    assert detect_handoff(text) == expected


def test_required_action_precedes_decision_then_resolves_to_decision():
    text = "Please choose a region. Please sign in."
    assert analyze_handoff(text) == Handoff("required-handoff", "action")
    assert analyze_handoff(text + " Authentication succeeded.") == Handoff("required-handoff", "decision")


@pytest.mark.parametrize("text", [
    "You don't need to sign in.",
    "There is no need for your approval.",
    "I am not asking you to review the patch.",
    "Please don't approve this.",
    "I do not need you to choose.",
    "Please review if useful.",
    "If you want, please sign in to try the demo.",
    "The documentation says: please sign in to SSO.",
    "The task description reads: please approve the deployment.",
    "Setup instructions:\n1. Sign in to your account.\n2. Choose the project.",
    "The login button says sign in.",
    "I reviewed the changes and approved the build.",
])
def test_non_handoffs(text):
    assert detect_handoff(text) == "none"


def test_fresh_handoff_after_instruction_section():
    text = "Setup instructions:\n1. Sign in.\n2. Choose a project.\nThe instructions are ready.\nPlease review them."
    assert detect_handoff(text) == "review-requested"
    assert detect_handoff("Setup instructions:\nSign in.\nFor this run, please approve access.") == "required-handoff"


def test_extraction_keeps_quoted_and_code_requests_out_of_detection():
    text = '> Please approve the deployment.\n```\nSign in to SSO.\n```\nThe instructions say "please choose a region". Done.'
    assert detect_handoff(assistant_prose(text)) == "none"


@pytest.mark.parametrize("text", [None, "", " ", "a" * 131_073])
def test_empty_or_oversize_input_is_neutral(text):
    assert analyze_handoff(text) == Handoff()


def test_long_adversarial_input_remains_bounded_and_keeps_final_request():
    start = time.monotonic()
    text = "which " * 20_000 + ". Please sign in."
    assert detect_handoff(text) == "required-handoff"
    assert detect_handoff("please " * 18_000) == "none"
    assert detect_handoff("please approve " * 8_000) == "required-handoff"
    # Loose wall-clock ceiling catches pathological suffix backtracking, while
    # tolerating slow CI machines; this is not a microbenchmark.
    assert time.monotonic() - start < 5


@pytest.mark.parametrize("text,expected", [
    ("I was waiting for your answer. You answered and I completed the changes.", "none"),
    ("I was blocked on your approval. Your approval was granted. Everything is done.", "none"),
    ("I need your permission. You granted permission and the operation succeeded.", "none"),
    ("I was waiting for your decision. I now have your decision and the feature is complete.", "none"),
    ("I need your approval.\nYou have\napproved. Done.", "none"),
    ("I need your approval got your\napproval was granted. Done.", "none"),
    ("Approval was granted. I need your approval.", "required-handoff"),
    ("I need your approval. Approval was granted. I need your decision.", "required-handoff"),
    ("I cannot help because I need your approval before proceeding.", "required-handoff"),
    ("Please review and approve the draft.", "required-handoff"),
    ("The guide is complete: please review it.", "review-requested"),
    ("Please review it now.", "review-requested"),
    ("Please review it. No response is needed.", "none"),
    ("Please sign in. No reply is needed.", "required-handoff"),
    ("Tell me if you'd like another format.", "none"),
    ("Please login to SSO.", "required-handoff"),
    ("You will need to sign in to continue.", "required-handoff"),
    ("You'll need to sign in to continue.", "required-handoff"),
])
def test_legacy_waiting_and_compound_request_regressions(text, expected):
    assert detect_handoff(text) == expected


def test_review_then_choice_is_a_decision():
    assert analyze_handoff("Please review the options and choose one.") == Handoff("required-handoff", "decision")
    assert handoff_kind("Please confirm which database to use.") == "decision"


@pytest.mark.parametrize("text,expectancy,kind", [
    ("I need your approval and your choice of deployment region. Approval was granted. Done.", "required-handoff", "decision"),
    ("I need your approval and choice of deployment region. Approval was granted.", "required-handoff", "decision"),
    ("I need your approval, your choice, and the logs. Approval was granted. You chose a region.", "required-handoff", "action"),
    ("I need your approval and your choice. Your choice was received.", "required-handoff", "action"),
    ("I need your approval and your choice. Approval was granted. Your choice was received.", "none", "action"),
    ("I need your approval and your answer is already available. Approval was granted.", "none", "action"),
    ("Please review the draft and sign in. Authentication succeeded. The draft is ready.", "review-requested", "action"),
    ("Please review the draft and sign in.", "required-handoff", "action"),
    ("Please review and approve it so I can merge.", "required-handoff", "action"),
    ("Please review and approve it so I can merge. You approved it.", "none", "action"),
    ("Please review the patch and approve it so I can merge. You approved it.", "none", "action"),
    ("I need your review and approval. Approval was granted.", "none", "action"),
    ("Please review the design. You approved the unrelated deployment.", "review-requested", "action"),
    ("Please review the design. Please approve the deployment. Approval was granted.", "review-requested", "action"),
    ("Please review the design and approve the deployment. Approval was granted.", "review-requested", "action"),
])
def test_coordinated_requests_keep_independent_dependencies(text, expectancy, kind):
    assert analyze_handoff(text) == Handoff(expectancy, kind)


@pytest.mark.parametrize("text,expectancy,kind", [
    ("Please sign in and approve the deployment. Authentication succeeded. The build is ready.", "required-handoff", "action"),
    ("Please approve the deployment and sign in. Authentication succeeded.", "required-handoff", "action"),
    ("Please sign in and approve the deployment. Approval was granted.", "required-handoff", "action"),
    ("Please approve the deployment and sign in. Approval was granted.", "required-handoff", "action"),
    ("Please sign in and approve the deployment. Authentication succeeded. Approval was granted.", "none", "action"),
    ("Please approve the deployment and sign in. Approval was granted. Authentication succeeded.", "none", "action"),
    ("Please sign in and choose a region. Authentication succeeded.", "required-handoff", "decision"),
    ("Please choose a region and sign in. Authentication succeeded.", "required-handoff", "decision"),
    ("Please sign in and choose a region. Your choice was received.", "required-handoff", "action"),
    ("Please choose a region and sign in. Authentication succeeded. Your choice was received.", "none", "action"),
    ("Please approve the device sign-in. Authentication succeeded.", "none", "action"),
    ("Please approve the deployment and approve the device sign-in. Authentication succeeded.", "required-handoff", "action"),
    ("Please approve the device sign-in and approve the deployment. Authentication succeeded. Approval was granted.", "none", "action"),
])
def test_compound_actions_keep_auth_and_approval_families_separate(text, expectancy, kind):
    assert analyze_handoff(text) == Handoff(expectancy, kind)


@pytest.mark.parametrize("text", [
    "Unlock the workspace. I'll retry the migration after that.",
    "I can retry the migration once you unlock the workspace.",
    "I can't validate the integration until the account is usable. Please unlock it.",
    "Rotate the credential; then I will rerun the connectivity check.",
    "Please attach the sanitized measurements. Once they arrive, I can finish the comparison.",
    "I will finish the comparison after the measurements arrive. Could you attach them?",
    "You'll need to acknowledge the device prompt before the operation can proceed.",
    "For this run, I need you to switch the account into its testing mode.",
    "I can carry on after that. Restore access to the sandbox.",
    "Refresh the session. Then I'll repeat the check.",
])
def test_structural_user_actions_do_not_depend_on_a_work_verb_catalogue(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "If you want, unlock the sample workspace. I'll retry the demo after that.",
    "The tutorial explains: unlock the workspace. Then I'll describe its behavior.",
    "Previously you needed to rotate the credential. I can now run the checks.",
    "The workspace is unlocked. I'll retry the migration after that.",
    "I unlocked the workspace. Then I'll retry the migration.",
    "The measurements are attached. I can finish the comparison after lunch.",
    "The feature is complete. Could you attach extra measurements if useful?",
    "Rotate the credential as a monthly maintenance precaution. I'll work on the summary tomorrow.",
    "The deploy is still running. Integration tests could not run. I'll report back once it completes.",
])
def test_structural_dependencies_exclude_optional_described_and_unrelated_work(text):
    assert analyze_handoff(text).expectancy == "none"


@pytest.mark.parametrize("handoff,resolution", [
    ("Unlock the workspace. I'll retry after that.", "You unlocked the workspace."),
    ("Rotate the credential. I can retry once that is done.", "The credential is now rotated."),
    ("Please attach the measurements. I'll finish once they arrive.", "You have attached the measurements."),
    ("Refresh the session. Then I'll reconnect.", "No need to refresh the session."),
])
def test_domain_action_completion_resolves_its_dependency(handoff, resolution):
    assert analyze_handoff(handoff).expectancy == "required-handoff"
    assert analyze_handoff(handoff + " " + resolution).expectancy == "none"


@pytest.mark.parametrize("text", [
    "Everything is staged locally. May I publish it now?",
    "It is ready on my side. Is it okay if I save it?",
    "I've assembled the response. Would you prefer that I post it or keep it here?",
    "We have drafted the announcement. Do you want us to publish it?",
    "The edits are complete. If you agree, I'll apply them.",
    "I prepared the answer. I'll post it once you approve.",
    "The material is written. With your permission, I can submit it.",
    "Could I save it now? Everything is prepared locally.",
    "The migration is staged. Should we apply it or leave it pending?",
    "I haven't posted the response yet. Would you like me to post it?",
    "The note has not been saved. Is it okay for me to save it?",
    "The response is written, would you prefer that I send it?",
])
def test_compositional_prepared_execution_permission_is_authorization(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "authorization")


@pytest.mark.parametrize("text", [
    "Would you prefer that I draft and publish an announcement?",
    "If everything is staged, may I publish it?",
    "The announcement will be ready tomorrow. Do you want me to publish it?",
    "It is not ready on my side. Is it okay if I save it?",
    "Everything is prepared. If you want, I can also publish an example.",
    "The edits are complete. Would you like me to post a separate explanation?",
    "I haven't built a release yet. Would you like me to build it?",
    "Previously everything was staged. Should I publish it now?",
    "The guide explains: everything is staged. If you agree, I'll apply it.",
    "The edits are complete. If you agree, I'll apply them. I applied them.",
    "Everything is ready. Could I save it now? I've saved it.",
    "The answer is written. Would you prefer that I post it? No approval is needed.",
])
def test_structural_authorization_excludes_unprepared_optional_and_resolved_work(text):
    assert analyze_handoff(text).expectancy == "none"


@pytest.mark.parametrize("text", [
    "I'll inspect both sets as soon as you attach the earlier one.",
    "Have the table exported as CSV and attach it here; with that file, I can reconcile the rows.",
    "Before I continue, rotate the token.",
    "Action for you: attach the revised intake form. Once I have it, I'll check the missing fields.",
    "Please run the diagnostic. Once it finishes, I'll compare the measurements.",
])
def test_temporal_input_causative_and_addressed_heading_structures(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "Please enjoy the dashboard. I will check it again after lunch.",
    "Please note the behavior. I can explain why after the investigation finishes.",
    "You need to know that the checks pass. Done.",
    "You must remember that this is a sample. Done.",
    "Please hydrate while I wait for the tests. I will continue when they finish.",
    "Please celebrate the good news. I will continue after the tests finish.",
    "The image conversion hasn't finished yet, and I'll share the converted set once it does.",
    "Done. awaitonalliteral Then I'll continue.",
    "Done. awaitonalcode Then I'll continue.",
])
def test_temporal_coincidence_and_social_or_mental_directives_are_not_workflow_gates(text):
    assert analyze_handoff(text).expectancy == "none"


@pytest.mark.parametrize("text", [
    "I've prepared the migration. If you agree with the approach, can I apply it?",
    "Are you happy for me to publish the revised schedule? I have the final version ready.",
    "The edits are ready. Are you comfortable with me applying them?",
    "The response is assembled. I can post it provided you approve.",
])
def test_permission_questions_and_approval_conditions_compose_with_prepared_state(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "authorization")


@pytest.mark.parametrize("text", [
    "Nothing has been drafted. Should I post the result?",
    "No response has been written. Should I post it?",
    "The release is ready. Can I save you some time by writing a guide?",
    "The application is ready. Could I publish a tutorial next week?",
    "The application is ready. Can I publish a tutorial next week?",
])
def test_negative_preparation_and_fresh_work_objects_do_not_authorize_prepared_execution(text):
    assert analyze_handoff(text).expectancy == "none"


@pytest.mark.parametrize("handoff,resolution", [
    ("Run the diagnostic. Then I'll compare the measurements.", "I ran it."),
    ("Write the account identifier here. Once I have it, I'll retry.", "You wrote the account identifier."),
])
def test_irregular_action_completion_resolves_a_generic_dependency(handoff, resolution):
    assert analyze_handoff(handoff).expectancy == "required-handoff"
    assert analyze_handoff(handoff + " " + resolution).expectancy == "none"


@pytest.mark.parametrize("text", [
    "The answer is complete. You should choose the smallest tier for a personal project.",
    "My advice is to ask the owner to check the numbers. Nothing else is pending.",
    "I recommend that you check the console output before adopting this approach.",
    "Check again later for the final results. I have answered the question.",
    "Choose a plan with enough storage. That is my recommendation.",
    "The analysis is complete with the stated data limits. Someone should verify the figures. If you want, I can build a separate model.",
    "The report is delivered. You need to check the output against the source; I can also prepare another report if useful.",
    "I am waiting for the output from the background job. Once it arrives, I'll compare the results.",
    "Waiting on the logs from the running job. I'll report back when the job completes.",
    "The scheduled job requires the output from the earlier job. I'll check once both finish.",
    "The timer is still counting down. I need the output before I can calculate the result.",
    "Please check the results as general advice. I will resume when the unrelated timer expires.",
    "Ask the administrator which plan to pick. I'll finish the unrelated summary tomorrow.",
])
def test_advice_and_non_user_prerequisites_do_not_play_attention(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "Please choose the target account. Once you do, I'll configure the connection.",
    "I recommend the smaller tier, but I need your choice before I can provision it.",
    "The figures are provisional. Could you paste the source output? Once I have it, I'll verify the totals.",
    "I can't compare the results without the source figures. Please attach those figures.",
    "Please run the local check and send me its output. Then I'll finish the diagnosis.",
    "Ask the administrator for access. Once you have it, I can complete the remaining checks.",
    "I can complete the analysis once you verify the missing count. Please check it against the source.",
])
def test_real_user_prerequisite_preserves_attention_across_advisory_context(text):
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("text", [
    "Do I target the shared environment or the isolated one?",
    "Would we use the temporary account or the permanent account?",
    "Do you prefer the regional instance or the shared instance?",
    "Would you rather use the compact layout or the detailed layout?",
    "Which destination should we use? I can publish once you choose it.",
])
def test_current_actor_scoped_decision_paraphrases(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "decision")


@pytest.mark.parametrize("text", [
    "The answer explains which account you should use.",
    "The guide asks: do you prefer the regional instance or the shared instance?",
    "Would you prefer that I draft a separate report?",
    "Do you want me to create another comparison?",
    "The paragraph considers which destination should we use as a rhetorical question.",
])
def test_described_questions_and_offers_do_not_create_decisions(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "I'm waiting for the timer to expire; please review the answer while it runs.",
    "The deployment is still running, and please review the preview if useful.",
    "I am waiting for the job output, and I'd appreciate your feedback on the document.",
])
def test_process_wait_does_not_promote_a_soft_review_to_required(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


def test_review_needed_for_a_specific_assistant_step_remains_required():
    assert analyze_handoff("I need your review to continue the deployment.").expectancy == "required-handoff"


@pytest.mark.parametrize("text", [
    "Both devices satisfy the requirement. Choose the smaller one for travel or the cheaper one for your desk.",
    "Either provider will work. Pick the local provider if latency is your priority.",
    "The two plans are suitable. Select the annual plan if you expect to keep using it.",
    "The analysis is complete. Please confirm the source count with its owner before relying on the results.",
    "Please check the measurements against an independent source before using them. The requested answer is above.",
    "The summary is delivered. Please verify the estimates yourself before acting on the recommendation.",
])
def test_selection_and_reader_verification_advice_are_not_current_gates(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "Before I can calculate the total, choose whether to include the first period or the second period.",
    "Pick either the compact or the accessible format. I cannot finalize the diagram until you make that choice.",
    "Select a reporting interval. Once you select it, I can produce the chart.",
    "Please pick the destination account.",
    "Please select the environment to use.",
])
def test_structural_selection_gate_keeps_the_decision_kind(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "decision")


@pytest.mark.parametrize("text", [
    "Please confirm the source count with the owner. I cannot complete the comparison until you confirm it.",
    "Please check the measurements against the reference. Then I'll calculate the result from those measurements.",
    "Verify the estimates yourself. Once you verify them, I can finish the report.",
])
def test_verification_advice_becomes_required_when_it_unblocks_assistant_work(text):
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("text,kind", [
    ("The diagram is ready for review, and please attach the source data so I can verify it.", "action"),
    ("No approval is needed for the analysis, and please send the input before I calculate the total.", "action"),
    ("Previously the measurements were missing, and now please attach them so I can finish.", "action"),
    ("I cannot finish until you provide the figures, though reviewing the draft is optional.", "action"),
    ("I recommend proceeding. Approve the release so that I can publish it.", "action"),
    ("The answer has a limitation, please paste the missing result so that we can finish the comparison.", "action"),
    ("The preview is ready for review, could you unlock the workspace? Then I will rerun the checks.", "action"),
    ("You can review the chart whenever convenient, please select the interval before I calculate its final values.", "decision"),
])
def test_independent_current_gate_survives_neighboring_response_status(text, kind):
    assert analyze_handoff(text) == Handoff("required-handoff", kind)


@pytest.mark.parametrize("text", [
    "The diagram is ready for review, and please attach extra source data if useful.",
    "No approval is needed for the analysis, and I can prepare a new comparison if you want.",
    "The measurements are missing from this answer, please verify them yourself before relying on it.",
    "I recommend proceeding. You should approve the release if it suits your own project.",
    "You can review the chart whenever convenient, please select a larger screen for easier reading.",
    "The preview is ready for review, could you celebrate the result? I will continue once the unrelated job finishes.",
    "If useful, please paste the logs. Then I can explain the example.",
    "If you want, please attach another image so that I can make a separate comparison.",
    "If you would like, could you send the result? Then I'll examine it.",
    "If helpful, please choose the interval before I calculate a new chart.",
    "If you want to go further, could you send the raw output? Then I'll inspect it.",
    "If useful to you, please choose the longer explanation before I draft another answer.",
])
def test_independent_request_boundaries_keep_optional_and_advisory_scope(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "The response is drafted. If it looks good to you, I'll send it.",
    "The edits are ready for review and if these changes are acceptable to you, I will apply them.",
    "The diagram is complete. If the layout seems right to you, we can publish it.",
])
def test_prepared_execution_can_depend_on_a_user_judgment_without_approval_vocabulary(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "authorization")
    assert analyze_handoff(text + " Your approval was received.").expectancy == "none"


@pytest.mark.parametrize("text", [
    "If the response looks good to you, I'll draft and send it.",
    "The response is drafted. If useful, I'll send another example.",
    "The response is ready. If it looks good to the reviewer, the job will publish it automatically.",
    "The response is drafted. If it looks good to you, I'll send it. I sent it.",
])
def test_judgment_conditions_need_current_prepared_work_and_a_user_owned_gate(text):
    assert analyze_handoff(text).expectancy == "none"


@pytest.mark.parametrize("text", [
    "I recommend option A. Before I can perform the final build, which route are we taking?",
    "To complete the chart, I still need to know your preferred interval.",
    "Before I produce the diagram, what format will it be: landscape or portrait?",
    "Which account will we use for this run? I cannot start until you choose it.",
    "Which option am I configuring? I need your choice before I can proceed.",
])
def test_needed_input_and_current_assistant_operation_questions_are_decisions(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "decision")


@pytest.mark.parametrize("text", [
    "I recommend option A. Which route you take depends on your own constraints.",
    "The chart is complete. If useful, I still need to know your preferred interval to make another one.",
    "What format will it be: landscape or portrait? The answer explains both options for you.",
    "The guide asks: which account will we use for this run?",
    "Which option am I configuring is an example question in the document.",
    "The completed answer explains both alternatives, which will we pick if we ever revisit this?",
    "For future reference, what account will we use for the next example?",
    "What will we see in the trace? A missing parent span, followed by the retry.",
    "Which labels will we see after deployment? The new status values are active and idle.",
    "What are we waiting for? The scheduled compaction is still running; I'll report back when it finishes.",
    "What will we discover after the switch? The trace explains the new order.",
    "Which behavior are we investigating? The trace explains the new order.",
    "Which route are we trying next? The answer gives both paths and no further work is pending.",
    "What should we expect from the output? The next line explains it.",
])
def test_interrogative_words_without_current_input_gate_do_not_create_decisions(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "The checks have yet to return. I will get back to you when they come back.",
    "The validation is queued. I will get back to you when it finishes. Please verify the owner before relying on this advice.",
    "The audit is running. I can finish the comparison when it completes. Please confirm those figures yourself before using the answer.",
    "The archive is being reconstructed. I'll report when it finishes. Please verify the checksum yourself before relying on my analysis.",
])
def test_process_completion_antecedent_does_not_become_a_later_reader_action(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "The validation is queued. I'll report back when it finishes. Please attach the missing file so that I can finish the separate comparison.",
    "The audit is running. I can finish the comparison when it completes. Before I can publish the analysis, please approve the prepared draft.",
])
def test_an_independent_user_gate_is_preserved_alongside_a_process_wait(text):
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("text", [
    "The job is queued, waiting for you to release it. I'll send an update afterward.",
    "The run is waiting on you to unlock the environment. I'll continue after that.",
    "Waiting for you to attach the remaining input. Once it arrives, I can finish.",
])
def test_current_user_owned_process_wait_accepts_a_domain_verb(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "The job was waiting for you to release it. It finished successfully.",
    "The example will be waiting for you to unlock the environment. The answer is complete.",
    "If useful, the job can be started, waiting for you to attach another input.",
    "The job is queued, waiting for the service to release it. I'll send an update afterward.",
])
def test_user_wait_structure_excludes_past_future_optional_and_non_user_actors(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("modifier", ["still", "currently", "urgently", "now", "still urgently"])
@pytest.mark.parametrize("request_text,kind", [
    ("I {modifier} need you to send the table definition before I can revise the query.", "action"),
    ("We {modifier} require you to unlock the account so that we can validate the connection.", "action"),
    ("I {modifier} need you to choose the reporting period before I can draw the chart.", "decision"),
    ("You {modifier} need to briefly run the local check for this run.", "action"),
])
def test_current_finite_user_requirements_preserve_their_actor_through_adverbs(modifier, request_text, kind):
    text = "I recommend retaining the current design. " + request_text.format(modifier=modifier)
    assert analyze_handoff(text) == Handoff("required-handoff", kind)


@pytest.mark.parametrize("text", [
    "I do not currently need you to send the table definition. The analysis is complete.",
    "We don't urgently require you to unlock the account. It is already available.",
    "You do not currently need to run the local check. Everything is complete.",
    "I would still need you to provide the measurements if we started a new investigation.",
    "Previously I urgently needed you to choose a period. You chose one and the chart is complete.",
    "If useful, I still need you to send an extra sample before I can produce a separate answer.",
    "I generally need you to unlock the account when demonstrating this workflow. The answer is complete.",
    "We hypothetically require you to attach the missing input in that example. No action is needed.",
])
def test_adverbial_requirements_do_not_erase_negation_modality_or_habitual_scope(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "Package validation for release 2.8 is underway in the build service. I will return with the report as soon as the service has produced it.",
    "Archive reconstruction across all shards is in progress. I'll report when the archive returns.",
    "Transfer verification for the previous batch is being checked. I will return with the verification once the batch finishes.",
])
def test_present_process_declarations_are_not_bare_user_imperatives(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "Package verification is underway. Please attach the manifest so that I can validate the separate release.",
    "The archive is being reconstructed. Please unlock the destination before I can run the independent comparison.",
])
def test_an_addressed_request_survives_a_neighboring_process_assertion(text):
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("text", [
    "To locate the failure in your run, paste the complete error trace here; I will trace it back to the responsible statement.",
    "In order to finish the comparison, attach the earlier measurements. We will compare them with the new run.",
    "To distinguish the cases, forward the original request to me. I will inspect it for the missing header.",
    "To reconcile the counts, supply the original records here. I'll check them against the summary.",
])
def test_purpose_led_input_request_with_promised_consumption_is_required(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "To understand the sample, paste the output into your own console. I will finish the unrelated review tomorrow.",
    "If useful, to extend the comparison, attach extra measurements. We will compare them next.",
    "To inspect the delivered answer, open the document. I will summarize it at tomorrow's meeting.",
    "The guide explains: to locate the failure, paste the error trace here. I will explain it later.",
    "To make your own comparison, attach the measurements in the example tool. I can prepare another answer if useful.",
])
def test_purpose_and_future_work_without_required_input_transfer_stay_optional(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "The parser accepts the sample, although the sample contains no nested lists. Please attach a nested list so that I can verify the remaining case.",
    "The guide includes only the public examples. Please provide the missing output so I can finish the diagnosis.",
    "The sample explains the discrepancy in the count. Please paste the original count before I can reconcile it.",
])
def test_document_narration_does_not_extend_its_scope_over_current_requests(text):
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("text", [
    "The guide includes these steps: attach a source sample. Once I have it, I can explain the comparison.",
    "Sample output: please send the measurements. I will inspect them once they arrive.",
    "Here are the authentication instructions. Sign in to SSO. Then I will describe the screen.",
])
def test_presented_instruction_bodies_remain_excluded_from_current_requests(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text,kind", [
    ("Attach the supporting records for those totals, and I can complete the reconciliation.", "action"),
    ("Unlock the shared account, and we can verify the connection.", "action"),
    ("Choose the compact layout or the detailed one, and I will produce the final diagram using your selection.", "decision"),
    ("Provide the previous run's results, and I'll compare them with today's run.", "action"),
])
def test_same_clause_imperative_and_assistant_consequence_establish_a_gate(text, kind):
    assert analyze_handoff(text) == Handoff("required-handoff", kind)


@pytest.mark.parametrize("text", [
    "If useful, attach extra records, and I can make a separate reconciliation.",
    "The guide says: unlock the shared account, and we can verify the connection.",
    "The account is unlocked, and we can verify the connection.",
    "The process is running. Please enjoy the result, and I will continue when it finishes.",
])
def test_coordinated_capability_preserves_optional_documented_and_completed_scope(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "The transfer is still progressing. I will summarize it when it returns. Remaining checks on the alternate recovery path were not run.",
    "The run is awaiting results. I'll report when it completes. Missing records from the earlier export have not been checked.",
    "The copy is in progress. I will compare it once it returns. Pending repairs in the separate workspace are outside this task.",
])
def test_long_noun_subjects_with_finite_predicates_do_not_become_imperatives(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "Attach the records that are missing. Once I have them, I can finish the calculation.",
    "Unlock the workspace before the next check can start. Then I will rerun it.",
])
def test_relative_and_temporal_clauses_do_not_turn_real_imperatives_into_noun_assertions(text):
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("text", [
    "The patch is complete. To inspect the syntax locally, paste the snippet into your editor. I'll publish it tomorrow.",
    "The draft is complete. To compare the examples, paste them into your own console. I'll send it to the team tomorrow.",
    "The answer is complete. To inspect the values, attach the sample in the local tool. I will inspect it during tomorrow's demonstration.",
    "To finish the comparison, attach the records. I will not inspect them.",
    "The answer is complete. Please verify the source yourself, and I will report back when the unrelated queue clears.",
    "The summary is complete. Please review the source in your browser, and I will publish it next week.",
])
def test_user_tool_transfers_and_unrelated_handback_promises_are_not_input_dependencies(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "To finish the comparison, paste the values into this chat. I'll inspect them for duplicate entries.",
    "To reconcile the counts, send the records to me in CSV. I will check them against the summary.",
    "To finish the chart, provide the measurements in CSV. I will compare them with the earlier run.",
])
def test_assistant_owned_input_destination_and_format_preserve_the_dependency(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "The guide contains the following steps. Sign in to the account. Approve the connection.",
    "The manual includes these instructions. Please grant access. Then select an account.",
    "The documentation explains the following recommended procedure. Please approve the connection. Then I will explain the resulting screen.",
    "Training run cedar-19 has two epochs left. I will compare its final score and give you the outcome after the run closes.",
    "Remaining checks on recovery-path-3 were not run. I will summarize the separate job when it finishes.",
])
def test_forward_instruction_introductions_and_identified_noun_subjects_stay_declarative(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "I recommend keeping the current design. Run the diagnostic on your laptop and paste the output into this chat. That output is required for me to identify the failing component.",
    "Please attach the original measurements. The measurements are necessary for us to complete the comparison.",
    "Send the corrected export here. That export remains essential for me to reconcile the totals.",
    "Provide the missing account details. These are needed for us to configure the connection.",
    "Please unlock the workspace. That is required for me to finish the validation.",
    "The preview is ready for review. Paste the original trace here. This is still necessary for us to isolate the first failure.",
])
def test_passive_need_for_assistant_infinitive_links_the_requested_input(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "Please verify the estimates yourself before using this answer. The timer is required for me to finish the separate task.",
    "Check the figures as general advice. The background job is necessary for us to prepare a separate report.",
    "Paste the example output into your own console before relying on the answer. That output is required for me to demonstrate the tool tomorrow.",
    "If useful, attach another export. That export is needed for me to create a new comparison.",
    "The guide says: attach the measurements. Those measurements are required for us to finish the example.",
    "The background job is processing the output. That output is necessary for me to complete the comparison.",
    "The workspace is unlocked. That is required for me to finish the check.",
    "Please attach a sample if we revisit this. If that sample is required for me to continue, I will ask then.",
])
def test_passive_needs_do_not_make_advice_optional_or_non_user_events_blocking(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("assertion", [
    "That export was required for me to finish yesterday's example.",
    "That export will be necessary for me to start the next task.",
    "That export is not needed for me to continue.",
    "If that export is essential for me to continue, I will ask later.",
])
def test_only_asserted_current_passive_needs_establish_a_new_gate(assertion):
    text = "The report is delivered. Review the export before relying on it. " + assertion
    assert analyze_handoff(text).expectancy != "required-handoff"


def _attention_handoff(text):
    return analyze_handoff(assistant_prose(response_prose(text, attention=True), attention=True),
                           response_scoped=True)


@pytest.mark.parametrize("closing", [
    "Should I post this as a reply to the discussion?",
    "Say the word and I'll post it.",
    "Would you like me to submit it as the review?",
])
def test_closing_assistant_permission_uses_preparation_across_a_draft_body(closing):
    text = ("Draft below, not posted:\n\n"
            "The proposed update explains the observed behavior.\n"
            "Please choose an account in this example document.\n\n" + closing)
    assert _attention_handoff(text) == Handoff("required-handoff", "authorization")


@pytest.mark.parametrize("text", [
    "The review is complete. The draft is ready for you to post. Please approve it before posting.",
    "The review is written. You can post the draft after approval. Once you approve it, post it yourself.",
    "The draft is ready for you to submit. I need your approval before you send it to the team.",
    "The review is complete. Please approve and post the draft yourself.",
])
def test_draft_handed_to_the_user_to_publish_is_not_an_assistant_gate(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("closing", [
    "Should I post it instead?",
    "Please approve it before I can post the final version.",
    "Could you attach the source before I can verify the review?",
])
def test_user_publication_context_does_not_hide_a_separate_assistant_gate(closing):
    text = "The draft is ready for you to post. " + closing
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("heading", ["Run this:", "Next is:", "Next step is:"])
@pytest.mark.parametrize("followup", [
    "Once they're in, I'll check the imported records.",
    "After that, I can compare the totals.",
])
def test_user_command_keeps_its_dependency_across_an_opaque_fence(heading, followup):
    text = heading + "\n```sh\n! samplectl import records\n```\n" + followup
    assert _attention_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "Next is:\n```sh\n! samplectl import records\n```\nThe requested instructions are complete.",
    "Next is:\n```sh\nprint('please sign in')\n```\nOnce they're in, I'll check the totals.",
    "If useful, run this:\n```sh\n! samplectl import extras\n```\nOnce they're in, I'll check them.",
    "```sh\n! samplectl import records\n```\nOnce they're in, I'll check the totals.",
])
def test_fenced_commands_without_a_current_user_gate_do_not_raise_attention(text):
    assert _attention_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("prefix", ["", "The answer is complete. Here are some practical next steps:\n"])
def test_parallel_advice_imperatives_do_not_claim_a_paused_assistant_task(prefix):
    text = (prefix + "1. Sign in to the dashboard.\n"
            "2. Run the diagnostic locally.\n"
            "3. Approve only the requests you recognize.\n"
            "4. Choose the plan that suits your budget.")
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "1. Run the collection command.\n2. Paste the output here.\nOnce I have it, I'll finish the diagnosis.",
    "The worker is running.\n1. Please sign in now.\n2. Check the activity panel when convenient.",
    "1. I need you to unlock the workspace for this run.\n2. Open the status panel.",
])
def test_current_user_gates_remain_required_inside_parallel_steps(text):
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("status", [
    "Relaunched the background worker.",
    "Restarted the background worker.",
    "Background worker relaunched.",
    "Background worker restarted.",
])
def test_elliptical_background_results_are_not_user_imperatives(status):
    assert analyze_handoff(status + " I'll report findings when it lands.").expectancy != "required-handoff"


def test_current_user_command_remains_required_beside_a_background_result():
    text = ("Background worker relaunched. It is running now. "
            "Please restart the local agent now. Once you restart it, I'll inspect the connection.")
    assert analyze_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("review_word", ["feedback", "review"])
def test_coordinated_approval_keeps_the_user_publication_scope(review_word):
    text = ("The draft is ready for you to post. I need your " + review_word
            + " and approval before you send it.")
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("review_word", ["feedback", "review"])
def test_coordinated_approval_remains_required_for_an_assistant_dependency(review_word):
    text = "I need your " + review_word + " and approval before I can deploy the prepared release."
    assert analyze_handoff(text).expectancy == "required-handoff"


@pytest.mark.parametrize("text", [
    "Keep the terminal connected. Once it is connected, I can verify the result.",
    "Leave the workspace unlocked. Once it is unlocked, I can finish the check.",
])
def test_causative_state_commands_are_not_elliptical_completed_results(text):
    assert analyze_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("request_text", [
    "Please approve the deployment now.",
    "Please authorize the environment access now.",
    "I need your approval for the separate deployment.",
])
def test_publication_handback_does_not_mask_an_unrelated_approval(request_text):
    text = "The draft is ready for you to post. " + request_text
    assert analyze_handoff(text).expectancy == "required-handoff"


def test_approval_of_the_handed_back_draft_remains_nonblocking_when_current():
    assert analyze_handoff("The draft is ready for you to post. Please approve it now before posting.").expectancy != "required-handoff"


@pytest.mark.parametrize("text", [
    "I cannot perform this check in your environment. Please execute the supplied command and return its final status.\n"
    "```sh\n! samplectl inspect\n```\n"
    "I will use that result to choose the remaining correction.",
    "Please run the local preview rebuild. Then tell me whether the new page has the corrected title.\n"
    "```sh\n! samplectl preview\n```\n"
    "Your result determines my remaining edit. I am waiting for that check before making the change.",
    "Run this diagnostic in the active notebook, then copy the version lines into your reply:\n"
    "```sh\n! samplectl versions\n```\n"
    "I will use those exact versions to assemble the final configuration. I need your result before I can finish.",
])
def test_explicit_user_command_keeps_its_returned_input_dependency_across_wrapper_sentences(text):
    assert _attention_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("heading", [
    "Next is a local environment check:",
    "The next step is a quick preview rebuild:",
])
def test_descriptive_next_command_heading_requires_an_assistant_use_of_its_result(heading):
    text = (heading + "\n```sh\n! samplectl inspect\n```\n"
            "I will use that result to finish the comparison.")
    assert _attention_handoff(text) == Handoff("required-handoff", "action")


@pytest.mark.parametrize("text", [
    "If useful, please execute the supplied command and return its final status.\n"
    "```sh\n! samplectl inspect\n```\nI will use that result to make a separate comparison.",
    "I ran the local check.\n```sh\n! samplectl inspect\n```\nI will use that result to finish.",
    "Please run the supplied command.\n```sh\n! samplectl inspect\n```\n"
    "The background job is running. I'll report findings when it lands.",
    "Next is an example command:\n```sh\n! samplectl inspect\n```\n"
    "I will use that result during the tutorial.",
    "```sh\n! samplectl inspect\n```\nI will use that result to finish the comparison.",
])
def test_command_block_does_not_create_a_gate_from_optional_past_example_or_unrelated_work(text):
    assert _attention_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("question", [
    "Do I have your go-ahead to apply this replacement copy to the help page?",
    "Do I have permission to post this prepared response to the issue?",
    "Do you approve my applying this replacement section to the guide now?",
    "Do you authorize me to publish this replacement section?",
    "Can we have the consent to publish this replacement section?",
])
def test_current_prepared_permission_question_is_not_an_asserted_approval_receipt(question):
    text = "The replacement section and response are drafted and ready. " + question
    assert analyze_handoff(text) == Handoff("required-handoff", "authorization")


@pytest.mark.parametrize("text", [
    "The draft is ready. Do I have your go-ahead to post it? I received your approval.",
    "The draft is ready. Should I post it? I have your go-ahead.",
    "Nothing is drafted. Do I have permission to post a response?",
    "The section is prepared. Do you approve your publishing it?",
])
def test_approval_receipts_still_resolve_and_assistant_actor_stays_required(text):
    assert analyze_handoff(text).expectancy != "required-handoff"


def test_new_destination_does_not_turn_prepared_execution_into_fresh_work():
    assert analyze_handoff("The procedure is drafted. May I save this prepared procedure as the new handbook entry?") == Handoff("required-handoff", "authorization")
    assert analyze_handoff("The procedure is drafted. May I save a new procedure?").expectancy != "required-handoff"


def test_prose_advice_checklist_does_not_turn_confirm_into_a_workflow_gate():
    text = ("A routine documentation check usually covers titles, links and examples. "
            "Start with the title and navigation. Read the headings in sequence. "
            "Confirm that the example names are consistent. Check that the screenshot is legible. "
            "The general checklist above is the full answer.")
    assert analyze_handoff(text).expectancy != "required-handoff"


@pytest.mark.parametrize("current_request", [
    "Please approve the deployment.",
    "Confirm the account now.",
    "Attach the missing records. Once they arrive, I will finish the comparison.",
])
def test_general_advice_frame_preserves_a_separate_current_user_gate(current_request):
    assert analyze_handoff("This general checklist covers the usual checks. " + current_request).expectancy == "required-handoff"


@pytest.mark.parametrize("introduction", [
    "The last command was:",
    "The following command has already finished:",
    "",
])
def test_command_bridge_does_not_borrow_unrelated_backup_advice(introduction):
    text = ("The draft is attached. Keep a backup of the old configuration. " + introduction
            + "\n```sh\n! samplectl validate\n```\nI will revise it tomorrow.")
    assert _attention_handoff(text).expectancy != "required-handoff"


def test_current_execution_request_can_describe_a_previously_supplied_command():
    text = ("Please execute the command that was supplied and return its final status.\n"
            "```sh\n! samplectl validate\n```\n"
            "I will use that result to finish the comparison.")
    assert _attention_handoff(text) == Handoff("required-handoff", "action")
