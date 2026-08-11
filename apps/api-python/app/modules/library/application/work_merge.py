"""Application contracts and orchestration for explicit multi-work merges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

MEDIA_KIND_ORDER = {"EBOOK": 0, "COMIC": 1, "AUDIOBOOK": 2}


class WorkMergeError(ValueError):
    code = "WORK_MERGE_INVALID"


class WorkMergeInProgressError(WorkMergeError):
    code = "WORK_MERGE_IN_PROGRESS"


class WorkMergeNotFoundError(WorkMergeError):
    code = "WORK_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class MergeMetadata:
    title: str
    author: str
    description: str | None
    series_name: str | None
    series_index: float | None
    tags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MergeCommand:
    work_ids: tuple[str, ...]
    metadata: MergeMetadata
    cover_volume_id: str
    actor_id: str


@dataclass(frozen=True, slots=True)
class MergePreview:
    works: tuple[dict[str, object], ...]
    media_groups: tuple[dict[str, object], ...]
    suggested_metadata: MergeMetadata
    default_cover_volume_id: str
    write_metadata_to_files: bool


@dataclass(frozen=True, slots=True)
class MergeResult:
    work_id: str
    source_work_ids: tuple[str, ...]
    media_versions: tuple[dict[str, object], ...]
    metadata_writebacks: tuple[dict[str, object], ...]
    operation: dict[str, object]


class WorkMergeGateway(Protocol):
    def preview(self, work_ids: tuple[str, ...]) -> MergePreview: ...

    def merge(self, command: MergeCommand) -> MergeResult: ...


class WorkMergeUnitOfWork(Protocol):
    def commit(self) -> None: ...

    def rollback(self) -> None: ...


class MergeMetadataWritebackPort(Protocol):
    def enabled(self) -> bool: ...

    def enqueue(
        self, *, work_id: str, media_version_id: str
    ) -> dict[str, object] | None: ...


def normalize_work_ids(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(value.strip() for value in values if value.strip())
    )
    if len(normalized) < 2:
        raise WorkMergeError("请至少选择两本图书")
    if len(normalized) > 500:
        raise WorkMergeError("一次最多合并 500 本图书")
    return normalized


class PreviewWorkMerge:
    def __init__(self, gateway: WorkMergeGateway) -> None:
        self._gateway = gateway

    def execute(self, work_ids: list[str] | tuple[str, ...]) -> MergePreview:
        return self._gateway.preview(normalize_work_ids(work_ids))


class CreateMergedWork:
    def __init__(
        self,
        gateway: WorkMergeGateway,
        unit_of_work: WorkMergeUnitOfWork,
    ) -> None:
        self._gateway = gateway
        self._unit_of_work = unit_of_work

    def execute(self, command: MergeCommand) -> MergeResult:
        normalized_ids = normalize_work_ids(command.work_ids)
        title = command.metadata.title.strip()
        if not title:
            raise WorkMergeError("标题不能为空")
        if not command.cover_volume_id.strip():
            raise WorkMergeError("请选择一个卷册作为封面")
        normalized = MergeCommand(
            work_ids=normalized_ids,
            metadata=MergeMetadata(
                title=title,
                author=command.metadata.author.strip(),
                description=command.metadata.description.strip()
                if command.metadata.description
                else None,
                series_name=command.metadata.series_name.strip()
                if command.metadata.series_name
                else None,
                series_index=command.metadata.series_index,
                tags=tuple(
                    dict.fromkeys(
                        tag.strip() for tag in command.metadata.tags if tag.strip()
                    )
                ),
            ),
            cover_volume_id=command.cover_volume_id.strip(),
            actor_id=command.actor_id,
        )
        try:
            result = self._gateway.merge(normalized)
            self._unit_of_work.commit()
        except Exception:
            self._unit_of_work.rollback()
            raise
        return result
