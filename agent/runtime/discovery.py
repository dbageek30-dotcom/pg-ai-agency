import os
import glob
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

# ============================================================
# CONFIGURATION
# ============================================================

CONFIG_PATH = "/opt/pgagent/config/config.json"
REGISTRY_PATH = "/opt/pgagent/runtime/registry.json"

def load_config():
    if not os.path.exists(CONFIG_PATH):
        return {}
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)


# ============================================================
# DISCOVERY : PostgreSQL binaries + extensions
# ============================================================

SEARCH_PATHS = [
    "/usr/lib/postgresql/*/bin",
    "/usr/pgsql-*/bin",
    "/usr/pgsql*/bin",
    "/opt/pgagent/bin",
    "/opt/patroni/bin",
    "/opt/pgbackrest/bin",
    "/usr/local/bin",
    "/usr/bin",
    "/usr/sbin"
]

def get_version_from_path(path):
    match = re.search(r'(?:postgresql|pgsql)[/-]?(\d+\.?\d*)', path)
    return match.group(1) if match else None

def discover_pg_extensions():
    extensions = {}
    try:
        query = "SELECT name, installed_version FROM pg_available_extensions WHERE installed_version IS NOT NULL;"
        result = subprocess.run(
            ["psql", "-Atc", query],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split('\n'):
                if '|' in line:
                    name, version = line.split('|')
                    extensions[name] = version
    except Exception:
        pass
    return extensions

def discover_binaries():
    registry = {
        "last_scan": datetime.now().isoformat(),
        "binaries": {},
        "capabilities": {
            "extensions": {},
            "os_info": os.uname().sysname if hasattr(os, 'uname') else "unknown"
        }
    }

    found_dirs = []
    for pattern in SEARCH_PATHS:
        for p in glob.glob(pattern):
            if os.path.isdir(p):
                found_dirs.append(p)

    found_dirs.sort(key=lambda x: (get_version_from_path(x) or "0"), reverse=True)

    for base_path in found_dirs:
        version = get_version_from_path(base_path)
        try:
            with os.scandir(base_path) as it:
                for entry in it:
                    try:
                        if entry.is_file() and os.access(entry.path, os.X_OK):
                            if entry.name not in registry["binaries"]:
                                registry["binaries"][entry.name] = entry.path

                            if version:
                                versioned_name = f"{entry.name}-{version}"
                                if versioned_name not in registry["binaries"]:
                                    registry["binaries"][versioned_name] = entry.path
                    except OSError:
                        continue
        except PermissionError:
            continue

    if "psql" in registry["binaries"]:
        registry["capabilities"]["extensions"] = discover_pg_extensions()

    return registry

def get_registry():
    if not os.path.exists(REGISTRY_PATH):
        return {}
    with open(REGISTRY_PATH, "r") as f:
        return json.load(f)


# ============================================================
# LLM CLIENTS
# ============================================================

class BaseLLMClient:
    def chat(self, prompt: str, model: str | None = None) -> str:
        raise NotImplementedError


class MockLLM(BaseLLMClient):
    def chat(self, prompt: str, model: str | None = None) -> str:
        return json.dumps({
            "goal": "mock goal",
            "mode": "readonly",
            "max_steps": 1,
            "steps": [
                {
                    "id": "mock_step",
                    "tool": "echo",
                    "args": ["hello"],
                    "intent": "mock",
                    "on_error": "abort"
                }
            ]
        })


class OllamaClient(BaseLLMClient):
    def __init__(self, url: str, model: str):
        self.url = url
        self.model = model

    def chat(self, prompt: str, model: str | None = None) -> str:
        import requests
        payload = {
            "model": model or self.model,
            "prompt": prompt
        }
        r = requests.post(f"{self.url}/api/generate", json=payload)
        r.raise_for_status()
        return r.text


class OpenAIClient(BaseLLMClient):
    def __init__(self, api_key: str, model: str):
        from openai import OpenAI
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def chat(self, prompt: str, model: str | None = None) -> str:
        response = self.client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content


class AzureOpenAIClient(BaseLLMClient):
    def __init__(self, endpoint: str, deployment: str, api_key: str):
        from openai import AzureOpenAI
        self.client = AzureOpenAI(
            api_key=api_key,
            azure_endpoint=endpoint,
            api_version="2024-02-01"
        )
        self.deployment = deployment

    def chat(self, prompt: str, model: str | None = None) -> str:
        response = self.client.chat.completions.create(
            model=self.deployment,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.choices[0].message.content


class LMStudioClient(BaseLLMClient):
    def __init__(self, url: str, model: str):
        self.url = url
        self.model = model

    def chat(self, prompt: str, model: str | None = None) -> str:
        import requests
        payload = {
            "model": model or self.model,
            "messages": [{"role": "user", "content": prompt}]
        }
        r = requests.post(f"{self.url}/v1/chat/completions", json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]


# ============================================================
# FACTORY : get_llm_client()
# ============================================================

_cached_client = None

def get_llm_client():
    global _cached_client
    if _cached_client:
        return _cached_client

    cfg = load_config().get("llm", {})
    provider = cfg.get("provider", "mock")

    if provider == "mock":
        _cached_client = MockLLM()

    elif provider == "ollama":
        _cached_client = OllamaClient(
            url=cfg.get("url", "http://localhost:11434"),
            model=cfg.get("model", "llama3.1")
        )

    elif provider == "openai":
        _cached_client = OpenAIClient(
            api_key=cfg.get("api_key", ""),
            model=cfg.get("model", "gpt-4o-mini")
        )

    elif provider == "azure":
        _cached_client = AzureOpenAIClient(
            endpoint=cfg.get("endpoint", ""),
            deployment=cfg.get("deployment", ""),
            api_key=cfg.get("api_key", "")
        )

    elif provider == "lmstudio":
        _cached_client = LMStudioClient(
            url=cfg.get("url", "http://localhost:1234"),
            model=cfg.get("model", "llama3.1")
        )

    else:
        raise ValueError(f"Unknown LLM provider: {provider}")

    return _cached_client


# ============================================================
# MAIN (scan only)
# ============================================================

if __name__ == "__main__":
    print(json.dumps(discover_binaries(), indent=4))

