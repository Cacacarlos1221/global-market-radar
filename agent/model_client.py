"""Minimal provider-neutral OpenAI-compatible JSON client (standard library only)."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

class ChatCompletionsClient:
    def __init__(self):
        self.base_url = os.getenv("MARKET_AGENT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("MARKET_AGENT_MODEL", "")
        self.api_key = os.getenv("MARKET_AGENT_API_KEY", "")
        if not self.model:
            raise ValueError("MARKET_AGENT_MODEL must be configured")
        if not self.base_url.startswith("https://") and not self.base_url.startswith("http://localhost:"):
            raise ValueError("Use HTTPS for remote model providers")

    def generate_json(self, system_prompt, user_prompt):
        payload = json.dumps({
            "model": self.model,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user", "content": user_prompt}],
            "temperature": 0.1,
        }).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(self.base_url + "/chat/completions", payload, headers)
        try:
            with urlopen(request, timeout=90) as response:
                body = json.load(response)
        except (HTTPError, URLError) as exc:
            raise RuntimeError(f"Model API request failed: {exc}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Model must return a single valid JSON object") from exc
        if not isinstance(result, dict):
            raise ValueError("Model response must be a JSON object")
        return result
