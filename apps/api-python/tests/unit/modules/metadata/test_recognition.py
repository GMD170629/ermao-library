"""M1 identity decisions: a search hit is evidence, not write permission."""

from dataclasses import replace
from typing import Literal

import pytest

from app.modules.metadata.application.recognition import (
    assess_candidates,
    candidate_evidence,
)
from app.modules.metadata.domain.recognition import (
    CandidateEvidence,
    Contributor,
    IdentityEvidence,
    MatchLevel,
    RecognitionContext,
    decide_match,
    normalize_isbn,
    rank_matches,
    title_parts,
)

BOOK_FIELDS = frozenset(
    {"book.title", "book.author", "book.description", "book.cover_ref"}
)
RESOURCE_FIELDS = frozenset(
    {
        "resource.title",
        "resource.description",
        "resource.cover_ref",
        "resource.isbn",
        "resource.publisher",
        "resource.language",
    }
)


def context(
    title: str = "三体",
    author: str | None = "刘慈欣",
    *,
    target_type: Literal["book", "resource"] = "book",
    authors: tuple[Contributor, ...] | None = None,
    aliases: tuple[str, ...] = (),
    isbn: str | None = None,
    isbn_scope: Literal["EDITION", "SET", "UNKNOWN"] = "UNKNOWN",
    source_ids: tuple[tuple[str, str], ...] = (),
) -> RecognitionContext:
    people = (
        authors if authors is not None else (Contributor(author),) if author else ()
    )
    return RecognitionContext(
        target_type=target_type,
        target_id="resource-1" if target_type == "resource" else "book-1",
        book_id="book-1",
        resource_id="resource-1" if target_type == "resource" else None,
        library_id="library-1",
        identity=IdentityEvidence(
            title,
            people,
            aliases=aliases,
            isbn=isbn,
            isbn_scope=isbn_scope,
            source_ids=source_ids,
        ),
        allowed_fields=RESOURCE_FIELDS if target_type == "resource" else BOOK_FIELDS,
    )


def candidate(
    title: str = "三体",
    author: str | None = "刘慈欣",
    *,
    level: MatchLevel = "WORK",
    provider_id: str = "douban",
    item_id: str = "item-1",
    authors: tuple[Contributor, ...] | None = None,
    aliases: tuple[str, ...] = (),
    isbn: str | None = None,
    isbn_scope: Literal["EDITION", "SET", "UNKNOWN"] = "UNKNOWN",
) -> CandidateEvidence:
    people = (
        authors if authors is not None else (Contributor(author),) if author else ()
    )
    return CandidateEvidence(
        provider_id,
        item_id,
        IdentityEvidence(
            title, people, aliases=aliases, isbn=isbn, isbn_scope=isbn_scope
        ),
        level,
    )


def test_only_same_title_candidate_with_conflicting_known_author_is_rejected() -> None:
    decisions = rank_matches(context(), (candidate(author="另一作者"),))
    assert len(decisions) == 1
    assert decisions[0].outcome == "REJECTED"
    assert "AUTHOR_CONFLICT" in decisions[0].reasons
    assert "target:author" in decisions[0].evidence_ids
    assert any(
        reference.endswith(":author") and reference != "target:author"
        for reference in decisions[0].evidence_ids
    )
    assert not decisions[0].allowed_fields


def test_unknown_author_is_neither_conflict_nor_positive_evidence() -> None:
    for remote_author in (None, "未知作者"):
        decision = decide_match(context(), candidate(author=remote_author))
        assert decision.outcome == "AMBIGUOUS"
        assert "AUTHOR_CONFLICT" not in decision.reasons
        assert not decision.allowed_fields


def test_work_match_cannot_grant_edition_fields() -> None:
    decision = decide_match(context(target_type="resource"), candidate(level="WORK"))
    assert decision.outcome == "MATCHED"
    assert decision.level == "WORK"
    assert "resource.isbn" not in decision.allowed_fields
    assert "resource.publisher" not in decision.allowed_fields
    assert "resource.language" not in decision.allowed_fields


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0-306-40615-2", "9780306406157"),
        ("978-0-306-40615-7", "9780306406157"),
        ("979-10-90636-07-1", "9791090636071"),
        ("0-306-40615-3", None),
        ("978-0-306-40615-8", None),
        ("979-10-90636-07-2", None),
    ],
)
def test_isbn_check_digits_and_ten_to_thirteen_equivalence(
    raw: str, expected: str | None
) -> None:
    assert normalize_isbn(raw) == expected


def test_valid_edition_isbn_confirms_equivalent_ten_and_thirteen() -> None:
    local = context(target_type="resource", isbn="0-306-40615-2", isbn_scope="EDITION")
    remote = candidate(level="EDITION", isbn="978-0-306-40615-7", isbn_scope="EDITION")
    decision = decide_match(local, remote)
    assert decision.outcome == "MATCHED"
    assert decision.level == "EDITION"
    assert "resource.isbn" in decision.allowed_fields
    assert "target:isbn" in decision.evidence_ids


def test_invalid_or_set_isbn_does_not_confirm_an_edition() -> None:
    for local_isbn, scope in (
        ("978-0-306-40615-8", "EDITION"),
        ("978-0-306-40615-7", "SET"),
    ):
        decision = decide_match(
            context(
                target_type="resource",
                author=None,
                isbn=local_isbn,
                isbn_scope=scope,
            ),
            candidate(
                author=None,
                level="EDITION",
                isbn="978-0-306-40615-7",
                isbn_scope="EDITION",
            ),
        )
        assert decision.outcome != "MATCHED"
        assert "resource.isbn" not in decision.allowed_fields


def test_strong_identifier_cannot_override_known_author_or_isbn_conflict() -> None:
    local = context(
        target_type="resource",
        isbn="9780306406157",
        isbn_scope="EDITION",
        source_ids=(("douban", "item-1"),),
    )
    for remote in (
        candidate(
            author="另一作者",
            level="EDITION",
            isbn="9780306406157",
            isbn_scope="EDITION",
        ),
        candidate(level="EDITION", isbn="9791090636071", isbn_scope="EDITION"),
    ):
        decision = decide_match(local, remote)
        assert decision.outcome == "REJECTED"
        assert not decision.allowed_fields


def test_source_id_with_known_author_conflict_is_rejected_without_isbn() -> None:
    decision = decide_match(
        context(source_ids=(("douban", "item-1"),)),
        candidate(author="另一作者"),
    )
    assert decision.outcome == "REJECTED"
    assert "AUTHOR_CONFLICT" in decision.reasons
    assert not decision.allowed_fields


def test_equal_isbn_cannot_override_original_work_vs_sequel_conflict() -> None:
    decision = decide_match(
        context(
            "三体",
            target_type="resource",
            isbn="9780306406157",
            isbn_scope="EDITION",
        ),
        candidate(
            "三体 续作",
            level="EDITION",
            isbn="9780306406157",
            isbn_scope="EDITION",
        ),
    )
    assert decision.outcome == "REJECTED"
    assert "TITLE_CONFLICT" in decision.reasons
    assert not decision.allowed_fields


def test_alias_cannot_hide_primary_title_volume_conflict() -> None:
    decision = decide_match(
        context("三体 第2卷"),
        candidate("三体 第1卷", aliases=("三体 第2卷",)),
    )
    assert decision.outcome == "REJECTED"
    assert "VOLUME_CONFLICT" in decision.reasons
    assert not decision.allowed_fields


@pytest.mark.parametrize(
    "local,remote,expected",
    [
        ("三体 第2卷", "三体 第二卷", "MATCHED"),
        ("三体 第2卷", "三体 第1卷", "REJECTED"),
        ("三体 上册", "三体 下册", "REJECTED"),
        ("三体", "三体 续作", "REJECTED"),
    ],
)
def test_volume_and_sequel_identity_are_preserved(
    local: str, remote: str, expected: str
) -> None:
    decision = decide_match(context(local), candidate(remote))
    assert decision.outcome == expected
    if expected == "REJECTED" and "册" in local:
        assert "VOLUME_CONFLICT" in decision.reasons


def test_documented_alias_can_confirm_work_with_author() -> None:
    decision = decide_match(context("地球往事", aliases=("三体",)), candidate())
    assert decision.outcome == "MATCHED"
    assert decision.level == "WORK"
    assert "target:title" in decision.evidence_ids


def test_contributor_roles_are_compared_only_when_comparable() -> None:
    local = context(
        authors=(Contributor("甲", "author"), Contributor("译甲", "translator"))
    )
    different_translator = candidate(
        authors=(Contributor("甲", "author"), Contributor("译乙", "translator"))
    )
    decision = decide_match(local, different_translator)
    assert decision.outcome == "REJECTED"
    assert "AUTHOR_CONFLICT" in decision.reasons
    unrelated_role = candidate(
        authors=(Contributor("甲", "author"), Contributor("乙", "editor"))
    )
    assert decide_match(local, unrelated_role).outcome == "MATCHED"


def test_multiple_independent_matches_remain_ambiguous() -> None:
    decisions = rank_matches(
        context(), (candidate(item_id="one"), candidate(item_id="two"))
    )
    assert len(decisions) == 2
    assert all(decision.outcome == "AMBIGUOUS" for decision in decisions)
    assert all("MULTIPLE_MATCHES" in decision.reasons for decision in decisions)
    assert all(not decision.allowed_fields for decision in decisions)


def test_same_provider_and_item_are_deduplicated_or_marked_conflicting() -> None:
    same = candidate()
    assert len(rank_matches(context(), (same, same))) == 1
    conflicting = rank_matches(context(), (same, candidate(author="另一作者")))
    assert len(conflicting) == 1
    assert conflicting[0].outcome == "AMBIGUOUS"
    assert not conflicting[0].allowed_fields


def test_ai_candidate_cannot_validate_its_own_claims() -> None:
    decision = decide_match(
        context(source_ids=(("ai", "claimed-id"),)),
        candidate(provider_id="ai", item_id="claimed-id"),
    )
    assert decision.outcome == "AMBIGUOUS"
    assert "AI_UNVERIFIED" in decision.reasons
    assert not decision.allowed_fields


def test_series_cannot_supply_a_resource_or_volume_cover() -> None:
    for target in (context(target_type="resource"), context("三体 第2卷")):
        decision = decide_match(target, candidate(level="SERIES"))
        assert decision.outcome != "MATCHED"
        assert not decision.allowed_fields


def test_aggregate_book_requires_series_scope_and_respects_protection() -> None:
    aggregate = replace(context(), aggregate=True, protected=frozenset({"author"}))
    assert decide_match(aggregate, candidate(level="WORK")).outcome == "AMBIGUOUS"
    series = decide_match(aggregate, candidate(level="SERIES"))
    assert series.outcome == "MATCHED"
    assert series.level == "SERIES"
    assert "book.author" not in series.allowed_fields


def test_application_maps_aliases_and_uses_same_decision() -> None:
    result = assess_candidates(
        context("地球往事"),
        "douban",
        [{"id": "one", "title": "三体", "author": "刘慈欣", "aliases": ["地球往事"]}],
    )
    assert len(result) == 1
    payload, decision = result[0]
    assert payload["id"] == "one"
    assert decision.outcome == "MATCHED"
    assert candidate_evidence("douban", payload).key == decision.candidate_key


def test_title_parser_retains_volume_identity_and_original_value() -> None:
    source = "三体 第二卷"
    assert title_parts(source) == ("三体", "2")
    assert source == "三体 第二卷"


def test_volume_label_without_work_identity_is_not_enough() -> None:
    assert decide_match(context("第一卷"), candidate("第一卷")).outcome != "MATCHED"


def test_joined_author_list_is_not_one_concatenated_name() -> None:
    assert (
        decide_match(
            context(author="甲 / 乙"),
            candidate(authors=(Contributor("乙"), Contributor("甲"))),
        ).outcome
        == "MATCHED"
    )
    assert (
        decide_match(context(author="甲 / 乙"), candidate(author="甲乙")).outcome
        == "REJECTED"
    )


def test_set_title_is_not_edition_evidence_even_with_equal_isbn() -> None:
    decision = decide_match(
        context(
            "三体套装",
            target_type="resource",
            isbn="9780306406157",
            isbn_scope="EDITION",
        ),
        candidate("三体套装", isbn="9780306406157", isbn_scope="EDITION"),
    )
    assert decision.level != "EDITION"
    assert "resource.isbn" not in decision.allowed_fields


@pytest.mark.parametrize("target_type", ["book", "resource"])
@pytest.mark.parametrize("same_isbn", [False, True])
def test_structured_volume_cannot_hide_title_conflict(target_type, same_isbn) -> None:
    local = context("示例书 第1卷", target_type=target_type)
    remote = candidate_evidence("douban", {
        "id": "one", "title": "示例书 第2卷", "volume": "1", "author": "刘慈欣",
        "isbn": "9780306406157" if same_isbn else None, "isbnScope": "EDITION",
    })
    if same_isbn:
        local = replace(local, identity=replace(local.identity, isbn="0306406152", isbn_scope="EDITION"))
    result = decide_match(local, remote)
    assert result.outcome == "REJECTED"
    assert "VOLUME_CONFLICT" in result.reasons
    assert not result.allowed_fields


@pytest.mark.parametrize("structured,expected", [("2", "REJECTED"), ("01", "MATCHED"), ("一", "MATCHED")])
def test_local_volume_evidence_is_checked_independently(structured, expected) -> None:
    local = context("示例书 第1卷")
    local = replace(local, identity=replace(local.identity, volume=structured))
    result = decide_match(local, candidate("示例书 第2卷" if structured == "2" else "示例书 第1卷"))
    assert result.outcome == expected
    if expected == "REJECTED":
        assert not result.allowed_fields


@pytest.mark.parametrize("scope", [None, "UNKNOWN", "SET", "EDITION"])
def test_provider_isbn_scope_requires_explicit_evidence(scope) -> None:
    payload = {"id": "one", "title": "三体", "author": "刘慈欣", "isbn": "9780306406157"}
    if scope is not None:
        payload["isbnScope"] = scope
    remote = candidate_evidence("douban", payload)
    assert remote.identity.isbn_scope == (scope or "UNKNOWN")
    result = decide_match(context(target_type="resource", isbn="0306406152", isbn_scope="EDITION"), remote)
    assert result.outcome == "MATCHED"
    assert ("resource.isbn" in result.allowed_fields) == (scope == "EDITION")


def test_set_scope_cannot_supply_edition_fields_for_a_volume() -> None:
    local = context("示例书 第1卷", target_type="resource", isbn="0306406152", isbn_scope="EDITION")
    remote = candidate_evidence("douban", {
        "id": "one", "title": "示例书 第1卷", "author": "刘慈欣",
        "isbn": "9780306406157", "isbnScope": "SET", "matchLevel": "EDITION",
    })
    result = decide_match(local, remote)
    assert result.outcome == "MATCHED"
    assert result.level == "VOLUME"
    assert not (result.allowed_fields & {"resource.isbn", "resource.publisher", "resource.language"})


def test_candidate_resource_index_does_not_override_explicit_volume() -> None:
    remote = candidate_evidence("douban", {
        "id": "one", "title": "示例书 第1卷", "author": "刘慈欣",
        "volume": "01", "resourceIndex": 2, "matchLevel": "VOLUME",
    })
    result = decide_match(context("示例书 第1卷"), remote)
    assert result.outcome == "REJECTED"
    assert f"{remote.key}:volume" in result.evidence_ids
    assert f"{remote.key}:resource_index" in result.evidence_ids
    assert not result.allowed_fields
