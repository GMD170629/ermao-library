"""The JSON wire format of every persisted SystemSetting value."""

from __future__ import annotations

import json
from typing import Any


def encode_setting_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON setting constant: {value}")


def decode_setting_value(raw: str) -> Any:
    return json.loads(raw, parse_constant=_reject_constant)
