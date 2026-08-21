import pytest

from app.modules.shelf.domain.errors import ShelfCollectionPolicyError
from app.modules.shelf.domain.policies import (
    ShelfKind,
    validate_collection_members,
    validate_shelf_content,
)


def test_collection_rejects_books_and_smart_rules() -> None:
    with pytest.raises(
        ShelfCollectionPolicyError,
        match="COLLECTION_CANNOT_CONTAIN_BOOKS",
    ):
        validate_shelf_content(
            kind=ShelfKind.COLLECTION,
            book_ids=("book-1",),
            has_smart_rules=False,
        )

    with pytest.raises(
        ShelfCollectionPolicyError,
        match="COLLECTION_CANNOT_HAVE_RULES",
    ):
        validate_shelf_content(
            kind=ShelfKind.COLLECTION,
            book_ids=(),
            has_smart_rules=True,
        )


def test_collection_rejects_nested_and_cross_owner_members() -> None:
    with pytest.raises(
        ShelfCollectionPolicyError,
        match="INVALID_COLLECTION_MEMBER",
    ):
        validate_collection_members(
            collection_owner_id="owner-1",
            members=(
                ("shelf-1", ShelfKind.STATIC, "owner-1"),
                ("collection-2", ShelfKind.COLLECTION, "owner-1"),
            ),
        )

    with pytest.raises(
        ShelfCollectionPolicyError,
        match="INVALID_COLLECTION_MEMBER",
    ):
        validate_collection_members(
            collection_owner_id="owner-1",
            members=(("shelf-2", ShelfKind.SMART, "owner-2"),),
        )


def test_regular_and_smart_shelves_are_valid_collection_members() -> None:
    validate_collection_members(
        collection_owner_id="owner-1",
        members=(
            ("shelf-1", ShelfKind.STATIC, "owner-1"),
            ("shelf-2", ShelfKind.SMART, "owner-1"),
        ),
    )
