"""Provider-neutral OpenAI-compatible JSON client; reads local ignored agent/.env."""
import json
import os
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

def load_local_env(path=None):
    path = Path(path) if path is not None else Path(__file__).with_name(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key.startswith("MARKET_AGENT_"):
            continue
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)

def model_configuration():
    load_local_env()
    return {"base_url": os.getenv("MARKET_AGENT_BASE_URL", "https://api.openai.com/v1"),
            "model": os.getenv("MARKET_AGENT_MODEL", ""),
            "key_present": bool(os.getenv("MARKET_AGENT_API_KEY", "")),
            "env_path": str(Path(__file__).with_name(".env"))}

class ChatCompletionsClient:
    def __init__(self):
        load_local_env()
        self.base_url = os.getenv("MARKET_AGENT_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("MARKET_AGENT_MODEL", "")
        self.api_key = os.getenv("MARKET_AGENT_API_KEY", "")
        if not self.model or self.model == "your-model-id":
            raise ValueError("Set MARKET_AGENT_MODEL in agent/.env")
        if not self.base_url.startswith("https://") and not self.base_url.startswith("http://localhost:"):
            raise ValueError("Use HTTPS for remote model providers")
        if not self.api_key and not self.base_url.startswith("http://localhost:"):
            raise ValueError("Set MARKET_AGENT_API_KEY in local agent/.env; never commit keys")

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
        except (HTTPError, URLError, TimeoutError) as exc:
            raise RuntimeError(f"Model API request failed: {getattr(exc, 'code', type(exc).__name__)}") from exc
        try:
            content = body["choices"][0]["message"]["content"]
            result = json.loads(content)
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError("Model must return a single valid JSON object") from exc
        if not isinstance(result, dict):
            raise ValueError("Model response must be a JSON object")
        return result
