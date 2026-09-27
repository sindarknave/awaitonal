"""Current background work is distinct from optional plans and old activity."""
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
])
def test_current_work_with_closing_completion_followup(text):
    assert detect_activity(text) == ("in-flight", "pending-followup")


@pytest.mark.parametrize("text", [
    "CI is running. I'll report back if any checks fail.",
    "I'm polling CI to see if the checks need attention; no action is needed.",
    "I am polling CI in the background; no action is needed from you.",
    "The checks are still running. I will report back later.",
])
def test_if_inside_current_work_does_not_hide_activity(text):
    assert detect_activity(text) == ("in-flight", "reported-prose")


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


def test_registry_corroboration_does_not_replace_current_prose():
    assert detect_activity("Understood.", 2, 1) == ("unknown", "none")
    assert detect_activity("The checks are still running.", 1, 0) == ("in-flight", "background-metadata")


def test_empty_registries_still_contradict_a_pending_followup():
    text = "The deploy is still running. I'll report back once it completes."
    assert detect_activity(text, 0, 0) == ("unknown", "empty-background-registry")
    assert detect_activity(text, 0, None) == ("in-flight", "pending-followup")
    assert detect_activity(text, 1, 0) == ("in-flight", "pending-followup")
