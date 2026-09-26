"""Conservative English delivery cues, separate from outcome and attention.

Input is already-cleaned assistant prose. These labels describe a reported
deliverable, not independently verified execution. Unsupported wording remains
unknown. All scans are linear in the bounded input, with fixed-size lookahead.
"""
import re
from typing import Literal

from .text import MAX_PROSE_CHARS

Delivery = Literal["change", "answer", "plan", "artifact", "published", "unknown"]

_WORDS = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_BREAKS = re.compile(r"(?<=[.!?])\s+|[;\n]+|\b(?:but|however)\b", re.I)
_PUBLICATION = {"published", "deployed", "released", "pushed", "uploaded", "merged", "shipped"}
_CHANGES = {"fixed", "implemented", "updated", "changed", "refactored", "added", "removed",
            "renamed", "corrected", "rewrote", "converted", "migrated", "restored", "replaced"}
_CREATION = {"created", "wrote", "generated", "exported", "saved", "rendered", "prepared", "built"}
_INSPECTION = {"found", "identified", "diagnosed", "analyzed", "reviewed", "compared", "checked"}
_ACTIONS = _PUBLICATION | _CHANGES | _CREATION | _INSPECTION | {"made", "completed"}
_MODIFIERS = {"now", "just", "also", "successfully", "already", "finally"}
_ARTIFACTS = {"pdf", "csv", "xlsx", "docx", "png", "jpg", "svg", "mp4", "mp3",
              "spreadsheet", "workbook", "presentation", "slides", "deck",
              "video", "image", "illustration", "audio", "wav", "archive", "zip", "wheel",
              "document", "report", "file", "export", "chart", "diagram",
              "files", "reports", "videos", "images", "documents"}
_CHANGE_OBJECTS = {"code", "patch", "fix", "feature", "implementation", "migration", "changes",
                   "change", "refactor", "refactoring", "query", "handler", "function", "helper",
                   "component", "test", "tests", "config", "configuration", "issue", "bug"}
_PUBLIC_OBJECTS = {"site", "website", "app", "service", "release", "version", "package", "build",
                   "deployment", "changes", "branch", "pr", "update", "function", "report"}
_PLAN_OBJECTS = {"plan", "proposal", "roadmap", "recommendations", "strategy"}
_ANSWER_OBJECTS = {"answer", "analysis", "assessment", "review", "audit", "diagnosis", "comparison"}
_HISTORY = {"previously", "earlier", "yesterday", "originally", "historically", "ago"}
_PAST_TIMES = {"time", "week", "month", "year", "release", "deployment", "session"}
_CALENDAR = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
             "january", "february", "march", "april", "may", "june", "july", "august",
             "september", "october", "november", "december"}
_SUBJECT_BLOCKERS = {"if", "when", "once", "unless", "example", "example's", "hypothetical",
                     "docs", "documentation", "tutorial", "says", "said", "saying",
                     "no", "not", "never", "will", "would", "could", "should", "may", "might",
                     "planned", "proposed", "future", "historical"}
_AUXILIARIES = {"is", "are", "was", "were", "has", "have"}
_PRIORITY = {"unknown": 0, "answer": 1, "plan": 2, "change": 3, "artifact": 4, "published": 5}
_STATUS_ONLY = {"not", "yet", "still", "fully", "actually", "currently", "fixed", "complete",
                "completed", "ready", "working", "implemented", "resolved", "done", "finished"}
_EXAMPLE_HEADERS = {("example",), ("for", "example"), ("hypothetical", "example"),
                    ("sample", "output"), ("expected", "output")}
_RESULT_HEADERS = {("actual", "result"), ("result",), ("changes", "made"),
                   ("current", "status"), ("actual", "changes")}


def _historical(words: list[str]) -> bool:
    if _HISTORY.intersection(words):
        return True
    for word, following in zip(words, words[1:]):
        if word in {"last", "previous"} and following in _PAST_TIMES:
            return True
        if word in {"in", "on"} and (following in _CALENDAR or
                                       (len(following) == 4 and following.isdigit())):
            return True
    return False


def _action(words: list[str]) -> int | None:
    """Find a terse past-tense report or a first-person completed action."""
    position = 0
    while position < min(len(words), 4) and words[position] in _MODIFIERS | {"done"}:
        position += 1
    personal = position < len(words) and words[position] in {"i", "we", "i've", "we've"}
    if personal:
        position += 1
        for _ in range(4):
            if position < len(words) and words[position] in _MODIFIERS | {"have"}:
                position += 1
            else:
                break
    if position < len(words) and words[position] in _ACTIONS:
        # A leading participle can describe a class of objects instead of an
        # event: 'Published packages include ...' is not 'Published the package'.
        if not personal:
            for word in words[position + 1:position + 6]:
                if word in {"and", "which", "that", "with", "to", "for"}:
                    break
                if word in {"is", "are", "was", "were", "include", "includes", "contain",
                            "contains", "explain", "explains", "can", "may", "should"}:
                    return None
        return position
    return None


def _action_kind(words: list[str], position: int) -> Delivery:
    verb = words[position]
    # Inspect only the immediate object, not later explanations mentioning
    # some unrelated artifact or publication. The nearest known object wins.
    objects = words[position + 1:position + 9]
    if {"no", "not", "nothing", "none", "neither"}.intersection(objects[:3]):
        return "unknown"
    if verb in _PUBLICATION:
        return "published"
    if verb in _CHANGES:
        return "change"
    if verb in _INSPECTION:
        return "answer" if len(objects) >= 2 else "unknown"
    for word in objects:
        if word in _PLAN_OBJECTS:
            return "plan"
        if word in _CHANGE_OBJECTS:
            return "change"
        if word in _ARTIFACTS:
            return "artifact"
        if word in _ANSWER_OBJECTS:
            return "answer"
    return "unknown"


def _passive(words: list[str]) -> Delivery:
    # Bounded subject + present/perfect predicate. Future/modal/negated
    # predicates do not match. A docs/example subject is not an event report.
    if {"if", "unless", "once", "example", "hypothetical"}.intersection(words):
        return "unknown"
    for position in range(1, min(len(words), 9)):
        if words[position] not in _AUXILIARIES:
            continue
        subject = words[:position]
        if _SUBJECT_BLOCKERS.intersection(subject):
            continue
        end = position + 1
        if words[position] in {"has", "have"}:
            if words[end:end + 1] != ["been"]:
                continue
            end += 1
        if words[end:end + 1] in (["now"], ["just"], ["successfully"]):
            end += 1
        if end >= len(words):
            continue
        predicate = words[end]
        version = any(word.startswith("v") and word[1:].isdigit() for word in subject)
        if predicate in _PUBLICATION | {"live"} and (_PUBLIC_OBJECTS.intersection(subject) or version):
            return "published"
        if predicate in _CREATION | {"written", "ready", "available", "attached"} and _ARTIFACTS.intersection(subject):
            return "artifact"
        if predicate in {"ready", "complete", "completed"} and _PLAN_OBJECTS.intersection(subject):
            return "plan"
        if predicate in _CHANGES | {"complete", "completed", "ready"} and _CHANGE_OBJECTS.intersection(subject):
            return "change"
        if predicate in {"complete", "completed", "ready"} and _ANSWER_OBJECTS.intersection(subject):
            return "answer"
    return "unknown"


def _framing(words: list[str], total_words: int) -> Delivery:
    """Recognize a delivered explanation/proposal, not a promise to make one."""
    if total_words < 5:
        return "unknown"
    first = words[:10]
    subject = 1 if first[0] in {"the", "my", "our", "your"} and len(first) > 1 else 0
    if first[subject] in _ANSWER_OBJECTS | _PLAN_OBJECTS | {"findings", "verdict"}:
        # A noun at the start is not always a report heading. Explicitly
        # unavailable/unfinished deliverables must not manufacture an answer.
        status = subject + 1
        while status < min(len(first), 4) and first[status] in {"is", "are", "remains", "still"}:
            status += 1
        if first[status:status + 1] and first[status] in {
            "not", "cannot", "can't", "couldn't", "failed", "unavailable", "incomplete",
            "pending", "blocked", "missing", "cancelled", "canceled",
        }:
            return "unknown"
    if first[:2] in (["changes", "made"], ["what", "changed"]):
        return "change"
    if first[:3] == ["summary", "of", "changes"]:
        return "change"
    if first[:2] in (["i", "recommend"], ["we", "recommend"], ["i", "propose"],
                     ["my", "proposal"], ["recommended", "approach"],
                     ["proposed", "approach"], ["implementation", "plan"]):
        return "plan"
    if first[:1] in (["plan"], ["proposal"], ["recommendations"]) and first[1:2] != ["to"]:
        return "plan"
    if first[:1] in (["findings"], ["analysis"], ["assessment"], ["diagnosis"], ["verdict"]):
        return "answer"
    if first[:3] in (["the", "cause", "is"], ["the", "problem", "is"],
                     ["the", "issue", "is"], ["the", "reason", "is"]):
        if set(words[3:]).issubset(_STATUS_ONLY):
            return "unknown"
        return "answer"
    if first[:2] == ["root", "cause"] or first[:4] == ["the", "root", "cause", "is"]:
        return "answer"
    # Here is / here's identifies a present deliverable, with a small,
    # explicit noun phrase. Do not treat any arbitrary following noun as one.
    start = 0
    if first[:2] in (["here", "is"], ["here", "are"]):
        start = 2
    elif first[:1] == ["here's"]:
        start = 1
    if start:
        for word in first[start:start + 5]:
            if word in _PLAN_OBJECTS:
                return "plan"
            if word in _ANSWER_OBJECTS | {"findings", "explanation", "breakdown", "why"}:
                return "answer"
            if word in {"pdf", "csv", "xlsx", "spreadsheet", "workbook", "slides", "deck", "video", "archive"}:
                return "artifact"
    # A substantive declarative explanation can lack an introductory heading.
    # Avoid promises and requests; they are not delivered information.
    if not set(first).intersection({"i", "we", "if", "will", "would", "could", "should", "please"}):
        if set(first).intersection({"because", "means", "causes", "occurs", "returns", "uses", "supports", "depends"}):
            return "answer"
        if (first[:1] in (["yes"], ["no"]) and len(words) >= 5
                and first[1:2] in (["this"], ["that"], ["it"], ["the"], ["your"])):
            return "answer"
    return "unknown"


def detect_delivery(prose: str) -> Delivery:
    """Return a conservative type for the current reported deliverable.

    Explicit publication outranks an artifact, which outranks a change. A plan
    or explanatory result needs positive framing; absence of an action cue is
    not evidence that an answer was delivered. Callers handle failure, waiting,
    refusal, structured output, and their effect on notification routing.
    """
    if not isinstance(prose, str) or len(prose) > MAX_PROSE_CHARS or not prose.strip():
        return "unknown"
    parts = _BREAKS.split(prose)
    clauses = [_WORDS.findall(part.lower()) for part in parts]
    total_words = sum(map(len, clauses))
    detected: Delivery = "unknown"
    example = False
    artifact_heading = False
    for part, words in zip(parts, clauses):
        if not words:
            continue
        previous_artifact_heading = artifact_heading
        artifact_heading = bool(
            part.rstrip().endswith(":")
            and _ARTIFACTS.intersection(words)
            and {"output", "requested", "deliverable"}.intersection(words)
            and not {"planned", "proposed", "future", "example", "expected"}.intersection(words)
            and not _historical(words)
        )
        if part.rstrip().endswith(":"):
            if tuple(words) in _EXAMPLE_HEADERS:
                example = True
                continue
            if tuple(words) in _RESULT_HEADERS:
                example = False
        if example:
            continue
        candidates = [_framing(words, total_words)]
        if not _historical(words):
            candidates.append(_passive(words))
            position = _action(words)
            if position is not None:
                kind = _action_kind(words, position)
                if (kind == "unknown" and previous_artifact_heading
                        and words[position] in {"rendered", "generated", "exported", "saved"}
                        and words[position + 1:] in (["and", "opened"], ["and", "saved"])):
                    kind = "artifact"
                candidates.append(kind)
            if position is not None or not _SUBJECT_BLOCKERS.intersection(words):
                # A completed action can inherit the initial subject. After
                # other status prose require a fresh first-person subject;
                # modal, conditional, and example framing stays excluded.
                for index, word in enumerate(words):
                    if word == "and":
                        tail = words[index + 1:index + 13]
                        if position is None and tail[:1] not in (["i"], ["we"], ["i've"], ["we've"]):
                            continue
                        follow = _action(tail)
                        if follow is not None:
                            candidates.append(_action_kind(tail, follow))
        best = max(candidates, key=_PRIORITY.__getitem__)
        if _PRIORITY[best] > _PRIORITY[detected]:
            detected = best
    return detected
