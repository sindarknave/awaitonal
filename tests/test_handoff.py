"""Authored behavioral contrasts, not measured classifier-evaluation data."""
import time

import pytest

from awaitonal.handoff import Handoff, analyze_handoff, detect_handoff, handoff_kind
from awaitonal.text import assistant_prose


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
    ("Please review it. Once your feedback is in, I can continue.", "review-requested"),
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
