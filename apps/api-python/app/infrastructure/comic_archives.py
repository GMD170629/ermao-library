"""Format-aware archive reading for comic ZIP and RAR containers."""

from __future__ import annotations

import mimetypes
import re
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, cast

import rarfile

from app.modules.imports.application.comic_types import (
    ComicArchiveInspection,
    ComicInfoMetadata,
)
from app.modules.imports.application.errors import (
    ComicArchiveBackendUnavailableError,
    ComicArchiveEncryptedError,
    ComicArchiveError,
    ComicArchiveInvalidError,
    ComicArchiveMultiVolumeError,
)
from app.modules.imports.application.import_support import (
    IMAGE_EXTS,
    _first_text,
    _ignored_entry,
    _natural_key,
    _safe_entry_name,
    _split_tags,
    _title_from_file,
)

MAX_COMIC_INFO_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class ComicArchiveEntry:
    filename: str
    file_size: int
    checksum: int | None
    directory: bool

    def is_dir(self) -> bool:
        return self.directory


ArchiveImplementation = zipfile.ZipFile | rarfile.RarFile


class ComicArchiveStream:
    """Binary entry stream that translates RAR backend failures."""

    def __init__(self, source: BinaryIO) -> None:
        self._source = source

    def __enter__(self) -> ComicArchiveStream:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._source.close()

    def read(self, size: int = -1) -> bytes:
        try:
            return self._source.read(size)
        except rarfile.RarCannotExec as exc:
            raise ComicArchiveBackendUnavailableError(
                "系统缺少 RAR 解压器，请安装 unrar 或 unar"
            ) from exc
        except (rarfile.PasswordRequired, rarfile.RarWrongPassword) as exc:
            raise ComicArchiveEncryptedError("RAR 漫画压缩包需要密码") from exc
        except rarfile.Error as exc:
            raise ComicArchiveInvalidError("RAR 漫画压缩包已损坏或不受支持") from exc


class ComicArchive:
    """Small ZIP-like facade over ``zipfile`` and ``rarfile``."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._archive = self._open(path)

    @staticmethod
    def _open(path: Path) -> ArchiveImplementation:
        if path.suffix.lower() in {".cbr", ".rar"}:
            archive: rarfile.RarFile | None = None
            try:
                archive = rarfile.RarFile(path)
                if archive.needs_password():
                    archive.close()
                    raise ComicArchiveEncryptedError("RAR 漫画压缩包需要密码")
                if len(archive.volumelist()) != 1:
                    archive.close()
                    raise ComicArchiveMultiVolumeError("暂不支持分卷 RAR 漫画压缩包")
                rarfile.tool_setup()
                return archive
            except ComicArchiveError:
                raise
            except (rarfile.PasswordRequired, rarfile.RarWrongPassword) as exc:
                raise ComicArchiveEncryptedError(
                    "RAR 漫画压缩包需要密码"
                ) from exc
            except rarfile.NeedFirstVolume as exc:
                raise ComicArchiveMultiVolumeError(
                    "暂不支持分卷 RAR 漫画压缩包"
                ) from exc
            except rarfile.RarCannotExec as exc:
                if archive is not None:
                    archive.close()
                raise ComicArchiveBackendUnavailableError(
                    "系统缺少 RAR 解压器，请安装 unrar 或 unar"
                ) from exc
            except rarfile.Error as exc:
                if archive is not None:
                    archive.close()
                raise ComicArchiveInvalidError("RAR 漫画压缩包已损坏或不受支持") from exc
        try:
            return zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise ComicArchiveInvalidError("ZIP 漫画压缩包已损坏") from exc

    def __enter__(self) -> ComicArchive:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._archive.close()

    def infolist(self) -> list[ComicArchiveEntry]:
        return [self._entry(info) for info in self._archive.infolist()]

    def getinfo(self, name: str) -> ComicArchiveEntry:
        try:
            return self._entry(self._archive.getinfo(name))
        except (KeyError, rarfile.NoRarEntry) as exc:
            raise KeyError(name) from exc

    def open(
        self, entry: str | ComicArchiveEntry, mode: str = "r"
    ) -> ComicArchiveStream:
        name = entry.filename if isinstance(entry, ComicArchiveEntry) else entry
        try:
            source = cast(BinaryIO, self._archive.open(name, mode))
            return ComicArchiveStream(source)
        except rarfile.RarCannotExec as exc:
            raise ComicArchiveBackendUnavailableError(
                "系统缺少 RAR 解压器，请安装 unrar 或 unar"
            ) from exc
        except (rarfile.PasswordRequired, rarfile.RarWrongPassword) as exc:
            raise ComicArchiveEncryptedError("RAR 漫画压缩包需要密码") from exc
        except rarfile.Error as exc:
            raise ComicArchiveInvalidError("RAR 漫画压缩包已损坏或不受支持") from exc

    def read(self, entry: str | ComicArchiveEntry) -> bytes:
        with self.open(entry) as source:
            return source.read()

    @staticmethod
    def _entry(info: zipfile.ZipInfo | rarfile.RarInfo) -> ComicArchiveEntry:
        return ComicArchiveEntry(
            filename=info.filename,
            file_size=int(info.file_size),
            checksum=int(info.CRC) if info.CRC is not None else None,
            directory=info.is_dir(),
        )


def open_comic_archive(path: Path) -> ComicArchive:
    return ComicArchive(path)


def inspect_comic_archive(
    path: Path, original_name: str | None = None
) -> ComicArchiveInspection:
    fmt = path.suffix.lower().removeprefix(".")
    with open_comic_archive(path) as archive:
        entries = [
            info
            for info in archive.infolist()
            if not info.is_dir() and _safe_entry_name(info.filename)
        ]
        images = [
            info
            for info in entries
            if Path(info.filename).suffix.lower() in IMAGE_EXTS
            and not _ignored_entry(info.filename)
        ]
        if not images:
            raise ValueError("漫画压缩包内没有可导入的图片")
        images.sort(key=lambda item: _natural_key(item.filename))
        comic_info_entry = next(
            (
                info
                for info in entries
                if info.filename.lower().endswith("comicinfo.xml")
                and info.file_size <= MAX_COMIC_INFO_BYTES
            ),
            None,
        )
        comic_info = (
            _parse_comic_info(archive.read(comic_info_entry).decode("utf-8", "replace"))
            if comic_info_entry
            else None
        )
        pages = [
            {
                "index": index + 1,
                "title": f"第 {index + 1} 页",
                "entryPath": info.filename,
                "mediaType": mimetypes.guess_type(info.filename)[0]
                or "application/octet-stream",
                "size": info.file_size,
            }
            for index, info in enumerate(images)
        ]
        cover_index = (comic_info or {}).get("coverImageIndex")
        cover = (
            pages[cover_index]
            if isinstance(cover_index, int) and 0 <= cover_index < len(pages)
            else next(
                (
                    page
                    for page in pages
                    if re.search(
                        r"(cover|folder|front|封面)",
                        Path(page["entryPath"]).name,
                        re.IGNORECASE,
                    )
                ),
                pages[0],
            )
        )
        image_formats = sorted(
            {Path(page["entryPath"]).suffix.lower().lstrip(".") for page in pages}
        )
        raw_metadata: dict[str, object] = {
            "hasComicInfo": comic_info is not None,
            "pageCount": len(pages),
            "imageFormats": image_formats,
            "coverEntryPath": cover["entryPath"],
        }
        if comic_info:
            raw_metadata["comicInfo"] = comic_info.get("raw") or {}
        return {
            "title": (comic_info or {}).get("title")
            or _title_from_file(Path(original_name or path.name)),
            "author": (comic_info or {}).get("writer")
            or (comic_info or {}).get("penciller")
            or "未知作者",
            "description": (comic_info or {}).get("summary"),
            "format": fmt,
            "pageCount": len(pages),
            "coverEntryPath": cover["entryPath"],
            "pages": pages,
            "comicInfo": comic_info,
            "rawMetadata": raw_metadata,
        }


def extract_comic_cover(
    storage_root: Path,
    source_path: Path,
    work_id: str,
    media_version_id: str,
    volume_id: str,
    entry_name: str,
) -> str:
    extension = Path(entry_name).suffix.lower() or ".jpg"
    target = (
        storage_root
        / "books"
        / work_id
        / media_version_id
        / volume_id
        / f"cover{extension}"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f"{target.suffix}.part")
    try:
        with (
            open_comic_archive(source_path) as archive,
            archive.open(entry_name, "r") as source,
            temporary.open("wb") as destination,
        ):
            shutil.copyfileobj(source, destination, length=1024 * 1024)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return str(target)


def _parse_comic_info(xml: str) -> ComicInfoMetadata:
    raw: dict[str, str] = {}
    for tag in [
        "Title",
        "Series",
        "Volume",
        "Summary",
        "Writer",
        "Penciller",
        "Publisher",
        "Genre",
        "Tags",
    ]:
        value = _first_text(xml, tag)
        if value:
            raw[tag] = value
    volume = (
        float(raw["Volume"])
        if str(raw.get("Volume", "")).replace(".", "", 1).isdigit()
        else None
    )
    cover_match = re.search(
        r"<Page\b[^>]*(?:Type|type)=['\"](?:FrontCover|Cover)['\"][^>]*(?:Image|image)=['\"](\d+)['\"]",
        xml,
        re.IGNORECASE,
    )
    return {
        "title": raw.get("Title"),
        "series": raw.get("Series"),
        "volume": volume,
        "summary": raw.get("Summary"),
        "writer": raw.get("Writer"),
        "penciller": raw.get("Penciller"),
        "publisher": raw.get("Publisher"),
        "tags": _split_tags(raw.get("Tags") or raw.get("Genre")),
        "coverImageIndex": int(cover_match.group(1)) if cover_match else None,
        "raw": raw,
    }
