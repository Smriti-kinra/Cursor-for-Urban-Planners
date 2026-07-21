"""Shared runtime config helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path

_BACKEND_DIR = Path(__file__).parent.parent
_MODEL_CONFIG_PATH = _BACKEND_DIR / "model_config.json"
_DEFAULT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-5.4-mini")


def get_model() -> str:
    try:
        data = json.loads(_MODEL_CONFIG_PATH.read_text())
        return data.get("model") or _DEFAULT_MODEL
    except Exception:
        return _DEFAULT_MODEL
