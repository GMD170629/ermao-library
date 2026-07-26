from __future__ import annotations

import re

_URL_PASSWORD = re.compile(r"(?P<prefix>[a-z][a-z0-9+.-]*://[^:/\s]+:)[^@\s]+@", re.I)
_NAMED_PASSWORD = re.compile(r"(?P<prefix>\bpassword\s*=\s*)[^\s,;]+", re.I)


def safe_error_detail(error: Exception) -> str:
    detail = str(error) or type(error).__name__
    detail = _URL_PASSWORD.sub(r"\g<prefix>***@", detail)
    detail = _NAMED_PASSWORD.sub(r"\g<prefix>***", detail)
    return detail[:4000]
