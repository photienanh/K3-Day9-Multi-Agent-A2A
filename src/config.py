"""Project paths and immutable runtime configuration."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
INPUT_DIR = PROJECT_ROOT / "input"
OUTPUT_DIR = PROJECT_ROOT / "output"
LOGGING_DIR = PROJECT_ROOT / "logging"

MODEL_NAME = "gpt-4o-mini"
MODEL_TEMPERATURE = 0.0
POLICY_VERSION = "EC_POLICY_V1"
MONEY_TOLERANCE_BRL = "0.10"

EXPECTED_CASE_COUNT = 50
TRACE_PATH = LOGGING_DIR / "trace.jsonl"
METADATA_PATH = LOGGING_DIR / "metadata.json"


def load_project_environment() -> None:
    """Load the untracked project .env without overriding exported variables."""

    load_dotenv(PROJECT_ROOT / ".env", override=False)
