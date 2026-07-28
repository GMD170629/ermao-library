from __future__ import annotations

import re


def mask_email(value: object) -> str:
    address = str(value or "")
    local, separator, domain = address.partition("@")
    if not separator:
        return "***"
    masked = local[:1] + "***" if len(local) <= 2 else local[:1] + "***" + local[-1:]
    return f"{masked}@{domain}"


def safe_error_message(
    error: BaseException | str,
    secrets: list[str] | None = None,
) -> str:
    message = str(error).strip() or error.__class__.__name__
    for secret in secrets or []:
        if secret:
            message = message.replace(secret, "[已隐藏]")
    message = re.sub(
        r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
        lambda match: mask_email(match.group(0)),
        message,
        flags=re.IGNORECASE,
    )
    message = re.sub(
        r"/(?:Users|home|var|Volumes|mnt|srv|opt)/[^\s'\"]+",
        "[本地路径]",
        message,
    )
    return message[:1000]
