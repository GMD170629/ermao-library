"""Match bounded real source records, shared by manual and queued recognition."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.contracts.metadata_identity import MetadataIdentity
from app.core.i18n import configured_locale
from app.modules.imports.public import normalize_identity_part
from app.modules.metadata.infrastructure.ai_client import (
    match_metadata,
    model_configured,
)
from app.modules.metadata.infrastructure.identity_context import identity_clues
from app.services.metadata_provider_registry import metadata_provider_runtime_config
from app.services.organize_service import choose_metadata_candidate


def candidate_key(candidate: Mapping[str, object]) -> str:
    return f"{candidate['source']}:{candidate['id']}"


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
    local_title: str = "",
    local_author: str | None = None,
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
            "query": title[:500],
            "language": locale,
            "localTitle": local_title[:500],
            "localAuthor": (local_author or "")[:500],
            **clues,
            "candidates": [
                {
                    "id": candidate_key(item),
                    "title": str(item.get("title") or "")[:500],
                    "author": str(item.get("author") or "")[:500],
                    "description": str(item.get("description") or "")[:1200],
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
