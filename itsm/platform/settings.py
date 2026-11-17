"""Settings from the orchestrator's .env. Values are never printed, logged or put in a query.

Only the keys a step needs are required, so phase 1 probes run with the admin login alone.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"

# Personal Developer Instances only, the change repository's rule (cm_agents/settings.py).
PDI_URL = re.compile(r"^https://dev\d+\.service-now\.com$")


class SettingsError(RuntimeError):
    """A required key is missing or the instance is not a PDI. The message never holds a value."""


@dataclass(frozen=True)
class Settings:
    instance: str
    values: dict[str, str] = field(repr=False)

    def get(self, key: str) -> str:
        v = self.values.get(key, "")
        if not v:
            raise SettingsError(f"missing or empty setting {key}; see .env.example")
        return v

    def secrets(self) -> list[str]:
        return [v for k, v in self.values.items() if v and ("PASSWORD" in k or "KEY" in k)]


def load(path: Path | None = None, required: tuple[str, ...] = ("SN_INSTANCE_URL",)) -> Settings:
    path = path or ENV_FILE
    if not path.is_file():
        raise SettingsError(f"{path.name} not found: copy .env.example to .env and fill it in")
    values = {k: (v or "").strip() for k, v in dotenv_values(path).items()}
    missing = [k for k in required if not values.get(k)]
    if missing:
        raise SettingsError("missing or empty setting: " + ", ".join(missing))
    instance = values.get("SN_INSTANCE_URL", "").rstrip("/")
    if not PDI_URL.fullmatch(instance):
        raise SettingsError("SN_INSTANCE_URL is not a Personal Developer Instance URL (https://devNNNNNN.service-now.com)")
    return Settings(instance, values)


def redact(text: str, secrets: list[str]) -> str:
    for s in secrets:
        if s:
            text = text.replace(s, "***")
    return text
