"""Composition root for normalized publication use cases."""

from collections.abc import Callable
from dataclasses import dataclass

from fastapi import Request
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
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
    PublicationNavigationLookupUnitOfWork,
    PublicationNavigationUnitOfWork,
)
from app.modules.publications.application.open_publication import OpenPublication
from app.modules.publications.domain.navigation import PublicationParserProfile
from app.modules.publications.infrastructure.epub_adapter import (
    EPUB_PARSER_IDENTIFIER,
    EpubPublicationAdapter,
)
from app.modules.publications.infrastructure.fb2_adapter import (
    FB2_PARSER_IDENTIFIER,
    Fb2PublicationAdapter,
)
from app.modules.publications.infrastructure.mobi_adapter import (
    CompositePublicationAdapter,
    MobiPublicationAdapter,
    load_mobi_core,
)
from app.modules.publications.infrastructure.navigation_cache import (
    ConfiguredPublicationParserProfiles,
)
from app.modules.publications.infrastructure.txt_adapter import (
    TXT_PARSER_IDENTIFIER,
    TxtPublicationAdapter,
)
from app.modules.publications.infrastructure.uow import (
    SqlAlchemyPublicationNavigationLookupUnitOfWork,
    SqlAlchemyPublicationNavigationUnitOfWork,
)


@dataclass(frozen=True)
class PublicationRuntime:
    adapter: CompositePublicationAdapter
    profiles: ConfiguredPublicationParserProfiles
    close_adapters: tuple[Callable[[], None], ...]

    def close(self) -> None:
        for close in self.close_adapters:
            close()


def publication_runtime(request: Request) -> PublicationRuntime:
    runtime: object = request.app.state.publication_runtime
    if not isinstance(runtime, PublicationRuntime):
        raise TypeError("publication runtime is unavailable")
    return runtime


def build_publication_runtime(settings: Settings) -> PublicationRuntime:
    epub = EpubPublicationAdapter(settings.resolved_storage_root)
    fb2 = Fb2PublicationAdapter(settings.resolved_storage_root)
    mobi_core = load_mobi_core()
    mobi = MobiPublicationAdapter(settings.resolved_storage_root, core=mobi_core)
    txt = TxtPublicationAdapter(settings.resolved_storage_root)
    profiles = {
        "epub": PublicationParserProfile(
            parser=EPUB_PARSER_IDENTIFIER,
            normalization="shuku-epub-navigation-v1",
        ),
        "fb2": PublicationParserProfile(
            parser=FB2_PARSER_IDENTIFIER,
            normalization="shuku-fb2-navigation-v1",
        ),
        "txt": PublicationParserProfile(
            parser=TXT_PARSER_IDENTIFIER,
            normalization="shuku-txt-navigation-v1",
        ),
    }
    if mobi_core is not None:
        mobi_profile = PublicationParserProfile(
            parser=mobi_core.parser_identifier,
            normalization="shuku-mobi-navigation-v1",
        )
        profiles.update(
            {
                "mobi": mobi_profile,
                "azw": mobi_profile,
                "azw3": mobi_profile,
                "prc": mobi_profile,
            }
        )
    return PublicationRuntime(
        CompositePublicationAdapter(
            {
                "epub": epub,
                "fb2": fb2,
                "mobi": mobi,
                "azw": mobi,
                "azw3": mobi,
                "prc": mobi,
                "txt": txt,
            }
        ),
        ConfiguredPublicationParserProfiles(profiles),
        (epub.close, fb2.close, mobi.close, txt.close),
    )


def open_publication(db: Session, runtime: PublicationRuntime) -> OpenPublication:
    return OpenPublication(
        SqlAlchemyPublicationSourceRepository(db),
        runtime.adapter,
    )


def ensure_publication_navigation(
    session_factory: sessionmaker[Session],
    runtime: PublicationRuntime,
) -> EnsurePublicationNavigation:

    def lookup_unit_of_work() -> PublicationNavigationLookupUnitOfWork:
        return SqlAlchemyPublicationNavigationLookupUnitOfWork(
            session_factory,
            SqlAlchemyPublicationSourceRepository,
            SqlAlchemyLibraryNavigationProjection,
        )

    def unit_of_work() -> PublicationNavigationUnitOfWork:
        return SqlAlchemyPublicationNavigationUnitOfWork(
            session_factory,
            SqlAlchemyLibraryNavigationProjection,
        )

    return EnsurePublicationNavigation(
        lookup_unit_of_work_factory=lookup_unit_of_work,
        publication_adapter=runtime.adapter,
        profile_resolver=runtime.profiles,
        unit_of_work_factory=unit_of_work,
    )


__all__ = [
    "PublicationRuntime",
    "build_publication_runtime",
    "ensure_publication_navigation",
    "open_publication",
    "publication_runtime",
]
