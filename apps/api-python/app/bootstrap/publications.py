"""Composition root for normalized publication use cases."""

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.modules.publications.application.open_publication import OpenPublication
from app.modules.publications.infrastructure.epub_adapter import EpubPublicationAdapter
from app.modules.publications.infrastructure.mobi_adapter import (
    CompositePublicationAdapter,
    MobiPublicationAdapter,
)
from app.modules.publications.infrastructure.source_repository import (
    SqlAlchemyPublicationSourceRepository,
)
from app.modules.publications.infrastructure.txt_adapter import TxtPublicationAdapter


def open_publication(db: Session, settings: Settings) -> OpenPublication:
    epub = EpubPublicationAdapter(settings.resolved_storage_root)
    mobi = MobiPublicationAdapter(settings.resolved_storage_root)
    txt = TxtPublicationAdapter(settings.resolved_storage_root)
    return OpenPublication(
        SqlAlchemyPublicationSourceRepository(db),
        CompositePublicationAdapter(
            {
                "epub": epub,
                "mobi": mobi,
                "azw": mobi,
                "azw3": mobi,
                "prc": mobi,
                "txt": txt,
            }
        ),
    )


__all__ = ["open_publication"]
