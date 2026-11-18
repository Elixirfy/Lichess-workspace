"""Small OpenAI-compatible chat-completions adapter."""

import json
import math
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

GROQ_BASE_URL = "https://api.groq.com/openai/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"


@dataclass(frozen=True)
class Completion:
    content: str
    usage: tuple[int, int] | None


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class ChatProvider:
    name = "openai-compatible"

    def __init__(self, base_url: str, model: str, auth: str = "", budget_seconds: float = 4, max_tokens: int = 600):
        parsed = urlsplit(base_url)
        if (parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password
                or parsed.query or parsed.fragment or (parsed.scheme == "http" and parsed.hostname not in ("127.0.0.1", "localhost", "::1"))):
            raise ValueError("HTTPS provider or localhost HTTP required; no URL credentials/query")
        if not model or len(model) > 120 or not math.isfinite(budget_seconds) or not 0 < budget_seconds <= 8 or not 1 <= max_tokens <= 1200:
            raise ValueError("invalid provider limits")
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model, self.auth = model, auth
        self.budget_seconds, self.max_tokens = budget_seconds, max_tokens
        self.opener = urllib.request.build_opener(NoRedirect)

    def complete(self, context: dict, *, repair: bool, deadline: float) -> Completion:
        system = ("Return one JSON object with schemaVersion=2 and textIndex, the zero-based "
                  "index of the most instructive entry in focus.texts. "
                  "Prefer concrete consequences and specific encouragement for a beginner. "
                  "If focus.teachingPatterns is present you may add followUp, a short Vietnamese question "
                  "formed by choosing one option in each parenthesis of one pattern. "
                  "Copy the rest of the pattern as written, including any move. "
                  "Omit followUp if there is no pattern. Do not return prose outside JSON.")
        if repair:
            system += " Previous response failed verification. Prefer textIndex 0 and only use a valid teaching pattern."
        groq = urlsplit(self.url).hostname == "api.groq.com"
        token_field = "max_completion_tokens" if groq else "max_tokens"
        body = {"model": self.model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ], "temperature": 0, token_field: self.max_tokens,
           "response_format": {"type": "json_object"}}
        if groq and self.model.startswith("openai/gpt-oss-"):
            body["reasoning_effort"] = "low"
        headers = {"Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": "LichessLocalCoach/1.0"}
        if self.auth:
            headers["Authorization"] = "Bearer " + self.auth
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("budget")
        request = urllib.request.Request(self.url, json.dumps(body, ensure_ascii=False).encode(), headers)
        with self.opener.open(request, timeout=remaining) as response:
            data = bytearray()
            # Bound bytes AND wall clock, including a peer trickling bytes.
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("budget")
                if response.fp is not None:
                    response.fp.raw._sock.settimeout(remaining)
                chunk = response.read1(min(4096, 32769 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > 32768:
                    raise RuntimeError("provider response limit")
        raw = json.loads(data)
        content = raw["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise ValueError("invalid provider content")
        usage = raw.get("usage")
        counts = None
        if isinstance(usage, dict):
            a, b = usage.get("prompt_tokens"), usage.get("completion_tokens")
            if type(a) is int and type(b) is int and 0 <= a <= 1000000 and 0 <= b <= 1000000:
                counts = a, b
        return Completion(content, counts)


def from_env(dotenv: Path | None = None):
    path = Path(__file__).with_name(".env") if dotenv is None else dotenv
    config = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            key, _, value = line.strip().partition("=")
            if key.strip().startswith("COACH_LLM_"):
                config[key.strip()] = value.strip().strip("\"'")
    config.update(os.environ)
    auth = config.get("COACH_LLM_API_KEY", "").strip() or config.get("COACH_LLM_AUTH", "").strip()
    mode = config.get("COACH_LLM_PROVIDER", "openai-compatible" if auth else "off")
    if mode == "off":
        return None
    if mode != "openai-compatible":
        raise ValueError("COACH_LLM_PROVIDER must be off or openai-compatible")
    base_url = config.get("COACH_LLM_BASE_URL") or (GROQ_BASE_URL if auth.startswith("gsk_") else OPENAI_BASE_URL)
    default_model = "openai/gpt-oss-20b" if urlsplit(base_url).hostname == "api.groq.com" else "gpt-4.1-mini"
    return ChatProvider(base_url,
                        config.get("COACH_LLM_MODEL", default_model), auth,
                        float(config.get("COACH_LLM_BUDGET_SECONDS", "4")),
                        int(config.get("COACH_LLM_MAX_TOKENS", "600")))
