"""Extraction preserves prose while staying bounded on malformed markup."""
import subprocess
import sys

import pytest

from awaitonal.text import assistant_prose


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
