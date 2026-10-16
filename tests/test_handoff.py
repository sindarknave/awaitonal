"""Authored behavioral contrasts, not measured classifier-evaluation data."""
import time
import subprocess
import sys

import pytest

from awaitonal.handoff import Handoff, analyze_handoff, detect_handoff, handoff_kind
from awaitonal.text import assistant_prose


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
