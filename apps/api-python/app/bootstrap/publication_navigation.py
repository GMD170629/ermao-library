"""Composition root for the API's synchronous lazy publication index."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.contracts.publication_sources import PublicationAccessScope
from app.core.config import Settings
from app.modules.library.application.resource_details import ResourceDetailAccessScope
from app.modules.library.infrastructure.publication_navigation import (
    SqlAlchemyLibraryNavigationProjection,
)
from app.modules.library.infrastructure.publication_source import (
    SqlAlchemyPublicationSourceRepository,
)
from app.modules.publications.application.ensure_navigation import (
    EnsurePublicationNavigation,
)
from app.modules.publications.application.navigation_ports import (
    PublicationNavigationLookupUnitOfWorkFactory,
    PublicationNavigationUnitOfWorkFactory,
)
from app.modules.publications.domain.model import (
    PublicationNotFoundError,
    PublicationResource,
)
from app.modules.publications.infrastructure.epub_adapter import (
    EpubPublicationAdapter,
)
from app.modules.publications.infrastructure.fb2_adapter import (
    Fb2PublicationAdapter,
)
from app.modules.publications.infrastructure.mobi_adapter import (
    CompositePublicationAdapter,
    MobiPublicationAdapter,
)
from app.modules.publications.infrastructure.txt_adapter import TxtPublicationAdapter
from app.modules.publications.infrastructure.uow import (
    SqlAlchemyPublicationNavigationLookupUnitOfWork,
    SqlAlchemyPublicationNavigationUnitOfWork,
)


@dataclass(slots=True)
class PublicationNavigationRuntime:
    """API-lifecycle owner for parser snapshots and lazy TOC generation."""

    _ensure: EnsurePublicationNavigation
    _adapter: CompositePublicationAdapter
    _source_repository_factory: Callable[
        [Session], SqlAlchemyPublicationSourceRepository
    ]

    def ensure(
        self,
        *,
        resource_id: str,
        context: ResourceDetailAccessScope,
    ) -> str:
        result = self._ensure.execute(
            resource_id=resource_id,
            access_scope=PublicationAccessScope(
                is_admin=context.is_admin,
                can_view_manual_imports=context.can_view_manual_imports,
                library_ids=context.library_ids,
            ),
        )
        return result.asset_id

    def close(self) -> None:
        self._adapter.close()

    def read_resource(
        self,
        *,
        session: Session,
        resource_id: str,
        access_scope: PublicationAccessScope,
        href: str,
    ) -> PublicationResource:
        """Read one validated Publication resource through the shared adapter.

        Reader delivery uses the same source lookup and format adapter as the
        publication navigation capability.  It does not duplicate parser or
        filesystem safety rules in a route module.
        """

        source = self._source_repository_factory(session).find_source(
            resource_id=resource_id,
            access_scope=access_scope,
        )
        if source is None:
            raise PublicationNotFoundError
        return self._adapter.read_resource(source, href)


def build_publication_navigation_runtime(
    session_factory: Callable[[], Session],
    settings: Settings,
) -> PublicationNavigationRuntime:
    """Wire one parser runtime; workers and Reader never use this graph."""

    mobi_adapter = MobiPublicationAdapter(settings.resolved_storage_root)
    adapter = CompositePublicationAdapter(
        {
            "epub": EpubPublicationAdapter(settings.resolved_storage_root),
            "fb2": Fb2PublicationAdapter(settings.resolved_storage_root),
            "txt": TxtPublicationAdapter(settings.resolved_storage_root),
            "mobi": mobi_adapter,
            "azw": mobi_adapter,
            "azw3": mobi_adapter,
            "prc": mobi_adapter,
        }
    )
    lookup_factory: PublicationNavigationLookupUnitOfWorkFactory = lambda: (
        SqlAlchemyPublicationNavigationLookupUnitOfWork(
            session_factory,
            SqlAlchemyPublicationSourceRepository,
            SqlAlchemyLibraryNavigationProjection,
        )
    )
    unit_of_work_factory: PublicationNavigationUnitOfWorkFactory = lambda: (
        SqlAlchemyPublicationNavigationUnitOfWork(
            session_factory,
            SqlAlchemyLibraryNavigationProjection,
        )
    )
    ensure = EnsurePublicationNavigation(
        lookup_unit_of_work_factory=lookup_factory,
        publication_adapter=adapter,
        unit_of_work_factory=unit_of_work_factory,
    )
    return PublicationNavigationRuntime(
        ensure,
        adapter,
        SqlAlchemyPublicationSourceRepository,
    )


__all__ = [
    "PublicationNavigationRuntime",
    "build_publication_navigation_runtime",
]
