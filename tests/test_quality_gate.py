"""
tests/test_quality_gate.py

Unit tests for the Data Quality Gate.
Run: pytest tests/test_quality_gate.py -v
"""

import pytest
from src.ingestion.quality_gate import (
    check,
    check_file_extension,
    RejectionReason,
    MIN_WORD_COUNT,
    MAX_WORD_COUNT,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_english_text(word_count: int) -> str:
    """Generate valid English-ish text with enough marker words to pass."""
    # Mix real English words with filler to hit exact word counts
    base = (
        "the team reported that the delivery milestone was delayed and the "
        "programme manager escalated to the director of engineering for review "
        "of the outstanding issues with the release pipeline and deployment "
    )
    tokens = base.split()
    result = (tokens * ((word_count // len(tokens)) + 1))[:word_count]
    return " ".join(result)


# ── File extension checks ─────────────────────────────────────────────────────

class TestFileExtension:
    def test_txt_passes(self):
        assert check_file_extension("report.txt").passed

    def test_docx_passes(self):
        assert check_file_extension("meeting_notes.docx").passed

    def test_pdf_passes(self):
        assert check_file_extension("incident_log.pdf").passed

    def test_csv_rejected(self):
        result = check_file_extension("data.csv")
        assert result.failed
        assert result.rejection_reason == RejectionReason.UNSUPPORTED_FILE_TYPE

    def test_xlsx_rejected(self):
        result = check_file_extension("tracker.xlsx")
        assert result.failed
        assert result.rejection_reason == RejectionReason.UNSUPPORTED_FILE_TYPE

    def test_no_extension_rejected(self):
        result = check_file_extension("README")
        assert result.failed

    def test_uppercase_extension_passes(self):
        # .TXT should be treated same as .txt
        assert check_file_extension("REPORT.TXT").passed


# ── Empty / whitespace content ────────────────────────────────────────────────

class TestEmptyContent:
    def test_empty_string_rejected(self):
        result = check("", filename="report.txt")
        assert result.failed
        assert result.rejection_reason == RejectionReason.EMPTY_CONTENT

    def test_whitespace_only_rejected(self):
        result = check("   \n\t  \n  ", filename="report.txt")
        assert result.failed
        assert result.rejection_reason == RejectionReason.EMPTY_CONTENT


# ── Word count boundaries ─────────────────────────────────────────────────────

class TestWordCount:
    def test_exactly_min_word_count_passes(self):
        text = _make_english_text(MIN_WORD_COUNT)
        result = check(text, filename="report.txt")
        assert result.passed
        assert result.word_count == MIN_WORD_COUNT

    def test_one_below_min_rejected(self):
        text = _make_english_text(MIN_WORD_COUNT - 1)
        result = check(text, filename="report.txt")
        assert result.failed
        assert result.rejection_reason == RejectionReason.TOO_SHORT

    def test_well_above_min_passes(self):
        text = _make_english_text(500)
        result = check(text, filename="report.txt")
        assert result.passed

    def test_exactly_max_word_count_passes(self):
        text = _make_english_text(MAX_WORD_COUNT)
        result = check(text, filename="report.txt")
        assert result.passed

    def test_one_above_max_rejected(self):
        text = _make_english_text(MAX_WORD_COUNT + 1)
        result = check(text, filename="report.txt")
        assert result.failed
        assert result.rejection_reason == RejectionReason.TOO_LONG

    def test_short_document_produces_warning(self):
        text = _make_english_text(100)   # passes min=50 but < 150
        result = check(text, filename="report.txt")
        assert result.passed
        assert any("Short document" in w for w in result.warnings)


# ── Garbled content ───────────────────────────────────────────────────────────

class TestGarbledContent:
    def test_garbled_ocr_rejected(self):
        # 70% single-character tokens — typical of bad OCR
        garbage = " ".join(["a", "b", "c", "d", "e", "f", "g"] * 20 + ["word"] * 10)
        result = check(garbage, filename="report.txt")
        assert result.failed
        assert result.rejection_reason == RejectionReason.GARBLED_CONTENT

    def test_normal_text_not_flagged_as_garbled(self):
        text = _make_english_text(200)
        result = check(text, filename="report.txt")
        # Should not be rejected for garbled content
        assert result.rejection_reason != RejectionReason.GARBLED_CONTENT


# ── Language check ─────────────────────────────────────────────────────────────

class TestLanguage:
    def test_english_text_passes(self):
        text = _make_english_text(200)
        result = check(text, filename="report.txt")
        assert result.passed

    def test_non_english_rejected(self):
        # German text with no overlap with English marker words.
        # "der", "die", "das" etc. are not in the English marker set.
        german = (
            "Das Projekt wurde aufgrund mangelnder Ressourcen verzögert "
            "Die Lieferung konnte nicht rechtzeitig abgeschlossen werden "
            "Alle Beteiligten wurden über die Situation informiert "
            "Eine neue Deadline wurde festgelegt um das Risiko zu minimieren "
            "Der Projektleiter hat eine umfassende Analyse durchgeführt "
        ) * 4
        result = check(german, filename="report.txt")
        assert result.failed
        assert result.rejection_reason == RejectionReason.NOT_ENGLISH


# ── Filename passed to check() ────────────────────────────────────────────────

class TestFilenameInCheck:
    def test_bad_extension_caught_by_check(self):
        text = _make_english_text(200)
        result = check(text, filename="data.csv")
        assert result.failed
        assert result.rejection_reason == RejectionReason.UNSUPPORTED_FILE_TYPE

    def test_no_filename_skips_extension_check(self):
        # When no filename is provided, extension check is skipped
        text = _make_english_text(200)
        result = check(text)
        assert result.passed


# ── Result string representations ─────────────────────────────────────────────

class TestResultStr:
    def test_pass_str_contains_word_count(self):
        text = _make_english_text(200)
        result = check(text, filename="notes.txt")
        assert "PASS" in str(result)
        assert "200" in str(result)

    def test_fail_str_contains_reason(self):
        result = check("", filename="notes.txt")
        assert "REJECT" in str(result)
        assert "empty_content" in str(result)
