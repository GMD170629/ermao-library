"""Shared bibliographic identity normalization without capability imports."""

import re
import unicodedata

UNKNOWN_AUTHOR = "未知作者"


def normalize_identity_part(value: object) -> str:
    normalized = unicodedata.normalize("NFKC", str(value or "")).lower()
    return re.sub(
        r"[\s_\-.[\]()（）【】《》:：,，!！?？\"'“”‘’·・、/\\]+",
        "",
        normalized,
    ).strip()
