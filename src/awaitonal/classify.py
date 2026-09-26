"""Small conservative rules baseline, independent of ML libraries."""
import re
from .text import assistant_prose, sentences
from .types import Classification, Event, STATES, controls_for, map_controls


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def result(state: str, event: Event, reason: str, threshold: float,
           diagnostics: dict | None = None) -> Classification:
    controls = controls_for(state)
    return Classification(map_controls(controls, threshold), controls,
                          event.evidence_source, reason, diagnostics or {})


def explicit_result(event: Event, threshold: float) -> Classification | None:
    if event.explicit_state in STATES:
        return result(event.explicit_state, event, "Explicit structured event.", threshold)
    return None


def is_optional(sentence: str) -> bool:
    return _has(r"\b(would you (?:also )?like|if you (?:want|would like)|let me know if|optional(?:ly)?|happy to|can also)\b", sentence)


NEGATED_COMPLETION = (
    r"\b(?:not|never|isn't|aren't|wasn't|weren't|hasn't|haven't|didn't|doesn't) "
    r"(?:(?:yet|fully|actually|been) )?(?:done|ready|working|work|fixed|finished|finish|complete(?:d)?|implemented|verified|resolved|successful)\b"
)


def has_completion(text: str) -> bool:
    if _has(NEGATED_COMPLETION, text):
        return False
    return _has(r"\b(done|completed?|implemented|finished|fixed|resolved|delivered|all set|ready|works|working|passes|passed|succeeded|successful(?:ly)?|verified)\b", text)


_WAITING_QUESTION_TOKENS = re.compile(
    r"(?P<boundary>[.!])|(?P<question>\b(?:which|what|how|should)\b)|"
    r"(?P<dependency>\b(?:before|until) (?:I |we |proceeding|continuing))", re.I)


def _waiting_question(text: str) -> bool:
    # Scan once: retrying an unbounded suffix after every question word makes
    # repeated 'which ' quadratic when there is no dependency marker.
    question = False
    for token in _WAITING_QUESTION_TOKENS.finditer(text):
        if token.lastgroup == "boundary":
            question = False
        elif token.lastgroup == "question":
            question = True
        elif question:
            return True
    return False


def is_waiting(text: str) -> bool:
    # Require a dependency on the user; a bare question mark is insufficient.
    return _has(
        r"\b(?:waiting|awaiting|blocked|paused) (?:on |for |pending )?(?:your|you|an? (?:answer|approval|decision))\b|"
        r"\b(?:need|require)(?:s)? (?:your |you to |an? )(?:answer|approval|permission|choice|decision|input|confirmation|selection|choose|select|decide|confirm|approve)\b|"
        r"\b(?:please|could you|can you|would you) (?:approve|authorize|confirm|choose|decide)\b|"
        r"\b(?:may|can) I (?:run|execute|install|delete|remove|access|use|proceed|continue)\b|"
        r"\b(?:cannot|can't|unable to) (?:continue|proceed) (?:without|until)\b", text) or _waiting_question(text)


def is_refusal(text: str) -> bool:
    return _has(
        r"\bI (?:cannot|can't|won't|will not|am unable to) (?:help|assist|comply)\b|"
        r"\bI (?:must |have to )?(?:decline|refuse)\b|"
        r"\b(?:this|your|the) request (?:is |has been )?(?:rejected|denied)\b|"
        r"\bI (?:won't|will not) (?:provide|create|build|implement)\b", text)


def unresolved(text: str) -> bool:
    if _has(NEGATED_COMPLETION, text):
        return True
    return _has(r"\b(caveat|unverified|untested|unavailable|incomplete|unresolved|remaining|blocked|pending|not (?:done|run|tested|verified|complete|implemented)|no tests (?:were )?run|could not|couldn't|cannot|can't|unable|failed|fails|fail|failure|errors?|limitation|may not|might not)\b", text)


_WAITING_RESOLVED = (
    r"\bno longer (?:waiting|blocked|paused|need)|"
    r"\b(?:approval|permission|confirmation|answer|decision) (?:is |was |has been )?(?:received|granted|provided|given|obtained)|"
    r"\b(?:received|obtained|got|have) (?:your |the )(?:approval|permission|confirmation|answer|decision)|"
    r"\byou (?:have |had )?(?:approved|authorized|confirmed|answered|chosen|selected)|"
    r"\byou (?:granted|provided|gave) (?:the |your )?(?:approval|permission|confirmation|answer|decision)"
)
# A lookahead includes overlapping phrases such as 'got your approval was
# granted'. The later 'approval was granted' may start in a different sentence.
_WAITING_RESOLUTION_STARTS = re.compile(r"(?=" + _WAITING_RESOLVED + r")", re.I)


def waiting_resolved(text: str) -> bool:
    """Require an explicit resolution of the dependency, not merely 'done'."""
    return _has(_WAITING_RESOLVED, text)


class RulesClassifier:
    def __init__(self, threshold: float = 0.5):
        map_controls(controls_for("done"), threshold)  # validate eagerly
        self.threshold = threshold

    def classify(self, event: Event) -> Classification | None:
        if not isinstance(event, Event):
            return None
        if event.explicit_state is not None:
            return explicit_result(event, self.threshold)
        prose = assistant_prose(event.text)
        if not prose:
            return None
        parts = sentences(prose)
        meaningful = [s for s in parts if not is_optional(s)] or parts
        # Search joined prose once, preserving resolution phrases spanning
        # lines without joining and rescanning every remaining sentence.
        last_resolution = max((match.start() for match in
                               _WAITING_RESOLUTION_STARTS.finditer(" ".join(meaningful))),
                              default=-1)
        resolved_waiting = set()
        suffix_start = 0
        for index, sentence in enumerate(meaningful):
            suffix_start += len(sentence) + 1
            if is_waiting(sentence):
                # A later 'done' alone does not imply permission was granted.
                if last_resolution >= suffix_start:
                    resolved_waiting.add(index)
                    continue
                if not _has(r"\b(?:no longer|not waiting|don't need|do not need|previously|earlier|initially)\b", sentence):
                    return result("needs-you", event, "Prose reports waiting for user input or permission.", self.threshold)
        for sentence in meaningful:
            if is_refusal(sentence) and not _has(r"\b(?:earlier|previously|initially|at first|no longer)\b", sentence):
                return result("rejected", event, "Prose contains a direct refusal.", self.threshold)
        # Drop an earlier failed attempt only when a later clause explicitly
        # reports recovery/success. Keep unrelated unverified tests as caveats.
        active = []
        for index, sentence in enumerate(meaningful):
            if index in resolved_waiting:
                continue
            clauses = re.split(r"\b(?:but|however|now|after (?:fixing|repairing))\b", sentence, flags=re.I)
            if len(clauses) > 1 and has_completion(clauses[-1]) and not unresolved(clauses[-1]):
                sentence = clauses[-1]
            active.append(sentence)
        joined = " ".join(active)
        if unresolved(joined):
            previous = " ".join(active[:-1])
            final = active[-1]
            # A later success resolves earlier errors, but not skipped validation.
            earlier_only_failure = _has(r"\b(?:fail|error|broke)", previous) and not _has(r"\b(?:unverified|untested|unavailable|not tested|not run|could not|couldn't|remaining)\b", previous)
            if not (earlier_only_failure and has_completion(final) and not unresolved(final)):
                return result("caveats", event, "Prose reports unresolved work or limited verification.", self.threshold)
        if has_completion(joined):
            return result("done", event, "Prose reports completion; correctness is not independently verified.", self.threshold)
        return result("caveats", event, "Ambiguous prose; conservative non-attention fallback.", self.threshold)
