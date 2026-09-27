"""Match bounded real source records, shared by manual and queued recognition."""

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.contracts.metadata_identity import MetadataIdentity
from app.core.exception_diagnostics import record_exception
from app.core.i18n import configured_locale
from app.modules.imports.public import normalize_identity_part
from app.modules.metadata.application.rate_limits import AutomaticMetadataRequestGate
from app.modules.metadata.infrastructure.ai_client import (
    match_metadata,
    model_configured,
)
from app.modules.metadata.infrastructure.identity_context import identity_clues
from app.services.metadata_provider_registry import metadata_provider_runtime_config
from app.services.organize_service import (
    choose_metadata_candidate,
    douban_base_url,
    douban_crawler_headers,
    external_metadata_cache_get,
    external_metadata_cache_put,
    fetch_douban_subject,
    normalize_douban_candidate,
)


def candidate_key(candidate: Mapping[str, object]) -> str:
    return f"{candidate['source']}:{candidate['id']}"


def candidate_type(candidate: Mapping[str, object]) -> str:
    if candidate.get("source") == "douban":
        return "豆瓣图书条目"
    raw = candidate.get("raw")
    return str(raw.get("platform") or "未提供细分类型")[:100] if isinstance(raw, dict) else "未提供细分类型"


@dataclass(frozen=True, slots=True)
class MetadataMatch:
    identity: MetadataIdentity | None
    primary_candidate_id: str | None = None
    related_candidate_ids: tuple[str, ...] = ()

    def application_candidate(
        self, candidates: Sequence[Mapping[str, object]]
    ) -> dict[str, object] | None:
        indexed = {candidate_key(item): item for item in candidates}
        primary = indexed.get(self.primary_candidate_id or "")
        if primary is None:
            return (
                self.identity.candidate()
                if self.identity and (self.identity.title or self.identity.author)
                else None
            )
        applied = dict(primary)
        # Only work-level missing fields; never mix edition identifiers/publication data.
        for key in self.related_candidate_ids:
            related = indexed[key]
            for field in ("description", "tags", "coverUrl"):
                if not applied.get(field) and related.get(field):
                    applied[field] = related[field]
        if self.identity:
            applied.update(
                title=self.identity.title or primary.get("title"),
                author=self.identity.author or primary.get("author"),
                identity=self.identity.payload(),
            )
        return applied


def prepare_matched_metadata(
    db: Session,
    match: MetadataMatch,
    candidates: Sequence[Mapping[str, object]],
    *,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> dict[str, object] | None:
    """Read only selected source records before standardizing application fields."""
    indexed = {candidate_key(item): dict(item) for item in candidates}
    primary = indexed.get(match.primary_candidate_id or "")
    if primary is None:
        return match.application_candidate(candidates)

    def detail(item: dict[str, object]) -> dict[str, object]:
        if item.get("source") != "douban" or item.get("_detailFetched") is True:
            return item
        try:
            identifier = str(item["id"])
            if not re.fullmatch(r"[0-9]{1,20}", identifier):
                raise ValueError("DOUBAN_INVALID_SUBJECT_ID")
            config = metadata_provider_runtime_config(db, "douban")
            if config is None:
                return item
            base_url = douban_base_url(config)
            cache_key = f"subject-detail:{base_url}:{identifier}"
            cached = external_metadata_cache_get(db, "douban", cache_key)
            db.close()
            if cached:
                records = cached.get("candidates", [])
                if records and records[0].get("id") == identifier and records[0].get("_detailFetched") is True:
                    return {**item, **records[0]}
            # Never use a model/raw URL; the configured source and validated ID own it.
            fetched = fetch_douban_subject(
                base_url, f"/subject/{identifier}/", douban_crawler_headers(config),
                {"id": identifier, "confidence": item.get("confidence", 0)},
                automatic_request_gate=automatic_request_gate,
            )
            if not fetched or str(fetched.get("id")) != identifier:
                raise ValueError("DOUBAN_SUBJECT_DETAIL_UNAVAILABLE")
            normalized = normalize_douban_candidate(fetched)
            normalized = {key: value for key, value in normalized.items() if value not in (None, "", [])}
            normalized["_detailFetched"] = True
        except Exception as error:  # noqa: BLE001 - optional detail preserves the search record.
            record_exception(logging.getLogger(__name__), "metadata.subject_detail_failed", error,
                             context={"step": "subject_detail", "resource_id": str(item.get("id"))})
            return {**item, "sourceIssues": ["douban:detail_failed"]}
        try:
            external_metadata_cache_put(db, "douban", cache_key, {"candidates": [normalized]})
        except Exception as error:  # noqa: BLE001 - cache failure must not lose fetched fields.
            record_exception(logging.getLogger(__name__), "metadata.subject_detail_cache_failed", error,
                             context={"step": "subject_detail_cache", "resource_id": identifier})
        return {**item, **normalized}

    indexed[match.primary_candidate_id or ""] = detail(primary)
    fields = ("description", "tags", "coverUrl")
    applied = indexed[match.primary_candidate_id or ""]
    related_keys: list[str] = []
    for key in match.related_candidate_ids:
        if all(applied.get(field) for field in fields):
            break
        related = indexed.get(key)
        if related is None:
            continue
        # Fetch only gaps this parser can provide; tags come from the search record.
        if any(not applied.get(field) and not related.get(field) for field in ("description", "coverUrl")):
            indexed[key] = detail(related)
        related_keys.append(key)
        applied = MetadataMatch(None, match.primary_candidate_id, tuple(related_keys)).application_candidate(list(indexed.values())) or applied
    return match.application_candidate(list(indexed.values()))


def match_metadata_candidates(
    db: Session,
    *,
    book_id: str,
    title: str,
    author: str | None,
    identity: MetadataIdentity | None,
    candidates: Sequence[Mapping[str, object]],
    source_node_id: str | None = None,
    manual_query: bool = False,
) -> MetadataMatch:
    # Source order is input order; a direct match per source is the fast path.
    bounded = list(candidates[:20])
    by_source: dict[str, list[Mapping[str, object]]] = {}
    for item in bounded:
        by_source.setdefault(str(item["source"]), []).append(item)
    direct = []
    for items in by_source.values():
        selected, _ = choose_metadata_candidate(items, title, author or "")
        if selected is not None:
            direct.append(selected)
    direct_authors = {
        normalize_identity_part(item.get("author"))
        for item in direct
        if item.get("author")
    }
    if direct and len(direct_authors) <= 1 and not (identity and identity.needs_review):
        primary = direct[0]
        final_identity = (
            MetadataIdentity(
                identity.title or str(primary.get("title") or "") or None,
                identity.author or str(primary.get("author") or "") or None,
                False,
                identity.reason,
            )
            if identity
            else None
        )
        return MetadataMatch(
            final_identity,
            candidate_key(primary),
            tuple(candidate_key(item) for item in direct[1:]),
        )
    config = metadata_provider_runtime_config(db, "ai")
    if not bounded or config is None or not model_configured(config):
        return MetadataMatch(identity)
    locale = configured_locale(db)
    clues = identity_clues(db, book_id, source_node_id)
    db.close()
    response = match_metadata(
        config,
        {
            "title": title[:500],
            "author": (author or "")[:500],
            "manualQuery": manual_query,
            "language": locale,
            "libraryName": clues["libraryName"],
            "fileNames": clues["fileNames"],
            "candidates": [
                {
                    "id": candidate_key(item),
                    "title": str(item.get("title") or "")[:500],
                    "author": str(item.get("author") or "")[:500],
                    "type": candidate_type(item),
                }
                for item in bounded
            ],
        },
    )
    available = {candidate_key(item) for item in bounded}
    references = [*response.relatedCandidateIds]
    if response.primaryCandidateId:
        references.append(response.primaryCandidateId)
    if any(key not in available for key in references):
        raise ValueError("AI_MATCH_UNKNOWN_CANDIDATE")
    if response.relatedCandidateIds and not response.primaryCandidateId:
        raise ValueError("AI_MATCH_RELATED_WITHOUT_PRIMARY")
    confirmed = next(
        (
            item
            for item in bounded
            if candidate_key(item) == response.primaryCandidateId
        ),
        None,
    )
    fallback_title = (
        str(confirmed.get("title") or "")
        if confirmed
        else identity.title
        if identity
        else None
    )
    fallback_author = (
        str(confirmed.get("author") or "")
        if confirmed
        else identity.author
        if identity
        else None
    )
    final_identity = MetadataIdentity(
        (response.title or "").strip() or fallback_title,
        (response.author or "").strip() or fallback_author,
        response.needsReview
        or bool(
            identity
            and identity.needs_review
            and not confirmed
            and not (response.title or response.author)
        ),
        response.reason.strip(),
    )
    return MetadataMatch(
        final_identity,
        response.primaryCandidateId,
        tuple(
            dict.fromkeys(
                key
                for key in response.relatedCandidateIds
                if key != response.primaryCandidateId
            )
        ),
    )
