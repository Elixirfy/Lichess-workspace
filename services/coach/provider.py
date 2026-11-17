"""Small OpenAI-compatible chat-completions adapter; no SDK or cloud default."""

import json
import math
import os
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlsplit


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
        system = ("Return JSON schemaVersion=1 with units. Select focus first, optionally turn. "
                  "Copy claimType, values and one complete text from the supplied statements. "
                  "Never add chess claims, moves, evaluation or free prose.")
        if repair:
            system += " Previous response failed verification. Return only exact supplied claims and wording."
        body = json.dumps({"model": self.model, "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
        ], "temperature": 0, "max_tokens": self.max_tokens,
           "response_format": {"type": "json_object"}}, ensure_ascii=False).encode()
        headers = {"Content-Type": "application/json"}
        if self.auth:
            headers["Authorization"] = "Bearer " + self.auth
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("budget")
        request = urllib.request.Request(self.url, body, headers)
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


def from_env():
    mode = os.environ.get("COACH_LLM_PROVIDER", "off")
    if mode == "off":
        return None
    if mode != "openai-compatible":
        raise ValueError("COACH_LLM_PROVIDER must be off or openai-compatible")
    return ChatProvider(os.environ["COACH_LLM_BASE_URL"], os.environ["COACH_LLM_MODEL"],
                        os.environ.get("COACH_LLM_AUTH", ""),
                        float(os.environ.get("COACH_LLM_BUDGET_SECONDS", "4")),
                        int(os.environ.get("COACH_LLM_MAX_TOKENS", "600")))
