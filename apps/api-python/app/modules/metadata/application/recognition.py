"""Convert provider payloads once before the shared identity decision."""

from collections.abc import Mapping
from math import isfinite
from typing import Literal, TypedDict, cast

from app.modules.metadata.domain.recognition import (
    CandidateEvidence,
    Contributor,
    IdentityEvidence,
    MatchDecision,
    MatchLevel,
    RecognitionContext,
    rank_matches,
)


class MatchView(TypedDict):
    outcome: str
    candidateKey: str
    level: str
    evidenceIds: list[str]
    reasons: list[str]
    allowedFields: list[str]


def match_view(decision: MatchDecision) -> MatchView:
    return {
        "outcome": decision.outcome,
        "candidateKey": decision.candidate_key,
        "level": decision.level,
        "evidenceIds": list(decision.evidence_ids),
        "reasons": list(decision.reasons),
        "allowedFields": sorted(decision.allowed_fields),
    }


def text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def title_strings(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value.strip(),) if value.strip() else ()
    if isinstance(value, (list, tuple)):
        return tuple(title for item in value for title in title_strings(item))
    if isinstance(value, Mapping):
        return tuple(
            title
            for key in ("v", "value", "title", "name", "name_cn", "alias")
            for title in title_strings(value.get(key))
        )
    return ()


def candidate_titles(candidate: Mapping[str, object]) -> tuple[str, ...]:
    values = [
        *title_strings(candidate.get("title")),
        *title_strings(candidate.get("titleAliases")),
        *title_strings(candidate.get("aliases")),
    ]
    raw_value = candidate.get("raw")
    raw = raw_value if isinstance(raw_value, Mapping) else {}
    for key in (
        "title",
        "name",
        "name_cn",
        "originalTitle",
        "original_title",
        "origin_title",
        "alt_title",
        "aliases",
        "aka",
    ):
        values.extend(title_strings(raw.get(key)))
    entries = raw.get("infobox")
    if isinstance(entries, list):
        for entry in entries:
            if isinstance(entry, Mapping) and any(
                label in text(entry.get("key"))
                for label in (
                    "别名",
                    "又名",
                    "中文名",
                    "简体中文",
                    "繁体中文",
                    "原名",
                    "日文名",
                    "英文名",
                )
            ):
                values.extend(title_strings(entry.get("value")))
    return tuple(dict.fromkeys(values))


def contributors(value: object, fallback: object = None) -> tuple[Contributor, ...]:
    result: list[Contributor] = []
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(Contributor(item.strip()))
            elif isinstance(item, Mapping) and text(item.get("name")):
                result.append(
                    Contributor(
                        text(item.get("name")), text(item.get("role")) or "unknown"
                    )
                )
    if not result and text(fallback):
        # A joined legacy author string is one observation, not guessed roles.
        result.append(Contributor(text(fallback)))
    return tuple(result)


def _volume_value(value: object) -> str | None:
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value) if isfinite(value) else None
    return None


def candidate_evidence(
    provider_id: str, value: Mapping[str, object]
) -> CandidateEvidence:
    scope = text(value.get("matchLevel"))
    level = (
        cast(MatchLevel, scope)
        if scope in ("WORK", "SERIES", "VOLUME", "EDITION")
        else "UNKNOWN"
    )
    isbn_scope: Literal["SET", "EDITION", "UNKNOWN"] = (
        "SET"
        if value.get("isbnScope") == "SET"
        else "EDITION"
        if value.get("isbnScope") == "EDITION"
        else "UNKNOWN"
    )
    return CandidateEvidence(
        provider_id,
        text(value.get("id")),
        IdentityEvidence(
            title=text(value.get("title")),
            authors=contributors(value.get("authors"), value.get("author")),
            aliases=candidate_titles(value),
            isbn=text(value.get("isbn")) or None,
            isbn_scope=isbn_scope,
            volume=_volume_value(value.get("volume")),
            # An unscoped resourceIndex can be an ordering/series position.
            resource_volume=(
                _volume_value(value.get("resourceIndex"))
                if level == "VOLUME"
                else None
            ),
            publisher=text(value.get("publisher")) or None,
            language=text(value.get("language")) or None,
            edition=text(value.get("edition")) or None,
        ),
        level,
    )


def assess_candidates(
    context: RecognitionContext, provider_id: str, candidates: list[dict[str, object]]
) -> list[tuple[dict[str, object], MatchDecision]]:
    evidence = tuple(candidate_evidence(provider_id, item) for item in candidates)
    payloads: dict[str, dict[str, object]] = {}
    for item, identity in zip(candidates, evidence, strict=True):
        payloads.setdefault(identity.key, item)
    return [
        (payloads[decision.candidate_key], decision)
        for decision in rank_matches(context, evidence)
    ]
