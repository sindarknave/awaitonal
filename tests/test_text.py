"""Extraction preserves prose while staying bounded on malformed markup."""
import subprocess
import sys

import pytest

from awaitonal.text import assistant_prose, response_prose


@pytest.mark.parametrize("intro", [
    "Here's the draft:", "Here is the report:", "Below is the email:",
    "I wrote the reply below:", "Draft reply:", "**Draft email:**", "Here’s the message:",
])
def test_explicit_plain_document_body_is_not_response_prose(intro):
    text = intro + "\nChoose the cheaper plan. It is safe to deploy.\n\n## Next steps\nPlease approve the purchase."
    kept = response_prose(text)
    assert "Choose" not in kept and "safe" not in kept and "Please approve" not in kept
    assert "draft" in kept.lower() or any(word in kept.lower() for word in ("report", "email", "reply", "message"))


@pytest.mark.parametrize("body", [
    "> Choose the cheaper plan.\n> Please approve the purchase.",
    "```text\nChoose the cheaper plan.\nPlease approve the purchase.\n```",
    "~~~\nChoose the cheaper plan.\nPlease approve the purchase.\n~~~",
])
def test_quoted_and_fenced_document_boundaries_preserve_following_wrapper(body):
    kept = response_prose("Here's the draft:\n" + body + "\nPlease review it.")
    assert "Choose" not in kept and "Please approve" not in kept
    assert "Please review it." in kept


def test_explicit_return_to_conversation_ends_plain_document_scope():
    text = "Here's the draft:\nChoose the cheaper plan.\n\nOutside the draft, I need your approval to post it."
    kept = response_prose(text)
    assert "Choose" not in kept
    assert "I need your approval to post it." in kept


@pytest.mark.parametrize("text", [
    "Here is my analysis:\nI recommend the smaller queue.",
    "Here is the answer:\nI would keep the old path.",
    "I wrote a helper to generate the report:\nThe parser is fixed.",
    "```text\nHere's the draft:\n```\nI recommend the smaller queue.",
    "> Here's the draft:\nI recommend the smaller queue.",
])
def test_answer_analysis_and_document_mentions_do_not_start_document_scope(text):
    assert response_prose(text) == text


def test_document_body_fences_cannot_fake_an_end_marker():
    text = "Here's the report:\n# Title\n```\nEnd of draft\nPlease approve it.\n```\nIt is safe to deploy."
    assert response_prose(text) == "Here's the report:"


@pytest.mark.parametrize("location", [
    "https://example.com/report", "https://claude.ai/artifacts/abc",
    "[report](https://example.com/report)", "awaitonalartifactlink",
])
def test_presented_document_locations_keep_their_evidence(location):
    text = "Here is your report: " + location
    assert response_prose(text) == text


def test_link_scheme_colons_do_not_start_document_bodies():
    text = "Here is your [report](https://claude.ai/artifacts/abc)."
    assert response_prose(text) == text


@pytest.mark.parametrize("intro", [
    "The requested note for `handover.md` is:", "Your document content follows:",
    "Draft dialogue for the training slide:",
])
def test_named_content_and_draft_titles_introduce_document_bodies(intro):
    text = intro + "\nPlease approve this so I can publish it.\nThis is safer."
    assert response_prose(text) == intro


@pytest.mark.parametrize("location", [
    "https://claude.ai/artifacts/abc", "[Download](sandbox:/mnt/data/report.md).",
    "[Download](\nsandbox:/mnt/data/report.md)",
])
def test_next_line_artifact_locations_are_not_document_body_text(location):
    text = "Here is your report:\n" + location
    assert response_prose(text) == text


@pytest.mark.parametrize("text,expected", [
    ("[Done](https://example.com).", "Done."),
    ("[Done](one) and [verified](two).", "Done and verified."),
    ("[Done [with caveats](target).", "Done [with caveats."),
    ("[Done\nwith caveats](target).", "Done\nwith caveats."),
    ("[](target) [Done](target).", "[](target) Done."),
    ("[broken] [Done](target).", "[broken] Done."),
    ("[broken [label] [Done](target).", "[broken [label] Done."),
    ("[Done](unfinished", "[Done](unfinished"),
    ("[[[Done", "[[[Done"),
    ('The log said "I refuse". Done.', "The log said . Done."),
    ("The log said “I refuse”. Done.", "The log said . Done."),
    ("The log said ‘I refuse’. Done.", "The log said . Done."),
    ('“The log said "I refuse".” Done.', "Done."),
    ('"The log said “I refuse”." Done.', "Done."),
    ("““I refuse”. Done.", ". Done."),
    ("“unfinished\nDone.”", "“unfinished\nDone.”"),
    ('“unfinished "I refuse". Done.', "“unfinished . Done."),
    ("I can't continue. 'Quoted refusal' was removed.", "I can't continue. was removed."),
])
def test_link_and_quote_extraction(text, expected):
    assert assistant_prose(text) == expected


@pytest.mark.parametrize("literal", [
    "`summary.customext`", "`out/notes`", "`/tmp/output`", "`../draft.txt`",
    '"Release reply.final"', "'findings.md'", "“Draft response.text”",
])
def test_typed_literal_keeps_file_shape_without_contents(literal):
    prose = assistant_prose("I saved the draft to " + literal + ".", typed_code=True)
    assert prose == "I saved the draft to awaitonalfile ."
    assert "summary" not in prose and "tmp" not in prose


@pytest.mark.parametrize("literal", [
    '`please approve the deployment`', '`raise RuntimeError("I refuse")`',
    '`! examplectl auth login`',
])
def test_typed_code_never_promotes_instructions_inside_a_literal(literal):
    assert assistant_prose("The example contains " + literal + ".", typed_code=True) == (
        "The example contains awaitonalcode .")
    assert assistant_prose(literal, typed_code=True) == ""


def test_literal_markers_cannot_be_supplied_as_plain_text():
    assert assistant_prose("awaitonalfile awaitonalcode awaitonalliteral", typed_code=True) == ""
    assert assistant_prose("Done. awaitonalfile", typed_code=True) == "Done."


def test_quoted_argument_preserves_shape_but_never_its_assertions():
    assert assistant_prose('"Pine" is the better choice.', typed_code=True) == (
        "awaitonalliteral is the better choice.")
    assert assistant_prose('The log said "Please approve. I refuse."', typed_code=True) == (
        "The log said awaitonalliteral")
    assert assistant_prose('"Please approve. I refuse."', typed_code=True) == ""


def test_typed_literals_preserve_existing_nonliteral_punctuation_behavior():
    assert assistant_prose("[" * 65536, typed_code=True) == "[" * 65536
    assert assistant_prose("`example`.", typed_code=True) == "awaitonalcode ."


def test_maximum_length_malformed_markup_finishes_promptly():
    # A subprocess bounds a regression's runtime instead of letting a quadratic
    # scan hold pytest for minutes. Five seconds allows ample CI scheduling
    # headroom; all these cases together normally take well under one second.
    subprocess.run(
        [sys.executable, "-c", """
from awaitonal.text import MAX_PROSE_CHARS, assistant_prose

for opener in ('[', '“', '‘'):
    text = opener * (MAX_PROSE_CHARS - len(' Done.')) + ' Done.'
    assert assistant_prose(text) == text

# Failed destinations must not repeatedly scan the remainder of the input.
text = '[x](' * (MAX_PROSE_CHARS // 4)
assert assistant_prose(text) == text
text = '[x] ' * ((MAX_PROSE_CHARS - 16) // 4) + '[Done](target).'
assert assistant_prose(text).endswith('Done.')
assert assistant_prose('prefix ' + '`' * (MAX_PROSE_CHARS - 11) + 'Done') == 'prefix Done'
"""],
        timeout=5,
        check=True,
        capture_output=True,
        text=True,
    )
