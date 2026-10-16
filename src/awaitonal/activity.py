"""Conservative ongoing-work evidence, independent of attention and delivery."""
import re

from .text import MAX_PROSE_CHARS, sentences

_PRESENT = r"(?:\b(?:is|are|am)\b|(?<=\w)'(?:s|re|m)\b)"
_MODIFIERS = r"(?:(?:still|currently|now|actively|already)\s+)*"
_PROGRESS_PREDICATE = r"(?:in progress|under ?way|ongoing|being\s+[a-z]+ed|[a-z]+ing)"
# Subjects deliberately do not appear in this grammar: a restore, transfer,
# replica, timer, or previously unseen operation has the same present tense.
_RUN_STATUS = re.compile(
    _PRESENT + r"\s+" + _MODIFIERS +
    r"(?P<predicate>" + _PROGRESS_PREDICATE + r")\b", re.I)
_DURATIVE_STATUS = re.compile(
    r"\b(?:remains?|continues?)\s+" + _MODIFIERS +
    r"(?:" + _PROGRESS_PREDICATE + r"|in (?:the )?background)\b", re.I)
_STATUS_HEADING = re.compile(
    r"^[^:;\n.!?]{1,160}:\s+" + _MODIFIERS + _PROGRESS_PREDICATE + r"\b", re.I)
_STATIC_PREDICATES = {"missing", "interesting", "confusing", "misleading", "worrying",
                      "concerning", "disappointing", "surprising", "outstanding",
                      "amazing", "annoying", "alarming", "embarrassing", "exciting",
                      "encouraging", "reassuring", "promising", "challenging",
                      "frustrating", "shocking", "blocking"}
_NEGATIVE_SUBJECT = re.compile(
    r"\b(?:nothing|nobody|no one|neither)\s*$|"
    r"\bno\s+(?:(?!(?:and|but|while|although|because)\b)[\w'-]+\s+){1,16}$|"
    r"\bnone\s+(?:of\s+(?:[\w'-]+\s+){1,12})?$", re.I)
_REMAINING = re.compile(
    r"\b(?:has|have) (?:(?:about|around|roughly|approximately) )?"
    r"(?:\d{1,6}(?:\.\d{1,3})?|one|two|three|four|five|six|seven|eight|nine|ten|"
    r"fifteen|twenty|thirty|sixty|a few|several) (?:seconds?|minutes?|hours?) (?:left|remaining)\b", re.I)
# Waiting describes a current state even when there is no present-tense
# auxiliary ("Waiting for the transfer to finish"). The object can be an
# operation, an output, or a completion event; its name is not an allowlist.
# Human-owned inputs remain handoffs rather than ongoing process evidence.
_WAIT_STATE = re.compile(
    _PRESENT + r"\s+" + _MODIFIERS + r"(?:waiting|awaiting)\b|"
    r"\b(?:i|we)\s+" + _MODIFIERS + r"(?:wait|await)\b|"
    r"^(?:still\s+|currently\s+)?(?:waiting|awaiting)\b", re.I)
_PENDING_STATE = re.compile(
    _PRESENT + r"\s+" + _MODIFIERS + r"pending\b|"
    r"\b(?:remains?|remain)\s+pending\b", re.I)
_NOT_COMPLETE_YET = re.compile(
    r"\b(?:hasn't|haven't|has not|have not)\s+"
    r"(?:finished|completed|ended|returned|settled|expired|elapsed)\s+yet\b|" +
    _PRESENT + r"\s+(?:still\s+)?not\s+(?:done|complete|finished|ready)\s+yet\b|"
    r"\b(?:isn't|aren't)\s+(?:done|complete|finished|ready)\s+yet\b", re.I)
_HUMAN_WAIT = re.compile(
    r"\b(?:you|users?|approval|permission|consent|authorization|authorisation)\b|"
    r"\b(?:your|their)\s+(?:reply|response|input|decision|feedback|confirmation|selection|choice|answer|review)\b", re.I)
_PROMISE = r"\b(?:i will|i'll|we will|we'll)\s+(?:(?:also|then)\s+)?"
_REPORT = (r"(?:report\s+(?:back|(?:the\s+)?(?:results?|verdict|outcome|findings))|"
           r"follow\s+up|update\s+you|notify\s+you|let\s+you\s+know|keep\s+you\s+posted|"
           r"(?:give|send)\s+you\s+(?:an?\s+|the\s+)?update|"
           r"send\s+(?:an?\s+|the\s+)?update|(?:be|come|circle)\s+back\s+with|return\s+with|"
           r"(?:share|send|post|summarize|relay)\b[^.!?\n]{0,80}\b"
           r"(?:results?|findings|summary|verdict|outcome|update))")
_FOLLOWUP = re.compile(
    _PROMISE + _REPORT + r"\b", re.I)
# With a definite completion clause, the future action's relation to that work
# matters more than its verb: delivering, attaching, or inspecting an output
# are all pending steps. Do not enumerate the verbs of possible work products.
_FOLLOWUP_ACTION = re.compile(_PROMISE + r"(?!not\b|never\b)[a-z]+\b", re.I)
_NEXT_ACTION = re.compile(
    r"^(?:then|afterwards?)\s*,?\s*" + _PROMISE + r"(?!not\b|never\b)[a-z]+\b|"
    r"\b(?:i will|i'll|we will|we'll)\s+then\s+(?!not\b|never\b)[a-z]+\b", re.I)
_TEMPORAL = re.compile(r"\b(?:when|once|after|as soon as)\b", re.I)
_COMPLETE = re.compile(
    r"\b(?:lands?|finish(?:es)?|completes?|ends?|settles?|resolves?|returns?|arrives?|"
    r"expires?|elapses?|go(?:es)? off|"
    r"catch(?:es)? up|"
    r"(?:has|have) (?:landed|finished|completed|ended|settled|returned|arrived|expired|elapsed|caught up))\b", re.I)
_COMPLETE_STATE = re.compile(
    _PRESENT + r"\s+(?:done|ready|finished|complete|available|through|over)\b", re.I)
_COMPLETE_ANAPHOR = re.compile(
    r"^\s*(?:it does|they do|that happens|this happens)\s*(?:[,.!?;]|$)", re.I)
_KEEPING_EYE = re.compile(
    r"\b(?:i am|i'm|we are|we're) (?:still |currently )?keeping an eye on (?:it|them)\b", re.I)
_POLLING = re.compile(r"\b(?:monitoring|polling|watching)\b[^.!?\n]{0,55}\b(?:background|ci|checks?)\b", re.I)
_QUIET = re.compile(r"\bno (?:action|reply|response) (?:is )?(?:needed|required)\b", re.I)
_EXCLUDED = re.compile(r"\b(?:earlier|previously|yesterday|example|documentation|would you like|let me know if|can also|happy to)\b", re.I)
_USER_CONDITIONAL = re.compile(
    r"\bif you (?:want|like|would like|approve|authorize|confirm|choose|decide)\b", re.I)
_CONDITIONAL = re.compile(r"^(?:if|unless|when|once|assuming|provided)\b", re.I)
_NEGATED = re.compile(r"\b(?:not|never|no longer|isn't|aren't|hasn't|haven't|won't)\b", re.I)
_ENDED = re.compile(
    r"\b(?:has|have|had)\s+(?:(?:now|already|just|finally|successfully)\s+)*"
    r"(?:finished|completed|passed|stopped|cancelled|canceled|landed|expired|elapsed|returned|arrived)\b|"
    r"\b(?:finished|completed|passed|stopped|cancelled|canceled|landed|expired|elapsed|returned|arrived|went off)\b"
    r"(?=\s*(?:[.!?,;:]|$|(?:successfully|cleanly|now|already|finally|soon|and|with|without)\b))|" +
    _PRESENT + r"\s+(?:now\s+)?(?:done|complete|finished|ready)\b|"
    r"\b(?:all done|everything is (?:complete|finished))\b", re.I)
_NO_LONGER_RUNNING = re.compile(
    r"(?:\b(?:is|are|am)\b|(?<=\w)'(?:s|re|m)\b)\s+(?:not|no longer)\s+"
    r"(?:[a-z]+ing|in progress|under ?way|ongoing)\b|"
    r"\b(?:isn't|aren't)\s+(?:[a-z]+ing|in progress|under ?way|ongoing)\b", re.I)


def _human_wait_target(text: str, start: int, end: int) -> bool:
    prefix = text[max(0, start - 96):start]
    prefix = re.split(r"[,;]|\b(?:and|but)\b", prefix, flags=re.I)[-1]
    target = text[end:min(len(text), end + 160)]
    # "I'll notify you" is the reporting step, not the object of "waiting".
    target = re.split(r"[,;]|\b(?:and|then)\b|" + _PROMISE,
                      target, maxsplit=1, flags=re.I)[0]
    return bool(_HUMAN_WAIT.search(prefix + " " + target))


def _current_status(text: str, *, include_monitor: bool = True) -> bool:
    """Recognize a present predicate, without guessing from the subject's name."""
    for match in _RUN_STATUS.finditer(text):
        predicate = match["predicate"].lower()
        if predicate in _STATIC_PREDICATES:
            continue
        if predicate in {"waiting", "awaiting", "pending"} and _human_wait_target(
                text, match.start(), match.end()):
            continue
        if _NEGATIVE_SUBJECT.search(text[max(0, match.start() - 160):match.start()]):
            continue
        if predicate == "keeping" and re.match(r"\s+an?\s+eye\b", text[match.end():match.end() + 24], re.I):
            continue
        if not include_monitor and predicate in {"monitoring", "polling", "watching", "keeping"}:
            continue
        # Present "going to" is an intention, not work underway now.
        if predicate == "going" and re.match(r"\s+to\b", text[match.end():match.end() + 16], re.I):
            continue
        if predicate == "working" and re.match(
                r"\s+(?:correctly|properly|fine|as expected)\b",
                text[match.end():match.end() + 32], re.I):
            continue
        return True
    heading = _STATUS_HEADING.search(text)
    if heading and not (re.search(r"\b(?:waiting|awaiting|pending)\b", heading[0], re.I)
                        and (_HUMAN_WAIT.search(heading[0]) or
                             _human_wait_target(text, heading.start(), heading.end()))):
        return True
    for match in _DURATIVE_STATUS.finditer(text):
        prefix = text[max(0, match.start() - 64):match.start()]
        if _NEGATIVE_SUBJECT.search(prefix):
            continue
        if re.search(r"\b(?:waiting|awaiting|pending)\b", match[0], re.I) and _human_wait_target(
                text, match.start(), match.end()):
            continue
        if not re.search(r"\b(?:not|never|will|would|could|should|might|may|to|doesn't|don't)\s*$", prefix, re.I):
            return True
    for match in _REMAINING.finditer(text):
        if not re.search(r"\b(?:will|would|could|should|might|may|to)\s*$",
                         text[max(0, match.start() - 64):match.start()], re.I):
            return True
    if _process_waiting(text):
        return True
    return False


def _process_waiting(text: str) -> bool:
    """An explicit unfinished wait, without inventing a human obligation.

    Keep the scope local so an earlier process wait does not absorb a later
    request for the user's approval. Conditional, historical, and ended
    clauses are filtered by detect_activity before this current-state check.
    """
    for pattern in (_WAIT_STATE, _PENDING_STATE, _NOT_COMPLETE_YET):
        for match in pattern.finditer(text):
            if _human_wait_target(text, match.start(), match.end()) or _NEGATIVE_SUBJECT.search(
                    text[max(0, match.start() - 160):match.start()]):
                continue
            prefix = text[max(0, match.start() - 64):match.start()]
            if re.search(r"\b(?:not|never|no longer|will|would|could|should|might|may|to)\s*$", prefix, re.I):
                continue
            return True
    return False


def current_process_status(text: str) -> bool:
    """Whether a clause asserts current process state, without inventing a promise.

    Used by outcome routing to associate a pending-completion assertion with
    the activity it reports, rather than erase unrelated unfinished work.
    """
    return bool(isinstance(text, str) and len(text) <= MAX_PROSE_CHARS
                and not (_EXCLUDED.search(text) or _USER_CONDITIONAL.search(text)
                         or _CONDITIONAL.search(text))
                and _current_status(text))


def _completion_followup(text: str) -> bool:
    """A reporting/review promise can precede or follow its completion clause."""
    promise = _FOLLOWUP_ACTION.search(text)
    if not promise:
        return False
    # Only the earliest temporal marker on either side matters. Rescanning
    # every suffix would be quadratic on repeated "when" in a long reply.
    for start, end in ((0, promise.start()), (promise.end(), len(text))):
        temporal = _TEMPORAL.search(text, start, end)
        if temporal and (_COMPLETE.search(text, temporal.end(), end) or
                         _COMPLETE_STATE.search(text, temporal.end(), end) or
                         _COMPLETE_ANAPHOR.search(text[temporal.end():min(end, temporal.end() + 64)])):
            return True
    return False


def _ended_now(text: str) -> bool:
    """Scope negation/modality to the completion, not a later reporting promise."""
    for match in _ENDED.finditer(text):
        prefix = text[max(0, match.start() - 96):match.start()]
        if re.search(r"\b(?:not|never|isn't|aren't|hasn't|haven't|won't|"
                     r"will|would|could|should|might|may)\b(?:\s+[\w']+){0,4}\s*$", prefix, re.I):
            continue
        return True
    return False


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
    prose = prose.replace("’", "'")
    running = followup = polling = quiet = closing_followup = False
    # A conditional clause must not hide an independent current status before
    # it, nor may a historical clause before "but" hide a current status after.
    parts = [part.strip(" ,") for sentence in sentences(prose)
             for part in re.split(r";|\b(?:but|however)\b", sentence, flags=re.I) if part.strip(" ,")]
    for part in parts:
        completion_followup = _completion_followup(part)
        completion_first = bool(_TEMPORAL.match(part) and completion_followup)
        if (_EXCLUDED.search(part) or _USER_CONDITIONAL.search(part) or
                _CONDITIONAL.search(part) and not completion_first):
            closing_followup = False
            continue
        # A future subordinate clause ("when CI has finished") is not a
        # completion now. Negated and prospective completions are not either.
        current = re.split(r"\b(?:when|once|after|as soon as|if)\b", part, maxsplit=1, flags=re.I)[0]
        if _NO_LONGER_RUNNING.search(current) or _ended_now(current):
            running = polling = followup = quiet = closing_followup = False
        current_running = _current_status(current)
        running |= current_running
        if not _NEGATED.search(current):
            polling |= bool(_POLLING.search(current))
        # A closing, explicitly running check that is still being watched is
        # unfinished work after a push. A bare background monitor elsewhere
        # in a delivered reply does not provide this stronger evidence.
        current_monitor = (not _NEGATED.search(current) and
                           _current_status(current, include_monitor=False) and
                           bool(_KEEPING_EYE.search(current)))
        report = _FOLLOWUP.search(part)
        report_promise = bool(report) and not _NEGATED.search(part[report.start():])
        next_step = _NEXT_ACTION.search(part)
        next_action = running and bool(next_step) and not _NEGATED.search(part[next_step.start():])
        followup |= report_promise or completion_followup or current_monitor or next_action
        # Only a closing follow-up can override a delivered item elsewhere in
        # the reply. A trailing "no action needed" does not change that status.
        # A direct promise to report back is a pending handback even without
        # the literal words "when it finishes". Adjacent status and promise
        # clauses work in either order; an unrelated closing delivery still
        # clears this stronger evidence while leaving passive activity intact.
        closing_followup = (completion_followup or report_promise or current_monitor or next_action or
                            followup and current_running or
                            closing_followup and bool(_QUIET.search(part)))
        quiet |= bool(_QUIET.search(part))
    observed = any(type(n) is int and n > 0 for n in (background_tasks, session_crons))
    if running and (followup or polling and quiet or observed):
        if background_tasks == 0 and session_crons == 0:
            return "unknown", "empty-background-registry"
        return "in-flight", ("pending-followup" if closing_followup else
                             "background-metadata" if observed else "reported-prose")
    return "unknown", "none"
