"""Presentation-safe access to existing Library view projections."""

from app.bootstrap.library import (
    book_view,
    bookshelf_book_list_view,
    bookshelf_item_view,
    bookshelf_item_views,
    get_book,
    list_resource_views,
    management_book_list_view,
    preferred_book_cover_path,
    resource_view,
)

__all__ = [
    "book_view",
    "bookshelf_book_list_view",
    "bookshelf_item_view",
    "bookshelf_item_views",
    "get_book",
    "list_resource_views",
    "management_book_list_view",
    "preferred_book_cover_path",
    "resource_view",
]
