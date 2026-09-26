"""Synthetic delivery contrasts; these fixtures do not estimate model quality."""
import subprocess
import sys

import pytest

from awaitonal.delivery import detect_delivery
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
