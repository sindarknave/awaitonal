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


def response_prose(text: str) -> str:
    """Keep response framing separate from explicitly presented document text.

    Plain document bodies have no implicit end at a blank line or a generic
    "Next steps" heading. Only an explicit return to the conversation ends
    that scope. Quoted/fenced bodies have their own unambiguous boundaries.
    This helper accepts raw Markdown or already-extracted prose; it does not
    interpret quoted content as instructions or judgments by the assistant.
    """
    if not isinstance(text, str) or len(text) > MAX_PROSE_CHARS:
        return ""
    kept = []
    body = None
    fence = None
    for line in text.splitlines():
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
            elif _DOCUMENT_RESUME.match(re.sub(r"[*_]", "", line)):
                body = None
            else:
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
        noun = _DOCUMENT_NOUN.search(intro["intro"]) if intro else None
        location = bool(intro and _DOCUMENT_LOCATION.match(intro["body"]))
        # A helper that writes a report is implementation prose, not the report
        # itself. Require the document to be the presented/direct object.
        if (noun and not location
                and not re.search(r"\b(?:https?|sandbox):", intro["intro"], re.I)
                and not re.search(r"\b(?:to|that|which|about)\b", intro["intro"][:noun.start()], re.I)):
            kept.append(intro["intro"])
            body = "plain" if intro["body"].strip() else "pending"
        else:
            kept.append(line)
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


def assistant_prose(text: str, *, link_types: bool = False, typed_code: bool = False) -> str:
    """Discard code and quoted material, returning empty for invalid/oversize input.

    This is deliberately not a Markdown parser. An unclosed fence consumes the
    remaining text, so copied code cannot accidentally become attention evidence.
    """
    if not isinstance(text, str) or len(text) > MAX_PROSE_CHARS or not text.strip():
        return ""
    lines = []
    fence = None
    for line in text.splitlines():
        mark = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if mark:
            token = mark.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence):
                fence = None
            continue
        if fence or re.match(r"^\s*>|^(?: {4}|\t)", line):
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
    if typed_code and not re.sub(
            r"\bawaitonal(?:file|code|literal)\b", " ", prose, flags=re.I).strip():
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
