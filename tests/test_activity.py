"""Current background work is distinct from optional plans and old activity."""
import subprocess
import sys

import pytest

from awaitonal.activity import completion_dependency, detect_activity


@pytest.mark.parametrize("text", [
    "Pushed the fix. CI is still running on the new head; I'm polling it in the background and I'll report the result when it lands.",
    "The evaluation run is going and should take about thirty minutes. I'll read the results when it finishes.",
    "The deploy is still running. I'll report back once it completes.",
    "The job is in progress. We'll inspect the output when it finishes.",
    "The build is running. I will review the diff once it is ready.",
    "I'm monitoring CI. I'll report the verdict when it lands.",
    "CI is running. I'll check the results once it finishes. No response is required.",
    "Earlier CI failed, but the new build is running. I'll report the result when it finishes.",
    "CI is running. I'll report the result when it lands, if any failures appear.",
    "The import is still running, about a third done. I'll send the summary when it completes.",
    "The timer has about five minutes left; when it goes off I'll repeat the check.",
    "Our timer has 30 seconds remaining. Once the timer goes off, we'll check the results.",
    "The checks are running. When they complete, I'll report back.",
    "Pushed the fix. The checks are running now and I'm keeping an eye on them.",
    "The build is running and we're currently keeping an eye on it.",
])
def test_current_work_with_closing_completion_followup(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "I'm polling CI to see if the checks need attention; no action is needed.",
    "I am polling CI in the background; no action is needed from you.",
])
def test_if_inside_current_work_does_not_hide_activity(text):
    assert detect_activity(text) == ("in-flight", "reported-prose")


@pytest.mark.parametrize("text", [
    "CI is running. I'll report back if any checks fail.",
    "The checks are still running. I will report back later.",
])
def test_explicit_closing_report_promise_does_not_need_completion_phrase(text):
    # A pending report is still current work after a delivered change. The
    # promise need not use the special wording "when it finishes".
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "I'll report the result when it lands.",
    "I'll read the results when it finishes.",
    "I will monitor CI and report back later.",
    "CI will be running later. I will update you.",
    "CI is going to be running soon. I'll report back once it completes.",
    "CI is going  to be running soon. I'll report back once it completes.",
    "CI was running. I'll report the result when it lands.",
    "Earlier the CI job was running. I'll report the result when it lands.",
    "Previously I was monitoring CI. I will report back.",
    "If CI is running, I'll report the result when it lands.",
    "When CI is running, I'll report back once it completes.",
    "Once the build is running, I'll report back.",
    "I'll report back if CI is running.",
    "CI is running if you approve. I'll report back once it completes.",
    "Would you like me to monitor CI in the background?",
    "I can also monitor CI and report the result when it lands.",
    "Happy to check the results when it finishes if you want.",
    "CI is running. I'll report the result when it lands if you want.",
    "CI is running; if you want, I'll report back once it completes.",
    "The migration is merged and the backfill finished cleanly. Happy to write the follow-up ticket if you want.",
    "The documentation says CI is running. I'll report back.",
    "The import was running. I'll send the summary when it completes.",
    "If the import is running, I'll send the summary when it completes.",
    "The import is still running. I'll send the summary when it completes if you want.",
    "The timer will have five minutes left. When it goes off I'll repeat the check.",
    "The timer had about five minutes left. When it goes off I'll repeat the check.",
    "If the timer has five minutes left, I'll repeat the check when it goes off.",
    "The timer has about five minutes left.",
    "When the timer goes off I'll repeat the check.",
    "The timer has five minutes left; when it goes off I'll repeat the check if you want.",
    "The timer has five minutes left; when it goes off I can repeat the check.",
    "Pushed the fix. The checks were running and I'm keeping an eye on them.",
    "Pushed the fix. If the checks are running, I'm keeping an eye on them.",
    "Pushed the fix. The checks are running and I'm not keeping an eye on them.",
    "Pushed the fix. The checks are running; I can also keep an eye on them.",
    "I am monitoring CI and I'm keeping an eye on it.",
])
def test_history_conditionals_and_optional_future_offers_are_not_current_work(text):
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("ending", [
    "CI finished and every check passed.",
    "The deploy completed successfully.",
    "The evaluation run has finished.",
    "The job was canceled.",
    "It has finished successfully.",
    "All done.",
    "CI is no longer running.",
    "CI is not running.",
    "I'm no longer monitoring CI.",
    "The import has finished.",
    "The timer has expired.",
])
def test_later_completion_or_stopped_monitor_clears_pending_followup(ending):
    text = "CI is running. I'll report the result when it lands. " + ending
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("text", [
    "The job is still running. It has not finished. I'll report once it finishes.",
    "The job is running and should be completed soon. I'll report back when it finishes.",
    "The job is running. I'll report back once the job has finished.",
])
def test_negated_or_future_completion_does_not_clear_current_work(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


def test_old_followup_is_not_the_current_closing_status():
    text = "CI is running. I'll report back when it finishes. Here is the requested report."
    assert detect_activity(text) == ("in-flight", "reported-prose")


def test_passive_monitor_does_not_get_pending_followup_evidence():
    text = "I exported the spreadsheet. I am polling CI in the background; no action is needed."
    assert detect_activity(text, 1, 0) == ("in-flight", "background-metadata")


def test_bare_background_monitor_after_delivery_remains_passive():
    text = "I exported the spreadsheet. I'm keeping an eye on CI in the background."
    assert detect_activity(text, 1, 0) == ("unknown", "none")


def test_later_delivery_clears_closing_current_run_monitor():
    text = "The checks are running and I'm keeping an eye on them. Here is the requested report."
    assert detect_activity(text) == ("in-flight", "reported-prose")


def test_registry_corroboration_does_not_replace_current_prose():
    assert detect_activity("Understood.", 2, 1) == ("unknown", "none")
    assert detect_activity("The checks are still running.", 1, 0) == ("in-flight", "background-metadata")


def test_empty_registries_still_contradict_a_pending_followup():
    text = "The deploy is still running. I'll report back once it completes."
    assert detect_activity(text, 0, 0) == ("unknown", "empty-background-registry")
    assert detect_activity(text, 0, None) == ("in-flight", "pending-followup")
    assert detect_activity(text, 1, 0) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "The replica of the primary ledger is still synchronizing; I'll let you know when it catches up.",
    "That conversion is underway. We'll share a summary once the result is available.",
    "The queue for the two archives is being drained. I'll report back.",
    "The second pass through every file is now processing; I'll be back with the findings.",
    "I'll update you once it returns; the remote operation is still executing.",
    "Once both sides have caught up, I'll send the findings. Both replicas are currently synchronizing.",
    "It is still parsing. I will circle back with a summary.",
    "It's underway, and I'll let you know once it ends.",
    "They're comparing the snapshots. We'll tell you what changed after they are done.",
    "The transfer to the replacement storage is ongoing. I will give you an update.",
    "The reconciliation of all six partitions is in progress. I'll keep you posted.",
    "I'm tracing the intermittent issue. I'll share the results when the trace is ready.",
    "We've started the restore. It is still copying, and I'll send you an update.",
    "The upload of the large archive is under way; as soon as it completes, I'll inspect the output.",
    "After the reconciliation has settled, I'll relay the results. It is still running.",
    "I'll report back. The operation that combines the old and new snapshots is still processing.",
    "Pushed the change. The validation of the renamed modules is running. I'll update you.",
    "The remote invocation is currently waiting for a worker; I'll let you know when it returns.",
    "The countdown has roughly two minutes remaining. When it goes off, I'll repeat the measurement.",
    "The replica isn't done and is still synchronizing. I'll report back.",
    "The queue is still draining and no retries are needed. I'll send you an update.",
    "The comparison remains underway. I'll circle back with the findings.",
    "The reconciliation continues in the background. I'll return with a summary after it completes.",
    "Once it's ready, I'll attach the output here. The reformatting is being worked through.",
    "After both stages are complete, I'll package the final folder. They are still processing.",
    "Queue replay: still processing. When it's complete, I'll bring the output back here.",
    "The two replicas remain synchronizing. I'll report back when they finish.",
])
def test_current_work_and_followup_are_independent_of_subject_and_clause_order(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "The replica was synchronizing. I'll let you know when it catches up.",
    "The conversion will be underway tomorrow. I'll give you an update.",
    "If the archive is being drained, I'll report back.",
    "Once the replicas are synchronizing, I'll let you know when they finish.",
    "The second pass is no longer processing. I'll share the findings.",
    "It isn't parsing. I will circle back with a summary.",
    "The transfer is ongoing. I can share a summary if you'd like.",
    "The reconciliation is in progress. If you want, I'll keep you posted.",
    "The operation is running. I won't report back.",
    "That explanation is confusing. I'll give you an update.",
    "The archive is missing. I'll notify you.",
    "The findings are interesting. I'll report back.",
    "I'll let you know when the transfer ends.",
    "The remote operation is going to be processing next week. I'll report back.",
    "The reconciliation will continue in the background. I'll return with a summary afterward.",
    "The comparison doesn't remain underway. I'll report back.",
    "The replay is still processing. When it is ready, I can attach the output if you want.",
    "No transfer is running. I'll report back when it ends.",
    "Nothing is running. I'll report back tomorrow.",
    "Nobody is working on it. I will report back tomorrow.",
    "Neither is processing. I'll update you.",
    "None of the replicas are copying. I'll let you know when they finish.",
    "The workaround is annoying. I'll report back tomorrow.",
    "This is amazing. I will send you an update.",
    "The finding is encouraging. I'll let you know when it is ready.",
    "The compiler is working correctly. I'll report back after lunch.",
    "The system is working as expected. I'll give you an update.",
    "The issue is blocking our users. I'll report back tomorrow.",
])
def test_structural_activity_requires_a_current_nonoptional_claim(text):
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("text", [
    "I'm waiting for the countdown to expire. I'll check again when it does.",
    "Waiting for the transfer to finish; then I'll inspect the result.",
    "Still awaiting the final output. I'll report back once it arrives.",
    "The result is pending. I'll let you know when it arrives.",
    "The second run remains pending. I'll report back after it finishes.",
    "The timer hasn't expired yet. Once it does, I'll repeat the measurement.",
    "The interval has not elapsed yet. I'll run the check when it does.",
    "The remote call hasn't returned yet. I'll send you an update.",
    "The remote call hasn't returned yet, and I'll send you an update.",
    "Both passes haven't finished yet. I'll check the output when they do.",
    "The comparison is still not ready yet. I'll return with the results.",
    "The comparison is still not ready yet, and I'll return with the results.",
    "The response isn't ready yet. I'll report back once it arrives.",
    "We await completion of the replication. I'll share the findings when it ends.",
    "We're waiting for the new snapshot; I'll send an update when it arrives.",
    "The job is waiting on a free slot. I'll update you when it returns.",
    "The job is waiting for a worker, and I'll notify you once it returns.",
    "We are awaiting the output and I'll let you know when it arrives.",
    "The result is pending and I'll send you an update once it's available.",
    "I'm waiting for your script to finish. I'll report back once it does.",
    "Your export is pending. I'll send you an update when it completes.",
    "Waiting for the cooldown to elapse. I'll then make another measurement.",
    "The remote call is awaiting completion; afterward, I'll attach the output.",
    "The countdown is waiting to expire. I'll check again once it's over.",
    "When the new output arrives, I'll review the result. We're still awaiting it.",
    "Once the pause has elapsed, I'll repeat the request. The timer is still pending.",
    "I will share the findings when they arrive. The output is pending.",
    "The queued operation is waiting for a worker. Then we'll examine the result.",
    "The retries are running. I'll check the output when they finish.",
    "The first attempt failed, but the retry is awaiting a worker. I'll report back.",
])
def test_current_process_waiting_and_dependent_followup_are_in_flight(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "We're waiting on the completion of the compaction. I'll get back to you afterward.",
    "The atlas pass is still in the queue. I'll return with the outcome.",
    "The second invocation remains queued. I'll post the findings here.",
    "Shard reconciliation: still queued. I'll get back to this thread after completion of the pass.",
    "The checksum response isn't back yet. I'll get back to you when it comes back.",
    "The scanner has not come back yet. I'll send you an update.",
    "The scan has yet to return. I'll get back to you with its findings.",
    "Still in the queue. The results will be shared once the pass completes.",
    "Both invocations haven't come back yet. Once they return, I'll inspect the payload.",
    "The submitted validation is still pending. The findings will be posted here once it finishes.",
    "An update will be provided when the comparison is complete. It remains in the queue.",
    "I'll get back to this message once the merge is through. The operation is currently queued.",
    "After completion of the transfer, I'll collect its output. We're still waiting on it.",
    "The summary will be shared afterward. The confirmation from the remote service isn't back yet.",
    "I'm awaiting completion of the unnamed pass. The results will be reported when it's done.",
    "I'll get back to you after the refresh comes back. The refresh remains pending.",
])
def test_current_wait_states_combine_with_definite_handback_in_either_order(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "The atlas pass will be in the queue tomorrow. I'll get back to you afterward.",
    "The invocation was queued. I'll post the findings here.",
    "If the invocation remains queued, I'll get back to this thread.",
    "The checksum response was not back yet. I'll get back to you when it comes back.",
    "The scan had yet to return. I'll get back to you with its findings.",
    "If still in the queue, I'll send an update.",
    "An update will be provided when the comparison is complete.",
    "I'll get back to this message after completion of the pass.",
    "The result is queued. I can get back to you if you'd like.",
    "The result is queued. If you want, the findings will be shared here.",
    "Your approval is still pending. The findings will be posted once you approve.",
    "Your confirmation isn't back yet. I'll get back to you afterward.",
    "Authorization: still queued. I'll get back to you afterward.",
    "No invocation remains queued. I'll send the results tomorrow.",
    "Nothing is in the queue. I'll get back to you afterward.",
    "The result is no longer queued. I'll get back to this message.",
])
def test_queue_and_report_grammar_preserves_human_future_and_optional_boundaries(text):
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("handback", [
    "No summary will be posted.",
    "The old message said the summary will be shared afterward.",
    'The previous message says "The findings will be posted here."',
    '"The results will be shared here," the document promises.',
    "The summary will be posted by the customer tomorrow.",
    "The findings will be shared here by another agent once the pass finishes.",
    "The summary will not be shared here.",
    "The results will be shared if requested.",
    "A summary will be posted if there is interest.",
    "The findings will be posted only if someone asks for them.",
    "Results will be shared when requested.",
    "The results will be provided once needed.",
])
def test_passive_reports_need_a_current_assistant_handback(handback):
    assert detect_activity("The result is queued. " + handback) == ("unknown", "none")


@pytest.mark.parametrize("handback", [
    "The results will be posted here.",
    "The summary will be shared by me once the pass finishes.",
    "The findings will be shared here once the pass is completed by the scheduler.",
])
def test_direct_passive_reports_can_commit_to_a_handback(handback):
    assert detect_activity("The result is queued. " + handback) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("wait_target", [
    "you to release it",
    "your approval",
    "your confirmation",
])
def test_user_wait_attached_to_a_queue_assertion_blocks_process_activity(wait_target):
    text = f"The job is queued, waiting for {wait_target}. I'll send an update afterward."
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("wait_target", ["a worker", "a free slot", "the next cycle"])
def test_process_wait_attached_to_a_queue_assertion_remains_current(wait_target):
    text = f"The job is queued, waiting for {wait_target}. I'll send an update afterward."
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "The ledger export is still assembling its CSV. As soon as the file becomes available, I will check the row count and send you the link.",
    "Validation of the bundle is underway. I will return with its report as soon as the service has produced it.",
    "I am keeping an eye on that job and will post its final status here after the merge and verification complete.",
    "We're keeping an eye on the submitted pass and will update you once its output gets ready.",
    "The conversion remains underway. When the service has generated the refreshed archive, I'll inspect its entries.",
    "As soon as the output gets available, I'll review it. The conversion is still processing.",
])
def test_completion_transitions_and_assistant_coordinated_future_generalize(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "The export was assembling its CSV. As soon as the file becomes available, I will inspect it.",
    "Validation will be underway tomorrow. I'll return with its report when the service has produced it.",
    "I will keep an eye on that job and will post its status after verification completes.",
    "I am keeping an eye on that job and can post its final status after verification completes.",
    "The support team is keeping an eye on that job and will post its status after verification completes.",
    "I am not keeping an eye on that job and will post its final status after verification completes.",
    "If I am keeping an eye on that job, I will post its final status after verification completes.",
    "The conversion remains underway. When the service has generated the archive, I can inspect it if you want.",
])
def test_completion_events_do_not_invent_current_work_or_an_assistant_commitment(text):
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("text", [
    "I am keeping an eye on your response and will update you when it arrives.",
    "We are keeping an eye on your approval and will report back once it is available.",
    "I'm keeping an eye on your confirmation. I'll send an update when it arrives.",
])
def test_named_monitor_does_not_turn_human_input_into_process_activity(text):
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("text", [
    "I am keeping an eye on the batch and will update you when it finishes.",
    "We are keeping an eye on your batch and will report back once it completes.",
])
def test_named_monitor_preserves_process_targets_including_user_owned_jobs(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "Underway now is the verification job. I'll send you an update when it finishes.",
    "Still active: the named reconciliation batch. I will post its result after it completes.",
    "In progress currently are both replicas. Once they settle, I'll review their output.",
    "Currently ongoing: the archive comparison. We'll report back when it ends.",
    "I am waiting for its checksum comparison to complete, after which I will tell you which archives passed.",
    "We await the second invocation to finish, after which we'll inspect the returned data.",
    "The render queue is producing frames. You will get the preview and my notes after the render completes.",
    "The conversion remains underway. You'll receive its output once it becomes ready.",
    "The remote pass is still running. You will be sent the summary by me when the pass finishes.",
    "The upload is in progress. You will get the report from us after it returns.",
])
def test_inverted_status_relative_completion_and_recipient_promises(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "Previously underway was the verification job. I'll report back after it finishes.",
    "If still active: the reconciliation batch. I'll send an update when it completes.",
    "Not active: the reconciliation batch. I'll send an update when it completes.",
    "Still active: your approval. I'll report back when it arrives.",
    "Underway now is your review. I will post an update after it finishes.",
    "I will wait for its checksum comparison to complete, after which I will tell you which archives passed.",
    "I am waiting for your review to complete, after which I will send an update.",
    "I am waiting for the comparison to complete, after which I can inspect its output if you want.",
    "The queue was producing frames. You will get the preview after the render completes.",
    "You will get the preview after the render completes.",
    "The conversion remains underway. You can receive its output once it becomes ready.",
    "The conversion remains underway. You will receive its output if requested after it finishes.",
    "The conversion remains underway. You will receive its output from the customer once it becomes ready.",
    "The job is still running. The customer says you will receive the summary when it finishes.",
    "The conversion remains underway. You will get the checks running once it completes.",
    "The conversion remains underway. You will review the output once it becomes ready.",
    "The remote pass is running. You will be sent the summary by another agent when it finishes.",
])
def test_new_constructions_preserve_current_actor_and_definite_receipt_boundaries(text):
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("text, expected", [
    ("I will summarize the result once the remaining checks have returned.",
     "once the remaining checks have returned"),
    ("After the output becomes available, I'll inspect it. One source remains unverified.",
     "After the output becomes available"),
    ("I will inspect the result when the service has produced it. One part is unfinished.",
     "when the service has produced it"),
    ("I am keeping an eye on the job and will post here after verification completes.",
     "after verification completes"),
    ("I’ll inspect the result once it becomes ready.", "once it becomes ready"),
])
def test_completion_dependency_span_excludes_main_promise_and_other_limitations(text, expected):
    span = completion_dependency(text)
    assert span is not None
    assert text[slice(*span)] == expected


@pytest.mark.parametrize("text", [
    "If the job becomes available, I will review it.",
    "Earlier I said I'll review the output when it becomes available.",
    "I'll inspect the output once it becomes available if you want.",
    "I can inspect the output when it becomes available.",
    "I'll inspect the output when the service never returns it.",
])
def test_completion_dependency_requires_an_affirmative_assistant_commitment(text):
    assert completion_dependency(text) is None


@pytest.mark.parametrize("text", [
    "I'm waiting for your approval. I'll report back after you approve.",
    "We are awaiting your reply. I'll send you an update.",
    "Your confirmation is pending. I'll report back once it arrives.",
    "Approval remains pending. I'll let you know when it arrives.",
    "Approval: still pending. I'll report back.",
    "I am waiting for you to finish the review. I'll report back afterward.",
    "The authorization isn't ready yet. I'll share an update.",
    "I will wait for the timer to expire. Then I'll repeat the measurement.",
    "I'll await the output and report back when it arrives.",
    "The result will be pending. I'll report back when it arrives.",
    "The result was pending. I'll share the findings when it arrives.",
    "Earlier I was waiting for the remote call. I'll report back.",
    "If the result is pending, I'll report back once it arrives.",
    "When the result is pending, I'll share an update.",
    "I am no longer waiting for the transfer. I'll report back tomorrow.",
    "The output is no longer pending. I'll send you an update.",
    "Nothing is pending. I'll report back when it arrives.",
    "No result is pending. I'll share the findings.",
    "I'm waiting for the countdown to expire.",
    "The output hasn't arrived yet. I can report back if you want.",
    "The result is pending. If you want, I'll share an update.",
    "Waiting for the transfer to finish; then I can inspect the output if you'd like.",
    "The transfer is waiting for a worker. I won't report back.",
    "I'll check again when the timer expires.",
    "Then I'll inspect the output once it is ready.",
    "The interval elapsed. I'll repeat the request shortly.",
])
def test_process_waiting_does_not_invent_user_obligations_or_current_work(text):
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("ending", [
    "The remote call has returned.",
    "The countdown has expired.",
    "The pending result is now ready.",
    "I'm no longer waiting.",
])
def test_later_completion_clears_process_waiting(ending):
    text = "Waiting for the remote call to complete. I'll report back. " + ending
    assert detect_activity(text) == ("unknown", "none")


@pytest.mark.parametrize("ending", [
    "The synchronization has finished.",
    "The replication is now complete.",
    "The transfer is no longer copying.",
    "It is done.",
    "They aren't comparing the snapshots anymore.",
    "The replication has finished, and I'll send you a summary.",
    "The transfer is complete; I'll share the results shortly.",
])
def test_later_arbitrary_subject_completion_clears_followup(ending):
    text = "The replicas are synchronizing. I'll update you. " + ending
    assert detect_activity(text) == ("unknown", "none")


def test_finished_adjective_in_unrelated_delivery_does_not_claim_running_work_ended():
    text = "The replicas are synchronizing. I'll update you. I wrote a report of completed tasks."
    assert detect_activity(text) == ("in-flight", "reported-prose")


@pytest.mark.parametrize("prose,expected", [
    ("The replica is running. " + "when " * 20_000 + "it finishes, I'll report back.", "in-flight"),
    ("The replica is running. I'll report back " + "when " * 20_000 + "it finishes.", "in-flight"),
    ("will have five minutes left and " * 3_000 + "I'll report back.", "unknown"),
    ("It is going to " * 8_000 + "run. I'll report back.", "unknown"),
    ("The operation is waiting for your approval and " * 2_000 + "I'll report back.", "unknown"),
    ("The operation is pending approval and " * 2_500 + "I'll report back.", "unknown"),
], ids=["completion-first", "promise-first", "repeated-future-countdown", "repeated-future-status",
        "repeated-user-wait", "repeated-pending-approval"])
def test_adversarial_temporal_and_status_claims_finish_promptly(prose, expected):
    result = subprocess.run(
        [sys.executable, "-c", "import sys; from awaitonal.activity import detect_activity; "
         "print(detect_activity(sys.stdin.read())[0])"],
        input=prose, capture_output=True, text=True, check=True, timeout=5,
    )
    assert result.stdout.strip() == expected
