"""Load configuration. API keys are never read from a config file."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from tasks_recapture.errors import ConfigError

SECRET_KEYS = {
    "api_key",
    "apikey",
    "api-key",
    "token",
    "secret",
    "password",
    "authorization",
}


@dataclass
class Settings:
    tasks_dir: Path
    timezone: str
    model: str
    api_base: str
    timeout: float
    provider: str
    mock_script: Path | None
    send: bool


def _reject_secrets(payload: dict, label: str) -> None:
    found = sorted(key for key in payload if key.lower() in SECRET_KEYS)
    if found:
        raise ConfigError(
            f"{label} contains {', '.join(found)}. "
            "Put the API key only in the TASKS_RECAPTURE_API_KEY environment variable."
        )


def load_config_file(path: Path | None) -> dict:
    if path is None:
        default = Path("tasks-recapture.json")
        if default.is_file():
            path = default
        else:
            return {}
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError("config file is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ConfigError("config file must be a JSON object")
    _reject_secrets(payload, path.name)
    return payload


def _pick(cli_value, env_name: str, file_value, default):
    if cli_value is not None:
        return cli_value
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    if file_value not in (None, ""):
        return file_value
    return default


def build_settings(
    *,
    config_path: Path | None = None,
    tasks_dir: str | None = None,
    timezone: str | None = None,
    model: str | None = None,
    api_base: str | None = None,
    timeout: float | None = None,
    provider: str | None = None,
    mock_script: str | None = None,
    send: bool = False,
) -> Settings:
    file_payload = load_config_file(config_path)
    tasks_value = _pick(
        tasks_dir,
        "TASKS_RECAPTURE_TASKS_DIR",
        file_payload.get("tasks_dir"),
        "tasks",
    )
    timezone_value = _pick(
        timezone,
        "TASKS_RECAPTURE_TIMEZONE",
        file_payload.get("timezone"),
        "UTC",
    )
    model_value = _pick(
        model,
        "TASKS_RECAPTURE_MODEL",
        file_payload.get("model"),
        "",
    )
    api_value = _pick(
        api_base,
        "TASKS_RECAPTURE_API_BASE",
        file_payload.get("api_base"),
        "https://api.openai.com/v1",
    )
    timeout_value = _pick(
        timeout,
        "TASKS_RECAPTURE_TIMEOUT",
        file_payload.get("timeout_seconds"),
        60,
    )
    provider_value = _pick(
        provider,
        "TASKS_RECAPTURE_PROVIDER",
        file_payload.get("provider"),
        "",
    )
    script_value = _pick(
        mock_script,
        "TASKS_RECAPTURE_MOCK_SCRIPT",
        file_payload.get("mock_script"),
        "",
    )
    try:
        timeout_number = float(timeout_value)
    except (TypeError, ValueError) as exc:
        raise ConfigError("timeout_seconds must be a number") from exc
    if provider_value and provider_value not in {"mock", "openai-compatible"}:
        raise ConfigError("provider must be mock or openai-compatible")
    return Settings(
        tasks_dir=Path(tasks_value).expanduser(),
        timezone=str(timezone_value),
        model=str(model_value or ""),
        api_base=str(api_value),
        timeout=timeout_number,
        provider=str(provider_value or ""),
        mock_script=Path(script_value) if script_value else None,
        send=send,
    )
