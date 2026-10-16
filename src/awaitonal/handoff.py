"""Current conversational handoffs, independent of outcome classification.

Input is assistant prose (already stripped of quotations and code). These small
rules recognize explicit invitations/dependencies; they do not infer intent from
an arbitrary question or verify the assistant's claims. Scan once with
``analyze_handoff`` when both fields are needed.
"""
from dataclasses import dataclass
import re
from typing import Literal

from .text import MAX_PROSE_CHARS, response_prose
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
_HISTORICAL = _rx(r"\b(?:previously|initially|at first|yesterday|last time|i had asked|we had asked)\b|\bearlier(?=\s+(?:i|we|you)\b|\s*[,;.!?]|$)")
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
    r"\byou(?: (?:will )?need to|'ll need to| must| have to)\s+|\b(?:waiting for|until|once|after) you (?:to )?|"
    r"\b(?:after|once|when) you [^.!?\n]{1,100},\s*)"
    r"(?P<verb>review|look over|take a look at|check|sign[ -]?in(?:to)?|log[ -]?in(?:to)?|authenticate|"
    r"complete (?:the |your )?(?:sso|sign[- ]in|authentication)|do (?:the )?auth|"
    r"approve|authorize|grant|confirm|choose|select|pick|decide|clarify|specify|tell me|"
    r"send|share|paste|upload|provide|reproduce|export|restart|reconnect|run|open|click|enable|install)\b"
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
    r"\b(?:i|we) (?:need|require) (?:you to clarify|to know (?:which|what|whether))\b|"
    r"^\s*(?:should|shall|do|would) (?:i|we)\b[^.!?\n]{1,90}\bor\b[^.!?\n]{1,60}\?|"
    r"^\s*(?:do you (?:want|prefer)|would you (?:prefer|rather))\b[^.!?\n]{1,140}\?"
)
_PERMISSION = _rx(r"\b(?:may|can) i (?:run|execute|install|delete|remove|access|use|proceed|continue|publish|merge|deploy)\b")
_DEPENDENCY = _rx(
    r"\b(?:before (?:i|we) can|(?:so|until|once) (?:i|we) can|to (?:continue|proceed|resume|unblock)|"
    r"(?:i|we) (?:cannot|can't|am unable to|are unable to) (?:continue|proceed)|"
    r"waiting|blocked|paused|still (?:need|needs)|now)\b|"
    r"\b(?:and|then) (?:i|we)(?:'ll| will) (?:carry on|continue|resume|proceed)\b"
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
    "choice": _rx(r"\b(?:your |the )?(?:choice|answer|decision|selection|clarification) (?:is |was |has been )?(?:received|provided|made|given)\b|\b(?:received|got|have) your (?:choice|answer|decision|selection|clarification)\b|\byou (?:have )?(?:chosen|selected|picked|answered|clarified|decided)\b"),
    "diagnostics": _rx(r"\b(?:logs?|output|evidence|results?) (?:is |are |was |were |has been |have been )?(?:received|provided|uploaded|available)\b|\b(?:received|got|have) (?:your |the )?(?:logs?|output|evidence|results?)\b"),
    "action": _rx(r"\b(?:restart|upload|installation) (?:is |was |has )?(?:complete(?:d)?|finished|succeeded)\b|\b(?:service|connection) (?:has )?(?:reconnected|restarted)\b"),
}
_UNRESOLVED = _rx(r"\b(?:not|never|hasn't|haven't|isn't|wasn't|weren't|aren't|didn't|don't|without|until|once|when|if)\b")
_PREPARED = _rx(
    r"\b(?:draft|patch|branch|changes?|preview|release|email|message|report|review|video|package)\b[^.!?\n]{0,45}"
    r"\b(?:ready|complete|completed|prepared|written|committed|rendered|saved)\b|"
    r"\b(?:i |we )?(?:prepared|wrote|rendered|saved|committed)\b[^.!?\n]{0,45}"
    r"\b(?:draft|patch|branch|changes?|preview|release|email|message|report|review|video|package)\b|"
    r"\b(?:the |my |our )?draft (?:reply|response|message|email) (?:is |appears )?(?:above|below|attached)\b|"
    r"\b(?:config(?:uration)? rules?|config(?:uration)? changes?|patch|changes?)\b[^.!?\n]{0,35}"
    r"\b(?:is |are )?(?:listed|shown|provided) (?:above|below|here)\b"
)
_OUTWARD_BASES = "push publish post send submit merge deploy release commit apply save".split()
_OUTWARD_VERBS = "(?:" + "|".join(_OUTWARD_BASES) + ")"
_OUTWARD_ACTIONS = "(?:" + "|".join(_OUTWARD_BASES + [
    "committing" if verb == "commit" else "submitting" if verb == "submit" else
    verb[:-1] + "ing" if verb.endswith("e") else verb + "ing"
    for verb in _OUTWARD_BASES]) + ")"
_OUTWARD = _rx(r"\b" + _OUTWARD_ACTIONS + r"\b")
_STAGED_OFFER = _rx(
    r"(?:^|[,:—]\s*|\band\s+)(?:(?:do you )?want (?:me|us) to|would you like (?:me|us) to)\s+"
    + _OUTWARD_VERBS + r"\b|"
    r"(?:^|[,:—]\s*|\band\s+)say the word[^.!?\n]{0,45}\b(?:i'll|i will|we'll|we will)\s+"
    + _OUTWARD_VERBS + r"\b|"
    r"^\s*(?:(?:should|shall|may|can) (?:i|we)\s+|ok(?:ay)? to\s+)" + _OUTWARD_VERBS + r"\b[^.!?\n]{0,100}\?"
)
_OUTWARD_COMPLETED = _rx(
    r"(?:^|\b(?:i|we|i've|we've) (?:have )?(?:already |just )?)(?P<verb>pushed|published|posted|sent|submitted|merged|deployed|released|committed|applied|saved)\b|"
    r"\b(?:pr|pull request) is (?:open|merged)\b|"
    r"\b(?:pr|pull request) is up(?=\s*(?:[.!,:;]|$|\bawaitonalprlink\b))"
)
_NOT_PREPARED = _rx(r"\b(?:if|would|will|no|not|never|isn't|aren't|haven't|hasn't|wasn't|weren't)\b")

# Preparation is a predicate, not a catalogue of filenames or deliverable nouns.
# The assistant may call the same item a note, response, change, or simply "it".
_PREPARATION = _rx(
    r"\b(?:is|are|was|were|has been|have been|hasn't been|haven't been|has not been|have not been|isn't|aren't|is not|are not)\s+"
    r"(?:(?:already|now|fully|all|not|yet)\s+){0,3}"
    r"(?:ready|prepared|staged|drafted|written|assembled|complete|completed)\b|"
    r"\b(?:i|we|i've|we've)\s+(?:(?:have|already|just|now|not|haven't)\s+){0,3}"
    r"(?:prepared|drafted|wrote|written|assembled|staged|finished|put together)\b|"
    r"\b(?:i|we)\s+have\s+(?:the|a|our|my|this|that)\s+[^.!?\n]{1,60}\s+(?:ready|prepared|staged)\b|"
    r"^\s*(?:ready|prepared|staged|drafted)\s+(?:on my side|for your|to go)\b"
)
_PREPARATION_NEGATED = _rx(r"\b(?:not|never|isn't|aren't|haven't|hasn't)\b")
_PERMISSION_QUESTION = _rx(
    r"(?:^|[,;:]\s*)(?:(?:so|now)\s+)?(?:"
    r"(?:should|shall|may|can|could)\s+(?:i|we)\b|"
    r"(?:do you want|would you (?:like|prefer))\s+(?:me|us|that i|that we)\b|"
    r"(?:want|need)\s+(?:me|us)\s+to\b|"
    r"(?:is (?:it|that)|would (?:it|that) be)\s+(?:ok(?:ay)?|all right|acceptable)\b|"
    r"are you\s+(?:happy|comfortable|content|okay)\s+(?:for|with)\s+(?:me|us)(?:\s+to)?\b|"
    r"(?:ok(?:ay)?|permission|your go[- ]ahead)\s+(?:to|for me to|for us to)\b|"
    r"(?:do|can)\s+(?:i|we)\s+have\s+your\s+(?:permission|approval|go[- ]ahead)\b)"
    r"[^.!?\n]{0,140}\b" + _OUTWARD_ACTIONS + r"\b"
)
_APPROVAL_CONDITION = _rx(
    r"\b(?:if|once|when|provided)\s+you\s+(?:agree|approve|consent|authorize|confirm|give (?:me|us) (?:the |your )?go[- ]ahead)\b"
    r"[^.!?\n]{0,90}\b(?:(?:i|we)(?:'ll| will| can)|(?:can|could|may|should) (?:i|we))\b[^.!?\n]{0,60}\b" + _OUTWARD_VERBS + r"\b|"
    r"\b(?:with|subject to|pending)\s+your\s+(?:permission|approval|consent|go[- ]ahead)\b"
    r"[^.!?\n]{0,90}\b(?:i|we)(?:'ll| will| can)\b[^.!?\n]{0,60}\b" + _OUTWARD_VERBS + r"\b|"
    r"\b(?:i|we)(?:'ll| will| can)\b[^.!?\n]{0,60}\b" + _OUTWARD_VERBS + r"\b"
    r"[^.!?\n]{0,90}\b(?:if|once|when|provided)\s+you\s+(?:agree|approve|consent|authorize|confirm)\b"
)
_USER_ACTION = _rx(
    r"(?P<address>\bplease\s+|\b(?:can|could|would|will) you\s+|"
    r"\b(?:i|we) (?:need|require) you to\s+|\byou(?: must| have to| need to|'ll need to| will need to)\s+|"
    r"\b(?:once|after|when|until|before|as soon as) you(?:'ve| have)?\s+)"
    r"(?P<verb>[a-z][a-z-]*)\b"
)
_BARE_ACTION = _rx(r"^\s*(?:[-*]\s*|\d+[.)]\s*)?(?:(?:first|next),?\s+)?(?P<verb>[a-z][a-z-]*)\b\s+(?P<rest>\S.*)")
_CAUSATIVE_ACTION = _rx(r"^\s*(?:please\s+)?(?P<verb>have|get)\s+(?:the|your|this|that|these|those)\s+[^.!?\n]{1,70}\s+[a-z]+ed\b")
_NON_IMPERATIVE = frozenset(
    "i we you he she it they the a an this that these those there here my our your their "
    "all everything nothing anything no yes done then now after before once when until if please "
    "should shall may can could will would is are was were has have had not don't do "
    "another other some any which what how why where who and but however yet or waiting awaiting pending blocked need needs require requires awaitonalcode awaitonalfile awaitonalliteral".split()
)
_ASSISTANT_DEPENDENCY = _rx(
    r"\b(?:i|we)(?:'ll| will| can| cannot| can't| am unable to| are unable to| am waiting| are waiting)\b|"
    r"\b(?:i'm|we're)\s+(?:waiting|blocked|paused)\b|\bbefore (?:i|we)\s+[a-z]+\b"
)
_LINK = _rx(r"\b(?:before|after|once|when|until|then|without|waiting|blocked|paused|need|require|as soon as)\b|\b(?:so|and) (?:i|we)\b|\bwith (?:that|this|your|the)\b")
_NON_ACTION = frozenset("know remember note enjoy understand realize realise".split())
_USER_NECESSITY = _rx(r"\b(?:you(?: must| have to| need to|'ll need to| will need to)|(?:i|we) (?:need|require) you to)\b")
# Advice can address the reader without requesting input for this turn.  It
# becomes a handoff only when the assistant ties its own next step to that input.
_ADVISORY = _rx(
    r"\b(?:you (?:should|could|might|may want to)|(?:i|we) (?:recommend|suggest)|"
    r"(?:my|our|general) (?:advice|recommendation)|consider|someone should|someone needs to|"
    r"check (?:again )?later|before (?:you )?(?:rely|relying|use|using|adopt|adopting|act|acting)\b|(?:to|for) (?:try|trying|explore|exploring) (?:the|a) (?:demo|example))\b"
)
_READER_VERIFICATION = _rx(
    r"\b(?:confirm|check|verify)\b[^.!?\n]{0,90}"
    r"\b(?:against|with (?:the|your|an?)|independently|yourself|on your own)\b"
)
_EXPLICIT_REQUEST = _rx(
    r"(?:^|[,;:]\s*)(?:please\s+|(?:can|could|would|will) you\s+|"
    r"(?:i|we) (?:need|require) you to\s+)|\bplease\s+"
)
_ACTOR_CHOICE = _rx(
    r"\b(?:should|shall|can|could|do|would) (?:i|we)\b|"
    r"\b(?:do you (?:want|prefer|mean)|would you (?:like|prefer|rather))\b|"
    r"\b(?:i|we) (?:need|require) (?:you to clarify|to know)\b"
)

_OUTSTANDING_EXECUTION = _rx(
    r"\b(?:i|we)(?: haven't| have not)\s+(?:yet\s+)?"
    r"(?:pushed|published|posted|sent|submitted|merged|deployed|released|committed|applied|saved)\s+"
    r"(?:it|this|that|them|the|our|my)\b|"
    r"\b(?:it|this|that|they|the [\w -]{1,50})\s+(?:hasn't|haven't|has not|have not)\s+been\s+"
    r"(?:pushed|published|posted|sent|submitted|merged|deployed|released|committed|applied|saved)\b"
)


def _preparation_state(clause: str) -> bool | None:
    """Return a current preparation fact, scoping negation to its predicate."""
    clause = clause.lower()
    if _HISTORICAL.search(clause) or _FUTURE.search(clause):
        return None
    match = _PREPARATION.search(clause)
    if match:
        prefix = clause[:match.start()]
        if _OPTIONAL.search(prefix) or re.search(r"\b(?:if|would|will)\b", prefix):
            return None
        return not bool(_PREPARATION_NEGATED.search(match[0]) or re.search(r"\b(?:nothing|none|no)\b", prefix))
    # Displayed drafts and completed local commits remain supported evidence.
    match = _PREPARED.search(clause)
    if match:
        return not bool(_NOT_PREPARED.search(clause[:match.end()]))
    return None


def _structural_action(clause: str) -> tuple[int, str] | None:
    """Recognize address and verb position without a work-specific verb list."""
    offset = 0
    # Ordinary prose may wrap a request in a heading and a leading gate.
    # Peel at most those two wrappers instead of recursively re-parsing an
    # arbitrary number of attacker-controlled "you:" prefixes.
    for _ in range(2):
        wrapper = (re.match(r"^[^:.!?\n]{0,45}\byou\b[^:.!?\n]{0,15}:\s*", clause)
                   or re.match(r"^\s*(?:before|until) (?:i|we)\b[^,.!?\n]{1,60},\s*", clause))
        if not wrapper:
            break
        offset += wrapper.end()
        clause = clause[wrapper.end():]
    direct = _USER_ACTION.search(clause)
    if direct and direct["verb"] not in _NON_IMPERATIVE | _NON_ACTION:
        return offset + direct.start(), direct["verb"]
    causative = _CAUSATIVE_ACTION.match(clause)
    if causative:
        return offset + causative.start(), causative["verb"]
    bare = _BARE_ACTION.match(clause)
    if (bare and bare["verb"] not in _NON_IMPERATIVE | _NON_ACTION
            and not any(pattern.search(clause) for pattern in _RESOLUTIONS.values())
            and not re.fullmatch(r"[a-z]+ed[.!?]?", bare["rest"])
            and not re.match(r"(?:\w+\s+){0,2}(?:is|are|was|were|has|have|had|hasn't|haven't|isn't|aren't|can't|couldn't|can|could|would|will|may|might|must)\b", bare["rest"])):
        return offset + bare.start(), bare["verb"]
    return None


def _linked_dependency(parts: list[str], index: int) -> bool:
    """An adjacent assistant step depends on this user action, in either order.

    Keep the window small and require both an assistant actor and a dependency
    relation. Merely promising unrelated future work is not a workflow gate.
    """
    target = parts[index].lower()
    direct = _USER_ACTION.search(target)
    request = target[direct.start("verb"):] if direct else target
    request = re.split(r"[,;]|\b(?:while|once|after|before|until|when|so|and i|and we)\b", request, maxsplit=1)[0]
    target_words = set(re.findall(r"\b[a-z]{3,}\b", request.lower())) - _NON_IMPERATIVE - _NON_ACTION - {"please", "could", "would", "will", "have", "need", "must", "once", "after", "then", "can"}
    object_reference = bool(re.search(r"\b(?:it|them|this|that|these|those)\b", request))
    has_object = len(re.findall(r"\b[a-z]+\b", request)) > (2 if request.strip().startswith("please ") else 1)
    for neighbor in parts[max(0, index - 1):index + 2]:
        neighbor = neighbor.lower()
        if (_DOC.search(neighbor) or _HISTORICAL.search(neighbor)
                or _FUTURE.search(neighbor) or _OPTIONAL.search(neighbor)):
            continue
        if _ASSISTANT_DEPENDENCY.search(neighbor) and _LINK.search(neighbor):
            if re.search(r"\b(?:before (?:i|we)|(?:once|after|when|until|as soon as) you)\b", neighbor):
                return True
            if ((has_object and re.search(r"\b(?:then|so) (?:i|we)\b", neighbor))
                    or (_DIRECT.search(target) and re.search(
                        r"\b(?:then|and) (?:i|we)(?:'ll| will) (?:carry on|continue|resume|proceed)\b", neighbor))):
                return True
            # Pronouns can refer to the requested action/result; a named event
            # such as a timer completing must instead match the prerequisite.
            if has_object and re.search(
                    r"\b(?:once|after|when|until|as soon as) (?:it|that|this|they|those|these)\b|"
                    r"\b(?:once|after|when) (?:i|we) (?:have|receive|get) (?:it|that|this|them)\b|"
                    r"\b(?:after|with) (?:that|this)\b|"
                    r"\bwaiting (?:for|on) (?:it|that|this|them)\b", neighbor):
                return True
            # A repeated prerequisite noun also links sentences, without
            # requiring it to be called a log, file, credential, or report.
            for relation in re.finditer(r"\b(?:after|once|when|until|without|with)\s+([^,.!?\n]{1,90})", neighbor):
                words = set(re.findall(r"\b[a-z]{3,}\b", relation[1].lower())) - _NON_IMPERATIVE
                if (target_words & words or (
                        re.search(r"\b(?:review|look over|take a look)\b", request)
                        and re.search(r"\byour (?:feedback|review|comments)\b", relation[1]))):
                    return True
                if (object_reference and re.search(r"\b(?:usable|available|accessible|unlocked|restored|granted|arrive|arrives|arrived|received|provided|attached)\b", relation[1])):
                    return True
    return False


def _user_gate(clause: str, kind: str, source: str, matched: str,
               linked_dependency: bool, verdict: bool) -> bool:
    """Require a current user-owned request on every textual entry route.

    An explicit request to the reader or permission question can itself state
    the current gate. Advice and generic need/wait predicates require stronger
    evidence: an assistant continuation that depends on a user-owned action.
    """
    if kind == "review":
        return True  # A soft review invitation does not play the attention cue.
    if not linked_dependency and (_ADVISORY.search(clause)
                                  or _READER_VERIFICATION.search(clause)):
        return False
    if source == "need":
        # "The job is waiting for the output" names a process prerequisite,
        # whereas "I need your output" asks the user to supply something.
        return bool(re.search(r"\byour\b", matched))
    if source == "choice":
        if _OUTWARD.search(clause):
            return False  # Prepared execution is handled as authorization.
        if re.search(r"\b(?:me|us|that i|that we) (?:to )?(?:draft|write|create|prepare|build)\b", clause):
            return False  # Offer of fresh work, rather than a current decision.
        addressed_question = bool(
            re.match(r"^\s*(?:what|which|should|shall|can|could|do|would|i|we)\b", clause)
            and (_ACTOR_CHOICE.search(clause))
            and ("?" in clause or re.search(r"\b(?:need|require)\b", clause)))
        return addressed_question or bool(
            linked_dependency and re.match(r"^\s*(?:what|which)\b", clause))
    if source == "permission":
        return True  # Explicit assistant actor: "May I install ...?"
    if source == "structural":
        return bool(linked_dependency
                    or re.search(r"\b(?:i|we) (?:need|require) you to\b", clause)
                    or (_USER_NECESSITY.search(clause)
                        and re.search(r"\b(?:for this run|before|to continue|to proceed)\b", clause)))
    if linked_dependency or _EXPLICIT_REQUEST.search(clause):
        return True
    if kind == "choice":
        return False  # Bare selection advice does not establish a paused task.
    if _USER_NECESSITY.search(clause) and not re.search(
            r"\b(?:for this run|to continue|to proceed)\b", clause):
        return False
    # Standalone auth and approval requests remain supported. Selection
    # instructions require an explicit request or assistant dependency above.
    return not verdict and not bool(re.search(
        r"\b(?:to try|to see|to explore|as (?:a|an) [^.!?\n]{0,80}precaution|in general)\b", clause))


def _completed_action(clause: str, verb: str) -> bool:
    """Resolve an ordinary domain verb only under an asserted completion."""
    # These are grammatical verb forms, shared across subject matter.
    irregular = {"run": "ran|run", "write": "wrote|written", "send": "sent", "give": "gave|given", "choose": "chose|chosen", "set": "set", "put": "put", "read": "read"}
    past = irregular.get(verb, verb + "d" if verb.endswith("e") else verb[:-1] + "ied" if verb.endswith("y") else verb + "ed")
    return bool(re.search(
        r"\b(?:(?:i|we|you)(?:'ve| have)?\s+(?:(?:already|now|just)\s+){0,2}|"
        r"(?:is|are|was|were|has been|have been)\s+(?:now\s+)?)(?:" + past + r")\b", clause))


def _new_execution_object(clause: str, prepared_parts: list[str]) -> bool:
    """Reject a fresh work offer or an idiom that only resembles execution."""
    outward = _OUTWARD.search(clause)
    if not outward:
        return False
    tail = clause[outward.end():outward.end() + 90]
    if re.match(r"\s+(?:you|me|us)\b", tail):
        return True  # e.g. "save you time", not saving the prepared result.
    fresh = re.match(r"\s+(?:a|an)\s+(?P<noun>[a-z-]+)", tail)
    return bool(fresh and not any(re.search(r"\b" + re.escape(fresh["noun"]) + r"\b", part)
                                         for part in prepared_parts))


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
        prepared |= _preparation_state(part) is True
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
    if verb in {"choose", "select", "pick", "decide", "clarify", "specify"}:
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
    if verb == "export":
        return "diagnostics" if "diagnostic" in signals else "action" if "dependency" in signals else None
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


def analyze_handoff(prose: str, *, response_scoped: bool = False) -> Handoff:
    """Return the strongest unresolved current handoff in one bounded analysis.

    Later explicit resolutions clear matching dependency families only. Routine
    instruction sections are excluded until a fresh current-turn cue appears.
    These are conservative English rules, not a general discourse parser.
    Dependencies are tracked by family, not by individual document/operation;
    approval clears review only when the request explicitly couples the two.
    """
    if not isinstance(prose, str) or not prose.strip() or len(prose) > MAX_PROSE_CHARS:
        return Handoff()
    if not response_scoped:
        prose = response_prose(prose)
    pending: dict[str, Expectancy] = {}
    prepared = False
    preparation_denied = False
    prepared_parts: list[str] = []
    generic_action: str | None = None
    review_approval_coupled = False
    in_instructions = False
    prose = prose.replace("’", "'")
    verdict = detect_assessment(prose, response_scoped=True) == "verdict"
    # Preserve explicit line boundaries but join common soft-wrapped phrases.
    prose = re.sub(r"\b(have|has|had|your|the|been|is|are|was|were|need|needs|require|requires|for|to)\s*\n\s*", r"\1 ", prose, flags=re.I)
    parts = _PARTS.split(prose)
    for index, part in enumerate(parts):
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
        # A concrete prepared deliverable makes an outward-action confirmation
        # a handoff. An unprepared offer of more work remains optional. Track
        # these in order so later permission or publication can resolve them.
        preparation = _preparation_state(clause)
        if preparation is not None:
            prepared = preparation
            preparation_denied = not preparation
            prepared_parts = [clause] if preparation else []
        elif (not preparation_denied and _OUTSTANDING_EXECUTION.search(clause)
              and not _OPTIONAL.search(clause)):
            prepared = True
        # The preparation assertion may follow the permission question, as in
        # "May I save it? Everything is ready locally." Keep this local.
        adjacent_prepared = (index + 1 < len(parts)
                             and not _DOC.search(parts[index + 1])
                             and _preparation_state(parts[index + 1]) is True)
        staged_offer = None
        if prepared or adjacent_prepared:
            staged_offer = (_STAGED_OFFER.search(clause)
                            or _PERMISSION_QUESTION.search(clause)
                            or _APPROVAL_CONDITION.search(clause))
            preparation_context = prepared_parts + ([parts[index + 1].lower()] if adjacent_prepared else [])
            if staged_offer and _new_execution_object(clause, preparation_context):
                staged_offer = None
        condition = re.search(r"\bif\b", clause)
        if (re.search(r"\b(?:optional|can also|happy to|next time|another|separate|new)\b", clause)
                or (condition and not _APPROVAL_CONDITION.search(clause)
                    and (not staged_offer or condition.start() < staged_offer.start()))):
            staged_offer = None
        # Keep resolution positions: an answer can arrive later in the same
        # clause as a previously stated request.
        events = []
        if not _UNRESOLVED.search(clause):
            for kind, pattern in _RESOLUTIONS.items():
                events.extend((match.start(), 1, kind, None)
                              for match in pattern.finditer(clause))
            if generic_action and _completed_action(clause, generic_action):
                events.append((0, 1, "action", None))
                generic_action = None
            completed = list(_OUTWARD_COMPLETED.finditer(clause))
            if completed:
                events.extend((match.start(), 1, "staged-approval", None) for match in completed)
                # Completing a local preparation step resolves its permission
                # request while leaving the result ready for publication.
                if any(match["verb"] not in {"committed", "applied", "saved"} for match in completed):
                    prepared = False
        if _NEGATED.search(clause):
            if re.search(r"\bno need to " + _OUTWARD_VERBS + r"\b", clause):
                pending.pop("staged-approval", None)
            for kind, words in {
                "auth": r"auth|sign|log|access", "approval": r"approv|permission|consent|go-ahead",
                "review": r"review|feedback", "choice": r"choic|decis|input|answer|clarif|select",
                "diagnostics": r"logs?|output|evidence", "action": r"restart|upload|install",
            }.items():
                if re.search(words, clause):
                    pending.pop(kind, None)
                    if kind == "approval":
                        pending.pop("staged-approval", None)
            if generic_action and re.search(r"\b" + re.escape(generic_action) + r"\b", clause):
                pending.pop("action", None)
                generic_action = None
            continue
        if _OPTIONAL.search(clause) and not staged_offer:
            if re.search(r"\bno (?:response|reply|action) (?:is )?(?:needed|required)\b", clause):
                pending.pop("review", None)
                pending.pop("staged-approval", None)
            continue
        # Compute clause facts once: repeating a full-clause search for each
        # imperative would be quadratic on repeated adversarial requests.
        signals = {name for name, pattern in (
            ("diagnostic", _DIAGNOSTIC), ("review-object", _REVIEW_OBJECT),
            ("review-answer", _REVIEW_ANSWER), ("confirm-choice", _CONFIRM_CHOICE),
        ) if pattern.search(clause)}
        linked_dependency = _linked_dependency(parts, index)
        if linked_dependency:
            signals.add("dependency")
        gate_cache: dict[tuple[str, str, bool], bool] = {}

        def current_gate(kind: str, source: str, matched: str) -> bool:
            # Full-clause evidence is shared across repeated requests. Keep
            # adversarial repetition linear rather than rescanning per match.
            key = (kind, source, bool(re.search(r"\byour\b", matched)))
            if key not in gate_cache:
                gate_cache[key] = _user_gate(clause, kind, source, matched,
                                             linked_dependency, verdict)
            return gate_cache[key]

        candidates: list[tuple[int, str]] = []
        recognized_direct = False
        if staged_offer:
            candidates.append((staged_offer.start(), "staged-approval"))
        for match in _DIRECT.finditer(clause):
            if match["verb"] == "review" and re.match(r"\s+verdict\s*:", clause[match.end():]):
                continue
            if (verdict and match["verb"] == "approve"
                    and re.fullmatch(r"approve(?:[.!]?| (?:once|when|after) .+)", clause)):
                continue  # Completed review verdict, not a request for approval.
            if (match["verb"] == "share" and "dependency" not in signals
                    and re.search(r"\b(?:page|share|sharing) menu\b", clause)):
                continue  # Usage instruction after delivering an artifact.
            kind = _direct_kind(match["verb"], signals, _auth_object(clause, match.end("verb")))
            if kind and current_gate(kind, "direct", match[0]):
                candidates.append((match.start(), kind))
                recognized_direct = True
                if kind == "action" and " " not in match["verb"]:
                    generic_action = match["verb"]
        # A workflow gate supplies the meaning of a user verb even when the
        # operation is domain-specific (rotate, unlock, attach, acknowledge...).
        # Explicit current requests also establish user ownership; general
        # reader advice and bare noun phrases do not supply a workflow gate.
        action = _structural_action(clause)
        if (action and not staged_offer and not recognized_direct
                and current_gate("action", "structural", clause)):
            structural_choice = (action[1] in {
                "choose", "select", "pick", "decide", "clarify", "specify"
            } or (action[1] in {"make", "give", "state", "express"} and re.search(
                r"\b" + re.escape(action[1]) + r"\b(?:\s+[a-z]+){0,3}\s+"
                r"(?:choice|selection|decision|preference)\b", clause)))
            structural_kind = "choice" if structural_choice else "action"
            candidates.append((action[0], structural_kind))
            if structural_kind == "action":
                generic_action = action[1]
        # A compound imperative carries the same address to the user.
        if candidates:
            for match in re.finditer(r"\band (?:then )?(approve|authorize|confirm|choose|select|sign in|log in)\b", clause):
                kind = _direct_kind(match[1], signals, _auth_object(clause, match.end(1)))
                if kind and current_gate(kind, "direct", match[0]):
                    candidates.append((match.start(), kind))
        needs = [match for match in _NEED.finditer(clause)
                 if current_gate(_need_kind(match["object"]), "need", match[0])]
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
            for match in pattern.finditer(clause):
                if kind == "approval" and condition and not staged_offer:
                    continue
                if (kind == "approval" and not staged_offer
                        and _new_execution_object(clause, prepared_parts)):
                    continue
                if kind == "choice" and staged_offer and match.start() == staged_offer.start():
                    continue  # "Should I commit it or leave it?" asks permission.
                if current_gate(kind, "choice" if kind == "choice" else "permission", match[0]):
                    candidates.append((match.start(), kind))
        # An independent soft review stays soft after a neighboring required
        # action resolves. Only an explicit workflow gate strengthens it.
        review_coupled_here = bool(_REVIEW_APPROVAL.search(clause)) and any(
            kind == "approval" for _, kind in candidates)
        review_blocked = (linked_dependency or bool(re.search(
            r"\b(?:i|we) (?:need|require) your (?:review|feedback)\b[^.!?\n]{0,80}"
            r"\b(?:to continue|to proceed|before (?:i|we) can)\b", clause)))
        for position, kind in candidates:
            expectancy = (
                "review-requested" if kind == "review" and not review_blocked
                else "required-handoff"
            )
            events.append((position, 0, kind, expectancy))
        for _, _, kind, expectancy in sorted(events):
            if expectancy is None:
                pending.pop(kind, None)
                if kind == "approval":
                    pending.pop("staged-approval", None)
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
        if "staged-approval" in required and not required - {"review", "approval", "staged-approval"}:
            return Handoff("required-handoff", "authorization")
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
