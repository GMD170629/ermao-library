"""Evidence-based identity decisions; ranking never grants write permission."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, replace
from difflib import SequenceMatcher
from typing import Literal

MatchLevel = Literal["SERIES", "WORK", "VOLUME", "EDITION", "UNKNOWN"]
MatchOutcome = Literal["MATCHED", "AMBIGUOUS", "REJECTED", "NO_MATCH"]


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        c
        for c in text
        if not c.isspace() and not unicodedata.category(c).startswith("P")
    )


def normalize_isbn(value: str) -> str | None:
    """Validate an ISBN and compare valid ISBN-10 using its ISBN-13 equivalent."""
    isbn = re.sub(r"[\s\-‐‑–]", "", unicodedata.normalize("NFKC", value)).upper()
    if re.fullmatch(r"[0-9]{9}[0-9X]", isbn):
        digits = [int(c) if c != "X" else 10 for c in isbn]
        if sum((10 - i) * n for i, n in enumerate(digits)) % 11:
            return None
        stem = "978" + isbn[:9]
        return stem + str(
            (-sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(stem))) % 10
        )
    if (
        re.fullmatch(r"97[89][0-9]{10}", isbn)
        and sum(int(n) * (1 if i % 2 == 0 else 3) for i, n in enumerate(isbn)) % 10 == 0
    ):
        return isbn
    return None


def _volume_number(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).strip().casefold()
    if re.fullmatch(r"[0-9]+\.0+", value):
        value = value.split(".", 1)[0]
    if value.isdecimal():
        return str(int(value))
    numbers = {
        "零": 0,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
    }
    if re.fullmatch(r"[一二两三四五六七八九]?十[一二三四五六七八九]?", value):
        left, right = value.split("十", 1)
        return str((numbers.get(left, 1) if left else 1) * 10 + numbers.get(right, 0))
    return str(numbers[value]) if value in numbers else value


def title_parts(title: str) -> tuple[str, str | None]:
    text = unicodedata.normalize("NFKC", title).casefold()
    match = re.search(
        r"(?:第\s*([0-9零一二两三四五六七八九十]+)\s*[卷册集]|\bvol(?:ume)?\.?\s*([0-9]+)\b|([上下中])册)",
        text,
    )
    if match is None:
        return normalize_text(text), None
    volume = next(part for part in match.groups() if part)
    return normalize_text(text[: match.start()] + text[match.end() :]), _volume_number(
        volume
    )


@dataclass(frozen=True)
class Contributor:
    name: str
    role: str = "author"


@dataclass(frozen=True)
class IdentityEvidence:
    title: str
    authors: tuple[Contributor, ...] = ()
    aliases: tuple[str, ...] = ()
    isbn: str | None = None
    isbn_scope: Literal["EDITION", "SET", "UNKNOWN"] = "UNKNOWN"
    volume: str | None = None
    publisher: str | None = None
    language: str | None = None
    edition: str | None = None
    source_ids: tuple[tuple[str, str], ...] = ()
    # Only populated when the index is known to describe a publication volume.
    resource_volume: str | None = None
    work_title: str | None = None


@dataclass(frozen=True)
class RecognitionContext:
    target_type: Literal["book", "resource"]
    target_id: str
    book_id: str
    library_id: str
    identity: IdentityEvidence
    resource_id: str | None = None
    revision: str = ""
    related_revision: str = ""
    parent_title: str | None = None
    aggregate: bool = False
    values: tuple[tuple[str, object], ...] = ()
    protected: frozenset[str] = frozenset()
    provenance: tuple[tuple[str, str], ...] = ()
    allowed_fields: frozenset[str] = frozenset()
    execution: Literal["MANUAL", "AUTOMATIC"] = "MANUAL"
    config_revision: str = ""


def recognition_fingerprint(context: RecognitionContext) -> str:
    return hashlib.sha256(repr((context.target_type, context.target_id,
                               context.revision, context.related_revision,
                               context.config_revision)).encode()).hexdigest()


@dataclass(frozen=True)
class CandidateEvidence:
    provider_id: str
    item_id: str
    identity: IdentityEvidence
    level: MatchLevel = "UNKNOWN"

    @property
    def key(self) -> str:
        # Length prefix avoids collisions when plugin IDs contain punctuation.
        return f"{len(self.provider_id)}:{self.provider_id}:{self.item_id}"


@dataclass(frozen=True)
class MatchDecision:
    outcome: MatchOutcome
    candidate_key: str
    level: MatchLevel
    evidence_ids: tuple[str, ...]
    reasons: tuple[str, ...]
    allowed_fields: frozenset[str] = frozenset()


def _authors(identity: IdentityEvidence) -> dict[str, frozenset[str]]:
    roles: dict[str, set[str]] = {}
    for person in identity.authors:
        # Legacy author fields join lists with these explicit separators.
        # Keep commas intact: they can also separate a person's family name.
        for value in re.split(r"[/、;；]", person.name):
            name = normalize_text(value)
            if name and name not in {"unknown", "未知", "未知作者", "佚名"}:
                roles.setdefault(person.role, set()).add(name)
    return {role: frozenset(names) for role, names in roles.items()}


def decide_match(
    context: RecognitionContext, candidate: CandidateEvidence
) -> MatchDecision:
    local, remote = context.identity, candidate.identity
    refs: list[str] = []
    reasons: list[str] = []

    def decision(
        outcome: MatchOutcome,
        level: MatchLevel = "UNKNOWN",
        fields: frozenset[str] = frozenset(),
    ) -> MatchDecision:
        return MatchDecision(
            outcome,
            candidate.key,
            level,
            tuple(dict.fromkeys(refs)),
            tuple(dict.fromkeys(reasons)),
            fields,
        )

    if candidate.provider_id == "ai":
        reasons.append("AI_UNVERIFIED")
        return decision("AMBIGUOUS")
    if not candidate.item_id:
        reasons.append("INSUFFICIENT_EVIDENCE")
        return decision("AMBIGUOUS")
    local_authors, remote_authors = _authors(local), _authors(remote)
    if any(
        local_authors[role] != remote_authors[role]
        for role in local_authors.keys() & remote_authors.keys()
    ):
        reasons.append("AUTHOR_CONFLICT")
        refs.extend(("target:author", f"{candidate.key}:author"))
    author_match = bool(
        local_authors.get("author")
        and local_authors.get("author") == remote_authors.get("author")
    )
    local_title, parsed_volume = title_parts(local.title)
    remote_title, remote_parsed_volume = title_parts(remote.title)
    local_volumes: set[str] = set()
    remote_volumes: set[str] = set()
    for identity, parsed, prefix, observed in (
        (local, parsed_volume, "target", local_volumes),
        (remote, remote_parsed_volume, candidate.key, remote_volumes),
    ):
        for field, value in (
            ("title_volume", parsed),
            ("volume", identity.volume),
            ("resource_index", identity.resource_volume),
        ):
            if value and value.strip():
                observed.add(_volume_number(value))
                refs.append(f"{prefix}:{field}")
        if len(observed) > 1:
            reasons.append("VOLUME_CONFLICT")
    if local_volumes and remote_volumes and local_volumes != remote_volumes:
        reasons.append("VOLUME_CONFLICT")
        refs.extend(("target:volume", f"{candidate.key}:volume"))
    volume, other_volume = bool(local_volumes), bool(remote_volumes)
    # Edition and sequel markers are not removed by title normalization.
    edition_words = r"修订版|修訂版|增订版|增訂版|纪念版|紀念版|新版|revised|unabridged|abridged|续作|续篇|续集|前传|后传|sequel"
    markers = set(
        re.findall(edition_words, unicodedata.normalize("NFKC", local.title).casefold())
    )
    other_markers = set(
        re.findall(
            edition_words, unicodedata.normalize("NFKC", remote.title).casefold()
        )
    )
    if markers != other_markers and (markers or other_markers):
        reasons.append("EDITION_CONFLICT")
        refs.extend(("target:title", f"{candidate.key}:title"))
    for field in ("publisher", "language", "edition"):
        left, right = getattr(local, field), getattr(remote, field)
        if left and right and normalize_text(left) != normalize_text(right):
            reasons.append("EDITION_CONFLICT")
            refs.extend((f"target:{field}", f"{candidate.key}:{field}"))
    isbn, other_isbn = (
        normalize_isbn(local.isbn or ""),
        normalize_isbn(remote.isbn or ""),
    )
    isbn_match = bool(
        isbn
        and isbn == other_isbn
        and local.isbn_scope == remote.isbn_scope == "EDITION"
        and not re.search(
            r"套装|套裝|全套|全\s*[0-9一二三四五六七八九十]+\s*册",
            local.title + remote.title,
        )
    )
    if isbn and other_isbn and isbn != other_isbn:
        reasons.append("EDITION_CONFLICT")
        refs.extend(("target:isbn", f"{candidate.key}:isbn"))
    identifier_match = (candidate.provider_id, candidate.item_id) in local.source_ids
    if isbn_match:
        refs.extend(("target:isbn", f"{candidate.key}:isbn"))
    if identifier_match:
        refs.extend(("target:source_id", f"{candidate.key}:id"))
    titles = {
        title_parts(value)[0]
        for value in (local.title, *local.aliases)
        if value.strip()
    }
    # A confirmed parent supplies work identity only for a pure volume label.
    # Keep the child's title and volume observations intact.
    if not local_title and parsed_volume and local.work_title:
        parent_core, parent_volume = title_parts(local.work_title)
        if parent_core and parent_volume is None:
            titles.add(parent_core)
            local_title = parent_core
            refs.append("target:parent_work_title")
    candidate_titles = {
        title_parts(value)[0]
        for value in (remote.title, *remote.aliases)
        if value.strip()
    }
    title_match = bool((titles & candidate_titles) - {""})
    if title_match:
        refs.extend(("target:title", f"{candidate.key}:title"))
    elif (isbn_match or identifier_match) and local_title and remote_title:
        reasons.append("TITLE_CONFLICT")
    if author_match:
        refs.extend(("target:author", f"{candidate.key}:author"))
    if reasons:
        return decision("REJECTED")
    if (local.isbn and not isbn) or (remote.isbn and not other_isbn):
        reasons.append("INVALID_ISBN")
    if bool(volume) != bool(other_volume):
        reasons.append("UNKNOWN_SCOPE")
        return decision("AMBIGUOUS")
    if context.aggregate and candidate.level != "SERIES":
        reasons.append("UNKNOWN_SCOPE")
        return decision("AMBIGUOUS")
    if candidate.level == "SERIES" and (context.target_type == "resource" or volume):
        reasons.append("UNKNOWN_SCOPE")
        return decision("AMBIGUOUS")
    if not (isbn_match or identifier_match or (title_match and author_match)):
        reasons.append("INSUFFICIENT_EVIDENCE")
        return decision("AMBIGUOUS" if title_match or (volume and not local_title) else "NO_MATCH")
    level: MatchLevel = "EDITION" if isbn_match else "VOLUME" if volume else "WORK"
    if identifier_match and candidate.level != "UNKNOWN":
        level = candidate.level
    if context.aggregate:
        level = "SERIES"
    reasons.append(
        "IDENTIFIER_MATCH" if isbn_match or identifier_match else "TITLE_AUTHOR_MATCH"
    )
    prefix = context.target_type + "."
    # Unknown source scope grants only identity fields, never cover/description.
    names = (
        {"title", "author"}
        if context.target_type == "book"
        else {"title"}
        if level in {"VOLUME", "EDITION"}
        else set()
    )
    if candidate.level == level and names:
        names |= {"description", "cover_ref"}
    if context.target_type == "resource" and level == "EDITION":
        names |= {"isbn", "publisher", "language", "published_at"}
    if context.target_type == "resource" and level in {"VOLUME", "EDITION"}:
        names.add("resource_index")
    fields = frozenset(prefix + name for name in names) & context.allowed_fields
    fields = frozenset(
        field for field in fields if field.removeprefix(prefix) not in context.protected
    )
    return decision("MATCHED", level, fields)


def rank_matches(
    context: RecognitionContext, candidates: tuple[CandidateEvidence, ...]
) -> tuple[MatchDecision, ...]:
    unique: dict[str, CandidateEvidence] = {}
    conflicting: set[str] = set()
    for candidate in candidates:
        if candidate.key in unique and unique[candidate.key] != candidate:
            conflicting.add(candidate.key)
        unique.setdefault(candidate.key, candidate)
    decisions = [decide_match(context, candidate) for candidate in unique.values()]
    decisions = [
        replace(
            item,
            outcome="AMBIGUOUS",
            reasons=("INSUFFICIENT_EVIDENCE",),
            allowed_fields=frozenset(),
        )
        if item.candidate_key in conflicting
        else item
        for item in decisions
    ]
    if sum(item.outcome == "MATCHED" for item in decisions) > 1:
        decisions = [
            replace(
                item,
                outcome="AMBIGUOUS",
                reasons=(*item.reasons, "MULTIPLE_MATCHES"),
                allowed_fields=frozenset(),
            )
            if item.outcome == "MATCHED"
            else item
            for item in decisions
        ]
    order = {"MATCHED": 0, "AMBIGUOUS": 1, "NO_MATCH": 2, "REJECTED": 3}
    return tuple(
        sorted(
            decisions,
            key=lambda item: (
                order[item.outcome],
                -SequenceMatcher(
                    None,
                    normalize_text(context.identity.title),
                    normalize_text(unique[item.candidate_key].identity.title),
                ).ratio(),
            ),
        )
    )



def confirm_candidate(context: RecognitionContext, candidate: CandidateEvidence) -> MatchDecision:
    """An explicit human selection confirms a source ID, never hides conflicts."""
    if candidate.provider_id == "ai" or candidate.identity.isbn_scope == "SET" and context.target_type == "resource":
        return decide_match(context, candidate)
    identity = replace(context.identity, source_ids=(*context.identity.source_ids, (candidate.provider_id, candidate.item_id)))
    return decide_match(replace(context, identity=identity), candidate)
