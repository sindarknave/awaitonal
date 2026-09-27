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
_PUBLICATION = {"published", "republished", "deployed", "released", "pushed", "uploaded", "merged", "shipped"}
_CHANGES = {"fixed", "implemented", "updated", "changed", "refactored", "added", "removed",
            "renamed", "corrected", "rewrote", "converted", "migrated", "restored", "replaced"}
_CREATION = {"created", "wrote", "generated", "exported", "saved", "rendered", "prepared", "built"}
_INSPECTION = {"found", "identified", "diagnosed", "analyzed", "reviewed", "compared", "checked"}
_ACTIONS = _PUBLICATION | _CHANGES | _CREATION | _INSPECTION | {"made", "completed", "opened", "posted", "submitted"}
_MODIFIERS = {"now", "just", "also", "successfully", "already", "finally"}
_ARTIFACTS = {"pdf", "csv", "xlsx", "docx", "png", "jpg", "svg", "mp4", "mp3",
              "spreadsheet", "workbook", "presentation", "slides", "deck",
              "video", "image", "illustration", "audio", "wav", "archive", "zip", "wheel",
              "document", "report", "file", "export", "chart", "diagram",
              "files", "reports", "videos", "images", "documents", "artifact", "artifacts"}
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
_ARTIFACT_LOCATION = {"the", "a", "an", "my", "our", "your", "it", "this", "that", "requested",
                      "final", "same", "new", "latest", "to", "at", "url", "link"}
_SUMMARY_HEADER = re.compile(
    r"\A\s*(?:\#{1,6}[ \t]+Business[ \t]+Summary[ \t]*:?[ \t]*\n+"
    r"|(?:\*\*|__)Business[ \t]+Summary(?:\*\*|__)[ \t]*:?[ \t]*(?:\n+)?"
    r"|Business[ \t]+Summary[ \t]*(?::[ \t]*|\n+))", re.I)
_SUMMARY_BOTTOM_LINE = re.compile(
    r"\A\s*(?:\*\*|__)?(?:approve(?:\*\*|__)?(?=[.!;:]|\s*$)|request changes\b"
    r"|(?:don't|do not) (?:build|merge|ship|deploy|release|publish|use|proceed)\b"
    r"|safe(?: to (?:merge|ship|deploy|release|publish|use))?(?:\*\*|__)?(?=[,.!;:]|\s*$))", re.I)


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
    if verb == "opened":
        if {"inspect", "read", "browse", "browser", "view"}.intersection(objects):
            return "unknown"
        return "published" if ("awaitonalprlink" in objects or "pr" in objects or objects[:2] == ["pull", "request"]) else "unknown"
    if verb in {"posted", "submitted"} and set(objects).intersection({"review", "comment", "message", "pr", "issue", "awaitonalprlink"}):
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
        pr_subject = subject[1:] if subject[:1] in (["the"], ["my"], ["our"], ["your"]) else subject
        if (words[position] in {"is", "are"} and predicate == "up"
                and pr_subject in (["pr"], ["pull", "request"])
                and (not words[end + 1:] or words[end + 1] == "awaitonalprlink"
                     or words[end + 1:end + 3] in (["at", "awaitonalprlink"], ["on", "github"]))):
            return "published"
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
            if word in {"pdf", "csv", "xlsx", "spreadsheet", "workbook", "slides", "deck", "video", "archive", "artifact", "artifacts"}:
                return "artifact"
    # A substantive declarative explanation can lack an introductory heading.
    # Avoid promises and requests; they are not delivered information.
    if not set(first).intersection({"i", "we", "if", "will", "would", "could", "should", "please"}):
        if set(first).intersection({"because", "means", "causes", "occurs", "happens", "explains", "returns", "uses", "supports", "depends"}):
            return "answer"
        if (first[:1] in (["yes"], ["no"]) and len(words) >= 5
                and first[1:2] in (["this"], ["that"], ["it"], ["the"], ["your"])):
            return "answer"
    return "unknown"


def _artifact_link_delivery(words: list[str]) -> bool:
    """Recognize an artifact's presented destination, never a bare citation."""
    try:
        link = words.index("awaitonalartifactlink", 0, 16)
    except ValueError:
        return False
    before = words[:link]
    if _historical(before) or _SUBJECT_BLOCKERS.intersection(before):
        return False
    if words[:2] in (["here", "is"], ["here", "are"]) or words[:1] == ["here's"]:
        return not {"reference", "example", "source", "citation"}.intersection(before)
    position = _action(before)
    if position is None or before[position] not in _CREATION | _CHANGES | _PUBLICATION:
        return False
    objects = before[position + 1:]
    # A short destination directly after the action can stand in for the
    # artifact noun: 'Fixed — same URL: <artifact>'. A code/site change with
    # a reference link later in the sentence must retain its original type.
    return all(word in _ARTIFACT_LOCATION | _ARTIFACTS for word in objects)


def _summary_verdict(prose: str) -> bool:
    """A summary heading needs an actual bottom line and supporting prose."""
    header = _SUMMARY_HEADER.match(prose)
    if not header:
        return False
    body = prose[header.end():].strip()
    if not _SUMMARY_BOTTOM_LINE.match(body):
        return False
    parts = [_WORDS.findall(part.lower()) for part in _BREAKS.split(body)]
    parts = [words for words in parts if words]
    words = parts[0]
    # A conditional/historical recommendation is not a present verdict. The
    # heading alone, bare 'Approve', and general yes/no answers remain neutral.
    if _historical(words) or {"if", "unless", "when", "once", "example", "would", "will"}.intersection(words):
        return False
    if sum(map(len, parts)) < 8:
        return False
    # A short bottom line must be followed by present supporting prose, not
    # a promise to review later, an access request, or a sample response.
    support = words if len(words) >= 8 else (parts[1] if len(parts) > 1 else [])
    if (_historical(support) or set(support[:5]).intersection(
            {"example", "hypothetical", "please", "if", "unless", "will", "would", "could", "might"})):
        return False
    return len(support) >= 4


def detect_assessment(prose: str) -> str:
    """Recognize explicit current verdicts, never bare yes/no or imperatives."""
    if not isinstance(prose, str) or len(prose) > MAX_PROSE_CHARS:
        return "none"
    if _summary_verdict(prose):
        return "verdict"
    example = False
    completed_review = False
    leading_verdict = False
    assessed_object = False
    for part in _BREAKS.split(prose):
        words = _WORDS.findall(part.lower())
        if not words:
            continue
        if part.rstrip().endswith(":"):
            if tuple(words) in _EXAMPLE_HEADERS:
                example = True
            elif tuple(words) in _RESULT_HEADERS:
                example = False
        if example or _historical(words) or set(words[:5]).intersection({"if", "would", "will", "example", "says", "said"}):
            continue
        if re.search(r"\b(?:review|audit|assessment) (?:is |was |has been )?(?:complete|finished)\b", part, re.I):
            completed_review = True
        if re.search(r"\b(?:review|audit|assessment) found no (?:issues|blockers|problems)\b", part, re.I):
            completed_review = True
        if re.match(r"\s*(?:#+\s*)?(?:(?:review|audit|assessment) verdict|verdict(?: on [^:\n]{1,60})?)\s*:\s*\S", part, re.I):
            return "verdict"
        if re.match(r"\s*(?:approve|request changes|do not merge|don't merge)\b", part, re.I):
            leading_verdict = True
        if re.match(r"\s*safe to merge\b", part, re.I):
            leading_verdict = True
        if re.search(r"\b(?:patch|implementation|migration|handler|change)\b[^.!?\n]{0,35}"
                     r"\b(?:matches|loses|breaks|violates|preserves|is reversible|is safe|is unsafe|has a (?:race|failure))\b", part, re.I):
            assessed_object = True
        if re.search(r"\b(?:my|our) (?:review|assessment|verdict) (?:of|on|for)\b[^.!?\n]{1,70}\b(?:is|finds|concludes)\b", part, re.I):
            return "verdict"
    return "verdict" if (completed_review or assessed_object) and leading_verdict else "none"


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
        artifact_link = _artifact_link_delivery(words)
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
        # Republishing a presented artifact updates that deliverable. This
        # replaces the generic publication/change cue for this clause only;
        # separate reports of an external release still take precedence.
        if artifact_link:
            candidates = ["artifact"]
        best = max(candidates, key=_PRIORITY.__getitem__)
        if _PRIORITY[best] > _PRIORITY[detected]:
            detected = best
    if detected == "unknown" and detect_assessment(prose) == "verdict":
        return "answer"
    return detected
