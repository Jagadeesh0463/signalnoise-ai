"""
src/exceptions.py

Custom exception hierarchy for SignalNoise AI.
Every module raises from this hierarchy — never bare Exception.

Usage:
    from src.exceptions import LoaderError

    raise LoaderError("Could not extract text from file.pdf")
"""


class SignalNoiseError(Exception):
    """
    Base exception for all SignalNoise AI errors.
    Catch this to handle any application error in one place.
    """
    pass


# ── Ingestion Layer ───────────────────────────────────────────────────────────

class QualityGateError(SignalNoiseError):
    """Raised when a document fails the quality gate and cannot be processed."""
    pass


class LoaderError(SignalNoiseError):
    """Raised when a file cannot be read or text cannot be extracted."""
    pass


# ── Privacy Layer ─────────────────────────────────────────────────────────────

class PrivacyShieldError(SignalNoiseError):
    """Raised when PII removal or role mapping fails."""
    pass


# ── Signal Intelligence Layer ─────────────────────────────────────────────────

class EmbeddingError(SignalNoiseError):
    """Raised when MiniLM embedding generation or ChromaDB storage fails."""
    pass


class DetectionError(SignalNoiseError):
    """Raised when BERTopic signal detection fails."""
    pass


# ── Evidence and Risk Layer ───────────────────────────────────────────────────

class ValidationError(SignalNoiseError):
    """Raised when evidence validation cannot corroborate a signal."""
    pass


class RiskIntelligenceError(SignalNoiseError):
    """Raised when a Risk object cannot be constructed from a signal."""
    pass


# ── Narration Layer ───────────────────────────────────────────────────────────

class NarrationError(SignalNoiseError):
    """Raised when Groq API call fails or returns unusable output."""
    pass


# ── Memory Layer ──────────────────────────────────────────────────────────────

class MemoryStoreError(SignalNoiseError):
    """Raised when SQLite read or write fails."""
    pass


# ── Configuration ─────────────────────────────────────────────────────────────

class ConfigurationError(SignalNoiseError):
    """Raised when a required environment variable is missing at startup."""
    pass
