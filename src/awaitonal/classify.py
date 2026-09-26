"""Small conservative rules baseline, independent of ML libraries."""
import re
from .activity import detect_activity
from .delivery import detect_assessment, detect_delivery
from .handoff import analyze_handoff
from .text import assistant_prose, sentences
from .types import Classification, Event, STATES, controls_for, map_controls


def _has(pattern: str, text: str) -> bool:
    return bool(re.search(pattern, text, re.I))


def result(state: str, event: Event, reason: str, threshold: float,
           diagnostics: dict | None = None, *, delivery_kind="unknown",
           expectancy="none", handoff_kind="action", activity="unknown",
           assessment_kind="none") -> Classification:
    controls = controls_for(state)
    return Classification("unknown" if state == "unknown" else map_controls(controls, threshold), controls,
                          event.evidence_source, reason, diagnostics or {}, delivery_kind,
                          "required-handoff" if state == "needs-you" else expectancy, handoff_kind,
                          event.failure_code, activity, assessment_kind)


def explicit_result(event: Event, threshold: float) -> Classification | None:
    if event.explicit_state in STATES:
        reason = "Structured API failure: " + event.failure_code + "." if event.failure_code else "Explicit structured event."
        return result(event.explicit_state, event, reason, threshold,
                      handoff_kind="decision" if event.evidence_source == "claude:PreToolUse" else "action")
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
    return any(
        _has(r"\b(done|completed?|implemented|finished|fixed|resolved|delivered|all set|ready|works|working|passes|passed|succeeded|successful(?:ly)?|verified)\b", part)
        and not _has(r"\b(?:will|would|plan to|intend to|going to|tomorrow)\b|\b(?:I'll|we'll)\b", part)
        for part in sentences(text)
    )


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
        r"\bI (?:won't|will not) (?:provide|create|build|implement)\b|"
        r"\bI (?:cannot|can't) provide\b", text)


def unresolved(text: str) -> bool:
    if _has(NEGATED_COMPLETION, text):
        return True
    # Subject-matter words (error/failure/cannot/pending) are not evidence of
    # unfinished work. Require a status assertion or the assistant's inability
    # to carry out an action, keeping negative diagnostic findings neutral.
    return unfinished_work(text) or _has(
        r"\b(?:caveat|limitation)\s*:|\bwith (?:some |one |a )?caveats?\b|"
        r"\b(?:tests?|checks?|build) (?:still )?(?:fail(?:s|ed|ing)?)\b|"
        r"\b(?:failing|failed|unverified|untested) (?:tests?|checks?)\b|"
        r"\b(?:errors?|failures?) (?:remain|persist|in (?:the |our |my )?(?:tests?|checks?|build))\b|"
        r"\b(?:tests?|checks?|build|implementation|work|task|review|analysis|assessment|validation|verification|behavior)\b"
        r"[^.!?\n]{0,65}\b(?:remains? |is |are |was |were |still |has |have )+"
        r"(?:unverified|untested|unavailable|incomplete|unresolved|blocked|pending|failing|failed|fails?|errors?)\b|"
        r"\b(?:no tests (?:were )?run|tests? (?:were |was )?not (?:run|tested)|"
        r"remaining (?:work|checks|tests)|unverified (?:work|checks|tests)|untested (?:work|changes|code))\b", text)


def unfinished_work(text: str) -> bool:
    return _has(
        r"\b(?:i|we) (?:wasn't|weren't|was not|were not|haven't been|have not been) able to "
        r"(?:finish|complete|verify|validate|test|run|execute|check|fix|implement|build|inspect)\b|"
        r"(?:^|[.!?;]\s*)(?:could not|couldn't|unable to|failed to) "
        r"(?:finish|complete|verify|validate|test|run|execute|check|fix|implement|build|inspect)\b|"
        r"\b(?:verification|validation|tests?|checks?) (?:could not|couldn't|cannot|can't) be "
        r"(?:completed|finished|run|executed|performed)\b|"
        r"\b(?:i|we) (?:have |had )?(?:not|haven't|hadn't) (?:(?:yet|fully) )?(?:finished|completed|implemented|verified|validated|tested|fixed|built)\b|"
        r"\b(?:i|we) (?:was |were |am |are )?(?:could not|couldn't|cannot|can't|unable to|did not|didn't|have not|haven't|failed to) "
        r"(?:(?:yet|fully) )?(?:finish|complete|produce|provide|help|prepare|verify|validate|test|run|execute|check|fix|implement|build|deploy|publish|inspect)\b|"
        r"\b(?:tests?|checks?) (?:could not|couldn't|cannot|can't|were not|was not|have not been) (?:run|executed|completed|verified)\b|"
        r"\b(?:requested (?:work|task|change|implementation)|my (?:work|implementation)|our (?:work|implementation)) "
        r"(?:is |remains )?not (?:yet )?(?:done|complete|completed|ready|implemented)\b|"
        r"\b(?:work|task|review|analysis|assessment|cause|result|tests?|checks?|implementation|validation|verification) "
        r"(?:(?:is|are|was|were|remains?|still) ){1,3}(?:unfinished|unverified|untested|incomplete|unavailable|pending)\b|"
        r"\b(?:still investigating|not yet (?:finished|complete|ready)|"
        r"review (?:is |remains )?incomplete|analysis (?:is |remains )?incomplete)\b", text)


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
        if not isinstance(event, Event) or event.kind == "turn-start":
            return None
        if event.explicit_state is not None:
            return explicit_result(event, self.threshold)
        # Strip URL targets before *all* routing. Words in paths, queries, or
        # fragments are reference data, not claims about this turn's outcome.
        prose = assistant_prose(event.text, link_types=True)
        if not prose:
            return None
        handoff = analyze_handoff(prose)
        delivery = detect_delivery(prose)
        assessment = detect_assessment(prose)
        activity, activity_source = detect_activity(prose, event.background_tasks, event.session_crons)
        # Background registries are session-wide. A completed artifact or
        # assessment must not turn into an activity pulse due to a monitor.
        if delivery != "unknown":
            activity = "final"

        def classified(state, reason):
            return result(state, event, reason, self.threshold, delivery_kind=delivery,
                          expectancy=handoff.expectancy, handoff_kind=handoff.kind,
                          activity=activity if activity != "unknown" else "final" if state == "done" else "unknown",
                          assessment_kind=assessment,
                          diagnostics={"activity_evidence": activity_source} if activity_source != "none" else None)

        parts = sentences(prose)
        meaningful = [s for s in parts if not is_optional(s)] or parts
        for sentence in meaningful:
            if is_refusal(sentence) and not _has(r"\b(?:earlier|previously|initially|at first|no longer)\b", sentence):
                temporary_dependency = (
                    _has(r"\b(?:because|until|without|unless)\b", sentence)
                    and analyze_handoff(sentence).expectancy == "required-handoff"
                )
                temporary_inability = (
                    _has(r"\bI (?:cannot|can't|am unable to)\b", sentence)
                    and (_has(r"\b(?:yet|right now|at the moment)\b", sentence)
                         or (_has(r"\bbecause\b", sentence)
                             and _has(r"\b(?:unavailable|offline|missing|unreachable|"
                                      r"not accessible|not found|lack access|no access)\b", sentence)))
                )
                if not temporary_dependency and not temporary_inability:
                    return classified("rejected", "Prose contains a direct refusal.")
        if handoff.expectancy == "required-handoff":
            return classified("needs-you", "Current progress requires a user choice, authorization, or action.")
        # Drop an earlier failed attempt only when a later clause explicitly
        # reports recovery/success. Keep unrelated unverified tests as caveats.
        active = []
        for sentence in meaningful:
            if handoff.expectancy == "none":
                # A satisfied handoff is not a remaining limitation. Remove
                # only its clause, preserving independent testing caveats in
                # the same sentence. Each clause is scanned once, never a
                # growing suffix of all remaining prose.
                retained = []
                for clause in re.split(r",\s*|\s+and\s+", sentence, flags=re.I):
                    independent_limit = _has(
                        r"\b(?:unverified|untested|unavailable|unfinished|incomplete)\b|"
                        r"\b(?:tests?|checks?)\b[^.!?\n]{0,45}\b(?:fail|failed|not run|not tested)\b", clause)
                    if independent_limit or analyze_handoff(clause).expectancy != "required-handoff":
                        retained.append(clause)
                sentence = " and ".join(retained)
                if not sentence.strip():
                    continue
            clauses = re.split(r"\b(?:but|however|now|after (?:fixing|repairing))\b", sentence, flags=re.I)
            if len(clauses) > 1 and has_completion(clauses[-1]) and not unresolved(clauses[-1]):
                sentence = clauses[-1]
            active.append(sentence)
        joined = " ".join(active)
        # Negative findings can be the requested deliverable. A reported
        # explanation or plan is distinct from a failed attempt to produce it.
        incomplete_delivery = unfinished_work(joined) or (
            _has(NEGATED_COMPLETION, joined) and delivery not in ("answer", "plan"))
        if delivery in ("answer", "plan") and not incomplete_delivery:
            return classified("done", "A requested answer, assessment, or proposal is reported delivered.")
        if incomplete_delivery:
            return classified("caveats", "Prose explicitly reports unfinished work or a validation gap.")
        if unresolved(joined):
            previous = " ".join(active[:-1])
            final = active[-1] if active else ""
            # A later success resolves earlier errors, but not skipped validation.
            earlier_only_failure = _has(r"\b(?:fail|error|broke)", previous) and not _has(r"\b(?:unverified|untested|unavailable|not tested|not run|could not|couldn't|remaining)\b", previous)
            if not (earlier_only_failure and has_completion(final) and not unresolved(final)):
                return classified("caveats", "Prose reports unresolved work or limited verification.")
        if activity == "in-flight":
            return classified("unknown", "Work is reported ongoing without a required user action.")
        if has_completion(joined):
            return classified("done", "Prose reports completion; correctness is not independently verified.")
        if delivery != "unknown":
            return classified("done", "Prose reports a delivered result; correctness is not independently verified.")
        if handoff.expectancy == "review-requested":
            return classified("done", "The assistant directly invites review or feedback; no blocking dependency is stated.")
        return classified("unknown", "No clear completion, limitation, or required action; neutral uncertain fallback.")
