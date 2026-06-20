"""
src/ingestion/quality_gate.py

Data Quality Gate — Sprint 1
==============================
Validates documents BEFORE any processing (privacy layer, BERTopic, etc.).
Rejects documents that would produce unreliable or misleading signals.

Rules (all must pass):
  1. File type must be .txt, .docx, or .pdf
  2. Extracted text must not be empty after stripping whitespace
  3. Word count must be >= MIN_WORD_COUNT (default: 50)
  4. Word count must be <= MAX_WORD_COUNT (default: 100,000)
  5. Single-token ratio must be < MAX_SINGLE_TOKEN_RATIO (default: 0.6)
     — catches garbled OCR / binary content passed as text
  6. Language must be English (simple heuristic; swap for langdetect if needed)

Returns a QualityResult dataclass — never raises on bad input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# ── Constants ─────────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS: set[str] = {".txt", ".docx", ".pdf"}
MIN_WORD_COUNT: int = 50
MAX_WORD_COUNT: int = 100_000
MAX_SINGLE_TOKEN_RATIO: float = 0.60   # fraction of "words" that are 1 char long

# Common English function words used for language heuristic
_ENGLISH_MARKERS: set[str] = {
    "the", "and", "of", "to", "in", "is", "it", "that", "was", "for",
    "on", "are", "as", "with", "his", "they", "at", "be", "this", "have",
    "from", "or", "had", "by", "not", "but", "what", "all", "were", "we",
    "when", "your", "can", "said", "there", "use", "an", "each", "which",
    "she", "do", "how", "their", "if", "will", "up", "other", "about",
}
_ENGLISH_MARKER_THRESHOLD: float = 0.02   # >= 2% of words must be English markers


# ── Result types ──────────────────────────────────────────────────────────────

class RejectionReason(str, Enum):
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    EMPTY_CONTENT = "empty_content"
    TOO_SHORT = "too_short"
    TOO_LONG = "too_long"
    GARBLED_CONTENT = "garbled_content"
    NOT_ENGLISH = "not_english"


@dataclass
class QualityResult:
    passed: bool
    word_count: int = 0
    rejection_reason: Optional[RejectionReason] = None
    rejection_detail: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return not self.passed

    def __str__(self) -> str:
        if self.passed:
            return f"PASS — {self.word_count} words{' | warnings: ' + '; '.join(self.warnings) if self.warnings else ''}"
        return f"REJECT [{self.rejection_reason.value}] — {self.rejection_detail}"


# ── Public API ────────────────────────────────────────────────────────────────

def check(text: str, filename: str = "") -> QualityResult:
    """
    Validate extracted text from a document.

    Args:
        text:     The raw extracted text string.
        filename: Original filename (used for extension check). Optional.

    Returns:
        QualityResult with .passed True/False and rejection details if failed.

    Example:
        result = check(text, filename="sprint_review.txt")
        if result.failed:
            print(result)   # "REJECT [too_short] — 12 words, minimum is 50"
    """
    warnings: list[str] = []

    # Rule 1 — file type
    if filename:
        ext = Path(filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return QualityResult(
                passed=False,
                rejection_reason=RejectionReason.UNSUPPORTED_FILE_TYPE,
                rejection_detail=f"'{ext}' is not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
            )

    # Rule 2 — not empty
    stripped = text.strip()
    if not stripped:
        return QualityResult(
            passed=False,
            rejection_reason=RejectionReason.EMPTY_CONTENT,
            rejection_detail="Document produced no extractable text.",
        )

    # Tokenise once for remaining rules
    words = _tokenize(stripped)
    word_count = len(words)

    # Rule 3 — minimum length
    if word_count < MIN_WORD_COUNT:
        return QualityResult(
            passed=False,
            word_count=word_count,
            rejection_reason=RejectionReason.TOO_SHORT,
            rejection_detail=f"{word_count} words — minimum is {MIN_WORD_COUNT}.",
        )

    # Rule 4 — maximum length
    if word_count > MAX_WORD_COUNT:
        return QualityResult(
            passed=False,
            word_count=word_count,
            rejection_reason=RejectionReason.TOO_LONG,
            rejection_detail=f"{word_count} words — maximum is {MAX_WORD_COUNT:,}. Split the document.",
        )

    # Rule 5 — garbled / binary content check
    single_char_count = sum(1 for w in words if len(w) == 1)
    single_char_ratio = single_char_count / word_count
    if single_char_ratio >= MAX_SINGLE_TOKEN_RATIO:
        return QualityResult(
            passed=False,
            word_count=word_count,
            rejection_reason=RejectionReason.GARBLED_CONTENT,
            rejection_detail=(
                f"{single_char_ratio:.0%} of tokens are single characters "
                f"(threshold: {MAX_SINGLE_TOKEN_RATIO:.0%}). "
                "Document may be garbled OCR or binary data."
            ),
        )

    # Rule 6 — English language heuristic
    # Count total occurrences (not unique) so the ratio stays stable at scale.
    marker_hits_count = sum(1 for w in words if w.lower() in _ENGLISH_MARKERS)
    marker_ratio = marker_hits_count / word_count
    if marker_ratio < _ENGLISH_MARKER_THRESHOLD:
        return QualityResult(
            passed=False,
            word_count=word_count,
            rejection_reason=RejectionReason.NOT_ENGLISH,
            rejection_detail=(
                f"English marker word frequency {marker_ratio:.3f} is below threshold "
                f"{_ENGLISH_MARKER_THRESHOLD}. Only English documents are supported in MVP."
            ),
        )

    # Soft warnings (pass but flag)
    if word_count < 150:
        warnings.append(f"Short document ({word_count} words) — signal quality may be low.")
    if word_count > 50_000:
        warnings.append(f"Large document ({word_count:,} words) — processing may be slow.")

    return QualityResult(passed=True, word_count=word_count, warnings=warnings)


def check_file_extension(filename: str) -> QualityResult:
    """
    Lightweight check — extension only, no text needed.
    Use this at upload time before attempting text extraction.
    """
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        return QualityResult(
            passed=False,
            rejection_reason=RejectionReason.UNSUPPORTED_FILE_TYPE,
            rejection_detail=f"'{ext}' not supported. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}",
        )
    return QualityResult(passed=True)


# ── Internal helpers ───────────────────────────────────────────────────────────

def _tokenize(text: str) -> list[str]:
    """Split text into word tokens (alphanumeric, including apostrophes)."""
    return re.findall(r"[A-Za-z0-9']+", text)
