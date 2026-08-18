from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from app.bootstrap.library import (
    execute_work_facet_write,
    load_work_facet_projections,
    prepare_work_facet_write,
)
from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.public import prepare_work_facet
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from tests.support.sqlalchemy import StatementRecorder


def test_prepared_facet_sync_uses_existing_real_ids_and_preserves_updated_at(
    db_session: Session,
) -> None:
    original_updated_at = datetime(2026, 8, 11, 8, 0, tzinfo=UTC)
    db_session.add(
        LibraryWork(
            library_id="test-library", 
            id="prepared-facet-work",
            title="Prepared facets",
            normalized_title="preparedfacets",
            author="Old author",
            normalized_author="oldauthor",
            tags="[]",
            updated_at=original_updated_at,
        )
    )
    db_session.add(
        LibraryFacet(
            id="arbitrary-existing-author-id",
            kind="AUTHOR",
            name="Existing display author",
            normalized_name="newauthor",
            aliases='["kept"]',
        )
    )
    db_session.commit()

    projection = load_work_facet_projections(db_session, ("prepared-facet-work",))[0]
    db_session.rollback()
    prepared_work = prepare_work_facet(
        replace(
            projection,
            author="New author",
            tags_source='["Tag A", "Tag A"]',
            series_name="Series A",
        )
    )
    prepared_write = prepare_work_facet_write(
        (prepared_work,), now=datetime(2026, 8, 11, 8, 1, tzinfo=UTC)
    )

    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    with StatementRecorder(engine) as recorder:
        recorder.reset_after_warmup()
        db_session.execute(
            update(LibraryWork)
            .where(LibraryWork.id == "prepared-facet-work")
            .values(
                author="New author",
                tags='["Tag A", "Tag A"]',
                series_name="Series A",
                updated_at=LibraryWork.updated_at,
            )
        )
        execute_work_facet_write(db_session, prepared_write)
        db_session.commit()

    links = db_session.execute(
        select(LibraryFacet.kind, LibraryFacet.id)
        .join(LibraryWorkFacet, LibraryWorkFacet.facet_id == LibraryFacet.id)
        .where(LibraryWorkFacet.work_id == "prepared-facet-work")
    ).all()
    assert dict(links)["AUTHOR"] == "arbitrary-existing-author-id"
    assert {kind for kind, _facet_id in links} == {"AUTHOR", "TAG", "SERIES"}
    work = db_session.get(LibraryWork, "prepared-facet-work")
    assert work is not None
    assert work.updated_at == original_updated_at
    assert recorder.statement_count <= 6
