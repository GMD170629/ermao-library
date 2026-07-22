from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from time import time_ns
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.auth import get_current_user
from app.core.config import Settings, get_settings
from app.core.time import timestamp_ms_to_datetime
from app.db.session import get_db
from app.schemas.reader_v2 import (
    AudioChapterSummary,
    AudioLocation,
    AudioTrackSummary,
    ComicLocation,
    EpubLocationsClaimRequest,
    EpubLocationsSaveRequest,
    EpubLocation,
    PdfLocation,
    ReaderBookSummary,
    ReaderBootstrapData,
    ReaderBootstrapResponse,
    ReaderCapabilities,
    ReaderEditionOption,
    ReaderEditionSummary,
    ReaderPageSummary,
    ReaderPreferences,
    ReaderProgressData,
    ReaderProgressPut,
    ReaderProgressRecord,
    ReaderProgressResponse,
    ReaderServerPreferences,
    ReaderUnitSummary,
    ReaderVolumeSummary,
)
from app.schemas.responses import fail
from app.services.epub_location_cache import claim_epub_locations, save_epub_locations


router = APIRouter(prefix="/reader/v2", tags=["reader-v2"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _auth(db: Session, request: Request, settings: Settings):
    user, _token, _refresh = get_current_user(db, request, settings)
    if user is None:
        return None, fail("UNAUTHORIZED", status_code=401)
    return user, None


def _tables(db: Session) -> set[str]:
    # Introspect through the Session connection. On SQLite StaticPool,
    # checking the Engine back in during an open progress transaction can
    # roll that transaction back.
    return set(inspect(db.connection()).get_table_names())


def _columns(db: Session, table: str) -> set[str]:
    if table not in _tables(db):
        return set()
    return {column["name"] for column in inspect(db.connection()).get_columns(table)}


def _row(db: Session, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    result = db.execute(text(sql), params or {}).mappings().first()
    return dict(result) if result else None


def _rows(db: Session, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return [dict(row) for row in db.execute(text(sql), params or {}).mappings().all()]


def _json(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    return timestamp_ms_to_datetime(value)


def _reader_format(value: Any) -> str | None:
    normalized = str(value or "").lower()
    return {"epub": "epub", "ebook": "epub", "comic": "comic", "pdf": "pdf", "audio": "audio", "audiobook": "audio"}.get(normalized)


def _clamp(value: Any, minimum: float, maximum: float, fallback: float) -> float:
    try:
        return min(maximum, max(minimum, float(value)))
    except (TypeError, ValueError):
        return fallback


def _mark_work_reading_started(db: Session, work_id: str, now: datetime | None = None) -> bool:
    """Advance only unread works; reopening a finished work must not regress it."""

    result = db.execute(
        text(
            "UPDATE `LibraryWork` SET `status` = 'READING', `updatedAt` = :now "
            "WHERE `id` = :work_id AND `status` IN ('UNREAD', 'WANT')"
        ),
        {"work_id": work_id, "now": now or _now()},
    )
    return int(result.rowcount or 0) > 0


def _edition_media_kind(edition: dict[str, Any]) -> str:
    stored = str(edition.get("mediaKind") or "").strip().upper()
    if stored in {"EBOOK", "COMIC", "AUDIOBOOK"}:
        return stored
    reader_format = _reader_format(edition.get("format"))
    return "AUDIOBOOK" if reader_format == "audio" else "COMIC" if reader_format == "comic" else "EBOOK"


def _upsert_consumption_state(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    edition: dict[str, Any],
    status: str,
    volume_id: str | None = None,
    unit_id: str | None = None,
    preserve_finished: bool = False,
    now: datetime | None = None,
) -> None:
    if "LibraryConsumptionState" not in _tables(db):
        return
    media_kind = _edition_media_kind(edition)
    existing = _row(
        db,
        "SELECT * FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :work_id AND `mediaKind` = :media_kind",
        {"user_id": user_id, "work_id": work_id, "media_kind": media_kind},
    )
    resolved_status = "FINISHED" if preserve_finished and (existing or {}).get("status") == "FINISHED" else status
    timestamp = now or _now()
    values = {
        "status": resolved_status,
        "lastEditionId": str(edition["id"]),
        "lastVolumeId": volume_id,
        "lastUnitId": unit_id,
        "updatedAt": timestamp,
    }
    if existing:
        assignments = ", ".join(f"`{key}` = :{key}" for key in values)
        db.execute(text(f"UPDATE `LibraryConsumptionState` SET {assignments} WHERE `id` = :row_id"), {**values, "row_id": existing["id"]})
    else:
        db.execute(
            text(
                "INSERT INTO `LibraryConsumptionState` "
                "(`id`, `userId`, `workId`, `mediaKind`, `status`, `lastEditionId`, `lastVolumeId`, `lastUnitId`, `createdAt`, `updatedAt`) "
                "VALUES (:id, :user_id, :work_id, :media_kind, :status, :lastEditionId, :lastVolumeId, :lastUnitId, :now, :now)"
            ),
            {
                "id": f"consume_{time_ns()}",
                "user_id": user_id,
                "work_id": work_id,
                "media_kind": media_kind,
                "now": timestamp,
                **values,
            },
        )


def _project_work_status(db: Session, user_id: str, work_id: str, now: datetime) -> None:
    if "LibraryConsumptionState" not in _tables(db):
        return
    editions = _rows(db, "SELECT * FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0", {"work_id": work_id})
    kinds = {_edition_media_kind(item) for item in editions}
    states = {
        str(item.get("mediaKind")): str(item.get("status") or "UNREAD").upper()
        for item in _rows(
            db,
            "SELECT `mediaKind`, `status` FROM `LibraryConsumptionState` WHERE `userId` = :user_id AND `workId` = :work_id",
            {"user_id": user_id, "work_id": work_id},
        )
    }
    projected = (
        "FINISHED"
        if kinds and all(states.get(kind) == "FINISHED" for kind in kinds)
        else "READING"
        if any(states.get(kind) in {"READING", "FINISHED"} for kind in kinds)
        else "UNREAD"
    )
    db.execute(text("UPDATE `LibraryWork` SET `status` = :status, `updatedAt` = :now WHERE `id` = :work_id"), {"status": projected, "now": now, "work_id": work_id})


def _is_final_volume(db: Session, edition_id: str, volume_id: str | None) -> bool:
    if "LibraryVolume" not in _tables(db):
        return True
    volumes = _rows(
        db,
        "SELECT `id` FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder`, `id`",
        {"edition_id": edition_id},
    )
    if not volumes:
        return True
    return volume_id is not None and str(volumes[-1]["id"]) == volume_id


def _advance_work_status_for_progress(
    db: Session,
    *,
    user_id: str,
    edition: dict[str, Any],
    work_id: str,
    completed: bool,
    volume_id: str | None,
    unit_id: str | None,
    now: datetime,
) -> None:
    if "LibraryConsumptionState" not in _tables(db):
        if completed:
            db.execute(
                text("UPDATE `LibraryWork` SET `status` = 'FINISHED', `updatedAt` = :now WHERE `id` = :work_id"),
                {"work_id": work_id, "now": now},
            )
        else:
            _mark_work_reading_started(db, work_id, now)
        return
    _upsert_consumption_state(
        db,
        user_id=user_id,
        work_id=work_id,
        edition=edition,
        status="FINISHED" if completed else "READING",
        volume_id=volume_id,
        unit_id=unit_id,
        preserve_finished=True,
        now=now,
    )
    _project_work_status(db, user_id, work_id, now)


def _legacy_preferences(db: Session, user_id: str, reader_format: str) -> ReaderPreferences:
    defaults = ReaderPreferences()
    if "ReaderPreference" not in _tables(db):
        return defaults
    rows = _rows(db, "SELECT * FROM `ReaderPreference` WHERE `userId` = :user_id", {"user_id": user_id})
    by_type: dict[str, dict[str, Any]] = {}
    for row in rows:
        parsed = _json(row.get("settings"), {})
        by_type[str(row.get("readerType") or "").lower()] = parsed if isinstance(parsed, dict) else {}
    epub = by_type.get("epub") or by_type.get("ebook") or {}
    comic = by_type.get("comic") or {}
    pdf = by_type.get("pdf") or {}
    current = {"epub": epub, "comic": comic, "pdf": pdf}.get(reader_format, {})
    payload = defaults.model_dump()

    theme = current.get("theme")
    if theme in {"day", "warm", "night", "black"}:
        payload["appearance"]["theme"] = theme

    payload["epub"]["font_size"] = int(_clamp(epub.get("fontSize"), 14, 30, payload["epub"]["font_size"]))
    payload["epub"]["line_height"] = _clamp(epub.get("lineHeight"), 1.4, 2.4, payload["epub"]["line_height"])
    payload["epub"]["page_width"] = int(_clamp(epub.get("pageWidth"), 600, 1350, payload["epub"]["page_width"]))
    if epub.get("fontFamily") in {"pingfang", "heiti", "songti", "yahei", "kaiti"}:
        payload["epub"]["font_family"] = epub["fontFamily"]
    legacy_animation = epub.get("pageTurnAnimation") or epub.get("ebookPageTurnAnimation")
    if legacy_animation in {"kindle", "slide", "off"}:
        payload["epub"]["page_turn_animation"] = "slide" if legacy_animation == "kindle" else legacy_animation
    if epub.get("spreadMode") in {"single", "double"}:
        payload["epub"]["spread_mode"] = epub["spreadMode"]
    legacy_flow = epub.get("flow") or epub.get("layout")
    if legacy_flow in {"paginated", "scrolled"}:
        payload["epub"]["flow"] = legacy_flow

    if comic.get("comicDirection") in {"ltr", "rtl"}:
        payload["comic"]["direction"] = comic["comicDirection"]
    if comic.get("comicMode") in {"single", "double"}:
        payload["comic"]["mode"] = comic["comicMode"]
    if comic.get("pageTurnAnimation") in {"slide", "off"}:
        payload["comic"]["page_turn_animation"] = comic["pageTurnAnimation"]
    if comic.get("imageFit") in {"width", "height", "contain", "original"}:
        payload["comic"]["image_fit"] = comic["imageFit"]
    if comic.get("imageVariant") in {"original", "data-saver"}:
        payload["comic"]["image_variant"] = comic["imageVariant"]
    payload["comic"]["zoom"] = _clamp(comic.get("zoom"), 0.6, 2.4, payload["comic"]["zoom"])

    payload["pdf"]["zoom"] = _clamp(pdf.get("zoom"), 0.6, 2.4, payload["pdf"]["zoom"])
    legacy_fit = pdf.get("fit") or pdf.get("fitMode")
    if legacy_fit in {"width", "page"}:
        payload["pdf"]["fit"] = legacy_fit
    return ReaderPreferences.model_validate(payload)


def _delete_dict_path(value: dict[str, Any], location: tuple[Any, ...]) -> bool:
    if not location:
        return False
    cursor: Any = value
    for segment in location[:-1]:
        if not isinstance(cursor, dict) or segment not in cursor:
            return False
        cursor = cursor[segment]
    leaf = location[-1]
    if not isinstance(cursor, dict) or leaf not in cursor:
        return False
    del cursor[leaf]
    return True


def _recover_stored_preferences(value: object) -> ReaderPreferences | None:
    """Remove only invalid stored fields, preserving valid per-work choices."""

    if not isinstance(value, dict):
        return None
    candidate = deepcopy(value)
    while True:
        try:
            return ReaderPreferences.model_validate(candidate)
        except ValidationError as error:
            changed = False
            for detail in error.errors():
                location = detail.get("loc")
                if isinstance(location, tuple):
                    changed = _delete_dict_path(candidate, location) or changed
            if not changed:
                return None


def _book_preferences(db: Session, user_id: str, work_id: str, reader_format: str) -> tuple[ReaderPreferences, datetime | None]:
    if "ReaderBookPreference" not in _tables(db):
        return _legacy_preferences(db, user_id, reader_format), None
    existing = _row(
        db,
        "SELECT * FROM `ReaderBookPreference` WHERE `userId` = :user_id AND `workId` = :work_id",
        {"user_id": user_id, "work_id": work_id},
    )
    if existing:
        stored_preferences = _json(existing.get("preferences"), None)
        preferences = _recover_stored_preferences(stored_preferences)
        if preferences is None:
            preferences = _legacy_preferences(db, user_id, reader_format)
        canonical_preferences = preferences.model_dump(by_alias=True, mode="json")
        if existing.get("schemaVersion") != 3 or stored_preferences != canonical_preferences:
            updates = {"schemaVersion": 3, "preferences": _json_text(canonical_preferences)}
            allowed = _columns(db, "ReaderBookPreference")
            filtered = {key: value for key, value in updates.items() if key in allowed}
            assignments = ", ".join(f"`{key}` = :{key}" for key in filtered)
            if assignments:
                db.execute(
                    text(f"UPDATE `ReaderBookPreference` SET {assignments} WHERE `id` = :preference_id"),
                    {**filtered, "preference_id": existing["id"]},
                )
                db.commit()
        return preferences, _datetime(existing.get("updatedAt"))

    preferences = _legacy_preferences(db, user_id, reader_format)
    now = _now()
    values = {
        "id": f"py_{time_ns()}",
        "userId": user_id,
        "workId": work_id,
        "schemaVersion": 3,
        "preferences": _json_text(preferences.model_dump(by_alias=True, mode="json")),
        "createdAt": now,
        "updatedAt": now,
    }
    allowed = _columns(db, "ReaderBookPreference")
    filtered = {key: value for key, value in values.items() if key in allowed}
    keys = ", ".join(f"`{key}`" for key in filtered)
    placeholders = ", ".join(f":{key}" for key in filtered)
    try:
        db.execute(text(f"INSERT INTO `ReaderBookPreference` ({keys}) VALUES ({placeholders})"), filtered)
        db.commit()
    except IntegrityError:
        # Concurrent bootstraps can race to seed the same (user, work) row.
        # The unique key selects the winner and the loser reads that snapshot.
        db.rollback()
        winner = _row(
            db,
            "SELECT * FROM `ReaderBookPreference` WHERE `userId` = :user_id AND `workId` = :work_id",
            {"user_id": user_id, "work_id": work_id},
        )
        if not winner:
            raise
        winner_preferences = _recover_stored_preferences(_json(winner.get("preferences"), None))
        return (
            winner_preferences or _legacy_preferences(db, user_id, reader_format),
            _datetime(winner.get("updatedAt")),
        )
    return preferences, now


def _content_fingerprint(db: Session, edition: dict[str, Any], volume_id: str | None) -> str:
    files: list[dict[str, Any]] = []
    if "LibraryFile" in _tables(db):
        if volume_id:
            files = _rows(
                db,
                "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id AND `volumeId` = :volume_id ORDER BY `sortOrder`, `id`",
                {"edition_id": edition["id"], "volume_id": volume_id},
            )
        if not files:
            files = _rows(
                db,
                "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder`, `id`",
                {"edition_id": edition["id"]},
            )
    tokens = [
        {
            "id": file.get("id"),
            # Prefer the import-time fingerprint so a later full-hash backfill
            # does not invalidate an otherwise unchanged reader session.
            "hash": file.get("fingerprint") or file.get("fullHash"),
            "size": file.get("sizeBytes"),
            "mtime": file.get("mtimeMs"),
        }
        for file in files
    ]
    if not tokens:
        tokens = [{"edition": edition.get("id"), "updated": str(edition.get("updatedAt") or ""), "volume": volume_id}]
    digest = hashlib.sha256(_json_text(tokens).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _volume_summary(volume: dict[str, Any]) -> ReaderVolumeSummary:
    return ReaderVolumeSummary(
        id=str(volume["id"]),
        title=str(volume.get("title") or "未命名卷"),
        index=float(volume.get("volumeIndex") if volume.get("volumeIndex") is not None else volume.get("sortOrder") or 0),
        pageCount=volume.get("pageCount"),
        chapterCount=volume.get("chapterCount"),
        durationMs=volume.get("durationMs"),
    )


def _edition_summary(edition: dict[str, Any]) -> ReaderEditionSummary:
    reader_format = _reader_format(edition.get("format")) or "epub"
    media_kind = str(edition.get("mediaKind") or "").upper() or ("AUDIOBOOK" if reader_format == "audio" else "COMIC" if reader_format == "comic" else "EBOOK")
    return ReaderEditionSummary(
        id=str(edition["id"]),
        workId=str(edition["workId"]),
        format=reader_format,
        versionName=str(edition.get("versionName") or "默认版本"),
        pageCount=edition.get("pageCount"),
        chapterCount=edition.get("chapterCount"),
        mediaKind=media_kind,
        durationMs=edition.get("durationMs"),
        trackCount=edition.get("trackCount"),
        narrator=edition.get("narrator"),
    )


def _capabilities(reader_format: str, reading_direction: str = "ltr") -> ReaderCapabilities:
    return ReaderCapabilities(
        canGoNext=True,
        canGoPrevious=True,
        canJumpToProgress=True,
        canJumpToHref=reader_format == "epub",
        canJumpToIndex=True,
        canZoom=reader_format in {"comic", "pdf"},
        canSelectText=reader_format in {"epub", "pdf"},
        supportsPagination=reader_format != "audio",
        supportsScrolling=reader_format == "epub",
        supportsSpreads=reader_format in {"epub", "comic"},
        readingDirection=reading_direction,
    )


def _select_volume(volumes: list[dict[str, Any]], progresses: list[dict[str, Any]], requested: str | None) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    if requested:
        selected = next((volume for volume in volumes if str(volume.get("id")) == requested), None)
        if selected is None:
            return None, fail("卷册不存在", status_code=404)
        return selected, None
    latest_volume_id = next((row.get("volumeId") for row in progresses if row.get("volumeId")), None)
    selected = next((volume for volume in volumes if volume.get("id") == latest_volume_id), None)
    return selected or (volumes[0] if volumes else None), None


def _location_from_progress(
    progress: dict[str, Any] | None,
    reader_format: str,
    selected_volume_id: str | None = None,
):
    if not progress:
        return None
    parsed = _json(progress.get("locationJson"), None)
    if isinstance(parsed, dict):
        try:
            if parsed.get("type") == "epub":
                return EpubLocation.model_validate(parsed)
            if parsed.get("type") == "comic":
                volume_id = parsed.get("volumeId") or progress.get("volumeId") or selected_volume_id
                if volume_id:
                    return ComicLocation.model_validate({**parsed, "volumeId": str(volume_id)})
            if parsed.get("type") == "pdf":
                return PdfLocation.model_validate(parsed)
            if parsed.get("type") == "audio":
                volume_id = parsed.get("volumeId") or progress.get("volumeId") or selected_volume_id
                return AudioLocation.model_validate({**parsed, "volumeId": volume_id})
        except ValidationError:
            pass
    extra = _json(progress.get("extra"), {})
    if reader_format == "epub":
        cfi = extra.get("cfi") or progress.get("position")
        href = extra.get("currentHref") or extra.get("chapterHref")
        spine_index = max(0, extra["sectionIndex"]) if isinstance(extra.get("sectionIndex"), int) else None
        progression = _clamp(progress.get("percent"), 0, 100, 0) / 100
        return EpubLocation(type="epub", cfi=str(cfi) if cfi else None, href=str(href) if href else None, spineIndex=spine_index, progression=progression)
    try:
        page = max(1, int(progress.get("page") or extra.get("pageIndex") or 1))
    except (TypeError, ValueError):
        page = 1
    if reader_format == "comic":
        volume_id = progress.get("volumeId") or selected_volume_id
        if not volume_id:
            return None
        return ComicLocation(type="comic", volumeId=str(volume_id), pageIndex=page)
    if reader_format == "audio":
        file_id = extra.get("fileId")
        if not file_id:
            return None
        try:
            position_ms = max(0, int(extra.get("positionMs") or progress.get("position") or 0))
        except (TypeError, ValueError):
            position_ms = 0
        return AudioLocation(
            type="audio",
            volumeId=progress.get("volumeId") or selected_volume_id,
            fileId=str(file_id),
            chapterId=str(extra.get("chapterId")) if extra.get("chapterId") else None,
            positionMs=position_ms,
        )
    return PdfLocation(type="pdf", pageNumber=page)


def _progress_for_volume(progresses: list[dict[str, Any]], volume_id: str | None) -> dict[str, Any] | None:
    if volume_id is None:
        return next((row for row in progresses if row.get("volumeId") is None), progresses[0] if progresses else None)
    return next((row for row in progresses if row.get("volumeId") == volume_id), None)


@router.get(
    "/editions/{edition_id}/bootstrap",
    response_model=ReaderBootstrapResponse,
    response_model_by_alias=True,
)
def reader_bootstrap_v2(
    edition_id: str,
    request: Request,
    volume: str | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if not {"LibraryEdition", "LibraryWork"}.issubset(_tables(db)):
        return fail("阅读器数据库尚未初始化", status_code=503)
    edition = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id})
    if not edition:
        return fail("版本不存在", status_code=404)
    work = _row(db, "SELECT * FROM `LibraryWork` WHERE `id` = :id", {"id": edition["workId"]})
    if not work:
        return fail("作品不存在", status_code=404)
    reader_format = _reader_format(edition.get("format"))
    if reader_format is None:
        return fail("不支持的阅读格式", status_code=422)

    volumes = _rows(
        db,
        "SELECT * FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder`, `id`",
        {"edition_id": edition_id},
    ) if "LibraryVolume" in _tables(db) else []
    # One work-scoped read feeds both current-edition resume/volume selection
    # and the version navigator. Keeping this as the sole progress read avoids
    # N+1 queries while preserving the current edition's existing volume rules.
    all_work_progresses = _rows(
        db,
        "SELECT * FROM `LibraryReadingProgress` WHERE `userId` = :user_id AND `workId` = :work_id "
        "ORDER BY `updatedAt` DESC, `id` DESC",
        {"user_id": user.id, "work_id": work["id"]},
    ) if "LibraryReadingProgress" in _tables(db) else []
    progresses = [row for row in all_work_progresses if str(row.get("editionId")) == edition_id]
    selected_volume, volume_error = _select_volume(volumes, progresses, volume)
    if volume_error:
        return volume_error
    selected_volume_id = str(selected_volume["id"]) if selected_volume else None

    unit_type = "chapter" if reader_format == "epub" else "audio_chapter" if reader_format == "audio" else "page"
    units = _rows(
        db,
        "SELECT * FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id AND LOWER(`unitType`) = :unit_type AND "
        + ("`volumeId` = :volume_id " if selected_volume_id else "1 = 1 ")
        + "ORDER BY `sortOrder`, `id`",
        {"edition_id": edition_id, "unit_type": unit_type, **({"volume_id": selected_volume_id} if selected_volume_id else {})},
    ) if reader_format != "pdf" and "LibraryReadingUnit" in _tables(db) else []
    if reader_format == "comic" and selected_volume_id and not units:
        # Comic archives are intentionally indexed lazily by the existing file
        # service. Reuse that single index builder so bootstrap and page serving
        # cannot disagree about archive ordering.
        from app.api.routes.compat import _ensure_volume_page_index

        _ensure_volume_page_index(db, settings, selected_volume_id)
        units = _rows(
            db,
            "SELECT * FROM `LibraryReadingUnit` WHERE `editionId` = :edition_id AND `volumeId` = :volume_id AND LOWER(`unitType`) = 'page' ORDER BY `sortOrder`, `id`",
            {"edition_id": edition_id, "volume_id": selected_volume_id},
        ) if "LibraryReadingUnit" in _tables(db) else []
        refreshed_volume = _row(db, "SELECT * FROM `LibraryVolume` WHERE `id` = :id", {"id": selected_volume_id})
        if refreshed_volume:
            selected_volume = refreshed_volume
            volumes = [refreshed_volume if item.get("id") == selected_volume_id else item for item in volumes]
    unit_sort_orders = [int(unit["sortOrder"]) for unit in units if unit.get("sortOrder") is not None]
    unit_index_offset = 1 if unit_sort_orders and min(unit_sort_orders) == 0 else 0
    unit_summaries = [
        ReaderUnitSummary(
            id=str(unit.get("id")) if unit.get("id") else None,
            index=(int(unit["sortOrder"]) + unit_index_offset) if unit.get("sortOrder") is not None else index + 1,
            title=str(unit.get("title") or f"第 {index + 1} 节"),
            href=unit.get("href"),
            fileId=str(unit.get("fileId")) if unit.get("fileId") else None,
            startMs=unit.get("startMs"),
            endMs=unit.get("endMs"),
            durationMs=unit.get("durationMs"),
        )
        for index, unit in enumerate(units)
    ] if reader_format in {"epub", "audio"} else []
    page_summaries = [
        ReaderPageSummary(
            pageIndex=index + 1,
            title=unit.get("title"),
            mimeType=unit.get("mediaType"),
            width=unit.get("width"),
            height=unit.get("height"),
            size=unit.get("size"),
        )
        for index, unit in enumerate(units)
    ] if reader_format == "comic" else []
    total_pages = None
    if reader_format == "pdf":
        total_pages = int((selected_volume or {}).get("pageCount") or edition.get("pageCount") or 1)
        # PDF.js can address pages by number; returning one object per page makes
        # bootstrap payloads grow linearly for large documents.
        page_summaries = []
    elif reader_format == "comic":
        total_pages = len(page_summaries) or int((selected_volume or {}).get("pageCount") or edition.get("pageCount") or 0)

    audio_file_rows = _rows(
        db,
        "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder`, `id`",
        {"edition_id": edition_id},
    ) if reader_format == "audio" and "LibraryFile" in _tables(db) else []
    audio_manifest_row = _row(
        db,
        "SELECT `rawJson` FROM `LibraryMetadata` WHERE `editionId` = :edition_id AND `source` = 'audiobook_manifest' ORDER BY `createdAt` DESC LIMIT 1",
        {"edition_id": edition_id},
    ) if reader_format == "audio" and "LibraryMetadata" in _tables(db) else None
    audio_manifest = _json((audio_manifest_row or {}).get("rawJson"), {})
    track_titles = {
        str(item.get("fileId")): str(item.get("title"))
        for item in (audio_manifest.get("tracks") if isinstance(audio_manifest, dict) else []) or []
        if isinstance(item, dict) and item.get("fileId") and item.get("title")
    }
    audio_tracks = [
        AudioTrackSummary(
            fileId=str(item["id"]),
            title=track_titles.get(str(item["id"])) or str(Path(str(item.get("path") or item["id"])).stem),
            url=f"/api/files/{quote(str(item['id']), safe='')}",
            mimeType=str(item.get("mimeType") or "application/octet-stream"),
            durationMs=max(0, int(item.get("durationMs") or 0)),
            discNumber=item.get("discNumber"),
            trackNumber=item.get("trackNumber"),
            sortOrder=int(item.get("sortOrder") or 0),
        )
        for item in audio_file_rows
    ]
    if reader_format == "audio" and not audio_tracks:
        return fail("有声书没有可播放的音轨", status_code=422)
    audio_chapters = [
        AudioChapterSummary(
            id=str(item["id"]),
            title=str(item.get("title") or f"第 {index + 1} 章"),
            fileId=str(item.get("fileId")),
            startMs=max(0, int(item.get("startMs") or 0)),
            endMs=max(0, int(item.get("endMs") or 0)),
            durationMs=max(0, int(item.get("durationMs") or (int(item.get("endMs") or 0) - int(item.get("startMs") or 0)))),
            sortOrder=int(item.get("sortOrder") or index),
        )
        for index, item in enumerate(units)
        if item.get("fileId")
    ] if reader_format == "audio" else []
    total_duration_ms = max(sum(track.duration_ms for track in audio_tracks), int(edition.get("durationMs") or 0)) if reader_format == "audio" else None

    content_fingerprint = _content_fingerprint(db, edition, selected_volume_id)
    progress = _progress_for_volume(progresses, selected_volume_id)
    stored_fingerprint = progress.get("contentFingerprint") if progress else None
    fingerprint_mismatch = bool(stored_fingerprint and stored_fingerprint != content_fingerprint)
    # A location is only meaningful for the exact content identity that
    # produced it. Keep mismatch diagnostics, but never hand a stale location
    # to any adapter (including EPUB CFIs).
    discarded = "content_fingerprint_mismatch" if fingerprint_mismatch else None
    resume_location = None if discarded else _location_from_progress(progress, reader_format, selected_volume_id)
    preferences, preferences_updated_at = _book_preferences(db, user.id, str(work["id"]), reader_format)
    available_edition_rows = _rows(
        db,
        "SELECT * FROM `LibraryEdition` WHERE `workId` = :work_id AND COALESCE(`hidden`, 0) = 0 ORDER BY COALESCE(`primary`, 0) DESC, `createdAt`, `id`",
        {"work_id": work["id"]},
    )
    all_work_volumes = _rows(
        db,
        "SELECT v.* FROM `LibraryVolume` v JOIN `LibraryEdition` e ON e.`id` = v.`editionId` "
        "WHERE e.`workId` = :work_id AND COALESCE(e.`hidden`, 0) = 0 ORDER BY e.`createdAt`, v.`sortOrder`, v.`id`",
        {"work_id": work["id"]},
    ) if "LibraryVolume" in _tables(db) else []
    latest_progress_by_edition: dict[str, dict[str, Any]] = {}
    for candidate in all_work_progresses:
        candidate_edition_id = str(candidate.get("editionId") or "")
        if candidate_edition_id and candidate_edition_id not in latest_progress_by_edition:
            latest_progress_by_edition[candidate_edition_id] = candidate
    available_editions = [
        ReaderEditionOption(
            **_edition_summary(item).model_dump(),
            progress=_clamp(
                (latest_progress_by_edition.get(str(item.get("id"))) or {}).get("percent"),
                0,
                100,
                0,
            ),
            lastReadAt=_datetime(
                (latest_progress_by_edition.get(str(item.get("id"))) or {}).get("updatedAt")
            ),
            volumes=[_volume_summary(candidate) for candidate in all_work_volumes if candidate.get("editionId") == item.get("id")],
        )
        for item in available_edition_rows
        if _reader_format(item.get("format")) is not None
    ]
    volume_query = f"?volume={quote(selected_volume_id, safe='')}" if selected_volume_id else ""
    file_url = (
        audio_tracks[0].url
        if reader_format == "audio" and audio_tracks
        else f"/api/editions/{quote(edition_id, safe='')}/file{volume_query}"
    )
    data = ReaderBootstrapData(
        userId=user.id,
        readerType=reader_format,
        contentFingerprint=content_fingerprint,
        book=ReaderBookSummary(
            id=str(work["id"]),
            title=str(work.get("title") or "未命名作品"),
            author=work.get("author"),
            coverUrl=f"/api/works/{quote(str(work['id']), safe='')}/cover?size=large",
        ),
        edition=_edition_summary(edition),
        availableEditions=available_editions,
        selectedVolume=_volume_summary(selected_volume) if selected_volume else None,
        volumes=[_volume_summary(item) for item in volumes],
        units=unit_summaries,
        pages=page_summaries,
        tracks=audio_tracks,
        chapters=audio_chapters,
        totalDurationMs=total_duration_ms,
        totalPages=total_pages,
        fileUrl=file_url,
        capabilities=_capabilities(reader_format, preferences.comic.direction if reader_format == "comic" else "ltr"),
        serverPreferences=ReaderServerPreferences(settings=preferences, updatedAt=preferences_updated_at),
        resumeLocation=resume_location,
        resumeFingerprintMismatch=fingerprint_mismatch,
        resumeDiscardedReason=discarded,
        progressPercent=0 if discarded or not progress else _clamp(progress.get("percent"), 0, 100, 0),
    )
    if "LibraryConsumptionState" in _tables(db):
        resume_unit_id = resume_location.chapter_id if isinstance(resume_location, AudioLocation) else None
        _upsert_consumption_state(
            db,
            user_id=user.id,
            work_id=str(work["id"]),
            edition=edition,
            status="READING",
            volume_id=selected_volume_id,
            unit_id=resume_unit_id,
            preserve_finished=True,
        )
        _project_work_status(db, user.id, str(work["id"]), _now())
        db.commit()
    elif _mark_work_reading_started(db, str(work["id"])):
        db.commit()
    return ReaderBootstrapResponse(data=data)


def _resolve_progress_volume(db: Session, edition_id: str, requested_volume_id: str | None) -> tuple[str | None, JSONResponse | None]:
    if "LibraryVolume" not in _tables(db):
        return requested_volume_id, None
    volumes = _rows(db, "SELECT `id` FROM `LibraryVolume` WHERE `editionId` = :edition_id ORDER BY `sortOrder`, `id`", {"edition_id": edition_id})
    if requested_volume_id:
        if not any(str(row["id"]) == requested_volume_id for row in volumes):
            return None, fail("卷册不存在", status_code=404)
        return requested_volume_id, None
    if len(volumes) == 1:
        return str(volumes[0]["id"]), None
    if len(volumes) > 1:
        return None, fail("多卷版本必须提供 volumeId", status_code=422)
    return None, None


def _epub_location_target(
    db: Session,
    edition_id: str,
    requested_volume_id: str | None,
) -> tuple[dict[str, Any] | None, str | None, str | None, JSONResponse | None]:
    if "LibraryEdition" not in _tables(db):
        return None, None, None, fail("阅读器数据库尚未初始化", status_code=503)
    edition = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id})
    if not edition:
        return None, None, None, fail("版本不存在", status_code=404)
    if _reader_format(edition.get("format")) != "epub":
        return None, None, None, fail("只有 EPUB 支持全书位置索引", status_code=422)
    volume_id, volume_error = _resolve_progress_volume(db, edition_id, requested_volume_id)
    if volume_error:
        return None, None, None, volume_error
    return edition, volume_id, _content_fingerprint(db, edition, volume_id), None


@router.post("/editions/{edition_id}/epub-locations/claim")
def claim_reader_epub_locations(
    edition_id: str,
    payload: EpubLocationsClaimRequest,
    request: Request,
    volume: str | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    _edition, _volume_id, expected_fingerprint, target_error = _epub_location_target(db, edition_id, volume)
    if target_error:
        return target_error
    if payload.content_fingerprint != expected_fingerprint:
        return fail(
            "CONTENT_FINGERPRINT_MISMATCH",
            status_code=409,
            details={
                "expectedContentFingerprint": expected_fingerprint,
                "receivedContentFingerprint": payload.content_fingerprint,
                "editionId": edition_id,
                "volumeId": _volume_id,
            },
        )
    result = claim_epub_locations(
        settings,
        expected_fingerprint,
        payload.break_size,
        payload.cache_version,
    )
    return {"ok": True, "data": result}


@router.put("/editions/{edition_id}/epub-locations")
def save_reader_epub_locations(
    edition_id: str,
    payload: EpubLocationsSaveRequest,
    request: Request,
    volume: str | None = Query(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    _user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    _edition, _volume_id, expected_fingerprint, target_error = _epub_location_target(db, edition_id, volume)
    if target_error:
        return target_error
    if payload.content_fingerprint != expected_fingerprint:
        return fail("CONTENT_FINGERPRINT_MISMATCH", status_code=409)
    try:
        result = save_epub_locations(
            settings,
            expected_fingerprint,
            payload.break_size,
            payload.cache_version,
            payload.lease_token,
            payload.serialized,
        )
    except ValueError:
        return fail("EPUB 位置索引格式无效", status_code=422)
    except PermissionError:
        return fail("EPUB_LOCATION_LEASE_MISMATCH", status_code=409)
    return {"ok": True, "data": result}


def _legacy_projection(location, volume_id: str | None) -> tuple[str, int | None, dict[str, Any]]:
    if isinstance(location, EpubLocation):
        position = location.cfi or location.href or (str(location.progression) if location.progression is not None else "0")
        page = location.spine_index + 1 if location.spine_index is not None else None
        return position, page, {
            "cfi": location.cfi,
            "currentHref": location.href,
            "sectionIndex": location.spine_index,
            "progression": location.progression,
            "volumeId": volume_id,
        }
    if isinstance(location, ComicLocation):
        return str(location.page_index), location.page_index, {
            "pageIndex": location.page_index,
            "volumeId": location.volume_id,
        }
    if isinstance(location, AudioLocation):
        return str(location.position_ms), None, {
            "fileId": location.file_id,
            "chapterId": location.chapter_id,
            "positionMs": location.position_ms,
            "volumeId": location.volume_id or volume_id,
        }
    return str(location.page_number), location.page_number, {"pageIndex": location.page_number, "volumeId": volume_id}


def _audio_progress_percent(
    db: Session,
    edition_id: str,
    location: AudioLocation,
) -> tuple[float, bool, JSONResponse | None]:
    files = _rows(
        db,
        "SELECT * FROM `LibraryFile` WHERE `editionId` = :edition_id ORDER BY `sortOrder`, `id`",
        {"edition_id": edition_id},
    ) if "LibraryFile" in _tables(db) else []
    if not files:
        return 0, False, fail("有声书没有可播放的音轨", status_code=422)
    index = next((index for index, item in enumerate(files) if str(item.get("id")) == location.file_id), None)
    if index is None:
        return 0, False, fail("音频位置引用了不属于该版本的文件", status_code=422)
    current = files[index]
    current_duration = max(0, int(current.get("durationMs") or 0))
    if current_duration <= 0:
        return 0, False, fail("音轨时长不可用，无法保存播放进度", status_code=422)
    if location.position_ms > current_duration + 1000:
        return 0, False, fail("播放位置超出音轨时长", status_code=422)
    if location.chapter_id:
        chapter = _row(
            db,
            "SELECT `id`, `fileId` FROM `LibraryReadingUnit` WHERE `id` = :chapter_id AND `editionId` = :edition_id",
            {"chapter_id": location.chapter_id, "edition_id": edition_id},
        ) if "LibraryReadingUnit" in _tables(db) else None
        if not chapter or str(chapter.get("fileId")) != location.file_id:
            return 0, False, fail("音频章节与当前音轨不匹配", status_code=422)
    durations = [max(0, int(item.get("durationMs") or 0)) for item in files]
    total = sum(durations)
    if total <= 0:
        return 0, False, fail("有声书总时长不可用，无法保存播放进度", status_code=422)
    position = min(location.position_ms, current_duration)
    elapsed = sum(durations[:index]) + position
    at_final_end = index == len(files) - 1 and position >= current_duration
    # Reaching the geometric end is not itself a completion signal: a user can
    # seek the scrubber there. The client must additionally submit percent=100
    # from the media `ended` event; all ordinary seeks remain below 100.
    percent = min(99.999, max(0.0, (elapsed / total) * 100))
    return percent, at_final_end, None


def _claim_client_sequence(
    db: Session,
    *,
    user_id: str,
    work_id: str,
    client_id: str,
    client_sequence: int,
    mutation_id: str,
    now: datetime,
) -> bool:
    """Atomically advance one client's durable high-water mark.

    The caller must keep this transaction open until the corresponding progress
    row is written. The conditional UPDATE owns the row lock, so a lower or
    duplicate sequence cannot commit after a newer mutation.
    """

    initial_high_water = -1
    progress_columns = _columns(db, "LibraryReadingProgress")
    if {"clientId", "clientSequence"}.issubset(progress_columns):
        stored = db.execute(
            text(
                "SELECT MAX(`clientSequence`) FROM `LibraryReadingProgress` "
                "WHERE `userId` = :user_id AND `workId` = :work_id AND `clientId` = :client_id"
            ),
            {"user_id": user_id, "work_id": work_id, "client_id": client_id},
        ).scalar()
        if stored is not None:
            initial_high_water = int(stored)

    key = f"{user_id}\0{work_id}\0{client_id}"
    params = {
        "id": f"cursor_{hashlib.sha1(key.encode('utf-8')).hexdigest()}",
        "user_id": user_id,
        "work_id": work_id,
        "client_id": client_id,
        "high_water": initial_high_water,
        "now": now,
    }
    db.execute(
        text(
            """
            INSERT INTO `ReaderProgressCursor`
                (`id`, `userId`, `workId`, `clientId`, `highWater`, `lastMutationId`, `createdAt`, `updatedAt`)
            VALUES
                (:id, :user_id, :work_id, :client_id, :high_water, NULL, :now, :now)
            ON CONFLICT (`userId`, `workId`, `clientId`) DO NOTHING
            """
        ),
        params,
    )

    claimed = db.execute(
        text(
            """
            UPDATE `ReaderProgressCursor`
            SET `highWater` = :client_sequence,
                `lastMutationId` = :mutation_id,
                `updatedAt` = :now
            WHERE `userId` = :user_id
              AND `workId` = :work_id
              AND `clientId` = :client_id
              AND `highWater` < :client_sequence
            """
        ),
        {
            "user_id": user_id,
            "work_id": work_id,
            "client_id": client_id,
            "client_sequence": client_sequence,
            "mutation_id": mutation_id,
            "now": now,
        },
    )
    return int(claimed.rowcount or 0) == 1


@router.put(
    "/editions/{edition_id}/progress",
    response_model=ReaderProgressResponse,
    response_model_by_alias=True,
)
def save_progress_v2(
    edition_id: str,
    payload: ReaderProgressPut,
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user, auth_error = _auth(db, request, settings)
    if auth_error:
        return auth_error
    if payload.user_id != user.id:
        return fail("READER_USER_MISMATCH", status_code=403)
    if "LibraryEdition" not in _tables(db):
        return fail("阅读器数据库尚未初始化", status_code=503)
    edition = _row(db, "SELECT * FROM `LibraryEdition` WHERE `id` = :id", {"id": edition_id})
    if not edition:
        return fail("版本不存在", status_code=404)
    reader_format = _reader_format(edition.get("format"))
    if reader_format is None:
        return fail("不支持的阅读格式", status_code=422)
    if payload.location.type != reader_format:
        return fail("位置类型与版本格式不匹配", status_code=422)
    requested_volume_id = payload.volume_id
    if isinstance(payload.location, ComicLocation):
        if payload.volume_id is not None and payload.volume_id != payload.location.volume_id:
            return fail("漫画位置的 volumeId 与进度目标不匹配", status_code=422)
        requested_volume_id = payload.location.volume_id
    if isinstance(payload.location, AudioLocation):
        if payload.volume_id is not None and payload.location.volume_id is not None and payload.volume_id != payload.location.volume_id:
            return fail("音频位置的 volumeId 与进度目标不匹配", status_code=422)
        requested_volume_id = payload.location.volume_id or payload.volume_id
    volume_id, volume_error = _resolve_progress_volume(db, edition_id, requested_volume_id)
    if volume_error:
        return volume_error
    resolved_percent = float(payload.percent)
    completes_work = payload.percent >= 100 and _is_final_volume(db, edition_id, volume_id)
    if isinstance(payload.location, AudioLocation):
        resolved_percent, at_final_end, audio_error = _audio_progress_percent(db, edition_id, payload.location)
        if audio_error:
            return audio_error
        if payload.percent >= 100:
            if not at_final_end:
                return fail("只有最后一轨播放结束后才能将有声书标记为完成", status_code=422)
            resolved_percent = 100.0
            completes_work = True
        else:
            completes_work = False
    expected_fingerprint = _content_fingerprint(db, edition, volume_id)
    if payload.content_fingerprint != expected_fingerprint:
        return fail(
            "CONTENT_FINGERPRINT_MISMATCH",
            status_code=409,
            details={
                "expectedContentFingerprint": expected_fingerprint,
                "receivedContentFingerprint": payload.content_fingerprint,
                "editionId": edition_id,
                "volumeId": volume_id,
            },
        )
    if "LibraryReadingProgress" not in _tables(db):
        return fail("阅读进度表尚未初始化", status_code=503)
    if "ReaderProgressCursor" not in _tables(db):
        return fail("阅读进度游标表尚未初始化", status_code=503)

    position, page, extra = _legacy_projection(payload.location, volume_id)
    now = _now()
    values = {
        # The V1 rollback projection is VARCHAR(191); the complete location,
        # including long EPUB CFIs, remains lossless in locationJson.
        "position": position[:191],
        "page": page,
        "percent": resolved_percent,
        "extra": _json_text(extra),
        "volumeId": volume_id,
        "readerType": reader_format,
        "schemaVersion": 2,
        "locationType": reader_format,
        "locationJson": _json_text(payload.location.model_dump(by_alias=True, mode="json", exclude_none=True)),
        "contentFingerprint": expected_fingerprint,
        "mutationId": payload.mutation_id,
        "clientId": payload.client_id,
        "clientSequence": payload.client_sequence,
        "updatedAt": now,
    }
    allowed = _columns(db, "LibraryReadingProgress")
    claimed = _claim_client_sequence(
        db,
        user_id=user.id,
        work_id=str(edition["workId"]),
        client_id=payload.client_id,
        client_sequence=payload.client_sequence,
        mutation_id=payload.mutation_id,
        now=now,
    )
    if not claimed:
        # Persist a lazily seeded cursor for upgraded databases even when the
        # incoming mutation is already stale. No progress row is touched.
        db.commit()
        stale_progress = ReaderProgressRecord(
            mutationId=payload.mutation_id,
            clientId=payload.client_id,
            clientSequence=payload.client_sequence,
            contentFingerprint=expected_fingerprint,
            readerType=reader_format,
            workId=str(edition["workId"]),
            editionId=edition_id,
            volumeId=volume_id,
            location=payload.location,
            percent=resolved_percent,
            updatedAt=now,
        )
        return ReaderProgressResponse(
            data=ReaderProgressData(mutationId=payload.mutation_id, applied=False, progress=stale_progress)
        )
    existing = _row(
        db,
        "SELECT * FROM `LibraryReadingProgress` WHERE `userId` = :user_id AND `editionId` = :edition_id AND "
        + ("`volumeId` = :volume_id" if volume_id else "`volumeId` IS NULL"),
        {"user_id": user.id, "edition_id": edition_id, **({"volume_id": volume_id} if volume_id else {})},
    )
    filtered = {key: value for key, value in values.items() if key in allowed}
    if existing:
        assignments = ", ".join(f"`{key}` = :{key}" for key in filtered)
        db.execute(text(f"UPDATE `LibraryReadingProgress` SET {assignments} WHERE `id` = :row_id"), {**filtered, "row_id": existing["id"]})
    else:
        insert_values = {
            **filtered,
            "id": f"py_{time_ns()}",
            "userId": user.id,
            "workId": edition["workId"],
            "editionId": edition_id,
            "createdAt": now,
        }
        insert_values = {key: value for key, value in insert_values.items() if key in allowed}
        keys = ", ".join(f"`{key}`" for key in insert_values)
        placeholders = ", ".join(f":{key}" for key in insert_values)
        db.execute(text(f"INSERT INTO `LibraryReadingProgress` ({keys}) VALUES ({placeholders})"), insert_values)
    _advance_work_status_for_progress(
        db,
        user_id=user.id,
        edition=edition,
        work_id=str(edition["workId"]),
        completed=completes_work,
        volume_id=volume_id,
        unit_id=payload.location.chapter_id if isinstance(payload.location, AudioLocation) else None,
        now=now,
    )
    db.commit()

    progress = ReaderProgressRecord(
        mutationId=payload.mutation_id,
        clientId=payload.client_id,
        clientSequence=payload.client_sequence,
        contentFingerprint=expected_fingerprint,
        readerType=reader_format,
        workId=str(edition["workId"]),
        editionId=edition_id,
        volumeId=volume_id,
        location=payload.location,
        percent=resolved_percent,
        updatedAt=now,
    )
    return ReaderProgressResponse(data=ReaderProgressData(mutationId=payload.mutation_id, applied=True, progress=progress))
