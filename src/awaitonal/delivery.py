"""Conservative English delivery cues, separate from outcome and attention.

Input is already-cleaned assistant prose. These labels describe a reported
deliverable, not independently verified execution. Unsupported wording remains
unknown. All scans are linear in the bounded input, with fixed-size lookahead.
"""
import re
from typing import Literal

from .text import MAX_PROSE_CHARS, response_prose

Delivery = Literal["change", "answer", "plan", "artifact", "published", "unknown"]

_WORDS = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
_BREAKS = re.compile(r"(?<=[.!?])\s+|[;\n]+|\b(?:but|however)\b", re.I)
_PUBLICATION = {"published", "republished", "deployed", "released", "pushed", "uploaded", "merged", "shipped"}
_CHANGES = {"fixed", "implemented", "updated", "changed", "refactored", "added", "removed",
            "renamed", "corrected", "rewrote", "converted", "migrated", "restored", "replaced"}
_CREATION = {"created", "wrote", "written", "generated", "exported", "saved", "rendered", "prepared", "built", "assembled", "drafted", "composed"}
_INSPECTION = {"found", "identified", "diagnosed", "analyzed", "reviewed", "compared", "checked"}
_ACTIONS = _PUBLICATION | _CHANGES | _CREATION | _INSPECTION | {"made", "completed", "finished", "opened", "posted", "submitted"}
_MODIFIERS = {"now", "just", "also", "successfully", "already", "finally"}
_ARTIFACTS = {"pdf", "csv", "xlsx", "docx", "png", "jpg", "svg", "mp4", "mp3",
              "spreadsheet", "workbook", "presentation", "slides", "deck",
              "video", "image", "illustration", "audio", "wav", "archive", "zip", "wheel",
              "document", "report", "file", "export", "chart", "diagram",
              "files", "reports", "videos", "images", "documents", "artifact", "artifacts",
              "sheet", "table", "packet"}
_CHANGE_OBJECTS = {"code", "patch", "fix", "feature", "implementation", "migration", "changes",
                   "change", "refactor", "refactoring", "query", "handler", "function", "helper",
                   "component", "test", "tests", "config", "configuration", "issue", "bug",
                   "module", "script", "parser", "endpoint", "route", "schema", "adapter", "plugin"}
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
_VERDICT_HEADER = re.compile(
    r"\A\s*(?:\#{1,6}[ \t]+)?(?:\*\*|__)?"
    r"(?:(?:review|audit|assessment) verdict|verdict(?: on [^:\n]{1,60})?)"
    r"(?:\*\*|__)?[ \t]*:[ \t]*(?:\*\*|__)?[ \t]*(?P<body>\S.*)", re.I)
_FILE_DESTINATION = re.compile(
    r"\b(?:to|as|at)\s+(?:\.{0,2}/|/)?[a-z0-9_-][a-z0-9_./-]{0,180}\."
    r"(?:md|markdown|txt|rst|pdf|csv|tsv|xlsx|docx|pptx|png|jpe?g|svg|mp4|mp3|wav|zip)"
    r"(?=$|[\s.,;:!?)])", re.I)
_FILE_REFERENCE = re.compile(
    r"\b(?:to|as|at|into|in)\s+(?:(?:[a-z0-9'-]+\s+){0,4}awaitonal(?:file|artifactlink)\b|(?:\.{0,2}/|/)[a-z0-9_./~-]{1,180}"
    r"|[a-z0-9_-][a-z0-9_./-]{0,160}\.[a-z][a-z0-9]{0,12})(?=$|[\s.,;:!?)])", re.I)
_DRAFT_OBJECTS = {"reply", "draft", "message", "email", "response", "comment", "comments",
                  "memo", "letter", "brief", "notes", "checklist", "outline"}
_STORED = {"put", "placed", "stored", "left", "attached"}
_DIAGNOSIS_PREDICATES = {"is", "are", "isn't", "aren't", "doesn't", "don't", "reads", "uses",
                         "returns", "loads", "takes", "sends", "runs", "causes", "because",
                         "instead", "means", "depends"}
_UNAVAILABLE_VERDICT = {"pending", "unavailable", "incomplete", "unknown", "undecided", "undetermined", "deferred"}
_EVALUATION = {
    "correct", "incorrect", "sound", "unsound", "solid", "acceptable", "unacceptable",
    "appropriate", "inappropriate", "reasonable", "unreasonable", "sensible", "viable",
    "worthwhile", "sufficient", "insufficient", "safe", "unsafe", "risky", "overkill",
    "unnecessary", "necessary", "preferable", "better", "worse", "stronger", "weaker",
    "best", "worst", "right", "wrong", "good", "bad", "recommended", "safer", "riskier",
    "simpler", "cleaner",
}
_STANCE = {"recommend", "suggest", "favor", "favour", "prefer", "choose", "pick", "advise"}
_DECISION_ACTIONS = {"use", "keep", "retain", "stick", "choose", "pick", "select", "adopt",
                     "wait", "hold", "drop", "skip", "avoid", "proceed", "ship", "merge",
                     "release", "deploy", "publish", "build", "buy", "sell", "leave", "take", "replace"}
_ASSESSMENT_CONDITIONS = {"if", "unless", "when", "once", "assuming", "suppose", "hypothetical"}
# Verification and information-gathering suggestions are follow-up tasks, not
# an assessed choice. Keep this separate from decision actions such as waiting
# or retaining an alternative, which can themselves be the recommendation.
_PROCEDURES = {"ask", "asking", "check", "checking", "verify", "verifying",
               "confirm", "confirming", "validate", "validating", "test", "testing",
               "inspect", "inspecting", "review", "reviewing", "investigate", "investigating",
               "measure", "measuring", "monitor", "monitoring", "consult", "consulting",
               "contact", "contacting", "read", "reading", "discuss", "discussing",
               "find", "finding", "determine", "determining", "follow", "following"}


def _procedural_advice(words: list[str]) -> bool:
    """Identify the requested activity before inspecting its evaluated object."""
    target = words
    while target[:1] and target[0] in {"that", "you", "we", "they", "someone", "somebody",
                                         "anyone", "someone's", "the", "team", "should", "must", "to", "first", "and"}:
        target = target[1:]
    return bool(target and target[0] in _PROCEDURES)


def _current_assessment(words: list[str], part: str) -> bool:
    """Keep the asserted proposition separate from hypothetical/reported advice."""
    assertion = words
    # Conditions inside a causal explanation describe the evidence, rather
    # than necessarily making the recommendation itself contingent.
    for index, word in enumerate(words):
        if word in {"because", "since"}:
            assertion = words[:index]
            break
    if (not words or "?" in part or _historical(assertion)
            or _ASSESSMENT_CONDITIONS.intersection(assertion)):
        return False
    # A current stance may use "I would recommend"; a promised review and a
    # reported recommendation are not the assistant's present judgment.
    if set(assertion[:7]).intersection({"say", "says", "said", "i'll", "we'll", "will"}):
        return False
    if assertion[:1] in (["example"], ["examples"], ["hypothetical"]):
        return False
    if ({"docs", "documentation", "tutorial", "example"}.intersection(assertion[:3])
            and {"recommend", "recommends", "describes", "states", "explains", "calls"}.intersection(assertion[:7])):
        return False
    for index, word in enumerate(assertion[:10]):
        if (index and word in {"think", "thinks", "thought", "believe", "believes", "believed",
                               "recommend", "recommends", "recommended", "suggest", "suggests",
                               "suggested", "prefer", "prefers", "preferred", "advise", "advises"}
                and not {"i", "we", "i've", "we've", "i'd", "we'd"}.intersection(assertion[:index])):
            return False
    if words[:2] in (["i", "can't"], ["i", "cannot"], ["we", "can't"], ["we", "cannot"]):
        return False
    return True


def _structural_verdict(words: list[str], part: str) -> bool:
    """Recognize a stance or an evaluated subject, independent of its name.

    A preference selects an alternative; an implementation proposal merely
    promises work. Evaluative predicates require an asserted subject rather
    than finding an isolated judgment word anywhere in the response.
    """
    if not _current_assessment(words, part):
        return False
    # An explicit personal assessment label introduces the asserted clause;
    # its topic noun phrase is not the grammatical subject of that clause.
    if ":" in part:
        label, assertion = part.split(":", 1)
        label_words = _WORDS.findall(label.lower())
        if (label_words[:1] in (["my"], ["our"])
                and label_words[1:2] and label_words[1] in {
                    "assessment", "judgment", "judgement", "recommendation", "verdict", "conclusion"}):
            part = assertion.strip()
            words = _WORDS.findall(part.lower())
            if not _current_assessment(words, part):
                return False
    # Opening adjuncts do not change the grammatical subject of the main
    # assertion: "After comparing ..., I recommend ..." is still a stance.
    main = re.search(r",\s*(?:\*\*|__)?(?:i|we|i'd|we'd)\b", part, re.I)
    if main:
        words = _WORDS.findall(part[main.start() + 1:].lower())
    first = words[:16]
    # An affirmative go/no-go is already a judgment. Requiring an additional
    # rationale or a minimum reply length makes paraphrases of the same
    # recommendation disagree. Bare yes/no remains an ordinary answer.
    if (first[:1] == ["yes"] and len(first) >= 3
            and first[1] in _DECISION_ACTIONS | {"do"}):
        return True
    if (first[:2] in (["safe", "to"], ["unsafe", "to"])
            and first[2:3] and first[2] in _DECISION_ACTIONS):
        return True
    start = 0
    while start < min(len(first), 5) and first[start] in {
        "overall", "so", "therefore", "ultimately", "honestly", "personally", "now",
        "my", "our", "recommendation", "judgment", "judgement", "conclusion", "is",
    }:
        start += 1
    stance = first[start:]
    if stance[:1] and stance[0] in {"i", "we", "i'd", "we'd", "i'm", "we're"}:
        stance = stance[1:]
        while stance[:1] and stance[0] in {"would", "still", "now", "strongly", "definitely", "personally"}:
            stance = stance[1:]
        if stance[:1] == ["do"] and stance[1:2] == ["not"]:
            stance = ["don't", *stance[2:]]
        if stance[:1] == ["not"]:
            stance = ["wouldn't", *stance[1:]]
        if (stance[:1] in (["don't"], ["wouldn't"])
                and stance[1:2] and stance[1] in _STANCE and len(stance) >= 4):
            return True
        if stance[:1] and stance[0] in _STANCE and len(stance) >= 3:
            target = stance[1:]
            if _procedural_advice(target):
                return False
            # A bare plan to add/fix/investigate something is not an assessed
            # choice. Selection, abstention and named alternatives are.
            if target[0] not in {"adding", "fixing", "implementing", "investigating", "checking",
                                 "testing", "reviewing", "creating", "writing", "building",
                                 "to", "that"}:
                return True
            if target[0] == "that" and len(target) >= 4:
                return any(word in _DECISION_ACTIONS for word in target[1:5])
            if target[:1] == ["to"] and target[1:2] and target[1] in _DECISION_ACTIONS:
                return True
        if stance[:1] in (["go"], ["stick"]) and stance[1:2] == ["with"] and len(stance) >= 3:
            return True
        # A leaning/vote/ranking is a present choice, including softened
        # recommendations that never use the verb "recommend".
        choosing = stance
        if choosing[:1] in (["am"], ["'m"]):
            choosing = choosing[1:]
        if (choosing[:1] in (["lean"], ["leaning"])
                and choosing[1:2] in (["toward"], ["towards"], ["to"])
                and len(choosing) >= 3 and not _procedural_advice(choosing[2:])):
            return True
        if choosing[:2] in (["vote", "for"], ["vouch", "for"]) and len(choosing) >= 3:
            return True
        if (choosing[:1] in (["rank"], ["place"], ["put"])
                and len(choosing) >= 3
                and {"first", "ahead", "above"}.intersection(choosing[2:])):
            return True
        if stance[:1] and stance[0] in _DECISION_ACTIONS and len(stance) >= 3:
            # "I use this" reports behavior; "I'd keep this" gives advice.
            return any(word in {"i'd", "we'd", "would"} for word in first[:start + 3])
        if stance[:1] in (["wouldn't"], ["don't"]) and stance[1:2] and stance[1] in _DECISION_ACTIONS and len(stance) >= 4:
            return True
    # Standalone go/no-go labels express a decision but do not match ordinary
    # yes/no answers. A target, rationale or explicit status is still required.
    if (first[:2] in (["no", "go"], ["go", "ahead"])
            and len(first) >= 3 and not _procedural_advice(first[2:])):
        return True
    if ((first[:1] == ["don't"] and first[1:2]
         and first[1] in {"ship", "merge", "deploy", "release", "publish", "proceed"})
            or (first[:2] == ["do", "not"] and first[2:3]
                and first[2] in {"ship", "merge", "deploy", "release", "publish", "proceed"})):
        return True
    # Recommendation/choice framings can introduce any selected alternative,
    # without requiring "My call" or a specific heading.
    for index, word in enumerate(first[:6]):
        if (word in {"recommendation", "preference", "choice", "pick", "vote"}
                and set(first[:index]).issubset({"my", "our", "the", "current", "final", "preferred", "overall"})):
            tail = first[index + 1:]
            if tail[:1] == ["is"]:
                tail = tail[1:]
            if tail[:2] == ["goes", "to"]:
                tail = tail[2:]
            if _procedural_advice(tail):
                return False
            if tail[:1] == ["to"] and tail[1:2] and tail[1] in _DECISION_ACTIONS:
                return True
            if tail and tail[0] not in _UNAVAILABLE_VERDICT | {"not", "no", "to", "will"}:
                if len(tail) >= 2 and not {"later", "tomorrow"}.intersection(tail):
                    return True
    # Subject + copula + evaluative predicate. Unlike a list of domain nouns,
    # this works equally for a migration, vendor, design or unnamed "this".
    for index, word in enumerate(first[1:12], 1):
        if word not in {"is", "are", "looks", "look", "seems", "seem", "remains", "remain"}:
            continue
        subject = first[:index]
        if {"whether", "which", "how", "why", "tell", "know", "determine", "assess",
            "judge", "discuss", "explain", "describe", "ask", "asking", "check", "checking",
            "verify", "verifying", "confirm", "confirming", "ensure", "ensuring"}.intersection(subject):
            continue
        predicate = first[index + 1:]
        if word in {"looks", "look", "seems", "seem"} and predicate[:1] == ["like"]:
            predicate = predicate[1:]
        while predicate[:1] and predicate[0] in {"a", "an", "the", "clearly", "still", "now", "not", "too", "much", "probably", "really", "quite"}:
            predicate = predicate[1:]
        if predicate[:1] and predicate[0] in _EVALUATION:
            if predicate[1:2] == ["to"] and _procedural_advice(predicate[2:]):
                continue
            # Reporting which value was selected is not endorsing its quality.
            if predicate[0] in {"right", "wrong"} and predicate[1:2] in (["now"], ["side"]):
                continue
            return True
        if predicate[:1] == ["worth"] and len(predicate) >= 2:
            if predicate[1] not in {"noting", "mentioning", "remembering", "emphasizing"}:
                return True
        if predicate[:2] == ["ready", "to"] and set(predicate[2:4]).intersection(_DECISION_ACTIONS):
            return True
        if (predicate[:2] in (["my", "recommendation"], ["our", "recommendation"],
                               ["my", "preference"], ["our", "preference"],
                               ["my", "pick"], ["our", "pick"], ["my", "vote"], ["our", "vote"])):
            return True
        # A ranked choice may put its evaluation in the subject: "The safer
        # option is the staged release", rather than after the copula.
        if ({"best", "better", "safer", "preferred", "recommended"}.intersection(subject)
                and {"option", "choice", "approach", "alternative", "route", "path"}.intersection(subject)
                and predicate and predicate[0] not in _UNAVAILABLE_VERDICT | {"unknown", "unclear", "available", "ready"}):
            return True
    for index, word in enumerate(first[1:12], 1):
        if word in {"makes", "make"} and first[index + 1:index + 2] == ["sense"]:
            return True
        # Selection and ordering need an actual subject and comparator. An
        # ordinary factual "wins" or "first" elsewhere is not a verdict.
        if (word in {"beats", "outperforms", "outweighs"}
                and first[index + 1:] and {"option", "choice", "alternative", "approach"}.intersection(first[:index])):
            return True
        if (word in {"gets", "has", "earns", "wins"}
                and first[index + 1:index + 3] in (["my", "vote"], ["our", "vote"], ["my", "backing"], ["our", "backing"])):
            return True
        if (word in {"ranks", "comes"} and first[index + 1:index + 2] in (["first"], ["ahead"])
                and {"option", "choice", "alternative", "approach"}.intersection(first[:index])):
            return True
    # Withheld endorsement must identify a decision, rather than merely
    # reporting uncertainty about an observed fact.
    if (first[:3] in (["i", "don't", "see"], ["we", "don't", "see"])
            and {"case", "reason", "justification"}.intersection(first[3:7])
            and _DECISION_ACTIONS.intersection(first[4:12])):
        return True
    if ":" in part:
        label, selected = part.split(":", 1)
        label_words = _WORDS.findall(label.lower())
        selection = _WORDS.findall(selected.lower())
        if (set(label_words).intersection({"best", "better", "safer", "preferred", "recommended"})
                and set(label_words).intersection({"option", "choice", "approach", "alternative", "route", "path"})
                and selection and _available_verdict(selection)):
            return True
    return False


def _artifact_object(words: list[str]) -> bool:
    return (bool((_ARTIFACTS | _DRAFT_OBJECTS | {"awaitonalfile"}).intersection(words))
            or any(words[index:index + 2] == ["write", "up"] for index in range(len(words) - 1)))


def _available_verdict(words: list[str]) -> bool:
    """Explicit verdict framing must contain a judgment rather than defer it."""
    if len(words) < 2 or words[0] in _UNAVAILABLE_VERDICT:
        return False
    if words[:2] in (["not", "ready"], ["not", "available"], ["not", "yet"],
                     ["no", "verdict"], ["no", "decision"], ["no", "conclusion"]):
        return False
    if (words[:1] in (["i"], ["we"])
            and {"can't", "cannot", "couldn't", "don't"}.intersection(words[:4])
            and {"tell", "know", "decide", "determine", "conclude", "assess", "judge"}.intersection(words[:8])):
        return False
    return not {"i'll", "we'll", "docs", "documentation", "example", "hypothetical"}.intersection(words[:5])


def _diagnostic_explanation(words: list[str]) -> bool:
    """A terse 'Found it' needs a current explanation, not a promised one."""
    return (len(words) >= 6 and words[:1] in (["the"], ["this"], ["it"], ["our"], ["your"])
            and not _historical(words)
            and not _SUBJECT_BLOCKERS.intersection(words[:8])
            and bool(_DIAGNOSIS_PREDICATES.intersection(words[:12])))


def _supported_recommendation(parts: list[list[str]], position: int) -> bool:
    """Require present supporting prose for a terse go/no-go recommendation."""
    support = parts[position] if len(parts[position]) >= 8 else (
        parts[position + 1] if position + 1 < len(parts) else [])
    return (len(support) >= 4 and not _historical(support)
            and not set(support[:5]).intersection(
                {"example", "hypothetical", "please", "if", "unless", "when", "once",
                 "will", "would", "could", "might", "docs", "documentation", "says", "said"}))


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
    if len(objects) >= 2 and objects[0] == "and" and objects[1] in _ACTIONS:
        objects = objects[2:]
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
    if verb in _CREATION and any(objects[index:index + 2] == ["write", "up"] for index in range(len(objects) - 1)):
        return "artifact"
    # Compound noun phrases take their type from the head, so a "review
    # packet" is an artifact and an "implementation plan" is a plan. Stop
    # before descriptions of what the deliverable reads, produces or changes.
    object_phrase = []
    for word in objects:
        if word in {"to", "for", "of", "with", "from", "that", "which", "in", "at", "as", "and"}:
            break
        if (word.endswith("ing") and set(object_phrase).intersection(
                _PLAN_OBJECTS | _CHANGE_OBJECTS | _ARTIFACTS | _DRAFT_OBJECTS | _ANSWER_OBJECTS
                | {"awaitonalfile", "awaitonalartifactlink"})):
            break
        object_phrase.append(word)
    for word in reversed(object_phrase):
        if word in _PLAN_OBJECTS:
            return "plan"
        if word in _CHANGE_OBJECTS:
            return "change"
        if word in _ARTIFACTS:
            return "artifact"
        if word in _DRAFT_OBJECTS and verb in _CREATION | {"completed", "finished"}:
            return "artifact"
        if word in {"awaitonalfile", "awaitonalartifactlink"} and verb in _CREATION:
            return "artifact"
        if word in _ANSWER_OBJECTS:
            return "answer"
    if verb in _CREATION and set(objects).intersection({"awaitonalfile", "awaitonalartifactlink"}):
        return "artifact"
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
        if (predicate in _CREATION | _STORED | {"written", "ready", "available"}
                and (_artifact_object(subject)
                     or not _CHANGE_OBJECTS.intersection(subject)
                     and {"awaitonalfile", "awaitonalartifactlink"}.intersection(words[end + 1:]))):
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
    first = words[:10]
    presented_start = (2 if first[:2] in (["here", "is"], ["here", "are"])
                       else 1 if first[:1] == ["here's"] else 0)
    if presented_start and not _historical(words) and not _SUBJECT_BLOCKERS.intersection(first):
        phrase = []
        for word in first[presented_start:presented_start + 6]:
            if word in {"of", "for", "with", "below", "that", "containing"}:
                break
            phrase.append(word)
        for word in reversed(phrase):
            if word in _PLAN_OBJECTS:
                return "plan"
            if word in _DRAFT_OBJECTS | {"document", "documents"}:
                return "artifact"
            if word in _ANSWER_OBJECTS:
                return "answer"
    if total_words < 5:
        return "unknown"
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
        presented = words[start:start + 10]
        if (_DRAFT_OBJECTS.intersection(presented)
                and any(presented[index:index + 3] == ["ready", "to", "paste"]
                        for index in range(max(0, len(presented) - 2)))
                and not _SUBJECT_BLOCKERS.intersection(presented)
                and not _historical(words)):
            return "artifact"
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


def detect_assessment(prose: str, *, response_scoped: bool = False) -> str:
    """Recognize explicit current verdicts, never bare yes/no or imperatives."""
    if not isinstance(prose, str) or len(prose) > MAX_PROSE_CHARS:
        return "none"
    if not response_scoped:
        prose = response_prose(prose)
    if _summary_verdict(prose):
        return "verdict"
    example = False
    completed_review = False
    leading_verdict = False
    assessed_object = False
    no_blocker = False
    parts = [(part, _WORDS.findall(part.lower())) for part in _BREAKS.split(prose)]
    parts = [(part, words) for part, words in parts if words]
    clauses = [words for _, words in parts]
    for position, (part, words) in enumerate(parts):
        if part.rstrip().endswith(":"):
            if tuple(words) in _EXAMPLE_HEADERS:
                example = True
            elif tuple(words) in _RESULT_HEADERS:
                example = False
        if example:
            continue
        if _structural_verdict(words, part):
            return "verdict"
        # Explicit labels and later fallback evidence must obey the same
        # scope/tense/conditional checks as structural recommendations.
        if not _current_assessment(words, part):
            continue
        imperative = re.search(
            r"(?:^|,)\s*(?:yes[, ]+)?(?:(?:do not|don't)\s+)?"
            r"(?:choose|pick|select|keep|retain|avoid|skip|proceed|ship|merge|deploy|release|publish|go ahead)\b",
            part, re.I)
        if (imperative and not _procedural_advice(_WORDS.findall(part[imperative.end():].lower()))
                and _supported_recommendation(clauses, position)):
            return "verdict"
        if _historical(words) or set(words[:5]).intersection({"if", "would", "will", "example", "says", "said"}):
            continue
        if re.search(r"\b(?:review|audit|assessment) (?:is |was |has been )?(?:complete|finished)\b", part, re.I):
            completed_review = True
        if re.search(r"\b(?:review|audit|assessment) found no (?:issues|blockers|problems)\b", part, re.I):
            completed_review = True
        if header := _VERDICT_HEADER.match(part):
            body = _WORDS.findall(header["body"].lower())
            if _available_verdict(body):
                return "verdict"
        if (re.match(r"\s*(?:my|our) call\s*:\s*\S", part, re.I)
                and len(words) >= 5
                and _available_verdict(words[2:])
                and not {"if", "unless", "when", "once", "i'll", "we'll", "please",
                         "docs", "documentation", "hypothetical"}.intersection(words[2:5])):
            return "verdict"
        if (words[:3] in (["i'd", "go", "with"], ["we'd", "go", "with"])
                and len(words) >= 5
                and not {"if", "unless", "when", "once", "hypothetical"}.intersection(words)):
            return "verdict"
        if (words[:3] in (["yes", "ship", "it"], ["yes", "merge", "it"],
                          ["yes", "deploy", "it"], ["yes", "release", "it"],
                          ["yes", "publish", "it"], ["yes", "do", "it"])
                and not {"if", "unless", "when", "once"}.intersection(words)
                and _supported_recommendation(clauses, position)):
            return "verdict"
        if re.match(r"\s*(?:this|that|it|the (?:change|patch|issue)) (?:isn't|is not) "
                    r"(?:a )?(?:(?:release|merge|deployment) )?blocker\b", part, re.I):
            no_blocker = True
        if (no_blocker and re.match(r"\s*(?:i|we) wouldn't (?:delay|block|hold up) "
                                    r"(?:the |this |our )?(?:release|deployment|merge|launch)\b", part, re.I)
                and not {"if", "unless", "when", "once"}.intersection(words)):
            return "verdict"
        if re.match(r"\s*(?:approve|request changes|do not merge|don't merge)\b", part, re.I):
            leading_verdict = True
        if re.match(r"\s*safe to (?:merge|ship|deploy|release|publish)\b", part, re.I):
            leading_verdict = True
            if (not {"if", "unless", "when", "once"}.intersection(words)
                    and _supported_recommendation(clauses, position)):
                return "verdict"
        if re.search(r"\b(?:patch|implementation|migration|handler|change)\b[^.!?\n]{0,35}"
                     r"\b(?:matches|loses|breaks|violates|preserves|is reversible|is safe|is unsafe|has a (?:race|failure))\b", part, re.I):
            assessed_object = True
        if re.search(r"\b(?:my|our) (?:review|assessment|verdict) (?:of|on|for)\b[^.!?\n]{1,70}\b(?:is|finds|concludes)\b", part, re.I):
            return "verdict"
    return "verdict" if (completed_review or assessed_object) and leading_verdict else "none"


def detect_delivery(prose: str, *, response_scoped: bool = False) -> Delivery:
    """Return a conservative type for the current reported deliverable.

    Explicit publication outranks an artifact, which outranks a change. A plan
    or explanatory result needs positive framing; absence of an action cue is
    not evidence that an answer was delivered. Callers handle failure, waiting,
    refusal, structured output, and their effect on notification routing.
    """
    if not isinstance(prose, str) or len(prose) > MAX_PROSE_CHARS or not prose.strip():
        return "unknown"
    if not response_scoped:
        prose = response_prose(prose)
    parts = _BREAKS.split(prose)
    clauses = [_WORDS.findall(part.lower()) for part in parts]
    total_words = sum(map(len, clauses))
    detected: Delivery = "unknown"
    example = False
    artifact_heading = False
    found_it = False
    for part, words in zip(parts, clauses):
        if not words:
            continue
        previous_found_it = found_it
        found_it = False
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
            if previous_found_it and _diagnostic_explanation(words):
                candidates.append("answer")
            candidates.append(_passive(words))
            position = _action(words)
            if position is not None:
                kind = _action_kind(words, position)
                found_it = words[position:] == ["found", "it"]
                if (kind != "change" and words[position] in _CREATION
                        and not {"no", "not", "nothing", "none", "neither"}.intersection(
                            words[position + 1:position + 4])
                        and (_FILE_DESTINATION.search(part) or _FILE_REFERENCE.search(part))):
                    kind = "artifact"
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
    if detected == "unknown" and detect_assessment(prose, response_scoped=True) == "verdict":
        return "answer"
    return detected
