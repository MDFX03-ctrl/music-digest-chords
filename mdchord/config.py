"""API settings. The key stays in the environment."""

import os
from dataclasses import dataclass


@dataclass
class Config:
    base_url: str
    api_key: str
    model: str
    max_tokens: int = 8192


def load_config(base_url=None, api_key=None, model=None, max_tokens=None) -> Config:
    return Config(
        base_url=(base_url or os.environ.get("MDCHORD_BASE_URL") or "https://api.openai.com/v1").strip(),
        api_key=(api_key or os.environ.get("MDCHORD_API_KEY") or "").strip(),
        model=(model or os.environ.get("MDCHORD_MODEL") or "").strip(),
        max_tokens=int(max_tokens or os.environ.get("MDCHORD_MAX_TOKENS") or 8192),
    )


def missing_api(cfg: Config) -> list:
    missing = []
    if not cfg.api_key:
        missing.append("MDCHORD_API_KEY")
    if not cfg.model:
        missing.append("MDCHORD_MODEL")
    return missing
