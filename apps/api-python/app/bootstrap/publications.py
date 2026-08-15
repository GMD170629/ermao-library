"""Composition root for normalized publication use cases."""

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.modules.publications.application.ensure_navigation import (
    EnsurePublicationNavigation,
)
from app.modules.publications.application.ensure_render_artifact import (
    EnsurePublicationRenderArtifact,
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
from app.modules.publications.infrastructure.render_artifact import (
    ConfiguredPublicationRenderArtifactBuilder,
)
from app.modules.publications.infrastructure.render_cache import (
    LocalPublicationRenderFileStore,
)
from app.modules.publications.infrastructure.source_repository import (
    SqlAlchemyPublicationSourceRepository,
)
from app.modules.publications.infrastructure.txt_adapter import (
    TXT_PARSER_IDENTIFIER,
    TxtPublicationAdapter,
)
from app.modules.publications.infrastructure.uow import (
    SqlAlchemyPublicationNavigationLookupUnitOfWork,
    SqlAlchemyPublicationNavigationUnitOfWork,
    SqlAlchemyPublicationRenderLookupUnitOfWork,
    SqlAlchemyPublicationRenderUnitOfWork,
)


def _publication_adapter_and_profiles(
    settings: Settings,
) -> tuple[CompositePublicationAdapter, ConfiguredPublicationParserProfiles]:
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
    return (
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
    )


def open_publication(db: Session, settings: Settings) -> OpenPublication:
    adapter, _profiles = _publication_adapter_and_profiles(settings)
    return OpenPublication(
        SqlAlchemyPublicationSourceRepository(db),
        adapter,
    )


def ensure_publication_navigation(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> EnsurePublicationNavigation:
    adapter, profiles = _publication_adapter_and_profiles(settings)

    def lookup_unit_of_work() -> PublicationNavigationLookupUnitOfWork:
        return SqlAlchemyPublicationNavigationLookupUnitOfWork(session_factory)

    def unit_of_work() -> PublicationNavigationUnitOfWork:
        return SqlAlchemyPublicationNavigationUnitOfWork(session_factory)

    return EnsurePublicationNavigation(
        lookup_unit_of_work_factory=lookup_unit_of_work,
        publication_adapter=adapter,
        profile_resolver=profiles,
        unit_of_work_factory=unit_of_work,
    )


def ensure_publication_render_artifact(
    session_factory: sessionmaker[Session],
    settings: Settings,
) -> EnsurePublicationRenderArtifact:
    adapter, _profiles = _publication_adapter_and_profiles(settings)

    def lookup_unit_of_work() -> SqlAlchemyPublicationRenderLookupUnitOfWork:
        return SqlAlchemyPublicationRenderLookupUnitOfWork(session_factory)

    def unit_of_work() -> SqlAlchemyPublicationRenderUnitOfWork:
        return SqlAlchemyPublicationRenderUnitOfWork(session_factory)

    return EnsurePublicationRenderArtifact(
        lookup_unit_of_work_factory=lookup_unit_of_work,
        unit_of_work_factory=unit_of_work,
        artifact_builder=ConfiguredPublicationRenderArtifactBuilder(adapter),
        file_store=LocalPublicationRenderFileStore(
            settings.publication_render_cache_root
        ),
    )


__all__ = [
    "ensure_publication_navigation",
    "ensure_publication_render_artifact",
    "open_publication",
]
