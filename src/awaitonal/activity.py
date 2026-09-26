"""Conservative ongoing-work evidence, independent of attention and delivery."""
import re

from .text import MAX_PROSE_CHARS, sentences

_RUNNING = re.compile(
    r"\b(?:checks?|tests?|ci|build|job|task|deployment|analysis)\b[^.!?\n]{0,35}"
    r"\b(?:is |are )(?:still |currently |now )?(?:running|in progress)\b|"
    r"\b(?:i am|i'm|we are|we're) (?:still |currently )?(?:monitoring|polling|watching|investigating)\b", re.I)
_FOLLOWUP = re.compile(
    r"\b(?:i will|i'll|we will|we'll) (?:report (?:back|the results?)|follow up|update you|send (?:an? |the )?update|notify you)\b", re.I)
_POLLING = re.compile(r"\b(?:monitoring|polling|watching)\b[^.!?\n]{0,55}\b(?:background|ci|checks?)\b", re.I)
_QUIET = re.compile(r"\bno (?:action|reply|response) (?:is )?(?:needed|required)\b", re.I)
_EXCLUDED = re.compile(r"\b(?:earlier|previously|yesterday|example|documentation|if|would you like|let me know if|can also)\b", re.I)
_ENDED = re.compile(r"\b(?:ci|checks?|tests?|build|job|task)\b[^.!?\n]{0,30}\b(?:finished|completed|passed|stopped|cancelled|canceled)\b", re.I)


def detect_activity(prose: str, background_tasks: int | None = None,
                    session_crons: int | None = None) -> tuple[str, str]:
    """Return activity and evidence source, never deriving work from count alone.

    Counts are session-wide and therefore only corroborate an explicit current
    claim. Missing registry data is unknown, while two available empty registries
    contradict a background claim. A later completion clears earlier activity.
    """
    if not isinstance(prose, str) or len(prose) > MAX_PROSE_CHARS:
        return "unknown", "none"
    running = followup = polling = quiet = False
    for part in sentences(prose):
        if _EXCLUDED.search(part):
            continue
        if _ENDED.search(part):
            running = polling = followup = False
        if not re.search(r"\b(?:not|never|no longer)\b", part, re.I):
            running |= bool(_RUNNING.search(part))
            polling |= bool(_POLLING.search(part))
        followup |= bool(_FOLLOWUP.search(part))
        quiet |= bool(_QUIET.search(part))
    observed = any(type(n) is int and n > 0 for n in (background_tasks, session_crons))
    if running and (followup or polling and quiet or observed):
        if background_tasks == 0 and session_crons == 0:
            return "unknown", "empty-background-registry"
        return "in-flight", "background-metadata" if observed else "reported-prose"
    return "unknown", "none"
