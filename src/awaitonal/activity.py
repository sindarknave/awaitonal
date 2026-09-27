"""Conservative ongoing-work evidence, independent of attention and delivery."""
import re

from .text import MAX_PROSE_CHARS, sentences

_RUNNING = re.compile(
    r"\b(?:checks?|tests?|ci|build|job|task|deploy(?:ment)?|analysis|evaluation|run)\b[^.!?\n]{0,35}"
    r"\b(?:is |are )(?:still |currently |now )?(?:running|in progress|going(?!\s+to\b))\b|"
    r"\b(?:i am|i'm|we are|we're) (?:still |currently )?(?:monitoring|polling|watching|investigating)\b", re.I)
_FOLLOWUP = re.compile(
    r"\b(?:i will|i'll|we will|we'll) (?:report (?:back|(?:the )?(?:results?|verdict|outcome))|"
    r"follow up|update you|send (?:an? |the )?update|notify you)\b", re.I)
_COMPLETION_FOLLOWUP = re.compile(
    r"\b(?:i will|i'll|we will|we'll) (?:report|read|review|check|inspect|follow up|update you|notify you|send)\b"
    r"[^.!?\n]{0,100}\b(?:when|once)\b[^.!?\n]{0,60}"
    r"\b(?:lands?|finishes?|completes?|(?:is|are) (?:done|ready|finished|complete)|"
    r"(?:has|have) (?:landed|finished|completed))\b", re.I)
_POLLING = re.compile(r"\b(?:monitoring|polling|watching)\b[^.!?\n]{0,55}\b(?:background|ci|checks?)\b", re.I)
_QUIET = re.compile(r"\bno (?:action|reply|response) (?:is )?(?:needed|required)\b", re.I)
_EXCLUDED = re.compile(r"\b(?:earlier|previously|yesterday|example|documentation|would you like|let me know if|can also|happy to)\b", re.I)
_CONDITIONAL = re.compile(
    r"^(?:if|unless|when|once|assuming|provided)\b|"
    r"\bif you (?:want|like|would like|approve|authorize|confirm|choose|decide)\b", re.I)
_NEGATED = re.compile(r"\b(?:not|never|no longer|isn't|aren't|hasn't|haven't|won't)\b", re.I)
_FUTURE = re.compile(r"\b(?:will|would|could|should|might|may|going to)\b", re.I)
_ENDED = re.compile(
    r"\b(?:ci|checks?|tests?|build|job|task|deploy(?:ment)?|analysis|evaluation|run|it)\b"
    r"[^.!?\n]{0,30}\b(?:finished|completed|passed|stopped|cancelled|canceled|landed)\b|"
    r"\b(?:all done|everything is (?:complete|finished))\b", re.I)
_NO_LONGER_RUNNING = re.compile(
    r"\b(?:ci|checks?|tests?|build|job|task|deploy(?:ment)?|analysis|evaluation|run)\b"
    r"[^.!?\n]{0,30}\b(?:is not|are not|isn't|aren't|is no longer|are no longer) (?:running|in progress)\b|"
    r"\b(?:i am|i'm|we are|we're) (?:not|no longer) (?:monitoring|polling|watching|investigating)\b", re.I)


def detect_activity(prose: str, background_tasks: int | None = None,
                    session_crons: int | None = None) -> tuple[str, str]:
    """Return activity and evidence source, never deriving work from count alone.

    Counts are session-wide and therefore only corroborate an explicit current
    claim. Missing registry data is unknown, while two available empty registries
    contradict a background claim. A later completion clears earlier activity.
    A closing promise tied to completion is stronger than a passive monitor:
    the caller may use pending-followup to distinguish it from a final delivery.
    """
    if not isinstance(prose, str) or len(prose) > MAX_PROSE_CHARS:
        return "unknown", "none"
    running = followup = polling = quiet = closing_followup = False
    # A conditional clause must not hide an independent current status before
    # it, nor may a historical clause before "but" hide a current status after.
    parts = [part.strip(" ,") for sentence in sentences(prose)
             for part in re.split(r";|\b(?:but|however)\b", sentence, flags=re.I) if part.strip(" ,")]
    for part in parts:
        if _EXCLUDED.search(part) or _CONDITIONAL.search(part):
            closing_followup = False
            continue
        # A future subordinate clause ("when CI has finished") is not a
        # completion now. Negated and prospective completions are not either.
        current = re.split(r"\b(?:when|once|if)\b", part, maxsplit=1, flags=re.I)[0]
        if (_NO_LONGER_RUNNING.search(current) or
                _ENDED.search(current) and not (_NEGATED.search(current) or _FUTURE.search(current))):
            running = polling = followup = quiet = closing_followup = False
        if not _NEGATED.search(current):
            running |= bool(_RUNNING.search(current))
            polling |= bool(_POLLING.search(current))
        completion_followup = bool(_COMPLETION_FOLLOWUP.search(part))
        followup |= bool(_FOLLOWUP.search(part)) or completion_followup
        # Only a closing follow-up can override a delivered item elsewhere in
        # the reply. A trailing "no action needed" does not change that status.
        closing_followup = completion_followup or closing_followup and bool(_QUIET.search(part))
        quiet |= bool(_QUIET.search(part))
    observed = any(type(n) is int and n > 0 for n in (background_tasks, session_crons))
    if running and (followup or polling and quiet or observed):
        if background_tasks == 0 and session_crons == 0:
            return "unknown", "empty-background-registry"
        return "in-flight", ("pending-followup" if closing_followup else
                             "background-metadata" if observed else "reported-prose")
    return "unknown", "none"
