"""Bound model context while retaining the complete fetched sources in state."""
import os
import re

from .adapters import AdapterError


def context_budget():
    try:
        value = int(os.environ.get("DELUXE_SOURCE_CONTEXT_CHARS", "12000"))
    except ValueError as error:
        raise AdapterError("DELUXE_SOURCE_CONTEXT_CHARS must be an integer between 2000 and 48000.") from error
    if not 2000 <= value <= 48000:
        raise AdapterError("DELUXE_SOURCE_CONTEXT_CHARS must be between 2000 and 48000.")
    return value


def excerpt(text, question, limit):
    if len(text) <= limit:
        return text
    separator = "\n[... excerpt boundary ...]\n"
    block_size = max(1, min(600, (limit - 2 * len(separator)) // 3))
    spans = [(i, min(i + block_size, len(text))) for i in range(0, len(text), block_size)]
    stopwords = {"how", "can", "the", "and", "for", "with", "from", "that", "this", "what", "does", "use", "general"}
    terms = set(re.findall(r"[a-z0-9]{2,}", question.lower())) - stopwords
    def score(span):
        words = set(re.findall(r"[a-z0-9]{2,}", text[span[0]:span[1]].lower()))
        return len(terms & words)
    ranked = sorted(spans, key=lambda span: (-score(span), span[0]))
    # Preserve opening context, the best question match, and closing qualifiers.
    priorities = [spans[0], ranked[0], spans[-1]] + ranked
    selected, used = [], 0
    for span in priorities:
        if span in selected:
            continue
        cost = span[1] - span[0] + (len(separator) if selected else 0)
        if used + cost <= limit:
            selected.append(span)
            used += cost
    return separator.join(text[start:end] for start, end in sorted(selected))


def source_context(sources, question, limit=None):
    """Select bounded contiguous excerpts; do not mutate original source objects."""
    if not sources:
        return []
    budget = context_budget() if limit is None else limit
    remaining = budget
    result = []
    # Short sources donate unused space to longer sources without dropping any source IDs.
    ordered = sorted(enumerate(sources), key=lambda item: len(item[1]["text"]))
    selected = {}
    for position, (index, source) in enumerate(ordered):
        allowance = remaining // (len(ordered) - position)
        text = excerpt(source["text"], question, allowance)
        selected[index] = dict(source, text=text, text_excerpted=text != source["text"],
                               original_text_characters=len(source["text"]))
        remaining -= len(text)
    for index in range(len(sources)):
        result.append(selected[index])
    return result
