from __future__ import annotations

import json
import os
import re
import shutil
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlencode, urlparse
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

from sqlalchemy.orm import Session

from app.bootstrap.download import (
    claim_download_task_command,
    finalize_download_task_command,
)
from app.bootstrap.system import prepare_system_event
from app.core.config import Settings
from app.modules.download.infrastructure.tasks import (
    find_active_download_task as find_active_download_task_row,
)
from app.modules.download.infrastructure.tasks import (
    get_download_task,
    system_setting_value,
)
from app.modules.imports.domain.reflowable_formats import (
    REFLOWABLE_SOURCE_EXTENSIONS,
)
from app.modules.imports.public import SUPPORTED_AUDIO_EXTS

ALLOWED_EXTENSIONS = {
    ".epub",
    ".pdf",
    ".cbr",
    ".cbz",
    ".zip",
    ".rar",
    ".7z",
    ".torrent",
    *SUPPORTED_AUDIO_EXTS,
    *REFLOWABLE_SOURCE_EXTENSIONS,
}
BLOCKED_EXTENSIONS = {
    ".exe",
    ".sh",
    ".bat",
    ".cmd",
    ".js",
    ".php",
    ".msi",
    ".com",
    ".scr",
    ".ps1",
    ".vbs",
}
ACTIVE_DOWNLOAD_STATUSES = {"queued", "downloading", "downloaded", "completed"}


@dataclass(frozen=True)
class DownloadExecutionResult:
    task: dict[str, Any]
    import_result: Any = None


@dataclass(frozen=True)
class QbittorrentConfig:
    url: str | None = None
    username: str | None = None
    password: str | None = None
    category: str | None = None
    save_path: str | None = None


def now() -> datetime:
    return datetime.now(UTC)


def remote_ref(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def string_value(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def system_setting(db: Session, key: str) -> str | None:
    value = system_setting_value(db, key)
    if value is None:
        return None
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        parsed = value
    return string_value(parsed) or None


def qbittorrent_config(db: Session, settings: Settings) -> QbittorrentConfig:
    return QbittorrentConfig(
        url=system_setting(db, "download.qbittorrent.url") or settings.qbittorrent_url,
        username=system_setting(db, "download.qbittorrent.username")
        or settings.qbittorrent_username,
        password=system_setting(db, "download.qbittorrent.password")
        or settings.qbittorrent_password,
        category=system_setting(db, "download.qbittorrent.category")
        or settings.qbittorrent_category,
        save_path=system_setting(db, "download.qbittorrent.savePath")
        or settings.qbittorrent_save_path,
    )


def infer_download_task_type(provider_type: str, download_meta: Any) -> str:
    meta = remote_ref(download_meta)
    if string_value(meta.get("downloadUrl")):
        return "http"
    if provider_type in {"pt_rss", "torrent"}:
        return (
            "blackhole"
            if meta.get("type") == "blackhole"
            or meta.get("kind") == "blackhole"
            or string_value(meta.get("blackholePath"))
            else "torrent"
        )
    if provider_type in {"http", "rss", "comic_api"}:
        return "http"
    return "manual"


def has_usable_download_meta(provider_type: str, download_meta: Any) -> bool:
    meta = remote_ref(download_meta)
    if string_value(meta.get("downloadUrl")):
        return True
    return provider_type == "pt_rss" and bool(
        string_value(meta.get("magnetUrl"))
        or string_value(meta.get("torrentUrl"))
        or string_value(meta.get("blackholePath"))
    )


def create_remote_ref_from_search_record(record: dict[str, Any]) -> dict[str, Any]:
    download_meta = remote_ref(record.get("downloadMeta"))
    return {
        "providerType": record.get("providerType"),
        "externalId": record.get("externalId"),
        "externalUrl": record.get("externalUrl"),
        "format": record.get("format"),
        "size": record.get("size"),
        "downloadMeta": download_meta,
        **download_meta,
    }


def sanitize_filename(value: str) -> str:
    base = unicodedata.normalize("NFKC", Path(value).name)
    base = re.sub(r'[<>:"/\\|?*\x00-\x1F]', "_", base)
    base = re.sub(r"^\.+", "", base)
    base = re.sub(r"\s+", " ", base).strip()
    return base[:180] or "download"


def assert_allowed_extension(filename: str) -> None:
    ext = Path(filename).suffix.lower()
    if not ext:
        raise ValueError("下载文件缺少扩展名")
    if ext in BLOCKED_EXTENSIONS or ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"不允许下载 {ext[1:]} 文件")


def filename_from_content_disposition(header: str | None) -> str:
    if not header:
        return ""
    utf8_match = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", header, re.IGNORECASE)
    if utf8_match:
        return unquote(utf8_match.group(1).strip('"'))
    plain_match = re.search(r'filename\s*=\s*("?)([^";]+)\1', header, re.IGNORECASE)
    return plain_match.group(2) if plain_match else ""


def filename_from_url(value: str) -> str:
    parsed = urlparse(value)
    return unquote(Path(parsed.path).name) if parsed.path else ""


def unique_download_path(filename: str, root: Path) -> Path:
    directory = root.expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    sanitized = sanitize_filename(filename)
    parsed = Path(sanitized)
    stem = sanitize_filename(parsed.stem) or "download"
    suffix = parsed.suffix
    index = 0
    while True:
        candidate = (
            directory / f"{stem}{suffix}"
            if index == 0
            else directory / f"{stem}-{index}{suffix}"
        )
        resolved = candidate.resolve()
        if directory != resolved and directory not in resolved.parents:
            raise ValueError("下载路径越界")
        if not resolved.exists():
            return resolved
        index += 1


def task_save_root(task: dict[str, Any]) -> Path:
    raw = string_value(task.get("savePath"))
    if raw:
        root = Path(raw).expanduser().resolve()
        if root.exists() and root.is_dir():
            return root
    raise ValueError("下载任务缺少保存目录")


def _temporary_download_path(target_path: Path) -> Path:
    return target_path.with_name(f".{target_path.name}.{uuid4().hex}.part")


def _publish_text_file(target_path: Path, content: str) -> Path:
    temporary_path = _temporary_download_path(target_path)
    try:
        temporary_path.write_text(content, encoding="utf-8")
        if temporary_path.stat().st_size <= 0:
            raise ValueError("下载文件为空")
        os.replace(temporary_path, target_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return target_path


def execute_http_download(settings: Settings, task: dict[str, Any]) -> Path:
    ref = remote_ref(task.get("remoteRef"))
    download_url = string_value(ref.get("downloadUrl"))
    if not download_url:
        raise ValueError("下载任务缺少下载地址")
    parsed = urlparse(download_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("只允许 http/https 下载地址")

    request = UrlRequest(download_url, headers={"Accept": "*/*"})
    with urlopen(request, timeout=30) as response:
        filename = sanitize_filename(
            filename_from_content_disposition(
                response.headers.get("content-disposition")
            )
            or string_value(ref.get("filename"))
            or filename_from_url(response.geturl() or download_url)
            or string_value(task.get("displayName"))
        )
        assert_allowed_extension(filename)
        target_path = unique_download_path(filename, task_save_root(task))
        temporary_path = _temporary_download_path(target_path)
        try:
            with temporary_path.open("xb") as handle:
                shutil.copyfileobj(response, handle)
            if temporary_path.stat().st_size <= 0:
                raise ValueError("下载文件为空")
            os.replace(temporary_path, target_path)
            return target_path
        finally:
            temporary_path.unlink(missing_ok=True)


def execute_blackhole(settings: Settings, task: dict[str, Any]) -> Path:
    filename = sanitize_filename(f"{task.get('displayName') or task.get('id')}.txt")
    target_path = unique_download_path(filename, task_save_root(task))
    note = "\n".join(
        [
            "Blackhole download placeholder",
            f"Task: {task.get('id')}",
            f"Title: {task.get('displayName')}",
            f"Created: {now().isoformat()}",
            "",
            "This task type is a placeholder. No external BT client was invoked.",
        ]
    )
    return _publish_text_file(target_path, note)


def qbittorrent_endpoint(config: QbittorrentConfig, path: str) -> str:
    base = string_value(config.url)
    if not base:
        raise ValueError("qBittorrent URL 未配置")
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


def qbittorrent_request(
    config: QbittorrentConfig,
    path: str,
    payload: dict[str, str],
    cookie: str | None = None,
) -> tuple[int, str, str | None]:
    data = urlencode(payload).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    if cookie:
        headers["Cookie"] = cookie
    request = UrlRequest(
        qbittorrent_endpoint(config, path), data=data, headers=headers, method="POST"
    )
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8", "replace")
        return response.status, body, response.headers.get("set-cookie")


def qbittorrent_cookie(config: QbittorrentConfig) -> str | None:
    username = string_value(config.username)
    password = string_value(config.password)
    if not username and not password:
        return None
    status, body, cookie = qbittorrent_request(
        config, "/api/v2/auth/login", {"username": username, "password": password}
    )
    if status != 200 or body.strip().lower() not in {"ok", "ok.", ""}:
        raise ValueError("qBittorrent 登录失败")
    return cookie


def execute_qbittorrent_task(
    settings: Settings,
    config: QbittorrentConfig,
    task: dict[str, Any],
    torrent_ref: str,
    ref_type: str,
) -> Path:
    cookie = qbittorrent_cookie(config)
    payload = {"urls": torrent_ref, "paused": "false"}
    category = string_value(config.category)
    save_path = string_value(config.save_path)
    if category:
        payload["category"] = category
    if save_path:
        payload["savepath"] = save_path
    status, body, _cookie = qbittorrent_request(
        config, "/api/v2/torrents/add", payload, cookie
    )
    if status < 200 or status >= 300 or body.strip().lower() in {"fails.", "fail"}:
        raise ValueError(f"qBittorrent 提交失败：{body.strip() or status}")
    filename = ensure_suffix(
        string_value(task.get("displayName"))
        or string_value(task.get("id"))
        or "torrent",
        ".qbittorrent.json",
    )
    target_path = unique_download_path(filename, task_save_root(task))
    return _publish_text_file(
        target_path,
        json.dumps(
            {
                "type": "qbittorrent_submission",
                "taskId": task.get("id"),
                "title": task.get("displayName"),
                "refType": ref_type,
                "ref": torrent_ref,
                "category": category or None,
                "savePath": save_path or None,
                "expectedName": string_value(task.get("displayName")) or None,
                "submittedAt": now().isoformat(),
                "message": "任务已提交到 qBittorrent。下载完成后请从客户端保存目录导入成品文件。",
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def ensure_suffix(filename: str, suffix: str) -> str:
    return (
        filename if Path(filename).suffix.lower() == suffix else f"{filename}{suffix}"
    )


def execute_torrent_task(
    settings: Settings, task: dict[str, Any], qbit: QbittorrentConfig
) -> Path:
    ref = remote_ref(task.get("remoteRef"))
    torrent_url = string_value(ref.get("torrentUrl"))
    if torrent_url:
        if string_value(qbit.url):
            return execute_qbittorrent_task(
                settings, qbit, task, torrent_url, "torrentUrl"
            )
        return execute_http_download(
            settings,
            {
                **task,
                "remoteRef": {
                    **ref,
                    "downloadUrl": torrent_url,
                    "filename": ensure_suffix(
                        string_value(ref.get("filename"))
                        or string_value(task.get("displayName"))
                        or "download",
                        ".torrent",
                    ),
                },
            },
        )

    magnet_url = string_value(ref.get("magnetUrl"))
    if magnet_url:
        if not magnet_url.startswith("magnet:?"):
            raise ValueError("magnetUrl 格式不正确")
        if string_value(qbit.url):
            return execute_qbittorrent_task(
                settings, qbit, task, magnet_url, "magnetUrl"
            )
        filename = ensure_suffix(
            string_value(ref.get("filename"))
            or string_value(task.get("displayName"))
            or string_value(ref.get("externalId"))
            or str(task.get("id") or "torrent"),
            ".magnet",
        )
        target_path = unique_download_path(filename, task_save_root(task))
        return _publish_text_file(target_path, magnet_url)

    blackhole_path = string_value(ref.get("blackholePath"))
    if blackhole_path:
        return execute_blackhole(settings, task)
    raise ValueError("torrent 下载任务缺少 torrentUrl、magnetUrl 或 blackholePath")


def run_task(settings: Settings, task: dict[str, Any], qbit: QbittorrentConfig) -> Path:
    task_type = task.get("type")
    if task_type == "http":
        return execute_http_download(settings, task)
    if task_type == "blackhole":
        return execute_blackhole(settings, task)
    if task_type == "torrent":
        return execute_torrent_task(settings, task, qbit)
    raise ValueError(f"下载类型 {task_type} 暂未支持")


def error_summary(error: Exception) -> str:
    return str(error or "下载执行失败")[:500]


def execute_download_task(
    db: Session, settings: Settings, task_id: str
) -> DownloadExecutionResult:
    task = get_download_task(db, task_id)
    db.close()
    if not task:
        raise ValueError("下载任务不存在")
    if task.get("status") not in {"queued", "failed", "PENDING", "FAILED"}:
        return DownloadExecutionResult(task)
    qbit = qbittorrent_config(db, settings)
    db.close()
    claim_timestamp = now()
    claimed = claim_download_task_command(db, task_id, timestamp=claim_timestamp)
    if claimed is None:
        return DownloadExecutionResult(task)
    task = claimed
    try:
        file_path = run_task(settings, {**task, "status": "downloading"}, qbit)
        prepared_event = prepare_system_event(
            source="download",
            action="completed",
            message="下载完成，等待后台导入",
            target_type="downloadTask",
            target_id=task_id,
            metadata={
                "status": "downloaded",
                "filePath": str(file_path),
                "displayName": str(task.get("displayName") or ""),
            },
        )
        completed_at = now()
        updated = finalize_download_task_command(
            db,
            task_id,
            values={
                "status": "downloaded",
                "progress": 100,
                "filePath": str(file_path),
                "savePath": str(file_path.parent),
                "errorMessage": None,
                "updatedAt": completed_at,
            },
            event=prepared_event,
        )
        return DownloadExecutionResult(updated or task)
    except Exception as exc:  # noqa: BLE001 - task boundary persists failure state.
        summary = error_summary(exc)
        prepared_event = prepare_system_event(
            source="download",
            action="failed",
            level="error",
            message="下载失败",
            target_type="downloadTask",
            target_id=task_id,
            metadata={
                "status": "failed",
                "errorMessage": summary,
                "displayName": str(task.get("displayName") or ""),
            },
        )
        failed_at = now()
        updated = finalize_download_task_command(
            db,
            task_id,
            values={
                "status": "failed",
                "errorMessage": summary,
                "updatedAt": failed_at,
            },
            event=prepared_event,
        )
        return DownloadExecutionResult(updated or task)


def find_active_download_task(db: Session, record_id: str) -> dict[str, Any] | None:
    return find_active_download_task_row(db, record_id)
