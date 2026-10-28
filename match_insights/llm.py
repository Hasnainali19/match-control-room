"""The single LLM gateway. Provider precedence: Azure OpenAI > GitHub Models > offline templates.

* Azure OpenAI / Azure AI Foundry: AZURE_OPENAI_ENDPOINT + AZURE_OPENAI_DEPLOYMENT + (API key | managed identity).
* GitHub Models (OpenAI-compatible, Azure-hosted): GITHUB_MODELS_TOKEN or GITHUB_TOKEN, endpoint
  GITHUB_MODELS_ENDPOINT (default https://models.github.ai/inference), model GITHUB_MODELS_MODEL
  (default openai/gpt-4o-mini). NOTE: GitHub announced GitHub Models' retirement on 2026-07-30; the
  provider is kept configurable so any OpenAI-compatible endpoint can be plugged in the same way.
* Offline: ``online == False`` and agents use deterministic templates.

Free-tier protection: response cache, client-side request spacing (requests/minute), honour
429 Retry-After with one short backoff, then a cooldown during which callers get LLMUnavailable
(-> template fallback), plus a circuit breaker for repeated failures.
"""
from __future__ import annotations
import hashlib, json, logging, os, threading, time
from collections import OrderedDict

log = logging.getLogger(__name__)
GITHUB_DEFAULT_ENDPOINT = "https://models.github.ai/inference"
GITHUB_DEFAULT_MODEL = "openai/gpt-4o-mini"


class LLMUnavailable(Exception):
    pass


def _status_code(ex):
    return getattr(ex, "status_code", None) or getattr(getattr(ex, "response", None), "status_code", None)


def _retry_after(ex, default=10.0):
    try:
        h = ex.response.headers
        return float(h.get("retry-after") or h.get("x-ratelimit-timeout") or default)
    except Exception:
        return default


class LLMClient:
    def __init__(self, timeout_s: float | None = None, fail_threshold: int = 3, cooldown_s: float = 60,
                 http_client=None, env: dict | None = None, sleep=time.sleep):
        env = os.environ if env is None else env
        self.timeout_s = timeout_s or float(env.get("MCR_LLM_TIMEOUT", 8))
        self.fail_threshold, self.cooldown_s, self._sleep = fail_threshold, cooldown_s, sleep
        self._fails, self._open_until, self._rate_until, self._last_call = 0, 0.0, 0.0, 0.0
        self.calls = self.failures = self.cache_hits = self.rate_limited = 0
        self._cache: OrderedDict = OrderedDict()
        self._cache_max = int(env.get("MCR_LLM_CACHE_SIZE", 256))
        self._lock = threading.Lock()
        self._client, self.provider, self.model = None, "offline", None
        self.min_interval_s = 0.0
        az_ep, az_dep = env.get("AZURE_OPENAI_ENDPOINT"), env.get("AZURE_OPENAI_DEPLOYMENT")
        az_key, az_mi = env.get("AZURE_OPENAI_API_KEY"), env.get("AZURE_OPENAI_USE_MANAGED_IDENTITY") == "1"
        gh_token = env.get("GITHUB_MODELS_TOKEN") or env.get("GITHUB_TOKEN")
        try:
            if az_ep and az_dep and (az_key or az_mi):
                from openai import AzureOpenAI
                kw = dict(azure_endpoint=az_ep, api_version=env.get("AZURE_OPENAI_API_VERSION", "2024-10-21"),
                          timeout=self.timeout_s, max_retries=0, http_client=http_client)
                if az_key:
                    kw["api_key"] = az_key
                else:
                    from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                    kw["azure_ad_token_provider"] = get_bearer_token_provider(
                        DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
                self._client, self.provider, self.model = AzureOpenAI(**kw), "azure-openai", az_dep
            elif gh_token:
                from openai import OpenAI
                self.endpoint = env.get("GITHUB_MODELS_ENDPOINT", GITHUB_DEFAULT_ENDPOINT)
                self._client = OpenAI(base_url=self.endpoint, api_key=gh_token, timeout=self.timeout_s,
                                      max_retries=0, http_client=http_client)
                self.provider, self.model = "github-models", env.get("GITHUB_MODELS_MODEL", GITHUB_DEFAULT_MODEL)
                # free tier is roughly 10-15 requests/minute for low-tier models: space calls out
                self.min_interval_s = 60.0 / float(env.get("GITHUB_MODELS_RPM", 10))
        except Exception as ex:  # pragma: no cover
            log.warning("LLM client init failed (%s); running offline", ex)
            self._client, self.provider = None, "offline"

    # ------------------------------------------------------------------ status
    @property
    def online(self) -> bool:
        return self._client is not None

    @property
    def circuit_open(self) -> bool:
        return time.monotonic() < self._open_until

    def status(self):
        now = time.monotonic()
        return {"provider": self.provider, "online": self.online, "model": self.model if self.online else None,
                "circuit_open": self.circuit_open, "rate_limited_for_s": round(max(0.0, self._rate_until - now), 1),
                "calls": self.calls, "failures": self.failures, "cache_hits": self.cache_hits,
                "rate_limited": self.rate_limited}

    # ------------------------------------------------------------------ calls
    def _key(self, *parts):
        return hashlib.sha256(json.dumps([self.model, *parts]).encode()).hexdigest()

    def complete(self, system: str, user: str, max_tokens: int = 160, json_mode: bool = False) -> str:
        if not self._client:
            raise LLMUnavailable("offline mode (no LLM provider configured)")
        key = self._key(system, user, max_tokens, json_mode)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self.cache_hits += 1
                return self._cache[key]
        now = time.monotonic()
        if now < self._open_until:
            raise LLMUnavailable("circuit open after repeated failures")
        if now < self._rate_until:
            raise LLMUnavailable("rate limited; using templates until the window resets")
        if self.min_interval_s and now - self._last_call < self.min_interval_s:
            raise LLMUnavailable("request budget: spacing calls for the free tier")
        kw = {"response_format": {"type": "json_object"}} if json_mode else {}
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        for attempt in range(2):
            self._last_call = time.monotonic()
            self.calls += 1
            try:
                r = self._client.chat.completions.create(model=self.model, max_tokens=max_tokens, temperature=0.5,
                                                         messages=msgs, **kw)
                text = (r.choices[0].message.content or "").strip()
                if not text:
                    raise ValueError("empty completion")
                self._fails = 0
                with self._lock:
                    self._cache[key] = text
                    if len(self._cache) > self._cache_max:
                        self._cache.popitem(last=False)
                return text
            except Exception as ex:
                self.failures += 1
                if _status_code(ex) == 429:
                    self.rate_limited += 1
                    wait = _retry_after(ex)
                    if attempt == 0 and wait <= 2:
                        self._sleep(wait)  # one short backoff, then retry once
                        continue
                    self._rate_until = time.monotonic() + max(wait, 5)
                    log.warning("LLM rate limited (%s); template fallback for %.0fs", self.provider, wait)
                    raise LLMUnavailable("rate limited (429)") from ex
                self._fails += 1
                if self._fails >= self.fail_threshold:
                    self._open_until = time.monotonic() + self.cooldown_s
                    log.warning("LLM circuit opened for %ss", self.cooldown_s)
                raise LLMUnavailable(f"{type(ex).__name__}: {str(ex)[:160]}") from ex
        raise LLMUnavailable("rate limited (429)")

    def complete_json(self, system: str, user: str, max_tokens: int = 220) -> dict:
        txt = self.complete(system + " Respond with a single JSON object only.", user, max_tokens, json_mode=True)
        txt = txt.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            return json.loads(txt)
        except json.JSONDecodeError as ex:
            raise LLMUnavailable("model returned malformed JSON") from ex
