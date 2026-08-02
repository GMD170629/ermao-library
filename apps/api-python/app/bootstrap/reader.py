"""Reader capability composition root."""

from sqlalchemy.orm import Session

from app.modules.reader.application.volume_reader import VolumeReaderService
from app.modules.reader.infrastructure.volume_repository import (
    SqlAlchemyReaderVolumeRepository,
)


def reader_volume_service(session: Session) -> VolumeReaderService:
    return VolumeReaderService(SqlAlchemyReaderVolumeRepository(session), session)


__all__ = ["reader_volume_service"]
