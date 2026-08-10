from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.application.facet_index import RebuildFacetIndexBatch
from app.modules.library.infrastructure import facet_index as facet_index_module
from app.modules.library.infrastructure.uow import (
    SqlAlchemyFacetIndexUnitOfWork,
)


def _add_pending_works(db: Session, count: int) -> None:
    db.add_all(
        [
            LibraryWork(
                id=f"facet-work-{index}",
                title=f"Facet work {index}",
                normalized_title=f"facet work {index}",
                author=f"Author {index}",
                normalized_author=f"author {index}",
                tags=f'["Tag {index}"]',
                series_name="Repair series",
            )
            for index in range(count)
        ]
    )
    db.commit()


def _rebuilder(db: Session) -> RebuildFacetIndexBatch:
    factory = sessionmaker(
        bind=db.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    return RebuildFacetIndexBatch(lambda: SqlAlchemyFacetIndexUnitOfWork(factory))


def test_facet_index_repair_commits_bounded_restartable_batches(
    db_session: Session,
) -> None:
    _add_pending_works(db_session, 3)
    rebuild = _rebuilder(db_session)

    first = rebuild.execute(limit=2)
    db_session.expire_all()
    assert first.processed == 2
    assert first.may_have_more is True
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(LibraryWork)
            .where(LibraryWork.facet_index_version == 0)
        )
        == 1
    )

    second = rebuild.execute(limit=2)
    repeated = rebuild.execute(limit=2)
    db_session.expire_all()
    assert second.processed == 1
    assert second.may_have_more is False
    assert repeated.processed == 0
    assert db_session.scalar(select(func.count()).select_from(LibraryWorkFacet)) == 9
    assert db_session.scalar(select(func.count()).select_from(LibraryFacet)) == 7


def test_facet_index_repair_rolls_back_the_whole_failed_batch(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_pending_works(db_session, 2)
    original_sync = facet_index_module.sync_work_facets
    calls = 0

    def fail_second_work(db: Session, work_id: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("simulated facet repair failure")
        original_sync(db, work_id)

    monkeypatch.setattr(facet_index_module, "sync_work_facets", fail_second_work)

    with pytest.raises(RuntimeError, match="simulated facet repair failure"):
        _rebuilder(db_session).execute(limit=2)

    db_session.expire_all()
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(LibraryWork)
            .where(LibraryWork.facet_index_version == 0)
        )
        == 2
    )
    assert db_session.scalar(select(func.count()).select_from(LibraryWorkFacet)) == 0


def test_facet_index_repair_rejects_unbounded_batches(db_session: Session) -> None:
    with pytest.raises(ValueError, match="between 1 and 200"):
        _rebuilder(db_session).execute(limit=201)
