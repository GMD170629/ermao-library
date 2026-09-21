import hashlib
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import (
    Library,
    LibraryBook,
    LibrarySourceNode,
    LibrarySourceNodeMetadata,
)
from app.models.organize import MetadataWritebackPreparation, OrganizePolicy
from app.modules.library.application.metadata_effects import MetadataSideEffectPolicy
from app.modules.library.application.source_node_commands import (
    SourceNodeMetadataChanges,
    UpdateSourceNodeMetadata,
)
from app.modules.library.infrastructure.source_node_commands import (
    SqlAlchemySourceNodeMetadata,
)


def test_database_only_node_edit_does_not_schedule_files_with_auto_writeback_on(
    db_session, tmp_path
):
    root = tmp_path / "library"
    source = root / "book"
    source.mkdir(parents=True)
    original = source / "page.png"
    original.write_bytes(b"original")
    library = db_session.get(Library, "test-library")
    library.root_path = str(root)
    db_session.add(OrganizePolicy(id="default", write_metadata_to_files=True))
    db_session.add(
        LibrarySourceNode(
            id="node",
            library_id="test-library",
            relative_path="book",
            path_key="v1:" + hashlib.sha256(b"book").hexdigest(),
            name="book",
            physical_kind="DIRECTORY",
            observed_mtime_ns=0,
            observed_at=datetime.now(UTC),
        )
    )
    db_session.flush()
    db_session.add(
        LibraryBook(id="book", library_id="test-library", source_node_id="node")
    )
    db_session.commit()
    use_case = UpdateSourceNodeMetadata(
        SqlAlchemySourceNodeMetadata(db_session),
        db_session,
        side_effect_policy=MetadataSideEffectPolicy.DATABASE_ONLY,
    )
    assert use_case.execute(
        book_id="book",
        source_node_id="node",
        changes=SourceNodeMetadataChanges(
            title="新标题",
            description="新简介",
        ),
    )
    assert db_session.get(LibrarySourceNodeMetadata, "node").title == "新标题"
    assert list(db_session.scalars(select(MetadataWritebackPreparation))) == []
    assert list(source.iterdir()) == [original]
    assert original.read_bytes() == b"original"

    # The existing Web policy still enqueues exactly one configured writeback.
    assert UpdateSourceNodeMetadata(
        SqlAlchemySourceNodeMetadata(db_session), db_session
    ).execute(
        book_id="book",
        source_node_id="node",
        changes=SourceNodeMetadataChanges(title="Web 标题", description=None),
    )
    assert len(list(db_session.scalars(select(MetadataWritebackPreparation)))) == 1
