"""Provider-agnostic LLM client (configured provider: Google AI Studio / Gemini, free tier).

Features: disk cache, request pacing, timeout, retries with exponential backoff
+ jitter, server-provided retry delays, daily-quota detection (stop, never
upgrade), free-model allowlist, malformed-JSON recovery.

The API key is passed only in a request header and is scrubbed from any error
text before it can reach a log or exception message.
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from .. import config
from .cache import DiskCache


class LLMError(RuntimeError):
    pass


class QuotaExhausted(LLMError):
    """Free-tier daily quota hit. The run must stop; resume later from cache."""


class OfflineMiss(LLMError):
    """LLM_OFFLINE=1 and the response is not in the cache."""


@dataclass
class LLMResponse:
    text: str
    model: str
    cached: bool
    usage: dict


class Provider(Protocol):
    name: str

    def generate(self, model: str, system: str, user: str, temperature: float, json_mode: bool) -> tuple[str, dict]:
        ...


def _scrub(text: str, secret: str) -> str:
    if secret:
        text = text.replace(secret, "***")
    return re.sub(r"(key=)[A-Za-z0-9_\-]+", r"\1***", text)


class _HTTPStatus(LLMError):
    def __init__(self, status: int, body: str, retry_after: float | None, daily: bool):
        super().__init__(f"HTTP {status}: {body[:400]}")
        self.status, self.retry_after, self.daily = status, retry_after, daily


class GeminiProvider:
    """Native Gemini REST API (generateContent). Key in `x-goog-api-key` header."""

    name = "gemini"
    BASE = "https://generativelanguage.googleapis.com/v1beta/models"

    def __init__(self, api_key: str, timeout: float):
        self._key = api_key
        self._http = httpx.Client(timeout=timeout)

    def generate(self, model, system, user, temperature, json_mode):
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": temperature},
        }
        if json_mode:
            body["generationConfig"]["responseMimeType"] = "application/json"
        r = self._http.post(
            f"{self.BASE}/{model}:generateContent",
            headers={"x-goog-api-key": self._key, "content-type": "application/json"},
            json=body,
        )
        if r.status_code != 200:
            txt = _scrub(r.text, self._key)
            retry_after, daily = None, False
            try:
                err = r.json().get("error", {})
                for d in err.get("details", []) or []:
                    if d.get("@type", "").endswith("RetryInfo"):
                        m = re.match(r"([\d.]+)s", d.get("retryDelay", ""))
                        if m:
                            retry_after = float(m.group(1))
                    if d.get("@type", "").endswith("QuotaFailure"):
                        for v in d.get("violations", []) or []:
                            if "PerDay" in (v.get("quotaId", "") + v.get("quotaMetric", "")):
                                daily = True
            except (ValueError, AttributeError):
                pass
            raise _HTTPStatus(r.status_code, txt, retry_after, daily)
        data = r.json()
        cands = data.get("candidates") or []
        if not cands:
            raise LLMError(f"no candidates (promptFeedback={data.get('promptFeedback')})")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise LLMError(f"empty response (finishReason={cands[0].get('finishReason')})")
        return text, data.get("usageMetadata", {})


class OpenAICompatibleProvider:
    """Any OpenAI-compatible /chat/completions endpoint (kept for portability;
    not used in this submission because the budget is free-tier Gemini only)."""

    name = "openai_compatible"

    def __init__(self, api_key: str, base_url: str, timeout: float):
        self._key, self._base = api_key, base_url.rstrip("/")
        self._http = httpx.Client(timeout=timeout)

    def generate(self, model, system, user, temperature, json_mode):
        body: dict[str, Any] = {
            "model": model,
            "temperature": temperature,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        r = self._http.post(f"{self._base}/chat/completions", headers={"authorization": f"Bearer {self._key}"}, json=body)
        if r.status_code != 200:
            ra = r.headers.get("retry-after")
            raise _HTTPStatus(r.status_code, _scrub(r.text, self._key), float(ra) if ra and ra.isdigit() else None, False)
        data = r.json()
        return data["choices"][0]["message"]["content"], data.get("usage", {})


def extract_json(text: str) -> Any:
    """Recover a JSON object from model text: strips fences, finds the first
    balanced {...} block, tolerates trailing commas."""
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.S)
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        pass
    start = t.find("{")
    if start < 0:
        raise ValueError("no JSON object in response")
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                frag = t[start : i + 1]
                try:
                    return json.loads(frag)
                except json.JSONDecodeError:
                    return json.loads(re.sub(r",\s*([}\]])", r"\1", frag))
    raise ValueError("unbalanced JSON object in response")


class LLMClient:
    def __init__(self, provider: Provider | None = None, cache: DiskCache | None = None):
        self.cache = cache or DiskCache(config.CACHE_DIR / "llm")
        self._provider = provider
        self._last_call = 0.0
        self.stats = {"calls": 0, "cache_hits": 0, "retries": 0, "json_repairs": 0}

    @property
    def provider(self) -> Provider:
        if self._provider is None:
            if config.LLM_PROVIDER != "gemini":
                raise LLMError("Only the free-tier Gemini provider is enabled for this project.")
            key = config.env("GEMINI_API_KEY")
            if not key:
                raise LLMError("GEMINI_API_KEY is not set (put it in .env; see .env.example).")
            self._provider = GeminiProvider(key, config.LLM_TIMEOUT_S)
        return self._provider

    def _pace(self) -> None:
        wait = config.LLM_MIN_INTERVAL_S - (time.monotonic() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def complete(self, *, model: str, system: str, user: str, prompt_version: str,
                 temperature: float = 0.0, json_mode: bool = True) -> LLMResponse:
        if model not in config.FREE_TIER_ALLOWLIST:
            raise LLMError(f"model {model!r} is not on the free-tier allowlist; refusing to call it")
        k = DiskCache.key(provider=config.LLM_PROVIDER, model=model, v=prompt_version,
                          system=system, user=user, temperature=temperature, json=json_mode)
        hit = self.cache.get(k)
        if hit is not None:
            self.stats["cache_hits"] += 1
            return LLMResponse(hit["text"], hit["model"], True, hit.get("usage", {}))
        if config.LLM_OFFLINE:
            raise OfflineMiss(f"cache miss in offline mode ({prompt_version}, {model})")

        delay = 4.0
        last_err: Exception | None = None
        for attempt in range(config.LLM_MAX_RETRIES + 1):
            self._pace()
            try:
                self.stats["calls"] += 1
                text, usage = self.provider.generate(model, system, user, temperature, json_mode)
                rec = {"text": text, "model": model, "prompt_version": prompt_version, "usage": usage,
                       "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                self.cache.put(k, rec)
                return LLMResponse(text, model, False, usage)
            except _HTTPStatus as e:
                last_err = e
                if e.status == 429 and e.daily:
                    raise QuotaExhausted(
                        f"Free-tier daily quota reached for {model}. Stopping safely; rerun later — "
                        "completed calls are cached and will not be repeated.") from None
                if e.status in (429, 500, 502, 503, 504):
                    wait = max(e.retry_after or 0, delay) + random.uniform(0, 1.5)
                    self.stats["retries"] += 1
                    time.sleep(wait)
                    delay = min(delay * 2, 90)
                    continue
                raise LLMError(str(e)) from None
            except (httpx.TimeoutException, httpx.TransportError) as e:
                last_err = e
                self.stats["retries"] += 1
                time.sleep(delay + random.uniform(0, 1.5))
                delay = min(delay * 2, 90)
        if isinstance(last_err, _HTTPStatus) and last_err.status == 429:
            raise QuotaExhausted(f"Rate limit persisted after {config.LLM_MAX_RETRIES} retries on {model}; stopping safely.")
        raise LLMError(f"LLM call failed after retries: {last_err}")

    def complete_json(self, *, model: str, system: str, user: str, prompt_version: str,
                      temperature: float = 0.0) -> tuple[Any, LLMResponse]:
        resp = self.complete(model=model, system=system, user=user, prompt_version=prompt_version,
                             temperature=temperature, json_mode=True)
        try:
            return extract_json(resp.text), resp
        except ValueError:
            self.stats["json_repairs"] += 1
            fix = self.complete(
                model=model, prompt_version=prompt_version + "+jsonfix", temperature=0.0, json_mode=True,
                system="You repair malformed JSON. Output only the corrected JSON object, nothing else.",
                user="Return this as one valid JSON object, same content:\n\n" + resp.text[:12000],
            )
            return extract_json(fix.text), fix
