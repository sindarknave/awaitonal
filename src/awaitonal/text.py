"""Conservative assistant-prose extraction and bounded, token-aware selection."""
from dataclasses import dataclass
import re

MAX_PROSE_CHARS = 131_072
# These words select context for the encoder; they do not choose a class.
SALIENCE = re.compile(r"\b(wait|await|approval|approve|permission|choose|choice|decide|answer|before|cannot|can't|refus|declin|won't|unable|fail|error|recover|fixed|resolved|unavailable|blocked|remaining|caveat)", re.I)


def _strip_quotes(text: str) -> str:
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
            parts.extend((line[cursor:start], " "))
            cursor = end + 1
        parts.append(line[cursor:])
        lines.append("".join(parts))
    return "\n".join(lines)


def _strip_link_destinations(text: str) -> str:
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
        cursor = end + 1
    parts.append(text[cursor:])
    return "".join(parts)


def assistant_prose(text: str) -> str:
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
    prose = re.sub(r"`+[^`]*`+", " ", prose)
    prose = _strip_quotes(prose)
    prose = re.sub(r"(?<!\w)'[^'\n]+'(?!\w)", " ", prose)
    prose = _strip_link_destinations(prose)
    prose = prose.replace("’", "'")
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
