"""
src/config.py

Centralised configuration for SignalNoise AI.
Loads all settings from .env at import time.

Every module imports from here — never from os.environ directly.

Usage:
    from src.config import config

    print(config.GROQ_API_KEY)
    print(config.MIN_WORD_COUNT)
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from src.exceptions import ConfigurationError

# Load .env file into environment (local dev only — no-op on Streamlit Cloud)
load_dotenv()

# ── Streamlit Cloud secrets → environment variables ───────────────────────────
# On Streamlit Cloud, secrets are in st.secrets instead of .env.
# We copy them into os.environ so the rest of config.py works unchanged.
try:
    import streamlit as st
    for _key, _val in st.secrets.items():
        if isinstance(_val, str):
            os.environ.setdefault(_key, _val)
except Exception:
    pass  # Not running under Streamlit, or secrets not configured yet


# ── Logging setup (runs once when this module is first imported) ──────────────

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


# ── Helper ────────────────────────────────────────────────────────────────────

def _require(key: str) -> str:
    """
    Read a required environment variable.
    Raises ConfigurationError immediately if it is missing.
    Fail loudly at startup — not silently at runtime.
    """
    value = os.environ.get(key)
    if not value:
        raise ConfigurationError(
            f"Required environment variable '{key}' is missing. "
            f"Copy .env.example to .env and fill in the value."
        )
    return value


def _optional(key: str, default: str) -> str:
    return os.getenv(key, default)


def _optional_int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


def _optional_float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


# ── Configuration dataclass ───────────────────────────────────────────────────

@dataclass(frozen=True)
class Config:
    """
    All application settings in one place.
    frozen=True means settings cannot be changed after load — intentional.
    """

    # Groq
    GROQ_API_KEY: str
    GROQ_MODEL: str

    # Data paths (as Path objects — not raw strings)
    RAW_DATA_DIR: Path
    PROCESSED_DATA_DIR: Path
    SAMPLE_DATA_DIR: Path
    CHROMA_DB_PATH: Path
    SQLITE_DB_PATH: Path

    # Quality gate thresholds
    MIN_WORD_COUNT: int
    MAX_WORD_COUNT: int
    MAX_SINGLE_TOKEN_RATIO: float
    ENGLISH_MARKER_THRESHOLD: float

    # Signal detection
    MIN_DOCS_FOR_BERTOPIC: int
    MIN_TOPIC_SIZE: int

    # Privacy
    SPACY_MODEL: str
    MIN_GROUP_SIZE: int

    # Logging
    LOG_LEVEL: str


def _load_config() -> Config:
    """Build and return the Config object from environment variables."""
    cfg = Config(
        # Groq — required (will raise ConfigurationError if missing)
        GROQ_API_KEY=_require("GROQ_API_KEY"),
        GROQ_MODEL=_optional("GROQ_MODEL", "llama3-8b-8192"),

        # Data paths — use /tmp on read-only cloud filesystems (Streamlit Cloud),
        # or local data/ when running on a developer machine.
        RAW_DATA_DIR=Path(_optional("RAW_DATA_DIR", "/tmp/signalnoise/raw")),
        PROCESSED_DATA_DIR=Path(_optional("PROCESSED_DATA_DIR", "/tmp/signalnoise/processed")),
        SAMPLE_DATA_DIR=Path(_optional("SAMPLE_DATA_DIR", "/tmp/signalnoise/sample")),
        CHROMA_DB_PATH=Path(_optional("CHROMA_DB_PATH", "/tmp/signalnoise/chroma")),
        SQLITE_DB_PATH=Path(_optional("SQLITE_DB_PATH", "/tmp/signalnoise/signalnoise.db")),

        # Quality gate
        MIN_WORD_COUNT=_optional_int("MIN_WORD_COUNT", 50),
        MAX_WORD_COUNT=_optional_int("MAX_WORD_COUNT", 100_000),
        MAX_SINGLE_TOKEN_RATIO=_optional_float("MAX_SINGLE_TOKEN_RATIO", 0.60),
        ENGLISH_MARKER_THRESHOLD=_optional_float("ENGLISH_MARKER_THRESHOLD", 0.02),

        # Signal detection
        MIN_DOCS_FOR_BERTOPIC=_optional_int("MIN_DOCS_FOR_BERTOPIC", 10),
        MIN_TOPIC_SIZE=_optional_int("MIN_TOPIC_SIZE", 2),

        # Privacy
        SPACY_MODEL=_optional("SPACY_MODEL", "en_core_web_sm"),
        MIN_GROUP_SIZE=_optional_int("MIN_GROUP_SIZE", 5),

        # Logging
        LOG_LEVEL=_optional("LOG_LEVEL", "INFO"),
    )

    # Ensure all data directories exist on startup
    for directory in [
        cfg.RAW_DATA_DIR,
        cfg.PROCESSED_DATA_DIR,
        cfg.SAMPLE_DATA_DIR,
        cfg.CHROMA_DB_PATH,
    ]:
        directory.mkdir(parents=True, exist_ok=True)

    logger.info("Configuration loaded successfully.")
    return cfg


# ── Single shared instance — import this everywhere ───────────────────────────
config = _load_config()
