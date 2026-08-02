"""Backfill edition data into singleton media versions and volume resources.

Revision ID: 0006_media_versions_backfill
Revises: 0005_media_versions_expand
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import PurePosixPath

import sqlalchemy as sa
from alembic import op
from sqlalchemy.engine import RowMapping

revision: str = "0006_media_versions_backfill"
down_revision: str | Sequence[str] | None = "0005_media_versions_expand"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BATCH_SIZE = 100
PLACEHOLDER_TITLES = {"", "正文", "pdf", "全本", "ebook", "电子书", "漫画", "有声书"}


def _id(prefix: str, *parts: object) -> str:
    material = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]
    return f"{prefix}-{digest}"


def _media_kind(value: object, format_value: object) -> str:
    normalized = str(value or "").upper()
    if normalized in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        return normalized
    format_name = str(format_value or "").upper()
    if format_name in {"CBZ", "ZIP"}:
        return "COMIC"
    if format_name in {"M4B", "M4A", "MP3"}:
        return "AUDIOBOOK"
    return "EBOOK"


def _natural_key(value: object) -> tuple[tuple[int, object], ...]:
    parts = re.split(r"(\d+(?:\.\d+)?)", str(value or "").casefold())
    return tuple(
        (0, float(part)) if re.fullmatch(r"\d+(?:\.\d+)?", part) else (1, part)
        for part in parts
        if part
    )


def _json_object(value: object) -> dict[str, object]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _embedded_volume_id(value: object) -> str | None:
    parsed = _json_object(value)
    direct = parsed.get("volumeId")
    if isinstance(direct, str) and direct:
        return direct
    for key in ("location", "position", "extra"):
        nested = parsed.get(key)
        if isinstance(nested, dict):
            candidate = nested.get("volumeId")
            if isinstance(candidate, str) and candidate:
                return candidate
    return None


def _filename(path: object) -> str:
    return PurePosixPath(str(path or "").replace("\\", "/")).name


def _normalized_path(path: object) -> str:
    return str(path or "").replace("\\", "/").casefold()


def _title_without_extension(path: object) -> str:
    name = _filename(path)
    return PurePosixPath(name).stem or "正文"


def _canonical_edition(
    editions: list[RowMapping], primary_edition_id: object
) -> RowMapping:
    primary_id = str(primary_edition_id or "")
    return min(
        editions,
        key=lambda edition: (
            0 if str(edition["id"]) == primary_id else 1,
            0 if bool(edition["primary"]) else 1,
            0 if not bool(edition["hidden"]) else 1,
            edition["createdAt"],
            str(edition["id"]),
        ),
    )


def _record_event(
    connection: sa.Connection,
    events: sa.Table,
    *,
    work_id: str,
    record_type: str,
    record_id: str,
    code: str,
    details: dict[str, object],
) -> None:
    event_id = _id("media-migration-event", record_type, record_id, code)
    if connection.scalar(sa.select(events.c.id).where(events.c.id == event_id)):
        return
    connection.execute(
        sa.insert(events).values(
            id=event_id,
            workId=work_id,
            recordType=record_type,
            recordId=record_id,
            code=code,
            detailsJson=json.dumps(details, ensure_ascii=False, sort_keys=True),
            createdAt=datetime.now(UTC),
        )
    )


def _resolve_volume_id(
    *,
    location_value: object,
    content_fingerprint: object,
    candidate_volumes: list[RowMapping],
    files: list[RowMapping],
) -> tuple[str, str | None]:
    volume_ids = {str(volume["id"]) for volume in candidate_volumes}
    embedded = _embedded_volume_id(location_value)
    if embedded in volume_ids:
        return embedded, None

    fingerprint = str(content_fingerprint or "")
    if fingerprint:
        matched = {
            str(file["volumeId"])
            for file in files
            if file["volumeId"] is not None
            and fingerprint
            in {
                str(file["fingerprint"] or ""),
                str(file["fullHash"] or ""),
            }
        }
        if len(matched) == 1:
            return matched.pop(), None

    if len(candidate_volumes) == 1:
        return str(candidate_volumes[0]["id"]), None
    first = min(
        candidate_volumes,
        key=lambda volume: (
            int(volume["sortOrder"] or 0),
            str(volume["createdAt"]),
            str(volume["id"]),
        ),
    )
    return str(first["id"]), "AMBIGUOUS_FALLBACK_TO_FIRST_VOLUME"


def _first_volume_id(volumes: list[RowMapping]) -> str:
    return _resolve_volume_id(
        location_value=None,
        content_fingerprint=None,
        candidate_volumes=volumes,
        files=[],
    )[0]


def _collapse_duplicate_progress(
    connection: sa.Connection,
    tables: dict[str, sa.Table],
    *,
    work_id: str,
) -> None:
    """Preserve the newest state when legacy NULL volume rows converge."""

    progress_table = tables["LibraryReadingProgress"]
    rows = list(
        connection.execute(
            sa.select(progress_table)
            .where(progress_table.c.workId == work_id)
            .order_by(
                progress_table.c.userId,
                progress_table.c.volumeId,
                progress_table.c.updatedAt.desc(),
                progress_table.c.createdAt.desc(),
                progress_table.c.id.desc(),
            )
        ).mappings()
    )
    kept_by_scope: dict[tuple[str, str], str] = {}
    for row in rows:
        scope = (str(row["userId"]), str(row["volumeId"]))
        kept_id = kept_by_scope.get(scope)
        if kept_id is None:
            kept_by_scope[scope] = str(row["id"])
            continue
        _record_event(
            connection,
            tables["MediaVersionMigrationEvent"],
            work_id=work_id,
            record_type="READING_PROGRESS",
            record_id=str(row["id"]),
            code="DUPLICATE_PROGRESS_COLLAPSED",
            details={
                "keptProgressId": kept_id,
                "selectedVolumeId": str(row["volumeId"]),
            },
        )
        connection.execute(
            sa.delete(progress_table).where(progress_table.c.id == row["id"])
        )


def _backfill_work(
    connection: sa.Connection,
    tables: dict[str, sa.Table],
    work: RowMapping,
) -> None:
    editions_table = tables["LibraryEdition"]
    volumes_table = tables["LibraryVolume"]
    files_table = tables["LibraryFile"]
    editions = list(
        connection.execute(
            sa.select(editions_table).where(editions_table.c.workId == work["id"])
        ).mappings()
    )
    if not editions:
        return

    by_kind: dict[str, list[RowMapping]] = {}
    for edition in editions:
        kind = _media_kind(edition["mediaKind"], edition["format"])
        by_kind.setdefault(kind, []).append(edition)

    edition_to_media_version: dict[str, str] = {}
    for media_kind, kind_editions in by_kind.items():
        canonical = _canonical_edition(kind_editions, work["primaryEditionId"])
        media_version_id = str(canonical["id"])
        edition_to_media_version.update(
            {str(edition["id"]): media_version_id for edition in kind_editions}
        )
        exists = connection.scalar(
            sa.select(tables["LibraryMediaVersion"].c.id).where(
                tables["LibraryMediaVersion"].c.id == media_version_id
            )
        )
        if not exists:
            connection.execute(
                sa.insert(tables["LibraryMediaVersion"]).values(
                    id=media_version_id,
                    workId=work["id"],
                    mediaKind=media_kind,
                    createdAt=canonical["createdAt"],
                    updatedAt=canonical["updatedAt"],
                )
            )

    edition_volume_rows: dict[str, list[RowMapping]] = {}
    for edition in editions:
        edition_id = str(edition["id"])
        existing_volumes = list(
            connection.execute(
                sa.select(volumes_table).where(volumes_table.c.editionId == edition_id)
            ).mappings()
        )
        edition_files = list(
            connection.execute(
                sa.select(files_table).where(files_table.c.editionId == edition_id)
            ).mappings()
        )
        if not existing_volumes:
            volume_id = _id("migration-volume", edition_id)
            version_name = str(edition["versionName"] or "").strip()
            title = (
                version_name
                if version_name.casefold() not in PLACEHOLDER_TITLES
                else _title_without_extension(edition_files[0]["path"])
                if edition_files
                else "正文"
            )
            connection.execute(
                sa.insert(volumes_table).values(
                    id=volume_id,
                    editionId=edition_id,
                    mediaVersionId=edition_to_media_version[edition_id],
                    monitorFolderId=edition["monitorFolderId"],
                    origin=edition["origin"] or "MANUAL",
                    title=title,
                    volumeIndex=None,
                    sortOrder=0,
                    format=str(edition["format"] or "UNKNOWN").upper(),
                    resourceKey=f"migration:{edition_id}:{volume_id}",
                    sourceGroupKey=edition["sourceGroupKey"],
                    description=edition["description"],
                    language=edition["language"],
                    publisher=edition["publisher"],
                    publishedAt=edition["publishedAt"],
                    identifier=edition["identifier"],
                    isbn=edition["isbn"],
                    importStatus=edition["importStatus"] or "READY",
                    importError=edition["importError"],
                    sizeBytes=edition["sizeBytes"] or 0,
                    pageCount=edition["pageCount"],
                    chapterCount=edition["chapterCount"],
                    durationMs=edition["durationMs"],
                    trackCount=edition["trackCount"],
                    narrator=edition["narrator"],
                    abridged=edition["abridged"],
                    coverPath=edition["coverPath"],
                    coverStatus=edition["coverStatus"] or "PENDING",
                    hidden=edition["hidden"] or False,
                    createdAt=edition["createdAt"],
                    updatedAt=edition["updatedAt"],
                )
            )
            existing_volumes = list(
                connection.execute(
                    sa.select(volumes_table).where(volumes_table.c.id == volume_id)
                ).mappings()
            )

        for volume in existing_volumes:
            current_title = str(volume["title"] or "").strip()
            version_name = str(edition["versionName"] or "").strip()
            migrated_title = (
                version_name
                if len(existing_volumes) == 1
                and current_title.casefold() in PLACEHOLDER_TITLES
                and version_name.casefold() not in PLACEHOLDER_TITLES
                else current_title or version_name or "正文"
            )
            connection.execute(
                sa.update(volumes_table)
                .where(volumes_table.c.id == volume["id"])
                .values(
                    mediaVersionId=edition_to_media_version[edition_id],
                    monitorFolderId=edition["monitorFolderId"],
                    origin=edition["origin"] or "MANUAL",
                    title=migrated_title,
                    format=str(edition["format"] or "UNKNOWN").upper(),
                    resourceKey=volume["resourceKey"]
                    or f"migration:{edition_id}:{volume['id']}",
                    sourceGroupKey=edition["sourceGroupKey"],
                    description=edition["description"],
                    language=edition["language"],
                    publisher=edition["publisher"],
                    publishedAt=edition["publishedAt"],
                    identifier=edition["identifier"],
                    isbn=edition["isbn"],
                    importStatus=edition["importStatus"] or "READY",
                    importError=edition["importError"],
                    sizeBytes=edition["sizeBytes"] or 0,
                    pageCount=volume["pageCount"] or edition["pageCount"],
                    chapterCount=volume["chapterCount"] or edition["chapterCount"],
                    durationMs=volume["durationMs"] or edition["durationMs"],
                    trackCount=edition["trackCount"],
                    narrator=edition["narrator"],
                    abridged=edition["abridged"],
                    coverPath=volume["coverPath"] or edition["coverPath"],
                    coverStatus=edition["coverStatus"] or "PENDING",
                    hidden=edition["hidden"] or False,
                )
            )

        refreshed = list(
            connection.execute(
                sa.select(volumes_table).where(volumes_table.c.editionId == edition_id)
            ).mappings()
        )
        version_name = str(edition["versionName"] or "").strip()
        if version_name.casefold() not in PLACEHOLDER_TITLES and not (
            len(refreshed) == 1
            and str(refreshed[0]["title"] or "").strip() == version_name
        ):
            _record_event(
                connection,
                tables["MediaVersionMigrationEvent"],
                work_id=str(work["id"]),
                record_type="EDITION",
                record_id=edition_id,
                code="LEGACY_VERSION_NAME_ARCHIVED",
                details={"legacyVersionName": version_name},
            )
        edition_volume_rows[edition_id] = refreshed
        default_volume_id = str(
            min(
                refreshed,
                key=lambda volume: (
                    int(volume["sortOrder"] or 0),
                    str(volume["createdAt"]),
                    str(volume["id"]),
                ),
            )["id"]
        )
        connection.execute(
            sa.update(files_table)
            .where(
                files_table.c.editionId == edition_id,
                files_table.c.volumeId.is_(None),
            )
            .values(volumeId=default_volume_id)
        )
        connection.execute(
            sa.update(tables["LibraryReadingUnit"])
            .where(
                tables["LibraryReadingUnit"].c.editionId == edition_id,
                tables["LibraryReadingUnit"].c.volumeId.is_(None),
            )
            .values(volumeId=default_volume_id)
        )

        for facet in connection.execute(
            sa.select(tables["LibraryEditionFacet"]).where(
                tables["LibraryEditionFacet"].c.editionId == edition_id
            )
        ).mappings():
            for volume in refreshed:
                exists = connection.scalar(
                    sa.select(tables["LibraryVolumeFacet"].c.volumeId).where(
                        tables["LibraryVolumeFacet"].c.facetId == facet["facetId"],
                        tables["LibraryVolumeFacet"].c.volumeId == volume["id"],
                    )
                )
                if not exists:
                    connection.execute(
                        sa.insert(tables["LibraryVolumeFacet"]).values(
                            facetId=facet["facetId"],
                            volumeId=volume["id"],
                            createdAt=facet["createdAt"],
                        )
                    )

    for media_version_id in set(edition_to_media_version.values()):
        media_volumes = list(
            connection.execute(
                sa.select(volumes_table).where(
                    volumes_table.c.mediaVersionId == media_version_id
                )
            ).mappings()
        )
        ordered = sorted(
            media_volumes,
            key=lambda volume: (
                volume["volumeIndex"] is None,
                float(volume["volumeIndex"] or 0),
                _natural_key(volume["title"]),
                str(volume["createdAt"]),
                str(volume["id"]),
            ),
        )
        for sort_order, volume in enumerate(ordered):
            connection.execute(
                sa.update(volumes_table)
                .where(volumes_table.c.id == volume["id"])
                .values(sortOrder=sort_order)
            )

    all_files = list(
        connection.execute(
            sa.select(files_table).where(
                files_table.c.editionId.in_(edition_to_media_version)
            )
        ).mappings()
    )
    all_work_volumes = [
        volume for volumes in edition_volume_rows.values() for volume in volumes
    ]
    for progress in connection.execute(
        sa.select(tables["LibraryReadingProgress"]).where(
            tables["LibraryReadingProgress"].c.workId == work["id"]
        )
    ).mappings():
        if progress["volumeId"] is not None:
            continue
        edition_id = str(progress["editionId"] or "")
        candidate_volumes = edition_volume_rows.get(edition_id) or all_work_volumes
        candidate_files = (
            [file for file in all_files if str(file["editionId"]) == edition_id]
            if edition_id in edition_volume_rows
            else all_files
        )
        volume_id, ambiguity = _resolve_volume_id(
            location_value=progress["position"],
            content_fingerprint=progress["contentFingerprint"],
            candidate_volumes=candidate_volumes,
            files=candidate_files,
        )
        connection.execute(
            sa.update(tables["LibraryReadingProgress"])
            .where(tables["LibraryReadingProgress"].c.id == progress["id"])
            .values(volumeId=volume_id)
        )
        if ambiguity:
            _record_event(
                connection,
                tables["MediaVersionMigrationEvent"],
                work_id=str(work["id"]),
                record_type="READING_PROGRESS",
                record_id=str(progress["id"]),
                code=ambiguity,
                details={
                    "legacyEditionId": edition_id or None,
                    "selectedVolumeId": volume_id,
                },
            )

    _collapse_duplicate_progress(
        connection,
        tables,
        work_id=str(work["id"]),
    )

    for bookmark in connection.execute(
        sa.select(tables["ReaderBookmark"]).where(
            tables["ReaderBookmark"].c.workId == work["id"]
        )
    ).mappings():
        if bookmark["volumeId"] is not None:
            continue
        edition_id = str(bookmark["editionId"] or "")
        candidate_volumes = edition_volume_rows.get(edition_id) or all_work_volumes
        candidate_files = (
            [file for file in all_files if str(file["editionId"]) == edition_id]
            if edition_id in edition_volume_rows
            else all_files
        )
        volume_id, ambiguity = _resolve_volume_id(
            location_value=bookmark["locationJson"],
            content_fingerprint=bookmark["contentFingerprint"],
            candidate_volumes=candidate_volumes,
            files=candidate_files,
        )
        connection.execute(
            sa.update(tables["ReaderBookmark"])
            .where(tables["ReaderBookmark"].c.id == bookmark["id"])
            .values(volumeId=volume_id)
        )
        if ambiguity:
            _record_event(
                connection,
                tables["MediaVersionMigrationEvent"],
                work_id=str(work["id"]),
                record_type="BOOKMARK",
                record_id=str(bookmark["id"]),
                code=ambiguity,
                details={
                    "legacyEditionId": edition_id or None,
                    "selectedVolumeId": volume_id,
                },
            )

    for metadata_item in connection.execute(
        sa.select(tables["LibraryMetadata"]).where(
            tables["LibraryMetadata"].c.editionId.in_(edition_to_media_version)
        )
    ).mappings():
        if metadata_item["volumeId"] is not None:
            continue
        edition_id = str(metadata_item["editionId"] or "")
        raw = _json_object(metadata_item["rawJson"])
        source_name = raw.get("sourcePath") or raw.get("sourceFileName")
        edition_files = [
            file for file in all_files if str(file["editionId"]) == edition_id
        ]
        exact_ids = {
            str(file["volumeId"])
            for file in edition_files
            if source_name
            and _normalized_path(file["path"]) == _normalized_path(source_name)
        }
        filename_ids = {
            str(file["volumeId"])
            for file in edition_files
            if source_name and _filename(file["path"]) == _filename(source_name)
        }
        matched_ids = exact_ids if len(exact_ids) == 1 else filename_ids
        selected = (
            next(iter(matched_ids))
            if len(matched_ids) == 1
            else _first_volume_id(
                edition_volume_rows.get(edition_id) or all_work_volumes
            )
        )
        connection.execute(
            sa.update(tables["LibraryMetadata"])
            .where(tables["LibraryMetadata"].c.id == metadata_item["id"])
            .values(volumeId=selected)
        )
        if source_name and len(matched_ids) != 1:
            _record_event(
                connection,
                tables["MediaVersionMigrationEvent"],
                work_id=str(work["id"]),
                record_type="METADATA",
                record_id=str(metadata_item["id"]),
                code="AMBIGUOUS_METADATA_FALLBACK_TO_FIRST_VOLUME",
                details={
                    "source": str(source_name),
                    "candidateVolumeIds": sorted(matched_ids),
                    "selectedVolumeId": selected,
                },
            )

    for table_name in (
        "ImportTask",
        "KindleSendTask",
        "OrganizeJob",
        "MetadataLookupTask",
    ):
        table = tables[table_name]
        if "editionId" not in table.c or "volumeId" not in table.c:
            continue
        for edition_id, volume_rows in edition_volume_rows.items():
            default_id = _first_volume_id(volume_rows)
            connection.execute(
                sa.update(table)
                .where(table.c.editionId == edition_id, table.c.volumeId.is_(None))
                .values(volumeId=default_id)
            )

    for state in connection.execute(
        sa.select(tables["LibraryConsumptionState"]).where(
            tables["LibraryConsumptionState"].c.workId == work["id"]
        )
    ).mappings():
        candidate_edition = str(state["lastEditionId"] or "")
        media_version_id = edition_to_media_version.get(candidate_edition)
        if media_version_id is None:
            candidates = by_kind.get(_media_kind(state["mediaKind"], None), [])
            if not candidates:
                continue
            media_version_id = edition_to_media_version[str(candidates[0]["id"])]
            candidate_edition = str(candidates[0]["id"])
        last_volume_id = state["lastVolumeId"]
        if last_volume_id is None:
            last_volume_id = edition_volume_rows[candidate_edition][0]["id"]
        history_id = _id("user-media-history", state["userId"], media_version_id)
        exists = connection.scalar(
            sa.select(tables["UserMediaHistory"].c.id).where(
                tables["UserMediaHistory"].c.id == history_id
            )
        )
        values = {
            "lastVolumeId": last_volume_id,
            "updatedAt": state["updatedAt"],
        }
        if exists:
            connection.execute(
                sa.update(tables["UserMediaHistory"])
                .where(tables["UserMediaHistory"].c.id == history_id)
                .values(**values)
            )
        else:
            connection.execute(
                sa.insert(tables["UserMediaHistory"]).values(
                    id=history_id,
                    userId=state["userId"],
                    mediaVersionId=media_version_id,
                    createdAt=state["createdAt"],
                    **values,
                )
            )

    for conversion in connection.execute(
        sa.select(tables["BookConversionTask"])
    ).mappings():
        if conversion["sourceVolumeId"] is not None:
            continue
        import_volume = connection.scalar(
            sa.select(tables["ImportTask"].c.volumeId).where(
                tables["ImportTask"].c.id == conversion["importTaskId"]
            )
        )
        if import_volume is None:
            continue
        source_hash = str(conversion["sourceHash"] or "missing")
        target_format = str(conversion["targetFormat"] or "EPUB").upper()
        connection.execute(
            sa.update(tables["BookConversionTask"])
            .where(tables["BookConversionTask"].c.id == conversion["id"])
            .values(
                sourceVolumeId=import_volume,
                idempotencyKey=f"{import_volume}:{source_hash}:{target_format}",
            )
        )


def upgrade() -> None:
    connection = op.get_bind()
    legacy_progress_index = "LibraryReadingProgress_userId_editionId_volumeId_key"
    progress_indexes = {
        index["name"]
        for index in sa.inspect(connection).get_indexes("LibraryReadingProgress")
    }
    if legacy_progress_index in progress_indexes:
        op.drop_index(
            legacy_progress_index,
            table_name="LibraryReadingProgress",
        )
    metadata = sa.MetaData()
    names = (
        "LibraryWork",
        "LibraryEdition",
        "LibraryMediaVersion",
        "LibraryVolume",
        "LibraryFile",
        "LibraryReadingUnit",
        "LibraryMetadata",
        "LibraryReadingProgress",
        "ReaderBookmark",
        "LibraryEditionFacet",
        "LibraryVolumeFacet",
        "LibraryConsumptionState",
        "UserMediaHistory",
        "ImportTask",
        "KindleSendTask",
        "OrganizeJob",
        "MetadataLookupTask",
        "BookConversionTask",
        "MediaVersionMigrationCheckpoint",
        "MediaVersionMigrationEvent",
    )
    tables = {
        name: sa.Table(name, metadata, autoload_with=connection) for name in names
    }

    while True:
        completed = sa.select(tables["MediaVersionMigrationCheckpoint"].c.workId)
        work_batch = list(
            connection.execute(
                sa.select(tables["LibraryWork"])
                .where(tables["LibraryWork"].c.id.not_in(completed))
                .order_by(
                    tables["LibraryWork"].c.createdAt,
                    tables["LibraryWork"].c.id,
                )
                .limit(BATCH_SIZE)
            ).mappings()
        )
        if not work_batch:
            break
        for work in work_batch:
            _backfill_work(connection, tables, work)
            connection.execute(
                sa.insert(tables["MediaVersionMigrationCheckpoint"]).values(
                    workId=work["id"], completedAt=datetime.now(UTC)
                )
            )


def downgrade() -> None:
    # Data remains available through the legacy columns retained by the expand revision.
    pass
