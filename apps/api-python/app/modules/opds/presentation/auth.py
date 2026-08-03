from __future__ import annotations

import base64
import binascii

from app.modules.opds.application.dto import BasicCredentialsDto
from app.modules.opds.domain.errors import OpdsAuthenticationRequired


def parse_basic_authorization(value: str | None) -> BasicCredentialsDto:
    if value is None:
        raise OpdsAuthenticationRequired
    scheme, separator, encoded = value.partition(" ")
    if separator != " " or scheme.lower() != "basic" or not encoded.strip():
        raise OpdsAuthenticationRequired
    try:
        decoded = base64.b64decode(encoded.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise OpdsAuthenticationRequired from exc
    username, separator, password = decoded.partition(":")
    if separator != ":" or not username or not password:
        raise OpdsAuthenticationRequired
    return BasicCredentialsDto(username=username, password=password)
