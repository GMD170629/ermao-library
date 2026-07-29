from __future__ import annotations

from enum import StrEnum

from app.modules.shelf.domain.errors import ShelfCollectionPolicyError


class ShelfKind(StrEnum):
    STATIC = "STATIC"
    SMART = "SMART"
    COLLECTION = "COLLECTION"

    @classmethod
    def parse(cls, value: object) -> ShelfKind:
        try:
            return cls(str(value or cls.STATIC.value).strip().upper())
        except ValueError as error:
            raise ShelfCollectionPolicyError("INVALID_SHELF_KIND") from error


def validate_shelf_content(
    *,
    kind: ShelfKind,
    work_ids: tuple[str, ...],
    has_smart_rules: bool,
) -> None:
    if kind is not ShelfKind.COLLECTION:
        return
    if work_ids:
        raise ShelfCollectionPolicyError("COLLECTION_CANNOT_CONTAIN_WORKS")
    if has_smart_rules:
        raise ShelfCollectionPolicyError("COLLECTION_CANNOT_HAVE_RULES")


def validate_collection_members(
    *,
    collection_owner_id: str,
    members: tuple[tuple[str, ShelfKind, str | None], ...],
) -> None:
    for _member_id, member_kind, member_owner_id in members:
        if (
            member_kind is ShelfKind.COLLECTION
            or member_owner_id != collection_owner_id
        ):
            raise ShelfCollectionPolicyError("INVALID_COLLECTION_MEMBER")
