from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from threading import Event, Thread
from time import monotonic

import pytest
from app.bootstrap.library_facet_index import (
    library_facet_index_data_migration_is_complete,
)
from app.core.config import Settings
from app.db.base import Base
from app.db.bootstrap import bootstrap_database
from app.db.sqlite import create_sqlite_engine
from app.models.library import LibraryFacet, LibraryWork, LibraryWorkFacet
from app.modules.library.application.facet_index import (
    PreparedWorkFacets,
    RebuildFacetIndexBatch,
)
from app.modules.library.domain.facets import build_work_facet_values, parse_tag_names
from app.modules.library.infrastructure import facet_index as facet_index_module
from app.modules.library.infrastructure.facet_index import (
    SqlAlchemyFacetIndexRepository,
)
from app.modules.library.infrastructure.uow import (
    SqlAlchemyFacetIndexUnitOfWork,
)
from sqlalchemy import event, func, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker


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
    factory = sessionmaker(
        bind=db_session.get_bind(),
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    assert library_facet_index_data_migration_is_complete(factory) is False

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
    assert library_facet_index_data_migration_is_complete(factory) is True
    assert db_session.scalar(select(func.count()).select_from(LibraryWorkFacet)) == 9
    assert db_session.scalar(select(func.count()).select_from(LibraryFacet)) == 7


def test_facet_index_repair_rolls_back_the_whole_failed_batch(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _add_pending_works(db_session, 2)
    original_replace = SqlAlchemyFacetIndexRepository.replace_batch

    def fail_after_batch(
        repository: SqlAlchemyFacetIndexRepository,
        batch: tuple[PreparedWorkFacets, ...],
        *,
        index_version: int,
    ) -> int:
        original_replace(repository, batch, index_version=index_version)
        raise RuntimeError("simulated facet repair failure")

    monkeypatch.setattr(
        facet_index_module.SqlAlchemyFacetIndexRepository,
        "replace_batch",
        fail_after_batch,
    )

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


def test_facet_index_repair_uses_bounded_set_based_statements(
    db_session: Session,
) -> None:
    db_session.add_all(
        [
            LibraryWork(
                id=f"statement-work-{index}",
                title=f"Statement work {index}",
                normalized_title=f"statement work {index}",
                author=f"Author {index}",
                normalized_author=f"author {index}",
                tags=(
                    f'["Tag {index} A", "Tag {index} B", '
                    f'"Tag {index} C"]'
                ),
                series_name=f"Series {index}",
            )
            for index in range(25)
        ]
    )
    db_session.commit()
    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    statements = 0
    statement_kinds: list[str] = []

    def count_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        *_args: object,
    ) -> None:
        nonlocal statements
        statements += 1
        statement_kinds.append(statement.lstrip().split(None, 1)[0].upper())

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        result = _rebuilder(db_session).execute(limit=25)
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)

    assert result.processed == 25
    assert statements <= 15
    first_write = next(
        index
        for index, kind in enumerate(statement_kinds)
        if kind in {"DELETE", "INSERT", "UPDATE"}
    )
    assert statement_kinds[first_write] == "UPDATE"
    assert "WITH" in statement_kinds[first_write + 1 :]
    assert "SELECT" in statement_kinds[first_write + 1 :]


def test_facet_index_repair_preserves_work_updated_at(db_session: Session) -> None:
    original_updated_at = datetime(2020, 1, 2, 3, 4, 5, tzinfo=UTC)
    work = LibraryWork(
        id="preserved-updated-at-work",
        title="Preserved timestamp",
        normalized_title="preserved timestamp",
        author="Timestamp author",
        normalized_author="timestamp author",
        tags='["Timestamp tag"]',
        series_name="Timestamp series",
        updated_at=original_updated_at,
    )
    db_session.add(work)
    db_session.commit()

    result = _rebuilder(db_session).execute(limit=1)

    db_session.expire_all()
    refreshed = db_session.get(LibraryWork, work.id)
    assert result.processed == 1
    assert refreshed is not None
    assert refreshed.updated_at == original_updated_at


def test_facet_index_repair_preserves_existing_facet_identity(
    db_session: Session,
) -> None:
    existing = LibraryFacet(
        id="legacy-tag-id",
        kind="TAG",
        name="已重命名标签",
        normalized_name="tag0",
        aliases='["Tag 0"]',
    )
    work = LibraryWork(
        id="existing-facet-work",
        title="Existing facet",
        normalized_title="existing facet",
        author=None,
        normalized_author=None,
        tags='["Tag 0"]',
        series_name=None,
    )
    db_session.add_all([existing, work])
    db_session.commit()

    result = _rebuilder(db_session).execute(limit=1)

    db_session.expire_all()
    preserved = db_session.get(LibraryFacet, existing.id)
    link = db_session.scalar(
        select(LibraryWorkFacet).where(LibraryWorkFacet.work_id == work.id)
    )
    assert result.processed == 1
    assert preserved is not None
    assert preserved.name == "已重命名标签"
    assert preserved.aliases == '["Tag 0"]'
    assert link is not None
    assert link.facet_id == existing.id


def test_facet_index_repair_replaces_stale_links_for_empty_facets(
    db_session: Session,
) -> None:
    stale = LibraryFacet(
        id="stale-facet",
        kind="TAG",
        name="Stale",
        normalized_name="stale",
        aliases="[]",
    )
    work = LibraryWork(
        id="empty-facet-work",
        title="Empty facets",
        normalized_title="empty facets",
        author=None,
        normalized_author=None,
        tags="not-json",
        series_name=None,
    )
    db_session.add_all([stale, work])
    db_session.flush()
    db_session.add(
        LibraryWorkFacet(facet_id=stale.id, work_id=work.id, sort_order=0)
    )
    db_session.commit()

    result = _rebuilder(db_session).execute(limit=1)

    db_session.expire_all()
    refreshed = db_session.get(LibraryWork, work.id)
    assert result.processed == 1
    assert refreshed is not None
    assert refreshed.facet_index_version == 1
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(LibraryWorkFacet)
            .where(LibraryWorkFacet.work_id == work.id)
        )
        == 0
    )


def test_facet_index_repair_deduplicates_normalized_values(
    db_session: Session,
) -> None:
    work = LibraryWork(
        id="duplicate-facet-work",
        title="Duplicate facets",
        normalized_title="duplicate facets",
        author="Author A、Ａuthor A",
        normalized_author="author a",
        tags='["Tag A", "tag a", " Tag  A "]',
        series_name="Series A",
    )
    db_session.add(work)
    db_session.commit()

    result = _rebuilder(db_session).execute(limit=1)

    facets = db_session.execute(
        select(LibraryFacet.kind, LibraryFacet.normalized_name)
        .join(
            LibraryWorkFacet,
            LibraryWorkFacet.facet_id == LibraryFacet.id,
        )
        .where(LibraryWorkFacet.work_id == work.id)
        .order_by(LibraryFacet.kind)
    ).all()
    assert result.processed == 1
    assert facets == [
        ("AUTHOR", "authora"),
        ("SERIES", "seriesa"),
        ("TAG", "taga"),
    ]


def test_facet_index_repair_skips_source_changed_after_preparation(
    db_session: Session,
) -> None:
    work = LibraryWork(
        id="concurrently-changed-work",
        title="Changed source",
        normalized_title="changed source",
        author="Original author",
        normalized_author="original author",
        tags='["Original tag"]',
        series_name="Original series",
    )
    db_session.add(work)
    db_session.commit()
    repository = SqlAlchemyFacetIndexRepository(db_session)
    source = repository.pending_works(limit=1)[0]
    prepared = PreparedWorkFacets(
        source=source,
        facets=build_work_facet_values(
            author=source.author,
            tags=parse_tag_names(source.tags_source),
            series_name=source.series_name,
        ),
    )
    db_session.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work.id)
        .values(tags='["New tag"]', updated_at=LibraryWork.updated_at)
    )

    processed = repository.replace_batch((prepared,), index_version=1)
    db_session.commit()

    db_session.expire_all()
    skipped = db_session.get(LibraryWork, work.id)
    assert processed == 0
    assert skipped is not None
    assert skipped.facet_index_version == 0
    assert (
        db_session.scalar(
            select(func.count())
            .select_from(LibraryWorkFacet)
            .where(LibraryWorkFacet.work_id == work.id)
        )
        == 0
    )

    retry = _rebuilder(db_session).execute(limit=1)
    tag_names = set(
        db_session.scalars(
            select(LibraryFacet.name)
            .join(
                LibraryWorkFacet,
                LibraryWorkFacet.facet_id == LibraryFacet.id,
            )
            .where(
                LibraryWorkFacet.work_id == work.id,
                LibraryFacet.kind == "TAG",
            )
        )
    )
    assert retry.processed == 1
    assert tag_names == {"New tag"}


def test_facet_index_repair_processes_stable_subset_when_one_source_changed(
    db_session: Session,
) -> None:
    stable = LibraryWork(
        id="stable-subset-work",
        title="Stable subset",
        normalized_title="stable subset",
        author="Stable author",
        normalized_author="stable author",
        tags='["Stable tag"]',
        series_name=None,
    )
    changed = LibraryWork(
        id="changed-subset-work",
        title="Changed subset",
        normalized_title="changed subset",
        author="Original author",
        normalized_author="original author",
        tags='["Original tag"]',
        series_name=None,
    )
    db_session.add_all([stable, changed])
    db_session.commit()
    repository = SqlAlchemyFacetIndexRepository(db_session)
    sources = repository.pending_works(limit=2)
    prepared = tuple(
        PreparedWorkFacets(
            source=source,
            facets=build_work_facet_values(
                author=source.author,
                tags=parse_tag_names(source.tags_source),
                series_name=source.series_name,
            ),
        )
        for source in sources
    )
    db_session.execute(
        update(LibraryWork)
        .where(LibraryWork.id == changed.id)
        .values(tags='["New tag"]', updated_at=LibraryWork.updated_at)
    )

    processed = repository.replace_batch(prepared, index_version=1)
    db_session.commit()

    db_session.expire_all()
    assert processed == 1
    assert db_session.get(LibraryWork, stable.id).facet_index_version == 1
    assert db_session.get(LibraryWork, changed.id).facet_index_version == 0
    stable_facets = set(
        db_session.scalars(
            select(LibraryFacet.name)
            .join(
                LibraryWorkFacet,
                LibraryWorkFacet.facet_id == LibraryFacet.id,
            )
            .where(LibraryWorkFacet.work_id == stable.id)
        )
    )
    changed_links = db_session.scalar(
        select(func.count())
        .select_from(LibraryWorkFacet)
        .where(LibraryWorkFacet.work_id == changed.id)
    )
    assert stable_facets == {"Stable author", "Stable tag"}
    assert changed_links == 0


def test_facet_index_repair_compares_the_exact_tag_source(
    db_session: Session,
) -> None:
    work = LibraryWork(
        id="exact-tag-source-work",
        title="Exact tag source",
        normalized_title="exact tag source",
        author=None,
        normalized_author=None,
        tags='["Same tag"]',
        series_name=None,
    )
    db_session.add(work)
    db_session.commit()
    repository = SqlAlchemyFacetIndexRepository(db_session)
    source = repository.pending_works(limit=1)[0]
    prepared = PreparedWorkFacets(
        source=source,
        facets=build_work_facet_values(
            author=source.author,
            tags=parse_tag_names(source.tags_source),
            series_name=source.series_name,
        ),
    )
    db_session.execute(
        update(LibraryWork)
        .where(LibraryWork.id == work.id)
        .values(tags='[ "Same tag" ]', updated_at=LibraryWork.updated_at)
    )

    processed = repository.replace_batch((prepared,), index_version=1)
    db_session.commit()

    assert processed == 0
    retry = _rebuilder(db_session).execute(limit=1)
    assert retry.processed == 1


def test_facet_index_repair_short_timeout_defers_to_existing_writer(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "facet-contention.sqlite3"
    regular_engine = create_sqlite_engine(database_path, timeout_seconds=10)
    maintenance_engine = create_sqlite_engine(database_path, timeout_seconds=0.25)
    Base.metadata.create_all(regular_engine)
    regular_factory = sessionmaker(
        bind=regular_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    maintenance_factory = sessionmaker(
        bind=maintenance_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    with regular_factory() as seed:
        seed.add(
            LibraryWork(
                id="busy-work",
                title="Busy work",
                normalized_title="busy work",
                author="Busy author",
                normalized_author="busy author",
                tags='["Busy tag"]',
                series_name="Busy series",
            )
        )
        seed.commit()

    blocker = regular_factory()
    try:
        blocker.execute(
            update(LibraryWork)
            .where(LibraryWork.id == "busy-work")
            .values(title="Writer owns lock", updated_at=LibraryWork.updated_at)
        )
        rebuild = RebuildFacetIndexBatch(
            lambda: SqlAlchemyFacetIndexUnitOfWork(maintenance_factory)
        )

        started_at = monotonic()
        with pytest.raises(OperationalError, match="database is locked"):
            rebuild.execute(limit=1)
        elapsed = monotonic() - started_at
        assert 0.15 <= elapsed < 1.0

        with regular_factory() as reader:
            assert reader.get(LibraryWork, "busy-work").facet_index_version == 0
        blocker.rollback()

        retried = rebuild.execute(limit=1)
        assert retried.processed == 1
    finally:
        blocker.close()
        maintenance_engine.dispose()
        regular_engine.dispose()


def test_facet_index_repair_does_not_lock_writers_during_python_preparation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(storage_root=str(tmp_path / "storage"))
    regular_engine = create_sqlite_engine(settings.database_path)
    competing_engine = create_sqlite_engine(
        settings.database_path,
        timeout_seconds=0.1,
    )
    maintenance_engine = create_sqlite_engine(
        settings.database_path,
        timeout_seconds=0.25,
    )
    bootstrap_database(regular_engine, settings)
    maintenance_factory = sessionmaker(
        bind=maintenance_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    with Session(regular_engine) as seed:
        seed.add_all(
            [
                LibraryWork(
                    id="prepared-work",
                    title="Prepared work",
                    normalized_title="prepared work",
                    author="Prepared author",
                    normalized_author="prepared author",
                    tags='["Prepared tag"]',
                ),
                LibraryWork(
                    id="normal-write",
                    title="Normal write",
                    normalized_title="normal write",
                    author=None,
                    normalized_author=None,
                    tags="[]",
                    facet_index_version=1,
                ),
            ]
        )
        seed.commit()

    preparing = Event()
    release_preparation = Event()
    original_unique_values = facet_index_module._unique_facet_values

    def pause_during_preparation(
        batch: tuple[PreparedWorkFacets, ...],
    ) -> dict[tuple[str, str], tuple[str, str]]:
        preparing.set()
        assert release_preparation.wait(timeout=2)
        return original_unique_values(batch)

    monkeypatch.setattr(
        facet_index_module,
        "_unique_facet_values",
        pause_during_preparation,
    )
    results: list[int] = []
    errors: list[BaseException] = []

    def rebuild_in_background() -> None:
        try:
            rebuild = RebuildFacetIndexBatch(
                lambda: SqlAlchemyFacetIndexUnitOfWork(maintenance_factory)
            )
            results.append(rebuild.execute(limit=1).processed)
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=rebuild_in_background)
    try:
        thread.start()
        assert preparing.wait(timeout=2)
        with Session(competing_engine) as writer:
            writer.execute(
                update(LibraryWork)
                .where(LibraryWork.id == "normal-write")
                .values(title="normal request succeeded")
            )
            writer.commit()
        release_preparation.set()
        thread.join(timeout=2)

        assert not thread.is_alive()
        assert errors == []
        assert results == [1]
    finally:
        release_preparation.set()
        thread.join(timeout=2)
        maintenance_engine.dispose()
        competing_engine.dispose()
        regular_engine.dispose()


def test_budgeted_maintenance_transaction_is_interrupted_and_releases_writer(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "facet-budget.sqlite3"
    regular_engine = create_sqlite_engine(database_path)
    maintenance_engine = create_sqlite_engine(
        database_path,
        timeout_seconds=0.25,
        transaction_time_budget_seconds=0.001,
    )
    Base.metadata.create_all(regular_engine)
    with Session(regular_engine) as seed:
        seed.add_all(
            [
                LibraryWork(
                    id=f"budget-work-{index}",
                    title=f"Budget work {index}",
                    normalized_title=f"budget work {index}",
                    author="Budget author",
                    normalized_author="budget author",
                    tags="[]",
                )
                for index in range(200)
            ]
        )
        seed.commit()

    first_work = LibraryWork.__table__.alias("first_work")
    second_work = LibraryWork.__table__.alias("second_work")
    third_work = LibraryWork.__table__.alias("third_work")
    try:
        with Session(maintenance_engine) as maintenance:
            maintenance.execute(
                update(LibraryWork)
                .where(LibraryWork.id == "budget-work-0")
                .values(
                    title=LibraryWork.title,
                    updated_at=LibraryWork.updated_at,
                )
            )
            with pytest.raises(OperationalError, match="interrupted"):
                maintenance.scalar(
                    select(func.count()).select_from(
                        first_work.join(
                            second_work, first_work.c.id != second_work.c.id
                        ).join(third_work, second_work.c.id != third_work.c.id)
                    )
                )

        with Session(regular_engine) as writer:
            writer.execute(
                update(LibraryWork)
                .where(LibraryWork.id == "budget-work-0")
                .values(title="writer recovered", updated_at=LibraryWork.updated_at)
            )
            writer.commit()
    finally:
        maintenance_engine.dispose()
        regular_engine.dispose()
