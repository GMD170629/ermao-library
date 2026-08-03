"""SQLAlchemy projections for an authorized OPDS-compatible catalog."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, exists, func, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.selectable import ScalarSelect

from app.core.authorization import (
    AuthorizationContext,
    volume_visibility_predicate,
    work_visibility_predicate,
)
from app.models.library import (
    LibraryFacet,
    LibraryFile,
    LibraryMediaVersion,
    LibraryVolume,
    LibraryWork,
    LibraryWorkFacet,
)
from app.modules.library.application.catalog import (
    CatalogFacet,
    CatalogFacetKind,
    CatalogFacetPage,
    CatalogFile,
    CatalogVolume,
    CatalogWork,
    CatalogWorkFacet,
    CatalogWorkFilter,
    CatalogWorkPage,
)

CATALOG_MEDIA_KINDS = ("EBOOK", "COMIC")
CATALOG_READY_IMPORT_STATUSES = ("COMPLETED", "IMPORTED", "READY")


def _eligible_volume_exists(context: AuthorizationContext) -> ColumnElement[bool]:
    media_version = aliased(LibraryMediaVersion)
    volume = aliased(LibraryVolume)
    file = aliased(LibraryFile)
    return exists(
        select(volume.id)
        .join(media_version, media_version.id == volume.media_version_id)
        .join(file, file.volume_id == volume.id)
        .where(
            media_version.work_id == LibraryWork.id,
            media_version.media_kind.in_(CATALOG_MEDIA_KINDS),
            volume.hidden.is_(False),
            volume.import_status.in_(CATALOG_READY_IMPORT_STATUSES),
            volume_visibility_predicate(context, volume),
        )
    )


def _work_predicates(
    context: AuthorizationContext,
    filters: CatalogWorkFilter,
) -> list[ColumnElement[bool]]:
    predicates: list[ColumnElement[bool]] = [
        LibraryWork.hidden.is_(False),
        work_visibility_predicate(context),
        _eligible_volume_exists(context),
    ]
    if filters.search:
        term = filters.search.casefold()
        predicates.append(
            or_(
                func.lower(LibraryWork.title).contains(term, autoescape=True),
                func.lower(func.coalesce(LibraryWork.author, "")).contains(
                    term, autoescape=True
                ),
                func.lower(func.coalesce(LibraryWork.series_name, "")).contains(
                    term, autoescape=True
                ),
                func.lower(LibraryWork.tags).contains(term, autoescape=True),
            )
        )
    if filters.facet_kind is not None and filters.facet_id is not None:
        facet_link = aliased(LibraryWorkFacet)
        facet = aliased(LibraryFacet)
        predicates.append(
            exists(
                select(facet_link.work_id)
                .join(facet, facet.id == facet_link.facet_id)
                .where(
                    facet_link.work_id == LibraryWork.id,
                    facet_link.facet_id == filters.facet_id,
                    facet.kind == filters.facet_kind,
                )
            )
        )
    if filters.work_ids is not None:
        predicates.append(
            LibraryWork.id.in_(filters.work_ids)
            if filters.work_ids
            else LibraryWork.id.is_(None)
        )
    return predicates


def _latest_eligible_volume_at(
    context: AuthorizationContext,
) -> ScalarSelect[datetime]:
    media_version = aliased(LibraryMediaVersion)
    volume = aliased(LibraryVolume)
    file = aliased(LibraryFile)
    return (
        select(func.max(volume.updated_at))
        .join(media_version, media_version.id == volume.media_version_id)
        .join(file, file.volume_id == volume.id)
        .where(
            media_version.work_id == LibraryWork.id,
            media_version.media_kind.in_(CATALOG_MEDIA_KINDS),
            volume.hidden.is_(False),
            volume.import_status.in_(CATALOG_READY_IMPORT_STATUSES),
            volume_visibility_predicate(context, volume),
        )
        .correlate(LibraryWork)
        .scalar_subquery()
    )


class SqlAlchemyCatalogQueries:
    def __init__(self, db: Session) -> None:
        self._db = db

    def list_works(
        self,
        *,
        context: AuthorizationContext,
        filters: CatalogWorkFilter,
        page: int,
        page_size: int,
    ) -> CatalogWorkPage:
        predicates = _work_predicates(context, filters)
        total = int(
            self._db.scalar(
                select(func.count()).select_from(LibraryWork).where(*predicates)
            )
            or 0
        )
        statement = select(LibraryWork).where(*predicates)
        if filters.sort == "recent":
            latest = _latest_eligible_volume_at(context)
            statement = statement.order_by(
                latest.desc(), LibraryWork.updated_at.desc(), LibraryWork.id.asc()
            )
        else:
            statement = statement.order_by(
                LibraryWork.normalized_title.asc(), LibraryWork.id.asc()
            )
        work_rows = self._db.scalars(
            statement.offset((page - 1) * page_size).limit(page_size)
        ).all()
        works = self._assemble_works(context, work_rows)
        return CatalogWorkPage(
            works=works,
            total=total,
            page=page,
            page_size=page_size,
            updated_at=max((work.updated_at for work in works), default=None),
        )

    def get_work(
        self,
        *,
        context: AuthorizationContext,
        work_id: str,
    ) -> CatalogWork | None:
        page = self.list_works(
            context=context,
            filters=CatalogWorkFilter(work_ids=(work_id,)),
            page=1,
            page_size=1,
        )
        return page.works[0] if page.works else None

    def list_facets(
        self,
        *,
        context: AuthorizationContext,
        kind: CatalogFacetKind,
        search: str,
        page: int,
        page_size: int,
    ) -> CatalogFacetPage:
        filters: list[ColumnElement[bool]] = [
            LibraryFacet.kind == kind,
            func.trim(LibraryFacet.name) != "",
            LibraryWork.hidden.is_(False),
            work_visibility_predicate(context),
            _eligible_volume_exists(context),
        ]
        if search:
            filters.append(
                func.lower(LibraryFacet.name).contains(
                    search.casefold(), autoescape=True
                )
            )
        grouped = (
            select(
                LibraryFacet.id.label("facet_id"),
                LibraryFacet.kind.label("facet_kind"),
                LibraryFacet.name.label("facet_name"),
                LibraryFacet.normalized_name.label("normalized_name"),
                func.count(func.distinct(LibraryWork.id)).label("work_count"),
                func.max(LibraryFacet.updated_at).label("facet_updated_at"),
                func.max(LibraryWork.updated_at).label("work_updated_at"),
            )
            .join(LibraryWorkFacet, LibraryWorkFacet.facet_id == LibraryFacet.id)
            .join(LibraryWork, LibraryWork.id == LibraryWorkFacet.work_id)
            .where(*filters)
            .group_by(
                LibraryFacet.id,
                LibraryFacet.kind,
                LibraryFacet.name,
                LibraryFacet.normalized_name,
            )
        ).subquery()
        total = int(self._db.scalar(select(func.count()).select_from(grouped)) or 0)
        rows = self._db.execute(
            select(grouped)
            .order_by(grouped.c.normalized_name.asc(), grouped.c.facet_id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        facets = tuple(
            CatalogFacet(
                id=str(row.facet_id),
                kind=kind,
                name=str(row.facet_name),
                normalized_name=str(row.normalized_name),
                work_count=int(row.work_count),
                updated_at=max(row.facet_updated_at, row.work_updated_at),
            )
            for row in rows
        )
        return CatalogFacetPage(
            facets=facets,
            total=total,
            page=page,
            page_size=page_size,
            updated_at=max((facet.updated_at for facet in facets), default=None),
        )

    def _assemble_works(
        self,
        context: AuthorizationContext,
        work_rows: Sequence[LibraryWork],
    ) -> tuple[CatalogWork, ...]:
        if not work_rows:
            return ()
        work_ids = [work.id for work in work_rows]
        volumes = self._volumes_by_work(context, work_ids)
        facets = self._facets_by_work(work_ids)
        return tuple(
            CatalogWork(
                id=work.id,
                title=work.title,
                author=work.author,
                description=work.description,
                series_name=work.series_name,
                series_index=work.series_index,
                has_cover=bool(work.cover_path and work.cover_status == "READY"),
                facets=facets.get(work.id, ()),
                volumes=volumes.get(work.id, ()),
                created_at=work.created_at,
                updated_at=max(
                    [work.updated_at]
                    + [volume.updated_at for volume in volumes.get(work.id, ())]
                ),
            )
            for work in work_rows
        )

    def _volumes_by_work(
        self,
        context: AuthorizationContext,
        work_ids: list[str],
    ) -> dict[str, tuple[CatalogVolume, ...]]:
        preferred_file_id = (
            select(LibraryFile.id)
            .where(LibraryFile.volume_id == LibraryVolume.id)
            .order_by(LibraryFile.sort_order.asc(), LibraryFile.id.asc())
            .limit(1)
            .correlate(LibraryVolume)
            .scalar_subquery()
        )
        rows = self._db.execute(
            select(
                LibraryMediaVersion.work_id,
                LibraryMediaVersion.media_kind,
                LibraryVolume,
                LibraryFile.id.label("file_id"),
                LibraryFile.mime_type,
                LibraryFile.size_bytes.label("file_size_bytes"),
                LibraryFile.updated_at.label("file_updated_at"),
            )
            .join(
                LibraryMediaVersion,
                LibraryMediaVersion.id == LibraryVolume.media_version_id,
            )
            .join(LibraryFile, LibraryFile.id == preferred_file_id)
            .where(
                LibraryMediaVersion.work_id.in_(work_ids),
                LibraryMediaVersion.media_kind.in_(CATALOG_MEDIA_KINDS),
                LibraryVolume.hidden.is_(False),
                LibraryVolume.import_status.in_(CATALOG_READY_IMPORT_STATUSES),
                volume_visibility_predicate(context),
            )
            .order_by(
                LibraryMediaVersion.work_id.asc(),
                LibraryVolume.sort_order.asc(),
                LibraryVolume.volume_index.asc(),
                LibraryVolume.id.asc(),
            )
        ).all()
        by_work: defaultdict[str, list[CatalogVolume]] = defaultdict(list)
        for row in rows:
            volume = row.LibraryVolume
            by_work[str(row.work_id)].append(
                CatalogVolume(
                    id=volume.id,
                    title=volume.title,
                    media_kind=str(row.media_kind),
                    format=volume.format,
                    volume_index=volume.volume_index,
                    sort_order=volume.sort_order,
                    description=volume.description,
                    language=volume.language,
                    publisher=volume.publisher,
                    published_at=volume.published_at,
                    identifier=volume.identifier,
                    isbn=volume.isbn,
                    page_count=volume.page_count,
                    has_cover=bool(
                        volume.cover_path and volume.cover_status == "READY"
                    ),
                    file=CatalogFile(
                        id=str(row.file_id),
                        mime_type=str(row.mime_type),
                        size_bytes=int(row.file_size_bytes),
                        updated_at=row.file_updated_at,
                    ),
                    updated_at=max(volume.updated_at, row.file_updated_at),
                )
            )
        return {work_id: tuple(items) for work_id, items in by_work.items()}

    def _facets_by_work(
        self,
        work_ids: list[str],
    ) -> dict[str, tuple[CatalogWorkFacet, ...]]:
        rows = self._db.execute(
            select(
                LibraryWorkFacet.work_id,
                LibraryFacet.id,
                LibraryFacet.kind,
                LibraryFacet.name,
            )
            .join(LibraryFacet, LibraryFacet.id == LibraryWorkFacet.facet_id)
            .where(
                LibraryWorkFacet.work_id.in_(work_ids),
                LibraryFacet.kind.in_(("AUTHOR", "SERIES", "TAG")),
            )
            .order_by(
                LibraryWorkFacet.work_id.asc(),
                LibraryFacet.kind.asc(),
                LibraryWorkFacet.sort_order.asc(),
                LibraryFacet.normalized_name.asc(),
                LibraryFacet.id.asc(),
            )
        ).all()
        by_work: defaultdict[str, list[CatalogWorkFacet]] = defaultdict(list)
        for work_id, facet_id, kind, name in rows:
            by_work[str(work_id)].append(
                CatalogWorkFacet(
                    id=str(facet_id),
                    kind=kind,
                    name=str(name),
                )
            )
        return {work_id: tuple(items) for work_id, items in by_work.items()}
