"""P0 smoke test: one tiny JSON call per configured free-tier model.
Prints only model name, status and the parsed JSON — never the key."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import config  # noqa: E402
from app.llm.client import LLMClient, LLMError, QuotaExhausted  # noqa: E402


def main() -> int:
    client = LLMClient()
    models = sorted({config.SOLVER_A_MODEL, config.SOLVER_B_MODEL, config.JUDGE_MODEL, config.FALLBACK_MODEL})
    ok = True
    for m in models:
        try:
            data, resp = client.complete_json(
                model=m, prompt_version="smoke-v1",
                system='Reply with JSON only: {"ok": true, "sum": <number>}',
                user="What is 17 + 25?")
            print(f"{m:28s} OK   cached={resp.cached} -> {data}")
            ok &= data.get("sum") == 42
        except QuotaExhausted as e:
            print(f"{m:28s} QUOTA {e}")
            ok = False
        except LLMError as e:
            print(f"{m:28s} FAIL {str(e)[:200]}")
            ok = False
    print("stats", client.stats)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
