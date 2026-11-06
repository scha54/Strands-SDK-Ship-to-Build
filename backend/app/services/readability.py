"""Readability check for learner instructions (R-09.6; NFR-02).

An instruction passes when it has at most 3 sentences, each of at most 25 words, and a
Flesch-Kincaid grade of 6 or lower.
"""

from __future__ import annotations

import re

from app.domain.models import GateResult

MAX_SENTENCES = 3
MAX_WORDS_PER_SENTENCE = 25
MAX_GRADE = 6.0

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_WORD = re.compile(r"[A-Za-z0-9']+")


def split_sentences(text: str) -> list[str]:
    return [s for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]


def count_words(sentence: str) -> int:
    return len(_WORD.findall(sentence))


def count_syllables(word: str) -> int:
    """Vowel-group heuristic; at least one syllable per word."""
    w = re.sub(r"[^a-z]", "", word.casefold())
    if not w:
        return 1
    groups = len(re.findall(r"[aeiouy]+", w))
    if w.endswith("e") and not w.endswith(("le", "ee")) and groups > 1:
        groups -= 1
    return max(groups, 1)


def reading_grade(text: str) -> float:
    """Flesch-Kincaid grade level of ``text`` (0.0 for text without words)."""
    sentences = split_sentences(text)
    words = _WORD.findall(text)
    if not sentences or not words:
        return 0.0
    syllables = sum(count_syllables(w) for w in words)
    grade = 0.39 * (len(words) / len(sentences)) + 11.8 * (syllables / len(words)) - 15.59
    return max(grade, 0.0)


def check_readability(text: str, label: str = "instruction") -> GateResult:
    """Check sentence count, sentence length and reading grade (R-09.6)."""
    reasons: list[str] = []
    sentences = split_sentences(text)
    if not sentences:
        reasons.append(f"{label} is empty")
        return GateResult(passed=False, reasons=reasons)
    if len(sentences) > MAX_SENTENCES:
        reasons.append(f"{label} has {len(sentences)} sentences (max {MAX_SENTENCES})")
    for s in sentences:
        n = count_words(s)
        if n > MAX_WORDS_PER_SENTENCE:
            reasons.append(f"{label} has a sentence of {n} words (max {MAX_WORDS_PER_SENTENCE})")
    grade = reading_grade(text)
    if grade > MAX_GRADE:
        reasons.append(f"{label} reading grade {grade:.1f} exceeds grade {MAX_GRADE:.0f}")
    return GateResult(passed=not reasons, reasons=reasons)
