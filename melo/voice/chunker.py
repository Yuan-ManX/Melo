"""Sentence-aware text segmentation for natural streaming TTS.

Real-time agents should start speaking at a sentence boundary, never
mid-thought. This module provides three pure, deterministic helpers:

  * `normalize_whitespace` — collapse runs of whitespace to single spaces
  * `split_sentences`      — segment text, preserving trailing punctuation;
                             handles English + CJK enders and protects
                             abbreviations, initials, and decimals
  * `chunk_text`           — sentence-aware token budgeting with a
                             hard-split fallback for oversized sentences
"""

from __future__ import annotations

import re

#: Sentence-ending punctuation — Latin (`.`, `!`, `?`, `…`) and CJK
#: (。！？…). The final ellipsis char U+2026 and the CJK ellipsis U+2026
#: are both covered by the `…` literal; CJK full stop / exclamation /
#: question are included explicitly.
_SENTENCE_ENDERS = "!?。！？…"

#: A run of one or more sentence-ending characters.
_ENDER_RE = re.compile(r"[.!?。！？…]+")

#: Common abbreviations whose trailing period must not be treated as a
#: sentence end ("Dr. Smith" stays one sentence).
_ABBREVIATION_RE = re.compile(
    r"(?i)\b(?:"
    r"mr|mrs|ms|dr|prof|sr|jr|st|vs|etc|e\.g|i\.e|approx|dept|fig|"
    r"inc|corp|ltd|jan|feb|mar|apr|jun|jul|aug|sep|oct|nov|dec|"
    r"mon|tue|wed|thu|fri|sat|sun|"
    r"co|no|vol|ch|sec|min|max"
    r")\.$"
)

#: A single capital-letter initial ("J. Smith", "U.S.A.").
_INITIAL_RE = re.compile(r"(?i)\b[A-Z]\.$")

#: Closing punctuation / brackets that may follow a sentence ender and
#: should stay attached to the sentence (e.g. `"Stop."`).
_CLOSERS = set("\"')\u201d\u2019】」』》]>")

#: Number of characters of look-back used to test whether an ender is
#: really a boundary (abbreviation / initial detection).
_LOOKBACK = 14


def normalize_whitespace(text: str) -> str:
    """Collapse runs of whitespace (spaces, tabs, newlines) to one space.

    Returns a single-line, stripped string. Empty / whitespace-only
    input returns an empty string.
    """
    return " ".join(text.split())


def _is_real_boundary(text: str, end: int) -> bool:
    """Return True if the period ending at `end` is a genuine sentence end.

    A period is *not* a boundary when it terminates a known abbreviation
    or a single-letter initial, or when it is immediately followed by a
    digit (a decimal like "3.14"). `!`/`?`/CJK enders are always
    boundaries and never reach this check.
    """
    # A decimal: "3.14" — the period is followed by a digit.
    if end < len(text) and text[end].isdigit():
        return False
    before = text[max(0, end - _LOOKBACK) : end]
    if _ABBREVIATION_RE.search(before):
        return False
    if _INITIAL_RE.search(before):
        return False
    return True


def _is_cjk_start(ch: str) -> bool:
    """True if `ch` is a non-ASCII character that can start a sentence.

    CJK text often abuts sentences without any whitespace ("你好。世界！"),
    so a CJK ender is a valid boundary even when the next char is a CJK
    glyph rather than a space.
    """
    return not ch.isascii()


def split_sentences(text: str) -> list[str]:
    """Segment `text` into sentences, preserving trailing punctuation.

    Boundaries are sentence-ending punctuation (Latin + CJK) followed by
    whitespace, end-of-string, or a closing quote/bracket. Newlines are
    treated as hard boundaries (each line becomes its own utterance).
    Abbreviations ("Dr."), initials ("J."), and decimals ("3.14") are
    not split. Consecutive enders (e.g. "!!" or "….") group into one
    sentence.

    Returns a non-empty list; whitespace-only input yields `[""]`.
    """
    lines = re.split(r"\r?\n+", text)
    out: list[str] = []
    for line in lines:
        _split_one_line(line, out)
    if not out:
        # Preserve the empty-string contract when input had no text.
        out.append("")
    return out


def _split_one_line(line: str, out: list[str]) -> None:
    """Split a single (newline-free) line into sentences appended to `out`."""
    if not line or not line.strip():
        return
    stripped = line.strip()

    boundaries: list[int] = []
    for m in _ENDER_RE.finditer(stripped):
        end = m.end()
        last = stripped[end - 1]
        # Extend the boundary past any trailing closers so `"Stop."` is
        # kept as one sentence including its quotes.
        next_idx = end
        while next_idx < len(stripped) and stripped[next_idx] in _CLOSERS:
            next_idx += 1
        if next_idx < len(stripped):
            nxt = stripped[next_idx]
            # A Latin period must be followed by whitespace / end / closer.
            # CJK enders may abut the next sentence directly ("你好。世界！").
            if last == ".":
                if not nxt.isspace():
                    continue
            elif not (nxt.isspace() or _is_cjk_start(nxt)):
                continue
        # Only `.` enders need the abbreviation / initial / decimal guard.
        if last == "." and not _is_real_boundary(stripped, end):
            continue
        boundaries.append(next_idx)

    if not boundaries:
        out.append(stripped)
        return

    prev = 0
    for b in boundaries:
        sentence = stripped[prev:b].strip()
        if sentence:
            out.append(sentence)
        prev = b
    tail = stripped[prev:].strip()
    if tail:
        out.append(tail)


def chunk_text(text: str, *, max_chars: int = 400) -> list[str]:
    """Group sentences into chunks of at most `max_chars` characters.

    Sentences are packed greedily without exceeding `max_chars`. A single
    sentence longer than `max_chars` is hard-split on word boundaries
    (falling back to character boundaries for an unbreakable long word)
    so every returned chunk stays within the budget. Empty / whitespace-
    only input returns an empty list.
    """
    if not text or not text.strip():
        return []
    max_chars = max(1, int(max_chars))

    sentences = split_sentences(text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_hard_split_sentence(sentence, max_chars))
            continue
        if current and len(current) + 1 + len(sentence) > max_chars:
            chunks.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip() if current else sentence
    if current:
        chunks.append(current)
    return chunks


def _hard_split_sentence(sentence: str, max_chars: int) -> list[str]:
    """Split an oversized sentence on word boundaries, then characters."""
    words = sentence.split()
    chunks: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            # Unbreakable long token — hard character split.
            chunks.extend(
                word[i : i + max_chars] for i in range(0, len(word), max_chars)
            )
            continue
        if current and len(current) + 1 + len(word) > max_chars:
            chunks.append(current)
            current = word
        else:
            current = f"{current} {word}".strip() if current else word
    if current:
        chunks.append(current)
    return chunks


__all__ = ["normalize_whitespace", "split_sentences", "chunk_text"]
