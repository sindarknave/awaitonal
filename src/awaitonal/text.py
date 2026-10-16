"""Conservative assistant-prose extraction and bounded, token-aware selection."""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

MAX_PROSE_CHARS = 131_072
# These words select context for the encoder; they do not choose a class.
SALIENCE = re.compile(r"\b(wait|await|approval|approve|permission|choose|choice|decide|answer|before|cannot|can't|refus|declin|won't|unable|fail|error|recover|fixed|resolved|unavailable|blocked|remaining|caveat)", re.I)

_DOCUMENT_NOUN = re.compile(
    r"\b(?:draft|reply|response|email|message|letter|memo|document|report|brief|write-up|note|content|dialogue)\b", re.I)
_DOCUMENT_INTRO = re.compile(
    r"^\s*(?:\#{1,6}\s*)?(?P<intro>(?:"
    r"(?:here(?:'s| is| are)|below (?:is|are))\s+[^:\n]{1,160}|"
    r"(?:i|we)(?:'ve| have)?\s+(?:wrote|written|drafted|prepared|assembled)\s+[^:\n]{1,160}|"
    r"(?:the |your )?(?:requested |prepared |written )?(?:note|content|text|draft|document)\b[^:\n]{0,140}\b(?:is|follows)|"
    r"(?:draft(?:\s+[^:\n]{1,120})?|"
    r"(?:reply|response|email|message|letter|document)\s+draft)(?:\s*\([^\n)]{0,60}\))?"
    r")\s*:)\s*(?P<body>.*)$", re.I)
_DOCUMENT_RESUME = re.compile(
    r"^\s*(?:\#{1,6}\s*)?(?:end (?:of )?(?:the )?(?:draft|document|reply|report|message|file content|slide text|content|text)|"
    r"outside (?:of )?(?:the )?(?:draft|document|reply|report|message)|"
    r"back to (?:the |our )?(?:task|conversation|implementation)|"
    r"(?:next|current) (?:step|action) (?:for me|on my side))\b", re.I)
_DOCUMENT_LOCATION = re.compile(
    r"\s*(?:<?(?:https?://|sandbox:/)|\[[^\]\n]{1,200}\]\(\s*(?:(?:https?://|sandbox:/)|$)|"
    r"awaitonal(?:pr|artifact|reference)link\b)", re.I)
_ATTENTION_DOCUMENT_INTRO = re.compile(
    r"^\s*(?:\#{1,6}\s*)?(?P<intro>(?:"
    r"(?:draft|review|reply|response|email|message|document)\b[^:\n]{0,120}\b(?:below|follows)\b[^:\n]{0,60}|"
    r"(?:i|we)(?:'ve| have)?\s+(?:prepared|drafted|wrote|written|assembled)\s+[^:\n]{1,140}\b(?:below|follows)\b[^:\n]{0,60}|"
    r"(?:here(?:'s| is)|below is)\s+[^:\n]{0,100}\b(?:draft|review)\b[^:\n]{0,60}"
    r")\s*[:.]?)\s*$", re.I)
# Matching at an offset avoids repeatedly copying long suffixes while finding
# an explicitly presented document after a response-status sentence.
_ATTENTION_EMBEDDED_DOCUMENT_INTRO = re.compile(_DOCUMENT_INTRO.pattern[1:], re.I)
_ATTENTION_PREPARED = re.compile(
    r"\b(?:i|we)(?:'ve| have)?\s+(?:prepared|drafted|wrote|written|assembled)\b|"
    r"\b(?:draft|review|reply|response|email|message|document)\b[^.!?\n]{0,100}"
    r"\b(?:ready|prepared|written|drafted|below|not (?:yet )?(?:posted|sent|published))\b|"
    r"\b(?:here(?:'s| is)|below is)\s+[^.!?\n]{0,60}\bdraft\b", re.I)
_ATTENTION_EXECUTION = r"(?:post|publish|send|submit|commit|apply|save|merge|push|deploy|release)"
_ATTENTION_EXECUTION_ING = r"(?:posting|publishing|sending|submitting|committing|applying|saving|merging|pushing|deploying|releasing)"
# An assistant permission question can name arbitrary prepared work. Require a
# referential object rather than a catalogue of deliverable nouns.
_ATTENTION_OBJECT = r"(?:it|this|that|these|those|(?:the|my|our)\s+[a-z][\w'-]*(?:\s+[a-z][\w'-]*){0,8})\b"
_ATTENTION_PERMISSION_TAIL = re.compile(
    r"^\s*(?:"
    r"(?:(?:should|shall|may|can|could)\s+(?:i|we)|"
    r"(?:do you want|would you (?:like|prefer))\s+(?:me|us)\s+to)\s+"
    r"(?:go ahead and\s+)?" + _ATTENTION_EXECUTION + r"\s+" + _ATTENTION_OBJECT + r"[^\n]{0,180}\?"
    r"|(?:do|can)\s+(?:i|we)\s+have\s+(?:(?:your|the)\s+)?"
    r"(?:permission|approval|consent|go[- ]?ahead)\s+to\s+"
    + _ATTENTION_EXECUTION + r"\s+" + _ATTENTION_OBJECT + r"[^\n]{0,180}\?"
    r"|do you\s+(?:approve(?:\s+of)?|authorize|consent to)\s+(?:"
    r"(?:me|us)\s+to\s+" + _ATTENTION_EXECUTION + r"|"
    r"(?:me|us|my|our)\s+" + _ATTENTION_EXECUTION_ING + r")\s+"
    + _ATTENTION_OBJECT + r"[^\n]{0,180}\?"
    r"|say the word(?:\s+and|[,;])?\s+(?:i|we)(?:'ll| will)\s+" + _ATTENTION_EXECUTION + r"\s+" + _ATTENTION_OBJECT + r"[^\n]{0,180}[.!]?"
    r"|if you (?:agree|approve|give (?:me|us) (?:the|your) go[- ]ahead)[,;]?\s+"
    r"(?:i|we)(?:'ll| will)\s+" + _ATTENTION_EXECUTION + r"\s+" + _ATTENTION_OBJECT + r"[^\n]{0,180}[.!]?"
    r")\s*$", re.I)


def _attention_permission_tail(lines: list[str]) -> tuple[int, str] | None:
    """Find a final standalone assistant execution-permission paragraph.

    A blank line and preceding document content are still required by the
    caller. This does not infer arbitrary ends to an unmarked document body.
    """
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1
    start = end
    while start and lines[start - 1].strip():
        start -= 1
    if not start or not 1 <= end - start <= 3:
        return None
    if any(re.match(r"^(?: {4}|\t)|^\s*(?:>|[-*+]\s|\d+[.)]\s)", line) for line in lines[start:end]):
        return None
    tail = "\n".join(line.strip() for line in lines[start:end])
    if len(tail) > 400:
        return None
    normalized = tail.replace("’", "'")
    # Remove paired emphasis only. A list bullet, quotation, or inline-code
    # wrapper must not turn document text into a response permission request.
    for _ in range(2):
        normalized = re.sub(r"(?<!\w)(\*\*|__|\*|_)(?=\S)(.+?)(?<=\S)\1(?!\w)",
                            r"\2", normalized, flags=re.S)
    return (start, normalized) if _ATTENTION_PERMISSION_TAIL.fullmatch(normalized.replace("\n", " ")) else None


def _prepared_document_wrapper(line: str) -> bool:
    """Preparation must be asserted by current response framing, not a body."""
    return (bool(_ATTENTION_PREPARED.search(line))
            and not re.search(r"\b(?:if|would|will|yesterday|previously|last (?:week|month|time))\b", line, re.I)
            and not re.search(r"\b(?:not|never|isn't|aren't|hasn't been|haven't been)\s+"
                              r"(?:ready|prepared|written|drafted|assembled)\b", line, re.I))


def response_prose(text: str, *, attention: bool = False) -> str:
    """Keep response framing separate from explicitly presented document text.

    Plain document bodies have no implicit end at a blank line or a generic
    "Next steps" heading. Only an explicit return to the conversation ends
    that scope. Quoted/fenced bodies have their own unambiguous boundaries.
    The attention-only view can retain a final assistant execution-permission
    paragraph after current prepared-draft framing. Other consumers keep the
    stricter document boundary. Quoted content is never response evidence.
    """
    if not isinstance(text, str) or len(text) > MAX_PROSE_CHARS:
        return ""
    kept = []
    body = None
    fence = None
    lines = text.splitlines()
    tail = _attention_permission_tail(lines) if attention else None
    prepared_wrapper = False
    document_body_seen = False
    dialogue_body = False
    for index, line in enumerate(lines):
        mark = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if fence:
            if body is None:
                kept.append(line)
            if mark and mark[1][0] == fence[0] and len(mark[1]) >= len(fence):
                fence = None
                if body == "fence":
                    body = None
            continue
        if body:
            if not line.strip():
                continue
            if body == "pending":
                if _DOCUMENT_LOCATION.match(line):
                    kept.append(line)
                    body = None
                    continue
                if mark:
                    body, fence = "fence", mark[1]
                    continue
                body = "quote" if re.match(r"^\s*>", line) else "plain"
            if body == "quote":
                if re.match(r"^\s*>", line):
                    continue
                body = None
            elif body == "plain" and mark:
                fence = mark[1]
                continue
            elif (attention and body == "plain" and tail and index == tail[0]
                  and prepared_wrapper and document_body_seen and not dialogue_body):
                kept.append(tail[1])
                break
            elif _DOCUMENT_RESUME.match(re.sub(r"[*_]", "", line)):
                body = None
            else:
                document_body_seen = True
                continue
        if mark:
            fence = mark[1]
            kept.append(line)
            continue
        if re.match(r"^\s*>|^(?: {4}|\t)", line):
            kept.append(line)
            continue
        normalized = re.sub(r"[*_]", "", line).replace("’", "'")
        intro = _DOCUMENT_INTRO.match(normalized)
        intro_prefix = ""
        if attention and not intro:
            intro = _ATTENTION_DOCUMENT_INTRO.match(normalized)
        if attention and not intro:
            for boundary in re.finditer(r"(?<=[.!?])\s+(?=(?:here(?:'s| is| are)|below (?:is|are))\b)", normalized, re.I):
                intro = _ATTENTION_EMBEDDED_DOCUMENT_INTRO.match(normalized, boundary.end())
                if intro:
                    intro_prefix = normalized[:boundary.start()]
                    break
        intro_body = intro.groupdict().get("body", "") if intro else ""
        noun = _DOCUMENT_NOUN.search(intro["intro"]) if intro else None
        if (attention and intro and not noun
                and re.search(r"\bdraft\b|\bnot (?:yet )?(?:posted|published|sent)\b|"
                              r"\b(?:prepared|drafted|wrote|written|assembled)\b", intro["intro"], re.I)):
            noun = re.search(r"\breview\b", intro["intro"], re.I)
        location = bool(intro and _DOCUMENT_LOCATION.match(intro_body))
        # A helper that writes a report is implementation prose, not the report
        # itself. Require the document to be the presented/direct object.
        if (noun and not location
                and not re.search(r"\b(?:https?|sandbox):", intro["intro"], re.I)
                and not re.search(r"\b(?:to|that|which|about)\b", intro["intro"][:noun.start()], re.I)):
            if intro_prefix:
                kept.append(intro_prefix)
                prepared_wrapper |= _prepared_document_wrapper(intro_prefix)
            kept.append(intro["intro"])
            body = "plain" if intro_body.strip() else "pending"
            document_body_seen = bool(intro_body.strip())
            dialogue_body = bool(re.search(r"\b(?:dialogue|script|transcript|conversation)\b", intro["intro"], re.I))
            prepared_wrapper |= attention and _prepared_document_wrapper(intro["intro"])
        else:
            kept.append(line)
            prepared_wrapper |= attention and _prepared_document_wrapper(normalized)
    return "\n".join(kept)


def _literal_marker(value: str) -> str:
    """Keep a literal's shape, never its contents or executable instructions.

    File extensions are structural, not an allowlist of artifact types. The
    marker still needs a surrounding reported delivery before it is evidence
    of an artifact; a filename alone says nothing about the task's outcome.
    """
    value = value.strip()
    safe = (0 < len(value) <= 512
            and re.fullmatch(r"[\w .@+~:/\\-]+", value, re.UNICODE))
    file_shape = safe and (
        re.search(r"\.[\w-]{1,16}$", value)
        or re.match(r"(?:/|\.{1,2}/|~/|[a-z]:\\)", value, re.I)
        or re.fullmatch(r"[\w.@+~-]+(?:[/\\][\w .@+~-]+)+", value)
    )
    return " awaitonalfile " if file_shape else " awaitonalcode "


def _strip_quotes(text: str, *, typed_code: bool = False) -> str:
    """Remove paired quotations without rescanning unmatched opening marks."""
    closers = {'"': '"', '“': '”', '‘': '’'}
    lines = []
    for line in text.split("\n"):
        # An unmatched opener must not trigger a search of the remaining line
        # at every subsequent opener. Successful searches consume their span.
        last = {opener: line.rfind(closer) for opener, closer in closers.items()}
        parts = []
        cursor = 0
        for match in re.finditer('["“‘]', line):
            start = match.start()
            if start < cursor or start >= last[match.group()]:
                continue
            end = line.find(closers[match.group()], start + 1)
            value = line[start + 1:end]
            marker = _literal_marker(value) if typed_code else " "
            # Preserve an opaque argument for surrounding prose ("X is the
            # better choice"), never the assertions inside the quotation.
            parts.extend((line[cursor:start], marker if marker == " awaitonalfile "
                          else " awaitonalliteral " if typed_code else " "))
            cursor = end + 1
        parts.append(line[cursor:])
        lines.append("".join(parts))
    return "\n".join(lines)


def _link_marker(url: str) -> str:
    """Return a bounded URL family, without retaining or fetching the target."""
    try:
        parsed = urlsplit(url.strip().strip("<>"))
        host, path = parsed.hostname, parsed.path
        if parsed.scheme not in {"https", "http", "sandbox"} or parsed.username or parsed.password:
            return " awaitonalreferencelink "
        if host == "github.com" and re.fullmatch(r"/[^/]+/[^/]+/pull/[0-9]+/?", path):
            return " awaitonalprlink "
        if (host == "claude.ai" and re.fullmatch(r"/(?:code/)?artifacts?/[^/]+/?", path)
                or host == "docs.google.com" and re.match(r"/(?:document|spreadsheets|presentation)/d/[^/]+", path)
                or parsed.scheme == "sandbox" and path.startswith("/")
                or host and re.search(r"\.(?:pdf|csv|xlsx|docx|png|jpe?g|svg|mp4|mp3|wav|zip)$", path, re.I)):
            return " awaitonalartifactlink "
    except ValueError:
        pass
    return " awaitonalreferencelink "


def _strip_link_destinations(text: str, link_types: bool = False) -> str:
    """Keep inline-link labels, examining each possible delimiter only once."""
    parts = []
    cursor = 0
    while (opening := text.find("[", cursor)) != -1:
        closing = text.find("]", opening + 1)
        if closing == -1:
            break
        if closing == opening + 1 or text[closing + 1:closing + 2] != "(":
            # Every opener before this same closing bracket also fails.
            parts.append(text[cursor:closing + 1])
            cursor = closing + 1
            continue
        end = text.find(")", closing + 2)
        if end == -1:
            break
        parts.extend((text[cursor:opening], text[opening + 1:closing]))
        if link_types:
            parts.append(_link_marker(text[closing + 2:end]))
        cursor = end + 1
    parts.append(text[cursor:])
    return "".join(parts)


def assistant_prose(text: str, *, link_types: bool = False, typed_code: bool = False,
                    attention: bool = False) -> str:
    """Discard code and quoted material, returning empty for invalid/oversize input.

    This is deliberately not a Markdown parser. An unclosed fence consumes the
    remaining text, so copied code cannot accidentally become attention evidence.
    The attention-only view preserves the existence of a closed fenced ``!``
    command as an opaque marker, never its instructions or other code contents.
    """
    if not isinstance(text, str) or len(text) > MAX_PROSE_CHARS or not text.strip():
        return ""
    if attention:
        text = re.sub(r"\bawaitonalcommand\b", " ", text, flags=re.I)
    lines = []
    fence = None
    fenced_command = False
    for line in text.splitlines():
        mark = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if mark:
            token = mark.group(1)
            if fence is None:
                fence = token
                fenced_command = False
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
                if attention and fenced_command:
                    lines.append("awaitonalcommand")
            continue
        if fence:
            fenced_command |= bool(attention and re.match(r"^\s*!\s*\S", line))
            continue
        if re.match(r"^\s*>|^(?: {4}|\t)", line):
            continue
        lines.append(line)
    prose = "\n".join(lines)
    if typed_code:
        prose = re.sub(r"\bawaitonal(?:file|code|literal)\b", " ", prose, flags=re.I)
    prose = re.sub(r"`+[^`]*`+", lambda match: _literal_marker(match[0].strip("`"))
                   if typed_code else " ", prose)
    prose = _strip_quotes(prose, typed_code=typed_code)
    prose = re.sub(r"(?<!\w)'[^'\n]+'(?!\w)", lambda match:
                   " awaitonalfile " if typed_code and _literal_marker(match[0][1:-1]) == " awaitonalfile "
                   else " awaitonalliteral " if typed_code else " ", prose)
    if link_types:
        prose = re.sub(r"\bawaitonal(?:pr|artifact|reference)link\b", " ", prose, flags=re.I)
    prose = _strip_link_destinations(prose, link_types)
    if link_types:
        # Match each URL once; only family markers survive. Query text and
        # fragments must never become outcome or handoff evidence.
        prose = re.sub(r"(?:https?://|sandbox:/)[^\s<>]+", lambda m: _link_marker(m[0].rstrip(".,;!?)]")), prose)
    prose = prose.replace("’", "'")
    content = re.sub(r"\bawaitonal(?:file|code|literal)\b", " ", prose, flags=re.I) if typed_code else prose
    if attention:
        content = re.sub(r"\bawaitonalcommand\b", " ", content, flags=re.I)
    if (typed_code or attention) and not content.strip():
        return ""
    return re.sub(r"[ \t]+", " ", prose).strip()


def sentences(prose: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", prose) if s.strip()]


@dataclass(frozen=True)
class ProseChunk:
    text: str
    start: int
    end: int
    conclusion: bool


def select_chunks(prose: str, tokenizer, token_budget: int = 224,
                  max_chunks: int = 8) -> tuple[list[ProseChunk], dict]:
    """Select token windows, reserving the conclusion and neighboring context.

    Tokenize without truncation. Reserve the last two overlapping windows, then
    recent salient sentences with 1/3 preceding and 2/3 following context. Fill
    remaining slots with evenly spaced coverage. Exact word-piece budgets include
    a re-encode check, preventing silent model truncation after token decoding.
    """
    if token_budget < 16 or not 2 <= max_chunks <= 32:
        raise ValueError("token_budget >= 16 and 2 <= max_chunks <= 32 required")
    parts = sentences(prose)
    ids = []
    salient = []
    for part in parts:
        part_ids = tokenizer.encode(part, add_special_tokens=False, truncation=False, verbose=False)
        if SALIENCE.search(part):
            salient.append((len(ids), len(ids) + len(part_ids)))
        ids.extend(part_ids)
    count = len(ids)
    if not count:
        return [], {"input_tokens": 0, "selected_chunks": 0, "omitted_tokens": 0}
    starts = []
    def add(start):
        start = max(0, min(int(start), max(0, count - token_budget)))
        if start not in starts and len(starts) < max_chunks:
            starts.append(start)
    add(count - token_budget)
    if count > token_budget:
        add(count - 2 * token_budget + token_budget // 4)
    for start, end in reversed(salient):
        # Include the following clause/sentence so recovered failures keep context.
        add(start - token_budget // 3)
        if end - start > token_budget:
            add(end - token_budget)
    slots = max_chunks - len(starts)
    if slots:
        for i in range(slots):
            add((count - token_budget) * i / max(1, slots - 1))
    chunks = []
    covered = set()
    for start in sorted(starts):
        end = min(count, start + token_budget)
        is_tail = end == count
        decoded = tokenizer.decode(ids[start:end], skip_special_tokens=True)
        # Tokenizer decode/encode can expand punctuation or wordpiece fragments.
        while end > start and len(tokenizer.encode(decoded, add_special_tokens=False,
                                                    truncation=False, verbose=False)) > token_budget:
            if is_tail:
                start += 1  # preserve the conclusion even when re-encoding expands
            else:
                end -= 1
            decoded = tokenizer.decode(ids[start:end], skip_special_tokens=True)
        if decoded.strip():
            chunks.append(ProseChunk(decoded, start, end, end >= count))
            covered.update(range(start, end))
    return chunks, {"input_tokens": count, "selected_chunks": len(chunks),
                    "omitted_tokens": count - len(covered), "token_budget": token_budget}
