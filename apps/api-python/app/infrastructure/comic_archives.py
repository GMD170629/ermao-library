"""Format-aware archive reading for comic ZIP and RAR containers."""

from __future__ import annotations

import math
import re
import shutil
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Literal, Self, TypeAlias, cast
from xml.etree import ElementTree

# rarfile has no published typing metadata; ComicArchive is the typed adapter boundary.
import rarfile  # type: ignore[import-not-found,import-untyped]

from app.contracts.reader_safety_policy_generated import (
    ReaderSafetyAction,
    ReaderSafetyBudgetName,
    ReaderSafetyRuleId,
    reader_safety_budget,
    reader_safety_comic_page_mime_type,
    reader_safety_rule,
)
from app.core.natural_sort import natural_sort_key
from app.modules.imports.application.comic_types import (
    ComicArchiveInspection,
    ComicInfoMetadata,
    ComicPageInspection,
)
from app.modules.imports.application.errors import (
    ComicArchiveBackendUnavailableError,
    ComicArchiveEncryptedError,
    ComicArchiveError,
    ComicArchiveInvalidError,
    ComicArchiveMultiVolumeError,
)

_NUMBER = r"(?P<value>\d+(?:\.\d+)?)"
_ORDINAL_PREFIX = chr(0x7B2C)
_RESOURCE_UNITS = "".join(
    chr(codepoint) for codepoint in (0x5377, 0x518C, 0x90E8, 0x96C6)
)
_STRUCTURED_RESOURCE_PATTERNS = (
    re.compile(rf"^{_NUMBER}$", re.IGNORECASE),
    re.compile(rf"^{_NUMBER}\s*(?:of|/)\s*\d+(?:\.\d+)?$", re.IGNORECASE),
    re.compile(rf"^(?:vol(?:ume)?\.?|book)\s*{_NUMBER}$", re.IGNORECASE),
    re.compile(
        rf"^{re.escape(_ORDINAL_PREFIX)}\s*{_NUMBER}\s*[{re.escape(_RESOURCE_UNITS)}]$",
        re.IGNORECASE,
    ),
)


def _comic_policy_error(
    rule_id: ReaderSafetyRuleId,
    message: str,
    error_type: type[ComicArchiveError] = ComicArchiveInvalidError,
) -> ComicArchiveError:
    rule = reader_safety_rule(rule_id)
    if (
        rule.action is not ReaderSafetyAction.REJECT_PUBLICATION
        or rule.error_code is None
    ):
        raise RuntimeError(f"generated comic rule {rule_id.value} is not a rejection")
    return error_type(
        message,
        code=rule.error_code.value,
        rule_id=rule.id.value,
    )


def _title_from_file(path: Path) -> str:
    return re.sub(r"[_-]+", " ", path.stem).strip() or path.name


def _safe_entry_name(name: str) -> bool:
    if "\\" in name or "\x00" in name:
        return False
    path = PurePosixPath(name)
    normalized = str(path)
    return bool(
        name
        and not name.startswith("/")
        and not re.match(r"^[a-zA-Z]:", name)
        and all(part not in {"", ".", ".."} for part in path.parts)
        and not normalized.startswith("../")
        and "/../" not in normalized
    )


def _ignored_entry(name: str) -> bool:
    parts = name.split("/")
    last = parts[-1]
    return (
        "__MACOSX" in parts
        or last in {".DS_Store", "Thumbs.db"}
        or last.startswith("._")
        or any(part.startswith(".") for part in parts)
    )


def _split_tags(value: str | None) -> list[str]:
    return [tag.strip() for tag in re.split(r"[,，;]", value or "") if tag.strip()]


def _first_text(xml: str, tag: str) -> str | None:
    match = re.search(
        rf"<(?:[\w]+:)?{re.escape(tag)}\b[^>]*>([\s\S]*?)</(?:[\w]+:)?{re.escape(tag)}>",
        xml,
        re.IGNORECASE,
    )
    if match is None:
        return None
    value = re.sub(r"<!\[CDATA\[([\s\S]*?)\]\]>", r"\1", match.group(1))
    value = re.sub(r"<[^>]+>", " ", value)
    try:
        value = ElementTree.fromstring(f"<x>{value}</x>").text or value
    except ElementTree.ParseError:
        pass
    return re.sub(r"\s+", " ", value).strip() or None


def _parse_resource_index(value: object | None) -> float | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    for pattern in _STRUCTURED_RESOURCE_PATTERNS:
        match = pattern.fullmatch(normalized)
        if match is None:
            continue
        parsed = float(match.group("value"))
        return parsed if math.isfinite(parsed) and parsed >= 0 else None
    return None


MAX_COMIC_INFO_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.COMIC_MANIFEST_MAX_BYTES
)
MAX_COMIC_PAGES = reader_safety_budget(ReaderSafetyBudgetName.COMIC_PAGE_MAX_COUNT)
MAX_COMIC_UNCOMPRESSED_BYTES = reader_safety_budget(
    ReaderSafetyBudgetName.COMIC_EXPANDED_MAX_BYTES
)
MAX_COMIC_COMPRESSION_RATIO = reader_safety_budget(
    ReaderSafetyBudgetName.COMIC_COMPRESSION_RATIO_MAX
)


@dataclass(frozen=True, slots=True)
class ComicArchiveEntry:
    filename: str
    file_size: int
    checksum: int | None
    directory: bool
    compressed_size: int
    encrypted: bool
    unix_mode: int

    def is_dir(self) -> bool:
        return self.directory


ArchiveImplementation: TypeAlias = zipfile.ZipFile | rarfile.RarFile


class ComicArchiveStream:
    """Binary entry stream that translates RAR backend failures."""

    def __init__(self, source: BinaryIO) -> None:
        self._source = source

    def __enter__(self) -> Self:
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
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                "RAR 漫画压缩包需要密码",
                ComicArchiveEncryptedError,
            ) from exc
        except rarfile.Error as exc:
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                "RAR 漫画压缩包已损坏或不受支持",
            ) from exc


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
                    raise _comic_policy_error(
                        ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                        "RAR 漫画压缩包需要密码",
                        ComicArchiveEncryptedError,
                    )
                if len(archive.volumelist()) != 1:
                    archive.close()
                    raise _comic_policy_error(
                        ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                        "暂不支持分卷 RAR 漫画压缩包",
                        ComicArchiveMultiVolumeError,
                    )
                rarfile.tool_setup()
                return archive
            except ComicArchiveError:
                raise
            except (rarfile.PasswordRequired, rarfile.RarWrongPassword) as exc:
                raise _comic_policy_error(
                    ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                    "RAR 漫画压缩包需要密码",
                    ComicArchiveEncryptedError,
                ) from exc
            except rarfile.NeedFirstVolume as exc:
                raise _comic_policy_error(
                    ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                    "暂不支持分卷 RAR 漫画压缩包",
                    ComicArchiveMultiVolumeError,
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
                raise _comic_policy_error(
                    ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                    "RAR 漫画压缩包已损坏或不受支持",
                ) from exc
        try:
            return zipfile.ZipFile(path)
        except zipfile.BadZipFile as exc:
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                "ZIP 漫画压缩包已损坏",
            ) from exc

    def __enter__(self) -> Self:
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
        self, entry: str | ComicArchiveEntry, mode: Literal["r"] = "r"
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

    def validate_integrity(self) -> None:
        """Verify archive CRCs without publishing any extracted artifact."""

        try:
            if isinstance(self._archive, zipfile.ZipFile):
                failed_entry = self._archive.testzip()
                if failed_entry is not None:
                    raise _comic_policy_error(
                        ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                        "漫画压缩包包含校验失败的条目",
                    )
                return
            self._archive.testrar()
        except ComicArchiveError:
            raise
        except (zipfile.BadZipFile, rarfile.BadRarFile, rarfile.Error) as exc:
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                "漫画压缩包校验失败",
            ) from exc

    @staticmethod
    def _entry(info: zipfile.ZipInfo | rarfile.RarInfo) -> ComicArchiveEntry:
        flag_bits = int(getattr(info, "flag_bits", 0))
        external_attr = int(getattr(info, "external_attr", 0))
        return ComicArchiveEntry(
            filename=info.filename,
            file_size=int(info.file_size),
            checksum=int(info.CRC) if info.CRC is not None else None,
            directory=info.is_dir(),
            compressed_size=int(getattr(info, "compress_size", info.file_size)),
            encrypted=bool(flag_bits & 0x1),
            unix_mode=(external_attr >> 16) & 0xFFFF,
        )


def open_comic_archive(path: Path) -> ComicArchive:
    return ComicArchive(path)


def inspect_comic_archive(
    path: Path, original_name: str | None = None
) -> ComicArchiveInspection:
    fmt = path.suffix.lower().removeprefix(".")
    with open_comic_archive(path) as archive:
        all_entries = archive.infolist()
        _validate_comic_entries(all_entries)
        entries = [
            info
            for info in all_entries
            if not info.is_dir() and _safe_entry_name(info.filename)
        ]
        images = [
            info
            for info in entries
            if _comic_page_mime_type(info.filename) is not None
            and not _ignored_entry(info.filename)
        ]
        if not images:
            raise ValueError("漫画压缩包内没有可导入的图片")
        if len(images) > MAX_COMIC_PAGES:
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_PAGE_MAX_COUNT,
                "漫画压缩包页数超过安全限制",
            )
        images.sort(key=lambda item: natural_sort_key(item.filename))
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
        pages: list[ComicPageInspection] = [
            {
                "index": index + 1,
                "title": f"第 {index + 1} 页",
                "entryPath": info.filename,
                "mediaType": _comic_page_mime_type(info.filename)
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
        archive.validate_integrity()
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


def _comic_page_mime_type(filename: str) -> str | None:
    return reader_safety_comic_page_mime_type(Path(filename).suffix)


def _validate_comic_entries(entries: list[ComicArchiveEntry]) -> None:
    """Fail closed before indexing a comic whose archive metadata is unsafe."""

    names: set[str] = set()
    total_size = 0
    for entry in entries:
        if entry.encrypted:
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                "加密漫画压缩包不受支持",
                ComicArchiveEncryptedError,
            )
        if not _safe_entry_name(entry.filename):
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                "漫画压缩包包含不安全路径",
            )
        canonical_name = str(PurePosixPath(entry.filename)).casefold()
        if canonical_name in names:
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                "漫画压缩包包含规范化重复路径",
            )
        names.add(canonical_name)
        if entry.unix_mode and stat.S_ISLNK(entry.unix_mode):
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_STRUCTURE,
                "漫画压缩包包含符号链接",
            )
        total_size += entry.file_size
        if total_size > MAX_COMIC_UNCOMPRESSED_BYTES:
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_BUDGET,
                "漫画压缩包超过展开大小限制",
            )
        unsafe_ratio = (entry.file_size > 0 and entry.compressed_size == 0) or (
            entry.compressed_size > 0
            and entry.file_size / entry.compressed_size > MAX_COMIC_COMPRESSION_RATIO
        )
        if unsafe_ratio:
            raise _comic_policy_error(
                ReaderSafetyRuleId.COMIC_ARCHIVE_BUDGET,
                "漫画压缩包压缩比超过安全限制",
            )


def extract_comic_cover(
    storage_root: Path,
    source_path: Path,
    book_id: str,
    resource_id: str,
    asset_id: str,
    entry_name: str,
) -> str:
    extension = Path(entry_name).suffix.lower() or ".jpg"
    target = (
        storage_root / "books" / book_id / resource_id / asset_id / f"cover{extension}"
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
        "Number",
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
    resource_index = _parse_resource_index(raw.get("Volume"))
    if resource_index is None:
        resource_index = _parse_resource_index(raw.get("Number"))
    cover_match = re.search(
        r"<Page\b[^>]*(?:Type|type)=['\"](?:FrontCover|Cover)['\"][^>]*(?:Image|image)=['\"](\d+)['\"]",
        xml,
        re.IGNORECASE,
    )
    return {
        "title": raw.get("Title"),
        "series": raw.get("Series"),
        "volume": resource_index,
        "summary": raw.get("Summary"),
        "writer": raw.get("Writer"),
        "penciller": raw.get("Penciller"),
        "publisher": raw.get("Publisher"),
        "tags": _split_tags(raw.get("Tags") or raw.get("Genre")),
        "coverImageIndex": int(cover_match.group(1)) if cover_match else None,
        "raw": raw,
    }
