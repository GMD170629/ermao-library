"""Bounded provider queries and candidate-cache identity."""

import hashlib
import json
from collections.abc import Mapping

from app.modules.metadata.application.ai_assistance import PROMPT_VERSION
from app.modules.metadata.domain.recognition import normalize_isbn


def recognition_queries(
    context: Mapping[str, object], provider: str, override: str | None = None
) -> tuple[str, ...]:
    if override and override.strip():
        return (override.strip()[:500],)
    identity = context.get("identity")
    identity = identity if isinstance(identity, dict) else {}
    book = context.get("book")
    book = book if isinstance(book, dict) else {}
    title = str(identity.get("workTitle") or book.get("title") or "").strip()
    author = str(book.get("author") or "").strip()
    isbn = normalize_isbn(str(identity.get("isbn") or ""))
    queries = []
    if isbn and provider in {"douban", "google-books", "open-library"}:
        queries.append(isbn)
    queries.append(title if provider == "bangumi" else " ".join(part for part in (title, author) if part))
    aliases = identity.get("aliases")
    if isinstance(aliases, (list, tuple)):
        queries.extend(str(alias) for alias in aliases[:2] if isinstance(alias, str))
    return tuple(dict.fromkeys(query[:500] for query in queries if query))[:3]


def candidate_cache_key(
    context: Mapping[str, object], provider: str, query: str,
    config: Mapping[str, object],
) -> str:
    # Hash credentials only as part of the digest: rotations invalidate cached
    # authorization-specific responses without storing credentials in a key.
    payload = {"version": 3, "aiPrompt": PROMPT_VERSION if provider == "ai" else None, "provider": provider, "query": query,
               "config": dict(config), "context": dict(context)}
    return "recognition:v3:" + hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode()
    ).hexdigest()
