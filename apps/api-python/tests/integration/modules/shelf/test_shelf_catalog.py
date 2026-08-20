from sqlalchemy.orm import Session

from app.core.authorization import authorization_context
from app.models.auth import User
from app.models.library import (
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
)
from app.models.shelf import Shelf, ShelfWork
from app.modules.shelf.application.catalog import (
    ListCatalogShelfWorkIds,
    ListCatalogShelves,
)
from app.modules.shelf.infrastructure.catalog import SqlAlchemyCatalogShelfQueries


def test_catalog_shelves_are_owned_static_and_authorized(db_session: Session) -> None:
    owner = User(
        id="shelf-owner",
        email="shelf-owner@example.com",
        name="Shelf Owner",
        password_hash="unused",
        role="admin",
    )
    other = User(
        id="shelf-other",
        email="shelf-other@example.com",
        name="Shelf Other",
        password_hash="unused",
        role="admin",
    )
    visible = LibraryWork(
            library_id="test-library", 
        id="visible-work",
        title="Visible",
        normalized_title="visible",
        author="Author",
        normalized_author="author",
        tags="[]",
    )
    hidden = LibraryWork(
            library_id="test-library", 
        id="hidden-work",
        title="Hidden",
        normalized_title="hidden",
        author="Author",
        normalized_author="author",
        tags="[]",
        hidden=True,
    )
    owned = Shelf(
        id="owned-static",
        owner_user_id=owner.id,
        name="Owned",
        kind="STATIC",
    )
    smart = Shelf(id="owned-smart", owner_user_id=owner.id, name="Smart", kind="SMART")
    foreign = Shelf(
        id="foreign-static",
        owner_user_id=other.id,
        name="Foreign",
        kind="STATIC",
    )
    db_session.add_all([owner, other, visible, hidden, owned, smart, foreign])
    db_session.flush()
    media = LibraryMediaVersion(
        id="shelf-media", work_id=visible.id, media_kind="EBOOK"
    )
    volume = LibraryVolume(
        id="shelf-volume",
        version_id=media.id,
        title="Shelf Volume",
        format="EPUB",
        resource_key="shelf:volume",
        import_status="COMPLETED",
    )
    db_session.add_all(
        [
            media,
            volume,
            LibraryFile(
                id="shelf-file",
                volume_id=volume.id,
                path="books/shelf.epub",
                kind="BOOK",
                mime_type="application/epub+zip",
                size_bytes=1,
            ),
            ShelfWork(shelf_id=owned.id, work_id=visible.id),
            ShelfWork(shelf_id=owned.id, work_id=hidden.id),
        ]
    )
    db_session.commit()

    context = authorization_context(db_session, owner)
    queries = SqlAlchemyCatalogShelfQueries(
        db_session,
        smart_work_ids=lambda _rules, _user_id: [visible.id],
    )
    shelves = ListCatalogShelves(queries).execute(context=context)
    works = ListCatalogShelfWorkIds(queries).execute(context=context, shelf_id=owned.id)

    assert {shelf.id for shelf in shelves.shelves} == {owned.id, smart.id}
    assert works is not None
    assert works.work_ids == (visible.id,)
    smart_works = ListCatalogShelfWorkIds(queries).execute(
        context=context, shelf_id=smart.id
    )
    assert smart_works is not None
    assert smart_works.work_ids == (visible.id,)
    assert (
        ListCatalogShelfWorkIds(queries).execute(context=context, shelf_id=foreign.id)
        is None
    )
