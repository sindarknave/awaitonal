"""Current background work is distinct from optional plans and old activity."""
import subprocess
import sys

import pytest

from awaitonal.activity import detect_activity


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
], ids=["completion-first", "promise-first", "repeated-future-countdown", "repeated-future-status"])
def test_adversarial_temporal_and_status_claims_finish_promptly(prose, expected):
    result = subprocess.run(
        [sys.executable, "-c", "import sys; from awaitonal.activity import detect_activity; "
         "print(detect_activity(sys.stdin.read())[0])"],
        input=prose, capture_output=True, text=True, check=True, timeout=5,
    )
    assert result.stdout.strip() == expected
