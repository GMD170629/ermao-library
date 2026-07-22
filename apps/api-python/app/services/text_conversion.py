from __future__ import annotations

import codecs
import hashlib
import json
import os
import posixpath
import re
import shutil
import subprocess
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.time import now_timestamp_ms
from app.services.epub_normalizer import (
    EPUB_NORMALIZER_VERSION,
    EpubInspection,
    EpubNormalizationError,
    EpubNormalizationResult,
    inspect_libmobi_epub,
    normalize_libmobi_epub,
    validate_normalized_epub,
)
from app.services.internal_epub_conversion import (
    INTERNAL_CONVERTER_VERSION,
    InternalConversionError,
    convert_fb2_to_epub,
    convert_txt_to_epub,
)


CONVERTIBLE_TEXT_EXTS = {".mobi", ".azw", ".azw3", ".prc", ".fb2", ".txt"}
TEXT_EBOOK_EXTS = {".epub", *CONVERTIBLE_TEXT_EXTS}
INTERNAL_SOURCE_FORMATS = {"FB2", "TXT"}
LIBMOBI_SOURCE_FORMATS = {"MOBI", "AZW", "AZW3", "PRC"}
RETRYABLE_CONVERSION_ERRORS = {
    "CONVERTER_UNAVAILABLE",
    "CONVERSION_TIMEOUT",
    "CONVERSION_FAILED",
    "INVALID_EPUB_OUTPUT",
    "EPUB_NORMALIZATION_FAILED",
}
MAX_LOG_CHARS = 16_000


class ConversionFailure(RuntimeError):
    def __init__(self, code: str, message: str, *, retryable: bool | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = code in RETRYABLE_CONVERSION_ERRORS if retryable is None else retryable


@dataclass(frozen=True)
class ConversionArtifact:
    source_path: Path
    output_path: Path
    source_format: str
    source_hash: str
    converter: str
    converter_version: str
    cached: bool


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


def source_format(path: str | Path) -> str | None:
    suffix = Path(path).suffix.lower()
    if suffix == ".epub":
        return "EPUB"
    if suffix in CONVERTIBLE_TEXT_EXTS:
        return suffix.removeprefix(".").upper()
    return None


def is_convertible_text_ebook(path: str | Path) -> bool:
    return Path(path).suffix.lower() in CONVERTIBLE_TEXT_EXTS


def _now() -> int:
    return now_timestamp_ms()


def _id() -> str:
    return f"py_{time.time_ns()}"


def _has_table(db: Session, table: str) -> bool:
    return table in inspect(db.connection()).get_table_names()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def detect_txt_encoding(path: Path) -> str:
    sample = path.read_bytes()[: 4 * 1024 * 1024]
    if not sample:
        raise ConversionFailure("CONVERSION_FAILED", "TXT 文件为空", retryable=False)
    if sample.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if sample.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le"
    if sample.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be"
    if b"\x00" in sample:
        raise ConversionFailure("TEXT_ENCODING_UNCERTAIN", "无法可靠识别 TXT 编码", retryable=False)
    try:
        sample.decode("utf-8", errors="strict")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        decoded = sample.decode("gb18030", errors="strict")
    except UnicodeDecodeError as exc:
        raise ConversionFailure("TEXT_ENCODING_UNCERTAIN", "无法可靠识别 TXT 编码", retryable=False) from exc
    replacement_ratio = decoded.count("�") / max(1, len(decoded))
    if replacement_ratio > 0.001:
        raise ConversionFailure("TEXT_ENCODING_UNCERTAIN", "无法可靠识别 TXT 编码", retryable=False)
    return "gb18030"


def probe_text_source(path: Path) -> dict[str, Any]:
    fmt = source_format(path)
    if fmt is None or path.suffix.lower() not in CONVERTIBLE_TEXT_EXTS:
        raise ConversionFailure("UNSUPPORTED_FORMAT", "当前文件不是受支持的文本电子书格式", retryable=False)
    if not path.is_file() or path.stat().st_size <= 0:
        raise ConversionFailure("CONVERSION_FAILED", "文件为空或不存在", retryable=False)
    options: dict[str, Any] = {}
    if path.suffix.lower() == ".txt":
        options["inputEncoding"] = detect_txt_encoding(path)
        options["formattingType"] = "heuristic"
    if path.suffix.lower() == ".fb2":
        prefix = path.read_bytes()[:64 * 1024]
        if prefix.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            marker_source = prefix.decode("utf-16", errors="ignore")
        else:
            marker_source = prefix.decode("utf-8-sig", errors="ignore")
        if "FictionBook" not in marker_source:
            raise ConversionFailure("UNSUPPORTED_FORMAT", "FB2 文件结构无效", retryable=False)
    return {"sourceFormat": fmt, "options": options}


def validate_epub(path: Path, *, max_bytes: int | None = None) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size <= 0:
        raise ConversionFailure("INVALID_EPUB_OUTPUT", "转换结果为空")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise ConversionFailure("INVALID_EPUB_OUTPUT", "转换结果超过大小限制")
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if "META-INF/container.xml" not in names:
                raise ConversionFailure("INVALID_EPUB_OUTPUT", "EPUB 缺少 container.xml")
            mimetype = archive.read("mimetype").decode("ascii", errors="ignore").strip() if "mimetype" in names else ""
            if mimetype != "application/epub+zip":
                raise ConversionFailure("INVALID_EPUB_OUTPUT", "EPUB mimetype 无效")
            container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
            rootfile = next((node.attrib.get("full-path") for node in container.iter() if node.tag.endswith("rootfile")), None)
            if not rootfile or rootfile not in names:
                raise ConversionFailure("INVALID_EPUB_OUTPUT", "EPUB 缺少 OPF 文件")
            package = ElementTree.fromstring(archive.read(rootfile))
            spine_items = [node for node in package.iter() if node.tag.endswith("itemref")]
            if not spine_items:
                raise ConversionFailure("INVALID_EPUB_OUTPUT", "EPUB 不包含可阅读章节")
            manifest_items = [node for node in package.iter() if node.tag.endswith("item")]
            package_directory = posixpath.dirname(rootfile)
            documents: list[str] = []
            for item in manifest_items:
                href = str(item.attrib.get("href") or "").strip()
                if not href:
                    continue
                target = posixpath.normpath(posixpath.join(package_directory, unquote(urlsplit(href).path)))
                if target not in names:
                    raise ConversionFailure("INVALID_EPUB_OUTPUT", f"EPUB 资源引用不存在：{href}")
                if item.attrib.get("media-type") == "application/xhtml+xml":
                    documents.append(target)
            for document_name in documents:
                document = ElementTree.fromstring(archive.read(document_name))
                for node in document.iter():
                    for attribute, raw_value in node.attrib.items():
                        if attribute.rsplit("}", 1)[-1].lower() not in {"href", "src", "poster"}:
                            continue
                        value = str(raw_value).strip()
                        parsed = urlsplit(value)
                        if not value or value.startswith("#") or parsed.scheme or value.startswith("//"):
                            continue
                        reference = posixpath.normpath(
                            posixpath.join(posixpath.dirname(document_name), unquote(parsed.path))
                        )
                        if parsed.path and reference not in names:
                            raise ConversionFailure("INVALID_EPUB_OUTPUT", f"EPUB 文档引用不存在：{value}")
            return {"rootfile": rootfile, "spineCount": len(spine_items), "sizeBytes": path.stat().st_size}
    except ConversionFailure:
        raise
    except (OSError, ValueError, zipfile.BadZipFile, KeyError, ElementTree.ParseError) as exc:
        raise ConversionFailure("INVALID_EPUB_OUTPUT", "转换结果不是有效的 EPUB") from exc


def _command_runner(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, **kwargs)


def _converter_for_format(fmt: str) -> str:
    if fmt in INTERNAL_SOURCE_FORMATS:
        return "shuku-internal"
    if fmt in LIBMOBI_SOURCE_FORMATS:
        return "libmobi"
    raise ConversionFailure("UNSUPPORTED_FORMAT", "当前文件不是受支持的文本电子书格式", retryable=False)


def converter_version(settings: Settings, fmt: str, runner: CommandRunner | None = None) -> str:
    command_runner = runner or _command_runner
    if not settings.ebook_conversion_enabled:
        raise ConversionFailure("CONVERTER_UNAVAILABLE", "电子书转换功能未启用")
    if fmt in INTERNAL_SOURCE_FORMATS:
        return INTERNAL_CONVERTER_VERSION
    if fmt not in LIBMOBI_SOURCE_FORMATS:
        raise ConversionFailure("UNSUPPORTED_FORMAT", "当前文件不是受支持的文本电子书格式", retryable=False)
    try:
        result = command_runner(
            [settings.libmobi_bin, "-v"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        raise ConversionFailure("CONVERTER_UNAVAILABLE", "电子书转换服务不可用") from exc
    output = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0 or not output:
        raise ConversionFailure("CONVERTER_UNAVAILABLE", "电子书转换服务不可用")
    version_lines = [line.strip() for line in output.splitlines() if line.strip()][:2]
    return " | ".join(version_lines)[:191]


def converter_capability(settings: Settings, runner: CommandRunner | None = None) -> dict[str, Any]:
    internal = {
        "available": settings.ebook_conversion_enabled,
        "converter": "shuku-internal",
        "version": INTERNAL_CONVERTER_VERSION,
        "formats": sorted(INTERNAL_SOURCE_FORMATS),
    }
    try:
        version = converter_version(settings, "MOBI", runner)
        libmobi = {
            "available": True,
            "converter": "libmobi",
            "version": version,
            "normalizerVersion": EPUB_NORMALIZER_VERSION,
            "formats": sorted(LIBMOBI_SOURCE_FORMATS),
        }
    except ConversionFailure as exc:
        libmobi = {
            "available": False,
            "converter": "libmobi",
            "version": None,
            "normalizerVersion": EPUB_NORMALIZER_VERSION,
            "formats": sorted(LIBMOBI_SOURCE_FORMATS),
            "errorCode": exc.code,
            "message": str(exc),
        }
    return {
        "available": bool(internal["available"] and libmobi["available"]),
        "converter": "libmobi+shuku-internal",
        "version": (
            f"{libmobi.get('version') or 'unavailable'}; "
            f"{EPUB_NORMALIZER_VERSION}; {INTERNAL_CONVERTER_VERSION}"
        ),
        "engines": [internal, libmobi],
    }


def _conversion_row(db: Session, import_task_id: str) -> dict[str, Any] | None:
    if not _has_table(db, "BookConversionTask"):
        return None
    row = db.execute(
        text("SELECT * FROM `BookConversionTask` WHERE `importTaskId` = :import_task_id"),
        {"import_task_id": import_task_id},
    ).mappings().first()
    return dict(row) if row else None


def _update_stage(
    db: Session,
    import_task_id: str,
    *,
    status: str,
    progress: int,
    message: str,
    conversion_values: dict[str, Any] | None = None,
) -> None:
    now = _now()
    if _has_table(db, "ImportTask"):
        db.execute(
            text("UPDATE `ImportTask` SET `status` = 'PARSING', `progress` = :progress, `message` = :message, `updatedAt` = :now WHERE `id` = :id"),
            {"progress": progress, "message": message, "now": now, "id": import_task_id},
        )
    if _has_table(db, "BookConversionTask"):
        values = {"status": status, "progress": progress, "updatedAt": now, **(conversion_values or {})}
        assignments = ", ".join(f"`{key}` = :{key}" for key in values)
        db.execute(
            text(f"UPDATE `BookConversionTask` SET {assignments} WHERE `importTaskId` = :importTaskId"),
            {**values, "importTaskId": import_task_id},
        )
    db.commit()


def _ensure_conversion_task(
    db: Session,
    import_task_id: str,
    source: Path,
    fmt: str,
    converter: str,
    options: dict[str, Any],
) -> dict[str, Any]:
    existing = _conversion_row(db, import_task_id)
    if existing:
        return existing
    now = _now()
    values = {
        "id": _id(),
        "importTaskId": import_task_id,
        "mode": "AUTO",
        "sourceFormat": fmt,
        "targetFormat": "EPUB",
        "sourcePath": str(source),
        "converter": converter,
        "optionsJson": json.dumps(options, ensure_ascii=False, sort_keys=True),
        "status": "QUEUED",
        "progress": 5,
        "attempts": 0,
        "retryable": 0,
        "createdAt": now,
        "updatedAt": now,
    }
    columns = {column["name"] for column in inspect(db.connection()).get_columns("BookConversionTask")}
    values = {key: value for key, value in values.items() if key in columns}
    keys = ", ".join(f"`{key}`" for key in values)
    params = ", ".join(f":{key}" for key in values)
    db.execute(text(f"INSERT INTO `BookConversionTask` ({keys}) VALUES ({params})"), values)
    db.commit()
    return _conversion_row(db, import_task_id) or values


def _failure_from_process(stderr: str, stdout: str) -> ConversionFailure:
    detail = "\n".join(item for item in [stderr.strip(), stdout.strip()] if item).strip()
    if re.search(r"\bdrm\b|encrypted|encryption|locked book|版权保护|加密", detail, re.I):
        return ConversionFailure("DRM_PROTECTED", "文件可能受 DRM 保护，无法转换", retryable=False)
    message = "电子书转换失败"
    if detail:
        message = f"{message}：{detail[-800:]}"
    return ConversionFailure("CONVERSION_FAILED", message)


def _run_libmobi_conversion(
    settings: Settings,
    command_runner: CommandRunner,
    source: Path,
    temp_dir: Path,
    output_path: Path,
) -> None:
    command = [settings.libmobi_bin, "-e", "-o", str(temp_dir), str(source)]
    result = command_runner(
        command,
        capture_output=True,
        text=True,
        timeout=settings.ebook_conversion_timeout_seconds,
        check=False,
    )
    if result.returncode != 0:
        raise _failure_from_process(result.stderr or "", result.stdout or "")
    candidates = sorted(path for path in temp_dir.glob("*.epub") if path != output_path)
    expected = temp_dir / f"{source.stem}.epub"
    generated = expected if expected in candidates else candidates[0] if len(candidates) == 1 else None
    if generated is None:
        detail = "\n".join(item for item in [result.stderr or "", result.stdout or ""] if item).strip()
        classified_failure = _failure_from_process(result.stderr or "", result.stdout or "")
        if classified_failure.code == "DRM_PROTECTED":
            raise classified_failure
        if re.search(r"print replica|azw4|can't create epub|cannot create epub", detail, re.I):
            raise ConversionFailure("UNSUPPORTED_FORMAT", "当前 Kindle 文件类型无法转换为 EPUB", retryable=False)
        raise ConversionFailure("CONVERSION_FAILED", "libmobi 未生成 EPUB 文件")
    os.replace(generated, output_path)


def _run_internal_conversion(fmt: str, source: Path, output_path: Path, options: dict[str, Any]) -> dict[str, Any]:
    try:
        if fmt == "TXT":
            result = convert_txt_to_epub(source, output_path, encoding=str(options["inputEncoding"]))
        elif fmt == "FB2":
            result = convert_fb2_to_epub(source, output_path)
        else:
            raise ConversionFailure("UNSUPPORTED_FORMAT", "当前文件不是受支持的文本电子书格式", retryable=False)
    except InternalConversionError as exc:
        raise ConversionFailure("CONVERSION_FAILED", f"电子书转换失败：{str(exc)}") from exc
    return {
        **options,
        "detectedTitle": result.title,
        "detectedAuthor": result.author,
        "detectedLanguage": result.language,
        "chapterCount": result.chapter_count,
        "resourceCount": result.resource_count,
    }


def _libmobi_pipeline_version(converter_version_value: str) -> str:
    return f"{converter_version_value}; {EPUB_NORMALIZER_VERSION}"


def _cached_normalization_options(final_path: Path, inspection: EpubInspection) -> dict[str, Any]:
    metadata_path = final_path.with_name("normalization.json")
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        payload = None
    if isinstance(payload, dict) and payload.get("normalizerVersion") == EPUB_NORMALIZER_VERSION:
        return payload
    return {
        "normalizerVersion": EPUB_NORMALIZER_VERSION,
        "normalizationApplied": any("-shuku-" in section.href for section in inspection.sections),
        "normalizationReasons": [],
        "normalizationBefore": inspection.metrics(),
        "normalizationAfter": inspection.metrics(),
    }


def _write_normalization_options(final_path: Path, result: EpubNormalizationResult) -> None:
    metadata_path = final_path.with_name("normalization.json")
    temporary_path = metadata_path.with_suffix(".json.part")
    temporary_path.write_text(
        json.dumps(result.options(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary_path, metadata_path)


def convert_to_epub(
    db: Session,
    settings: Settings,
    import_task_id: str,
    source_path: str | Path,
    *,
    runner: CommandRunner | None = None,
) -> ConversionArtifact:
    command_runner = runner or _command_runner
    source = Path(source_path).expanduser().resolve()
    fmt = source_format(source) or "UNKNOWN"
    converter = _converter_for_format(fmt)
    task = _ensure_conversion_task(db, import_task_id, source, fmt, converter, {})
    try:
        probe = probe_text_source(source)
    except ConversionFailure as exc:
        _record_failure(db, import_task_id, exc)
        raise
    fmt = str(probe["sourceFormat"])
    options = dict(probe["options"])
    _update_stage(
        db,
        import_task_id,
        status="PROBING",
        progress=10,
        message="正在检查文件格式与保护状态",
        conversion_values={
            "sourceFormat": fmt,
            "converter": converter,
            "optionsJson": json.dumps(options, ensure_ascii=False, sort_keys=True),
        },
    )
    source_hash = _sha256(source)
    try:
        engine_version = converter_version(settings, fmt, command_runner)
    except ConversionFailure as exc:
        _record_failure(db, import_task_id, exc)
        raise
    version = _libmobi_pipeline_version(engine_version) if converter == "libmobi" else engine_version
    cache_signature = json.dumps(
        {"converter": converter, "converterVersion": version, "sourceFormat": fmt, "options": options},
        ensure_ascii=False,
        sort_keys=True,
    )
    cache_key = hashlib.sha256(cache_signature.encode("utf-8")).hexdigest()[:16]
    final_path = settings.conversion_root / source_hash / cache_key / "book.epub"
    if final_path.is_file():
        try:
            validate_epub(final_path, max_bytes=settings.ebook_conversion_max_output_bytes)
            normalized_inspection = validate_normalized_epub(final_path) if converter == "libmobi" else None
        except ConversionFailure:
            final_path.unlink(missing_ok=True)
            final_path.with_name("normalization.json").unlink(missing_ok=True)
        except EpubNormalizationError:
            final_path.unlink(missing_ok=True)
            final_path.with_name("normalization.json").unlink(missing_ok=True)
        else:
            if normalized_inspection is not None:
                options.update(_cached_normalization_options(final_path, normalized_inspection))
            _update_stage(
                db,
                import_task_id,
                status="COMPLETED",
                progress=85,
                message="已复用验证过的 EPUB，正在导入书库",
                conversion_values={
                    "sourceHash": source_hash,
                    "outputPath": str(final_path),
                    "converterVersion": version,
                    "optionsJson": json.dumps(options, ensure_ascii=False, sort_keys=True),
                    "errorCode": None,
                    "errorSummary": None,
                    "retryable": 0,
                    "finishedAt": _now(),
                },
            )
            return ConversionArtifact(source, final_path, fmt, source_hash, converter, version, True)

    temp_dir = settings.conversion_temp_root / import_task_id
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_path = temp_dir / "book.part.epub"
    _update_stage(
        db,
        import_task_id,
        status="CONVERTING",
        progress=20,
        message="正在生成 EPUB",
        conversion_values={
            "sourceHash": source_hash,
            "converterVersion": version,
            "optionsJson": json.dumps(options, ensure_ascii=False, sort_keys=True),
            "attempts": int(task.get("attempts") or 0) + 1,
            "startedAt": task.get("startedAt") or _now(),
            "finishedAt": None,
            "errorCode": None,
            "errorSummary": None,
            "retryable": 0,
        },
    )
    try:
        normalization_result: EpubNormalizationResult | None = None
        if converter == "libmobi":
            raw_output_path = temp_dir / "book.libmobi.epub"
            _run_libmobi_conversion(settings, command_runner, source, temp_dir, raw_output_path)
            validate_epub(raw_output_path, max_bytes=settings.ebook_conversion_max_output_bytes)
            try:
                inspection = inspect_libmobi_epub(raw_output_path)
                if inspection.requires_normalization:
                    _update_stage(
                        db,
                        import_task_id,
                        status="NORMALIZING",
                        progress=62,
                        message="正在修复异常 EPUB 并安全拆分章节",
                        conversion_values={
                            "optionsJson": json.dumps(
                                {
                                    **options,
                                    "normalizerVersion": EPUB_NORMALIZER_VERSION,
                                    "normalizationApplied": True,
                                    "normalizationReasons": list(inspection.reasons),
                                    "normalizationBefore": inspection.metrics(),
                                },
                                ensure_ascii=False,
                                sort_keys=True,
                            )
                        },
                    )
                    normalization_result = normalize_libmobi_epub(raw_output_path, output_path, inspection)
                else:
                    os.replace(raw_output_path, output_path)
                    normalization_result = EpubNormalizationResult(False, (), inspection, inspection)
                options.update(normalization_result.options())
            except EpubNormalizationError as exc:
                raise ConversionFailure(
                    "EPUB_NORMALIZATION_FAILED",
                    f"libmobi 转换结果无法安全标准化：{str(exc)[:800]}",
                ) from exc
        else:
            options = _run_internal_conversion(fmt, source, output_path, options)
            _update_stage(
                db,
                import_task_id,
                status="CONVERTING",
                progress=65,
                message="已识别章节与书内资源，正在封装 EPUB",
                conversion_values={"optionsJson": json.dumps(options, ensure_ascii=False, sort_keys=True)},
            )
        _update_stage(db, import_task_id, status="VALIDATING", progress=72, message="正在检查章节与书内资源")
        validate_epub(output_path, max_bytes=settings.ebook_conversion_max_output_bytes)
        if converter == "libmobi":
            try:
                validate_normalized_epub(output_path)
            except EpubNormalizationError as exc:
                raise ConversionFailure(
                    "EPUB_NORMALIZATION_FAILED",
                    f"标准化 EPUB 未通过完整性检查：{str(exc)[:800]}",
                ) from exc
        final_path.parent.mkdir(parents=True, exist_ok=True)
        os.replace(output_path, final_path)
        if normalization_result is not None:
            try:
                _write_normalization_options(final_path, normalization_result)
            except OSError:
                # The database row already carries the metrics; a missing cache sidecar
                # must not turn a readable EPUB into a failed import.
                pass
        _update_stage(
            db,
            import_task_id,
            status="COMPLETED",
            progress=85,
            message="转换完成，正在导入书库",
            conversion_values={
                "outputPath": str(final_path),
                "errorCode": None,
                "errorSummary": None,
                "retryable": 0,
                "finishedAt": _now(),
            },
        )
        return ConversionArtifact(source, final_path, fmt, source_hash, converter, version, False)
    except subprocess.TimeoutExpired as exc:
        failure = ConversionFailure("CONVERSION_TIMEOUT", "电子书转换超时，原文件已保留")
        _record_failure(db, import_task_id, failure)
        raise failure from exc
    except ConversionFailure as exc:
        _record_failure(db, import_task_id, exc)
        raise
    except (OSError, ValueError) as exc:
        failure = ConversionFailure("CONVERSION_FAILED", f"电子书转换失败：{str(exc)[:800]}")
        _record_failure(db, import_task_id, failure)
        raise failure from exc
    finally:
        if output_path.exists():
            output_path.unlink(missing_ok=True)
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


def _record_failure(db: Session, import_task_id: str, failure: ConversionFailure) -> None:
    summary = str(failure)[:MAX_LOG_CHARS]
    now = _now()
    if _has_table(db, "BookConversionTask"):
        db.execute(
            text(
                "UPDATE `BookConversionTask` SET `status` = 'FAILED', `progress` = 100, `retryable` = :retryable, "
                "`errorCode` = :error_code, `errorSummary` = :summary, `finishedAt` = :now, `updatedAt` = :now "
                "WHERE `importTaskId` = :id"
            ),
            {"retryable": failure.retryable, "error_code": failure.code, "summary": summary, "now": now, "id": import_task_id},
        )
    if _has_table(db, "ImportTask"):
        db.execute(
            text(
                "UPDATE `ImportTask` SET `errorCode` = :error_code, `retryable` = :retryable, "
                "`errorSummary` = :summary, `updatedAt` = :now WHERE `id` = :id"
            ),
            {"error_code": failure.code, "retryable": failure.retryable, "summary": summary, "now": now, "id": import_task_id},
        )
    db.commit()
