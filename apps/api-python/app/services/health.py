from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.services.text_conversion import converter_capability


def _check(name: str, status: str, message: str) -> dict[str, str]:
    return {"name": name, "status": status, "message": message}


def _env_check(name: str, value: str | None, required: bool = True) -> dict[str, str]:
    if required and not value:
        return _check(name, "error", f"{name} 未配置")
    return _check(name, "ok" if value else "unknown", "已配置" if value else "未配置")


def _check_monitor_root(path: Path | None) -> dict[str, str] | None:
    if path is None:
        return None
    if not path.exists():
        return _check("monitorRootReadable", "error", f"监控文件夹不存在：{path}")
    if not path.is_dir():
        return _check("monitorRootReadable", "error", "监控文件夹不是目录")
    try:
        next(path.iterdir(), None)
    except OSError as exc:
        return _check("monitorRootReadable", "error", f"监控文件夹不可读：{exc}")
    return _check("monitorRootReadable", "ok", "监控文件夹可读")


def _check_storage_root(path: Path) -> dict[str, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(prefix=".health-", dir=path, delete=True) as probe:
            probe.write(b"ok")
            probe.flush()
        return _check("storageWritable", "ok", "书库文件夹可写")
    except OSError as exc:
        return _check("storageWritable", "error", f"书库文件夹不可写：{exc}")


def run_system_health_checks(db: Session, settings: Settings) -> dict[str, object]:
    checks = [
        _env_check("SESSION_SECRET", settings.session_secret, required=False),
        _env_check("MONITOR_ROOT", settings.monitor_root),
    ]

    try:
        db.execute(text("SELECT 1"))
        checks.append(_check("database", "ok", "数据库可连接"))
    except Exception as exc:  # noqa: BLE001 - health checks should report the raw failure.
        checks.append(_check("database", "error", f"数据库不可用：{exc}"))

    monitor_check = _check_monitor_root(settings.resolved_monitor_root)
    if monitor_check:
        checks.append(monitor_check)
    checks.append(_check_storage_root(settings.resolved_storage_root))
    conversion = converter_capability(settings)
    conversion_message = (
        "文本电子书转换可用"
        if conversion["available"]
        else "文本电子书转换已停用"
        if not settings.ebook_conversion_enabled
        else "TXT/FB2 可用，libmobi 暂不可用"
    )
    conversion_check: dict[str, object] = _check(
        "ebookConversion",
        "ok" if conversion["available"] else "unknown",
        conversion_message,
    )
    conversion_check["details"] = conversion
    checks.append(conversion_check)

    return {
        "status": "error" if any(check["status"] == "error" for check in checks) else "ok",
        "checks": checks,
    }
