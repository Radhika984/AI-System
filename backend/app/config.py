"""Central configuration. Reads environment variables and an optional local .env.

The API key is only ever read here and handed to the LLM client; it is never
logged, printed, or written anywhere.
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]  # repo root
DATA_DIR = ROOT / "data"
CACHE_DIR = ROOT / "cache"
ARTIFACTS_DIR = ROOT / "artifacts"


def _load_dotenv(path: Path) -> None:
    """Minimal .env loader (no dependency). Never overrides real env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and v and k not in os.environ:
            os.environ[k] = v


_load_dotenv(ROOT / ".env")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


LLM_PROVIDER = env("LLM_PROVIDER", "gemini")
SOLVER_A_MODEL = env("SOLVER_A_MODEL", "gemini-3-flash-preview")
SOLVER_B_MODEL = env("SOLVER_B_MODEL", "gemini-3.1-flash-lite")
JUDGE_MODEL = env("JUDGE_MODEL", "gemini-3-flash-preview")
# No fallback model: on a quota stop the run halts; it never switches models or providers.
LLM_MIN_INTERVAL_S = float(env("LLM_MIN_INTERVAL_S", "6"))
LLM_TIMEOUT_S = float(env("LLM_TIMEOUT_S", "300"))
LLM_MAX_RETRIES = int(env("LLM_MAX_RETRIES", "5"))
LLM_OFFLINE = env("LLM_OFFLINE", "0") == "1"

# Models the client is allowed to call. Anything else is refused, so a typo or
# a stray env var can never route traffic to a paid model.
FREE_TIER_ALLOWLIST = {
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3-flash-preview",
    "gemini-3.1-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
}

STATE_DIR = Path(env("STATE_DIR", str(ROOT / "state")))
if not STATE_DIR.is_absolute():
    STATE_DIR = ROOT / STATE_DIR
CORS_ORIGINS = [o.strip() for o in env("CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()]

AUTO_APPLY_MIN_CONFIDENCE = 0.85
SOLVER_BATCH_SIZE = int(env("SOLVER_BATCH_SIZE", "10"))
JUDGE_BATCH_SIZE = int(env("JUDGE_BATCH_SIZE", "4"))
