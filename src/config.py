"""Configuration management for the Pre-Algebra Learning System."""

import logging
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def get_secret(key: str, default: str = "") -> str:
    """Get a secret from Streamlit secrets or environment variables.

    Streamlit Cloud uses st.secrets for secret management, while local
    development uses environment variables. This function tries both.
    """
    try:
        import streamlit as st
        if hasattr(st, 'secrets') and key in st.secrets:
            return st.secrets[key]
    except Exception:
        pass
    return os.getenv(key, default)


# --- Logging Setup ---
LOG_LEVEL = get_secret("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("prealgebra")

# Base paths
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"

# Database
DATABASE_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "prealgebra.db"))

# Folders
SCANS_FOLDER = Path(os.getenv("SCANS_FOLDER", DATA_DIR / "scans"))
GENERATED_FOLDER = Path(os.getenv("GENERATED_FOLDER", DATA_DIR / "generated"))

# Claude Projects folder (for auto-copy to accessible location)
CLAUDE_PROJECTS_DIR = os.getenv("CLAUDE_PROJECTS_DIR", "")

# Ensure folders exist
SCANS_FOLDER.mkdir(parents=True, exist_ok=True)
GENERATED_FOLDER.mkdir(parents=True, exist_ok=True)

# API Keys - use get_secret for Streamlit Cloud compatibility
ANTHROPIC_API_KEY = get_secret("ANTHROPIC_API_KEY", "")

# Student configuration
STUDENT_NAME = get_secret("STUDENT_NAME", "Student")

# Multi-student support - each student gets a distinct color for visual differentiation
STUDENT_COLORS = {
    "Tilley": "#FF6B9D",  # Pink
    "Henry": "#4A90D9",   # Blue
    "default": "#6B7280", # Gray
}

# Grading settings
MASTERY_THRESHOLD = 100  # Percentage required for mastery
DIAGNOSTIC_MASTERY_THRESHOLD = 100  # Percentage required to skip a module in diagnostic
AUTO_GRADE_PRACTICE = True  # Auto-grade practice problems
MANUAL_GRADE_ASSESSMENTS = True  # Manual trigger for quizzes/tests

# Content generation settings
PROBLEMS_PER_PRACTICE = 25  # Number of problems per practice set
QUESTIONS_PER_QUIZ = 12  # Number of questions per quiz
QUESTIONS_PER_TEST = 25  # Number of questions per test

# Adaptive Pacing Settings
SPEEDUP_STREAK = 3          # Perfect scores before reducing problems
SLOWDOWN_STREAK = 2         # Struggles before increasing support
STRUGGLE_THRESHOLD = 70     # Score below this = struggling
SKIP_OFFER_STREAK = 5       # Perfect scores before offering lesson skip
MIN_PROBLEMS = 15           # Minimum problems when speeding up
MAX_PROBLEMS = 35           # Maximum problems when slowing down
BASE_PROBLEMS = 25          # Standard problem count (same as PROBLEMS_PER_PRACTICE)
MASTERY_ASSESSMENT_QUESTIONS = 5  # Questions in mastery assessment for lesson skip

# Claude model settings
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_VISION_MODEL = "claude-sonnet-4-20250514"

# API retry settings
API_MAX_RETRIES = 3
API_RETRY_DELAY = 2  # seconds


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""
    pass


def validate_config(require_api_key: bool = True) -> list[str]:
    """Validate configuration and return list of issues.

    Args:
        require_api_key: If True, treat missing API key as an error rather than a warning.

    Returns:
        List of warning strings for non-critical issues.

    Raises:
        ConfigurationError: If require_api_key is True and the key is missing.
    """
    issues = []

    if not ANTHROPIC_API_KEY:
        msg = "ANTHROPIC_API_KEY not set in environment"
        if require_api_key:
            raise ConfigurationError(
                f"{msg}. Copy .env.example to .env and add your API key."
            )
        issues.append(msg)

    if not SCANS_FOLDER.exists():
        issues.append(f"Scans folder does not exist: {SCANS_FOLDER}")

    if not GENERATED_FOLDER.exists():
        issues.append(f"Generated folder does not exist: {GENERATED_FOLDER}")

    return issues


def get_database_url() -> str:
    """Get SQLAlchemy database URL."""
    return f"sqlite:///{DATABASE_PATH}"
