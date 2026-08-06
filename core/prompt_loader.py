from functools import lru_cache
from pathlib import Path


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"
POLICY_DIR = Path(__file__).resolve().parents[1] / "policies"


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    return (PROMPT_DIR / name).read_text(encoding="utf-8").strip()


@lru_cache(maxsize=None)
def load_policy(name: str = "EC_POLICY_V1.md") -> str:
    return (POLICY_DIR / name).read_text(encoding="utf-8").strip()

