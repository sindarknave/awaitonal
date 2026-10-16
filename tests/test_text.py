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


@pytest.mark.parametrize("intro", [
    "Draft below, not posted:",
    "I prepared the review below (not posted).",
    "Here is the draft:",
    "Review below, not posted:",
])
@pytest.mark.parametrize("closing", [
    "Should I post this as a reply to the thread?",
    "Say the word and I'll post it.",
    "If you agree, I will post it.",
    "Would you like me to publish this draft?",
    "Should I post this as a reply\nto the thread?",
])
def test_attention_only_keeps_prepared_wrapper_and_final_assistant_permission(intro, closing):
    text = intro + "\nPlease approve the rollout.\n\nIt is safe to deploy.\n\n" + closing
    kept = response_prose(text, attention=True)
    assert kept == intro + "\n" + closing
    assert response_prose(text) == response_prose(text, attention=False)


@pytest.mark.parametrize("closing", [
    "Do I have permission to post this prepared triage reply on the issue?",
    "Can we have the goahead to apply the prepared procedure?",
    "Do I have your approval to save the replacement copy?",
    "Do you approve my applying this prepared replacement section to the guide now?",
    "Do you authorize me to apply the prepared procedure?",
    "Do you consent to our publishing the replacement copy?",
    "Do you approve us posting that?",
    "Do you authorize our committing the prepared substitution?",
])
def test_attention_permission_tail_uses_assistant_actor_and_arbitrary_prepared_object(closing):
    text = "I prepared the draft below:\nPlease approve the rollout.\n\n" + closing
    assert response_prose(text, attention=True) == "I prepared the draft below:\n" + closing
    assert response_prose(text) == "I prepared the draft below:"


@pytest.mark.parametrize("closing,expected", [
    ("**Do I have permission to post this?**", "Do I have permission to post this?"),
    ("*Do I have permission* to **post** the replacement copy?",
     "Do I have permission to post the replacement copy?"),
    ("__Do you approve my applying the prepared procedure?__",
     "Do you approve my applying the prepared procedure?"),
    ("**Do you authorize us to release\nour prepared procedure?**",
     "Do you authorize us to release\nour prepared procedure?"),
])
def test_attention_permission_tail_normalizes_paired_emphasis_only(closing, expected):
    text = "Here's the draft:\nPlease approve the rollout.\n\n" + closing
    assert response_prose(text, attention=True) == "Here's the draft:\n" + expected


@pytest.mark.parametrize("closing", [
    "Do you have permission to post this?",
    "Does she have permission to post this?",
    "Do you approve your posting this?",
    "Do you approve their applying this?",
    "Do I have permission to create another draft?",
    "Would you like me to prepare a new response?",
    "Do you authorize me to write a new article?",
    "Do you approve my publishing a new article?",
    "* Do I have permission to post this?",
    "`Do I have permission to post this?`",
    "> Do I have permission to post this?",
    "    Do I have permission to post this?",
    "I already have permission to post this.",
    "Do I have permission to post this? The answer was yes.",
])
def test_attention_permission_tail_excludes_other_actors_new_work_and_document_syntax(closing):
    text = "Here's the draft:\nPlease approve the rollout.\n\n" + closing
    assert response_prose(text, attention=True) == "Here's the draft:"


def test_attention_preparation_can_precede_the_document_intro():
    text = ("I have prepared a draft.\nHere is the report:\nPlease approve the rollout."
            "\n\nShould I post this?")
    assert response_prose(text, attention=True) == (
        "I have prepared a draft.\nHere is the report:\nShould I post this?")
    assert response_prose(text) == "I have prepared a draft.\nHere is the report:"


@pytest.mark.parametrize("intro", ["Here is my review:", "Review below:"])
def test_attention_does_not_treat_an_ordinary_review_as_document_body(intro):
    text = intro + "\nPlease upload the trace so I can finish the review."
    assert response_prose(text, attention=True) == text


@pytest.mark.parametrize("intro", [
    "Here's a draft for you to post:", "Here is a draft for you to post:",
    "Below is the draft reply:",
])
def test_attention_only_scopes_presented_draft_after_same_line_status(intro):
    text = ("The review is complete. " + intro + "\n"
            "Please approve the revised schedule and grant the request.\n\n"
            "You can post this after the owner signs off.")
    assert response_prose(text, attention=True) == "The review is complete.\n" + intro
    assert response_prose(text) == text


@pytest.mark.parametrize("text", [
    # Preparation inside a document does not prepare the assistant's work.
    "Here is the report:\nI prepared the draft.\n\nShould I post it?",
    "Here is the draft, not ready:\nPlease approve the rollout.\n\nShould I post it?",
    "I prepared the draft below yesterday:\nPlease approve the rollout.\n\nShould I post it?",
    # A document for the user to post is not an assistant permission gate.
    "Here's the draft:\nPlease approve the rollout.\n\nPlease post it when you approve.",
    "Here's the draft:\nPlease approve the rollout.\n\nOnce you approve, you can post it.",
    # Preserve clear body scope for dialogue, quoted questions, and lists.
    "Here's the draft dialogue:\nAlex: Please approve it.\n\nShould I post it?",
    'Here\'s the draft:\nPlease approve it.\n\n"Should I post it?"',
    "Here's the draft:\nPlease approve it.\n\n1. Should I post it?",
    # Neither a question inside a paragraph nor an empty document ends scope.
    "Here's the draft:\nPlease approve it.\nShould I post it?",
    "Here's the draft:\n\nShould I post it?",
    "Here's the draft:\nPlease approve it.\n\nShould we choose the cheaper plan?",
])
def test_attention_permission_recovery_does_not_promote_document_body(text):
    kept = response_prose(text, attention=True)
    assert "Should" not in kept and "Please approve" not in kept
    assert "you can post" not in kept and "Please post" not in kept


def test_attention_permission_cannot_escape_an_unclosed_document_fence():
    text = ("Here's the draft:\n```text\nPlease approve it.\n\n"
            "Should I post it?")
    assert response_prose(text, attention=True) == "Here's the draft:"


@pytest.mark.parametrize("fence", ["```", "```bash", "~~~sh"])
def test_attention_only_keeps_opaque_closed_fenced_command_presence(fence):
    closing = "~~~" if fence.startswith("~") else "```"
    text = "Next is:\n" + fence + "\n! examplectl ingest --force\n" + closing + (
        "\nOnce they are in, I will check the imports.")
    expected = "Next is:\nawaitonalcommand\nOnce they are in, I will check the imports."
    assert assistant_prose(text, attention=True, typed_code=True) == expected
    assert "examplectl" not in assistant_prose(text, attention=True)
    assert assistant_prose(text) == "Next is:\nOnce they are in, I will check the imports."


@pytest.mark.parametrize("block", [
    "```sh\n! examplectl ingest",  # Unclosed fences never provide evidence.
    '```sh\necho "! examplectl ingest"\n```',
    "```python\nraise RuntimeError('Please approve it')\n```",
    "> ```sh\n> ! examplectl ingest\n> ```",
    "    ! examplectl ingest",
])
def test_attention_command_marker_excludes_unclosed_or_noncommand_content(block):
    assert assistant_prose("Next is:\n" + block, attention=True) == "Next is:"


def test_attention_markers_cannot_be_supplied_or_produced_by_document_commands():
    assert assistant_prose("awaitonalcommand", attention=True) == ""
    assert assistant_prose("Next is awaitonalcommand.", attention=True) == "Next is ."
    assert assistant_prose("awaitonalcommand", typed_code=True) == "awaitonalcommand"
    assert assistant_prose("awaitonalcommand", typed_code=True, attention=False) == "awaitonalcommand"
    assert assistant_prose("```\n! examplectl ingest\n```", attention=True) == ""
    text = "Here's the draft:\n```sh\n! examplectl ingest\n```\nPlease review it."
    assert assistant_prose(response_prose(text, attention=True), attention=True) == (
        "Here's the draft:\nPlease review it.")


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
from awaitonal.text import MAX_PROSE_CHARS, assistant_prose, response_prose

for opener in ('[', '“', '‘'):
    text = opener * (MAX_PROSE_CHARS - len(' Done.')) + ' Done.'
    assert assistant_prose(text) == text
    assert assistant_prose(response_prose(text, attention=True), attention=True) == text

# Failed destinations must not repeatedly scan the remainder of the input.
text = '[x](' * (MAX_PROSE_CHARS // 4)
assert assistant_prose(text) == text
text = '[x] ' * ((MAX_PROSE_CHARS - 16) // 4) + '[Done](target).'
assert assistant_prose(text).endswith('Done.')
assert assistant_prose('prefix ' + '`' * (MAX_PROSE_CHARS - 11) + 'Done') == 'prefix Done'
text = 'Draft below, not posted:\\n' + 'body ' * 25000 + '\\n\\nShould I post it?'
assert response_prose(text, attention=True) == 'Draft below, not posted:\\nShould I post it?'
"""],
        timeout=5,
        check=True,
        capture_output=True,
        text=True,
    )
