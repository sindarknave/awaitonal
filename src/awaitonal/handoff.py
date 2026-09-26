"""Current conversational handoffs, independent of outcome classification.

Input is assistant prose (already stripped of quotations and code). These small
rules recognize explicit invitations/dependencies; they do not infer intent from
an arbitrary question or verify the assistant's claims. Scan once with
``analyze_handoff`` when both fields are needed.
"""
from dataclasses import dataclass
import re
from typing import Literal

from .text import MAX_PROSE_CHARS
from .delivery import detect_assessment

Expectancy = Literal["none", "review-requested", "required-handoff"]
HandoffKind = Literal["decision", "action", "authorization"]


@dataclass(frozen=True)
class Handoff:
    expectancy: Expectancy = "none"
    # Meaningful for required handoffs; action is the neutral default otherwise.
    kind: HandoffKind = "action"


def _rx(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


# Split contrastive clauses so one negation does not suppress a later request.
# All searches below have fixed or bounded spans: no repeated unbounded suffixes.
_PARTS = _rx(r"(?<=[.!?])\s+|\n+|;\s*|\b(?:but|however|yet)\b\s*,?\s*|,\s*(?=now\b)")
_DOC = _rx(
    r"^(?:#+\s*)?(?:example|sample output|expected output|hypothetical example)\s*:|"
    r"\b(?:guide|manual|documentation|readme|tutorial|instructions?|quick[- ]start sheet|example|sample|template|prompt|task description)"
    r"[^.!?\n]{0,65}(?:\bsays?\b|\bexplains?\b|\bcontains?\b|\bincludes?\b|\breads?\b|\bsection\b)|"
    r"\b(?:wrote|created|prepared) (?:the |a |an )?(?:quick[- ]start sheet|instructions|guide|tutorial)[^.!?\n]{0,40}:|"
    r"\b(?:here are|follow these) (?:the )?(?:setup|installation|sign[- ]in|authentication) (?:instructions|steps)\b|"
    r"^(?:#+\s*)?(?:setup|installation|sign[- ]in|authentication) (?:instructions|steps)\s*:"
)
_DOC_END = _rx(r"\b(?:instructions|guide|sheet|documentation|tutorial) (?:is|are) (?:ready|complete|finished)\b")
_CURRENT = _rx(r"\b(?:right now|for this run|to unblock|before i can|before we can|i am waiting|i'm waiting|we are waiting)\b")
_HISTORICAL = _rx(r"\b(?:previously|earlier|initially|at first|yesterday|last time|i had asked|we had asked)\b")
_FUTURE = _rx(r"\b(?:on future|for future|next time|in future|during installation|before first use|when you (?:later|eventually))\b")
_OPTIONAL = _rx(
    r"\b(?:if (?:you (?:want|wish|would like)|you'd like|useful|helpful|needed)|in case you|"
    r"would you like (?:me|us) to|let me know if|optional(?:ly)?|no (?:response|reply|action) (?:is )?(?:needed|required)|"
    r"(?:available|ready) (?:for|to) review|whenever (?:useful|convenient))\b"
)
_NEGATED = _rx(
    r"\b(?:no longer (?:need|require|waiting|awaiting|blocked)|not (?:waiting|awaiting|asking)|"
    r"(?:don't|do not|doesn't|does not|didn't|did not|won't|will not) (?:need|require|ask)|"
    r"(?:don't|do not) (?:review|approve|authorize|sign|log|choose|send|run)|"
    r"no need (?:for|to)|no (?:review|approval|permission|authentication|sign[- ]in|confirmation|input) (?:is )?(?:needed|required)|(?:need not|don't have to|do not have to)|"
    r"(?:review|approval|permission|authentication|sign[- ]in|confirmation|input) (?:is |was )?not (?:needed|required|pending))\b"
)
_DIRECT = _rx(
    r"(?P<prefix>^\s*(?:[-*]\s*|\d+[.)]\s*)?(?:please\s+)?|\bplease\s+|"
    r"\b(?:can|could|would|will) you\s+|\b(?:i|we) (?:need|require) you to\s+|"
    r"\byou(?: (?:will )?need to|'ll need to| must| have to)\s+|\b(?:waiting for|until|once|after) you (?:to )?)"
    r"(?P<verb>review|look over|take a look at|check|sign[ -]?in(?:to)?|log[ -]?in(?:to)?|authenticate|"
    r"complete (?:the |your )?(?:sso|sign[- ]in|authentication)|do (?:the )?auth|"
    r"approve|authorize|grant|confirm|choose|select|decide|clarify|specify|tell me|"
    r"send|share|paste|upload|provide|reproduce|restart|reconnect|run|open|click|enable|install)\b"
)
_NEED_OBJECT = (
    r"(?P<object>review|feedback|approval|permission|consent|go[- ]ahead|"
    r"confirmation|choice|decision|selection|answer|input|clarification|credentials|"
    r"auth|authentication|sign[- ]in|login|authorization|access|logs?|output|evidence)\b"
)
_NEED = _rx(
    r"\b(?:need(?:s)?|require(?:s)?|waiting (?:on|for)|awaiting|pending|blocked on)\s+"
    r"(?:your|an?|the)\s+" + _NEED_OBJECT
)
_COORDINATED_NEED = _rx(r"(?:,\s*(?:and\s+)?|\band\s+)(?:(?:your|an?|the)\s+)?" + _NEED_OBJECT)
_NOUN_PREDICATE = _rx(r"\s+(?:is|are|was|were|has|have|had)\b")
_REVIEW_APPROVAL = _rx(
    r"\breview and (?:approve|(?:your )?approval)\b|"
    r"\breview\b[^.!?\n]{0,60}\band approve (?:it|this|that)\b"
)
_FEEDBACK = _rx(
    r"\b(?:please )?(?:let me know|tell me) (?:what you think|your (?:thoughts|feedback))\b|"
    r"\b(?:i'd|i would) (?:like|appreciate) your (?:review|feedback|thoughts)\b"
)
_CHOICE = _rx(
    r"\bwhich\b[^.!?\n]{0,85}\b(?:should (?:i|we)|would you (?:like|prefer)|do you (?:want|prefer))\b|"
    r"\b(?:what|which) (?:do you (?:mean|prefer)|option|version|file|directory|environment|account)\b[^.!?\n]{0,85}\?|"
    r"\b(?:i|we) (?:need|require) (?:you to clarify|to know (?:which|what|whether))\b"
)
_PERMISSION = _rx(r"\b(?:may|can) i (?:run|execute|install|delete|remove|access|use|proceed|continue|publish|merge|deploy)\b")
_DEPENDENCY = _rx(
    r"\b(?:before (?:i|we) can|(?:so|until|once) (?:i|we) can|to (?:continue|proceed|resume|unblock)|"
    r"(?:i|we) (?:cannot|can't|am unable to|are unable to) (?:continue|proceed)|"
    r"waiting|blocked|paused|still (?:need|needs)|now)\b"
)
_DIAGNOSTIC = _rx(r"\b(?:logs?|console|output|trace|error|crash|results?|evidence|reproduc\w*)\b")
_AUTH = _rx(r"\b(?:auth(?:entication|orization)?|sso|sign[- ]in|log[- ]in|login|browser|device|access)\b")
_ACTION_BOUNDARY = _rx(r"[,;.!?\n]|\b(?:and|then)\b")
_REVIEW_OBJECT = _rx(r"\b(?:this|it|that|draft|diff|patch|changes|preview|proposal|work|design|result|document|pr)\b")
_REVIEW_ANSWER = _rx(r"\b(?:what you think|your (?:thoughts|feedback))\b")
_CONFIRM_CHOICE = _rx(r"\bconfirm (?:which|what|how)\b")
_RESOLUTIONS = {
    "auth": _rx(r"\b(?:authentication|authorization|sign[- ]in|login|sso|access) (?:is |was |has |has been |now )?(?:complete(?:d)?|successful|succeeded|granted|restored)\b|\b(?:you|i|we) (?:have |has |are |am )?(?:signed in|logged in|authenticated)\b"),
    "approval": _rx(r"\b(?:approval|permission|consent|go[- ]ahead|authorization) (?:is |was |has been )?(?:received|granted|given|obtained)\b|\b(?:received|obtained|got|have) (?:your |the )?(?:approval|permission|consent|go[- ]ahead)\b|\byou (?:have )?(?:approved|authorized)\b|\byou (?:have )?(?:granted|provided|gave) (?:your |the )?(?:approval|permission|consent|go[- ]ahead)\b"),
    "review": _rx(r"\b(?:your review|your feedback) (?:is in|arrived|was received|has arrived)\b|\b(?:received|got|applied|addressed|incorporated) (?:your |the )?(?:review|feedback|comments|requested corrections)\b|\byou (?:have )?reviewed\b"),
    "choice": _rx(r"\b(?:your |the )?(?:choice|answer|decision|selection|clarification) (?:is |was |has been )?(?:received|provided|made|given)\b|\b(?:received|got|have) your (?:choice|answer|decision|selection|clarification)\b|\byou (?:have )?(?:chosen|selected|answered|clarified|decided)\b"),
    "diagnostics": _rx(r"\b(?:logs?|output|evidence|results?) (?:is |are |was |were |has been |have been )?(?:received|provided|uploaded|available)\b|\b(?:received|got|have) (?:your |the )?(?:logs?|output|evidence|results?)\b"),
    "action": _rx(r"\b(?:restart|upload|installation) (?:is |was |has )?(?:complete(?:d)?|finished|succeeded)\b|\b(?:service|connection) (?:has )?(?:reconnected|restarted)\b"),
}
_UNRESOLVED = _rx(r"\b(?:not|never|hasn't|haven't|isn't|wasn't|weren't|aren't|didn't|don't|without|until|once|when|if)\b")
_PREPARED = _rx(
    r"\b(?:draft|patch|branch|changes|preview|release|email|message|report|review|video|package)\b[^.!?\n]{0,45}"
    r"\b(?:ready|complete|completed|prepared|written|committed|rendered|saved)\b|"
    r"\b(?:i |we )?(?:prepared|wrote|rendered|saved|committed)\b[^.!?\n]{0,45}"
    r"\b(?:draft|patch|branch|changes|preview|release|email|message|report|review|video|package)\b"
)
_OUTWARD = _rx(r"\b(?:push|publish|post|send|submit|merge|deploy|release)\b")


def _staged_authorization(prose: str) -> bool:
    prepared = outward = False
    in_instructions = False
    for part in _PARTS.split(prose):
        if _CURRENT.search(part) or re.match(r"^(?:actual result|current status|result)\s*:", part, re.I):
            in_instructions = False
        if _DOC.search(part):
            in_instructions = True
            continue
        if in_instructions:
            if _DOC_END.search(part):
                in_instructions = False
            continue
        if (_HISTORICAL.search(part) or _FUTURE.search(part) or _OPTIONAL.search(part)
                or re.search(r"\b(?:can also|happy to|say the word|want me to)\b", part, re.I)):
            continue
        if not re.search(r"\b(?:if|would|will|no|not|never|isn't|is not)\b", part, re.I):
            prepared |= bool(_PREPARED.search(part))
        outward |= bool(_OUTWARD.search(part))
    return prepared and outward


def _auth_object(clause: str, verb_end: int) -> bool:
    # Inspect a bounded immediate object, stopping at the next action. A sign-in
    # elsewhere in the clause must not turn deployment approval into auth.
    immediate = _ACTION_BOUNDARY.split(clause[verb_end:verb_end + 80], maxsplit=1)[0]
    return bool(_AUTH.search(immediate))


def _direct_kind(verb: str, signals: set[str], auth_object: bool) -> str | None:
    if verb in {"review", "look over", "take a look at"}:
        return "review"
    if verb == "check":
        return "diagnostics" if "diagnostic" in signals else "review" if "review-object" in signals else None
    if verb in {"choose", "select", "decide", "clarify", "specify"}:
        return "choice"
    if verb == "tell me":
        if "review-answer" in signals:
            return "review"
        return "choice"
    if verb in {"approve", "authorize", "grant"}:
        return "auth" if auth_object else "approval"
    if verb == "confirm":
        if "confirm-choice" in signals:
            return "choice"
        return "approval"  # Permission to act is stronger than a preference.
    if verb in {"send", "share", "paste", "upload", "provide", "reproduce"}:
        return "diagnostics" if "diagnostic" in signals else "action"
    if verb in {"restart", "reconnect", "run", "open", "click", "enable", "install"}:
        if auth_object:
            return "auth"
        return "action" if "dependency" in signals or "diagnostic" in signals else None
    return "auth"


def _need_kind(obj: str) -> str:
    if obj in {"review", "feedback"}:
        return "review"
    if obj in {"approval", "permission", "consent", "go-ahead", "confirmation"}:
        return "approval"
    if obj in {"choice", "decision", "selection", "answer", "input", "clarification"}:
        return "choice"
    if obj in {"log", "logs", "output", "evidence"}:
        return "diagnostics"
    return "auth"


def analyze_handoff(prose: str) -> Handoff:
    """Return the strongest unresolved current handoff in one bounded analysis.

    Later explicit resolutions clear matching dependency families only. Routine
    instruction sections are excluded until a fresh current-turn cue appears.
    These are conservative English rules, not a general discourse parser.
    Dependencies are tracked by family, not by individual document/operation;
    approval clears review only when the request explicitly couples the two.
    """
    if not isinstance(prose, str) or not prose.strip() or len(prose) > MAX_PROSE_CHARS:
        return Handoff()
    pending: dict[str, Expectancy] = {}
    review_approval_coupled = False
    in_instructions = False
    prose = prose.replace("’", "'")
    verdict = detect_assessment(prose) == "verdict"
    # Preserve explicit line boundaries but join common soft-wrapped phrases.
    prose = re.sub(r"\b(have|has|had|your|the|been|is|are|was|were|need|needs|require|requires|for|to)\s*\n\s*", r"\1 ", prose, flags=re.I)
    for part in _PARTS.split(prose):
        clause = part.strip().lower()
        if not clause:
            continue
        if _CURRENT.search(clause) or re.match(r"^(?:actual result|current status|result)\s*:", clause):
            in_instructions = False
        if _DOC.search(clause):
            in_instructions = True
            continue
        if in_instructions:
            if _DOC_END.search(clause):
                in_instructions = False
            continue
        if _HISTORICAL.search(clause) or _FUTURE.search(clause):
            continue
        # Keep resolution positions: an answer can arrive later in the same
        # clause as a previously stated request.
        events = []
        if not _UNRESOLVED.search(clause):
            for kind, pattern in _RESOLUTIONS.items():
                events.extend((match.start(), 1, kind, None)
                              for match in pattern.finditer(clause))
        if _NEGATED.search(clause):
            for kind, words in {
                "auth": r"auth|sign|log|access", "approval": r"approv|permission|consent|go-ahead",
                "review": r"review|feedback", "choice": r"choic|decis|input|answer|clarif|select",
                "diagnostics": r"logs?|output|evidence", "action": r"restart|upload|install",
            }.items():
                if re.search(words, clause):
                    pending.pop(kind, None)
            continue
        if _OPTIONAL.search(clause):
            if re.search(r"\bno (?:response|reply) (?:is )?(?:needed|required)\b", clause):
                pending.pop("review", None)
            continue
        # Compute clause facts once: repeating a full-clause search for each
        # imperative would be quadratic on repeated adversarial requests.
        signals = {name for name, pattern in (
            ("diagnostic", _DIAGNOSTIC), ("review-object", _REVIEW_OBJECT),
            ("dependency", _DEPENDENCY),
            ("review-answer", _REVIEW_ANSWER), ("confirm-choice", _CONFIRM_CHOICE),
        ) if pattern.search(clause)}
        candidates: list[tuple[int, str]] = []
        for match in _DIRECT.finditer(clause):
            if match["verb"] == "review" and re.match(r"\s+verdict\s*:", clause[match.end():]):
                continue
            if (verdict and match["verb"] == "approve"
                    and re.fullmatch(r"approve[.!]?", clause)):
                continue  # Completed review verdict, not a request for approval.
            if (match["verb"] == "share" and "dependency" not in signals
                    and re.search(r"\b(?:page|share|sharing) menu\b", clause)):
                continue  # Usage instruction after delivering an artifact.
            kind = _direct_kind(match["verb"], signals, _auth_object(clause, match.end("verb")))
            if kind:
                candidates.append((match.start(), kind))
        # A compound imperative carries the same address to the user.
        if candidates:
            for match in re.finditer(r"\band (?:then )?(approve|authorize|confirm|choose|select|sign in|log in)\b", clause):
                kind = _direct_kind(match[1], signals, _auth_object(clause, match.end(1)))
                if kind:
                    candidates.append((match.start(), kind))
        needs = list(_NEED.finditer(clause))
        for match in needs:
            candidates.append((match.start(), _need_kind(match["object"])))
        if needs:
            # A shared need/wait predicate governs coordinated noun objects.
            # Ignore a new independent assertion such as "and your answer is
            # already available", which does not ask for that answer.
            first_need_end = needs[0].end()
            for match in _COORDINATED_NEED.finditer(clause):
                if match.start() >= first_need_end and not _NOUN_PREDICATE.match(clause, match.end()):
                    candidates.append((match.start(), _need_kind(match["object"])))
        for pattern, kind in ((_FEEDBACK, "review"), (_CHOICE, "choice"), (_PERMISSION, "approval")):
            candidates.extend((match.start(), kind) for match in pattern.finditer(clause))
        # An independent soft review stays soft after a neighboring required
        # action resolves. Only an explicit workflow gate strengthens it.
        review_coupled_here = bool(_REVIEW_APPROVAL.search(clause)) and any(
            kind == "approval" for _, kind in candidates)
        review_blocked = _DEPENDENCY.search(re.sub(r"\bnow\b", "", clause))
        for position, kind in candidates:
            expectancy = (
                "review-requested" if kind == "review" and not review_blocked
                else "required-handoff"
            )
            events.append((position, 0, kind, expectancy))
        for _, _, kind, expectancy in sorted(events):
            if expectancy is None:
                pending.pop(kind, None)
                if kind == "approval" and review_approval_coupled:
                    pending.pop("review", None)
                    review_approval_coupled = False
                elif kind == "review":
                    review_approval_coupled = False
            else:
                pending[kind] = expectancy
                if kind == "review":
                    review_approval_coupled = review_coupled_here
    required = {kind for kind, value in pending.items() if value == "required-handoff"}
    if required:
        # A required action wins when both action and a preference are pending.
        if required - {"review"} == {"approval"} and _staged_authorization(prose):
            return Handoff("required-handoff", "authorization")
        return Handoff("required-handoff", "decision" if required - {"review"} == {"choice"} else "action")
    if pending:
        return Handoff("review-requested")
    return Handoff()


def detect_handoff(prose: str) -> Expectancy:
    return analyze_handoff(prose).expectancy


def handoff_kind(prose: str) -> HandoffKind:
    return analyze_handoff(prose).kind
