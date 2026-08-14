"""Strict JSON-object extraction for model outputs."""
from __future__ import annotations

import json
from typing import Any


def parse_json_object(text: str) -> dict[str, Any]:
    """Decode the first complete JSON object, including fenced model output."""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("model output did not contain JSON")
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("model output did not contain a valid JSON object")


__all__ = ["parse_json_object"]
