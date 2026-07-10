"""Configure Hermes' primary model and ordered fallback chain.

All machine-specific values come from environment variables supplied by the
bootstrap script. The existing YAML is updated atomically and credentials are
never read or written here.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import yaml


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise SystemExit(f"Required environment variable is missing: {name}")
    return value


def timeout_seconds(name: str, default: int = 900) -> int:
    raw = os.environ.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise SystemExit(f"{name} must be an integer") from exc
    if value < 60:
        raise SystemExit(f"{name} must be at least 60 seconds")
    return value


def ollama_api_root(openai_base_url: str) -> str:
    parts = urlsplit(openai_base_url.rstrip("/"))
    path = parts.path.rstrip("/")
    if path.endswith("/v1"):
        path = path[:-3]
    return urlunsplit((parts.scheme, parts.netloc, path, "", "")).rstrip("/")


def validate_ollama(base_url: str, model: str) -> None:
    url = f"{ollama_api_root(base_url)}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            payload = json.load(response)
    except Exception as exc:
        raise SystemExit(f"Cannot reach Ollama at {url}: {exc}") from exc

    installed = {str(item.get("name", "")) for item in payload.get("models", [])}
    if model not in installed:
        available = ", ".join(sorted(installed)) or "none"
        raise SystemExit(f"Ollama model '{model}' is not installed. Available: {available}")


def main() -> None:
    config_path = Path(os.environ.get("HERMES_CONFIG_PATH", "/opt/data/config.yaml"))
    primary_provider = required("HERMES_PRIMARY_PROVIDER")
    primary_model = required("HERMES_PRIMARY_MODEL")
    nvidia_provider = required("HERMES_NVIDIA_PROVIDER")
    nvidia_model = required("HERMES_NVIDIA_FALLBACK_MODEL")
    ollama_provider = required("HERMES_OLLAMA_PROVIDER")
    ollama_model = required("HERMES_OLLAMA_MODEL")
    ollama_base_url = required("HERMES_OLLAMA_BASE_URL").rstrip("/")
    ollama_timeout = timeout_seconds("HERMES_OLLAMA_TIMEOUT")
    validate_ollama(ollama_base_url, ollama_model)

    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}

    model_config = config.get("model")
    if not isinstance(model_config, dict):
        model_config = {}
    model_config["default"] = primary_model
    model_config["provider"] = primary_provider
    # This option is global in Hermes 0.18.0. Keeping it here would make the
    # OpenAI primary look like a constrained Ollama runtime. The local context
    # is therefore controlled by OLLAMA_CONTEXT_LENGTH on the Ollama service.
    model_config.pop("ollama_num_ctx", None)
    config["model"] = model_config

    config["fallback_providers"] = [
        {"provider": nvidia_provider, "model": nvidia_model},
        {
            "provider": ollama_provider,
            "model": ollama_model,
            "base_url": ollama_base_url,
        },
    ]
    config.pop("fallback_model", None)

    providers = config.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    ollama_config = providers.get(ollama_provider)
    if not isinstance(ollama_config, dict):
        ollama_config = {}
    ollama_config["request_timeout_seconds"] = ollama_timeout
    ollama_config["stale_timeout_seconds"] = ollama_timeout
    providers[ollama_provider] = ollama_config
    config["providers"] = providers

    original_mode = stat.S_IMODE(config_path.stat().st_mode)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=config_path.parent, delete=False
    ) as handle:
        yaml.safe_dump(config, handle, sort_keys=False, allow_unicode=True)
        temp_path = Path(handle.name)
    temp_path.chmod(original_mode)
    temp_path.replace(config_path)

    print(f"Primary: {primary_model} via {primary_provider}")
    print(f"Fallback 1: {nvidia_model} via {nvidia_provider}")
    print(f"Fallback 2: {ollama_model} via {ollama_provider} at {ollama_base_url}")
    print(f"Ollama request timeout: {ollama_timeout}s")


if __name__ == "__main__":
    main()
