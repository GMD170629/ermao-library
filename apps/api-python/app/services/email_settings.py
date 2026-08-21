from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from typing import Any

from email_validator import EmailNotValidError, validate_email
from sqlalchemy.orm import Session

from app.modules.system.infrastructure.settings import (
    PreparedSettingsWrite,
    delete_setting,
    existing_setting_keys,
    get_settings_raw,
    parse_setting_value,
    prepare_settings_write,
    write_prepared_settings,
)

SMTP_PASSWORD_KEY = "email.smtp.password"
SETTING_KEYS = {
    "host": "email.smtp.host",
    "port": "email.smtp.port",
    "security": "email.smtp.security",
    "username": "email.smtp.username",
    "password": SMTP_PASSWORD_KEY,
    "fromEmail": "email.smtp.fromEmail",
    "fromName": "email.smtp.fromName",
    "maxAttachmentMb": "email.smtp.maxAttachmentMb",
    "kindleEmail": "kindle.email",
}
SMTP_SECURITY_VALUES = {"starttls", "ssl", "none"}


class EmailSettingsError(ValueError):
    pass


@dataclass(frozen=True)
class SmtpConnectionSettings:
    host: str
    port: int
    security: str
    username: str
    password: str
    from_email: str
    from_name: str
    max_attachment_mb: float | None


@dataclass(frozen=True)
class PreparedEmailSettingsUpdate:
    supplied: dict[str, Any]
    settings_write: PreparedSettingsWrite
    clear_password: bool
    changed_keys: tuple[str, ...]


def _load_values(db: Session) -> dict[str, Any]:
    keys = list(SETTING_KEYS.values())
    existing = existing_setting_keys(db, keys)
    if not existing:
        return {}
    raw = get_settings_raw(db, keys)
    return {key: parse_setting_value(raw[key]) for key in existing}


def _string(value: Any) -> str:
    return str(value or "").strip()


def _port(value: Any) -> int:
    if value in (None, ""):
        return 587
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise EmailSettingsError("SMTP 端口必须是整数") from None
    if not 1 <= port <= 65535:
        raise EmailSettingsError("SMTP 端口必须在 1 到 65535 之间")
    return port


def _max_attachment_mb(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        size = float(value)
    except (TypeError, ValueError):
        raise EmailSettingsError("附件大小上限必须是数字") from None
    if not 1 <= size <= 1000:
        raise EmailSettingsError("附件大小上限必须在 1 MB 到 1000 MB 之间")
    return round(size, 2)


def _email(value: Any, label: str, *, required: bool = False) -> str:
    candidate = _string(value)
    if not candidate:
        if required:
            raise EmailSettingsError(f"请填写{label}")
        return ""
    if "\r" in candidate or "\n" in candidate:
        raise EmailSettingsError(f"{label}格式不正确")
    try:
        return validate_email(candidate, check_deliverability=False).normalized
    except EmailNotValidError:
        raise EmailSettingsError(f"{label}格式不正确") from None


def _header(value: Any, label: str) -> str:
    candidate = _string(value)
    if "\r" in candidate or "\n" in candidate:
        raise EmailSettingsError(f"{label}不能包含换行符")
    return candidate


def _normalized(values: dict[str, Any]) -> dict[str, Any]:
    security = _string(values.get("security") or "starttls").lower()
    if security not in SMTP_SECURITY_VALUES:
        raise EmailSettingsError("SMTP 安全模式不受支持")
    return {
        "host": _header(values.get("host"), "SMTP 主机"),
        "port": _port(values.get("port")),
        "security": security,
        "username": _header(values.get("username"), "SMTP 用户名"),
        "password": str(values.get("password") or ""),
        "fromEmail": _email(values.get("fromEmail"), "发件邮箱"),
        "fromName": _header(values.get("fromName") or "二毛图书", "发件名称"),
        "maxAttachmentMb": _max_attachment_mb(values.get("maxAttachmentMb")),
        "kindleEmail": _email(values.get("kindleEmail"), "Kindle 邮箱"),
    }


def get_email_settings(
    db: Session, *, include_password: bool = False
) -> dict[str, Any]:
    stored = _load_values(db)
    values = {name: stored.get(key) for name, key in SETTING_KEYS.items()}
    normalized = _normalized(values)
    if not include_password:
        normalized.pop("password", None)
        normalized["passwordConfigured"] = bool(_string(stored.get(SMTP_PASSWORD_KEY)))
    return normalized


def public_email_settings(db: Session) -> dict[str, Any]:
    values = get_email_settings(db)
    return {
        "smtp": {
            key: values[key]
            for key in (
                "host",
                "port",
                "security",
                "username",
                "fromEmail",
                "fromName",
                "maxAttachmentMb",
                "passwordConfigured",
            )
        },
        "kindle": {"email": values["kindleEmail"]},
    }


def candidate_email_settings(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_email_settings(db, include_password=True)
    smtp_value = payload.get("smtp")
    smtp: dict[str, Any] = smtp_value if isinstance(smtp_value, dict) else {}
    kindle_value = payload.get("kindle")
    kindle: dict[str, Any] = kindle_value if isinstance(kindle_value, dict) else {}
    mapping = {
        "host": smtp.get("host", current["host"]),
        "port": smtp.get("port", current["port"]),
        "security": smtp.get("security", current["security"]),
        "username": smtp.get("username", current["username"]),
        "password": smtp.get("password") or current["password"],
        "fromEmail": smtp.get("fromEmail", current["fromEmail"]),
        "fromName": smtp.get("fromName", current["fromName"]),
        "maxAttachmentMb": smtp.get("maxAttachmentMb", current["maxAttachmentMb"]),
        "kindleEmail": kindle.get("email", current["kindleEmail"]),
    }
    if payload.get("clearSmtpPassword") is True:
        mapping["password"] = ""
    return _normalized(mapping)


def prepare_email_settings_update(
    db: Session, payload: dict[str, Any]
) -> PreparedEmailSettingsUpdate:
    normalized = candidate_email_settings(db, payload)
    smtp_value = payload.get("smtp")
    smtp: dict[str, Any] = smtp_value if isinstance(smtp_value, dict) else {}
    kindle_value = payload.get("kindle")
    kindle: dict[str, Any] = kindle_value if isinstance(kindle_value, dict) else {}
    supplied: dict[str, Any] = {}
    for key in (
        "host",
        "port",
        "security",
        "username",
        "fromEmail",
        "fromName",
        "maxAttachmentMb",
    ):
        if key in smtp:
            supplied[SETTING_KEYS[key]] = normalized[key]
    if "password" in smtp and str(smtp.get("password") or "").strip():
        supplied[SMTP_PASSWORD_KEY] = str(smtp["password"])
    if "email" in kindle:
        supplied[SETTING_KEYS["kindleEmail"]] = normalized["kindleEmail"]

    changed_keys = list(supplied.keys())
    clear_password = payload.get("clearSmtpPassword") is True
    if clear_password and SMTP_PASSWORD_KEY not in changed_keys:
        changed_keys.append(SMTP_PASSWORD_KEY)

    return PreparedEmailSettingsUpdate(
        supplied=supplied,
        settings_write=prepare_settings_write(supplied),
        clear_password=clear_password,
        changed_keys=tuple(changed_keys),
    )


def write_prepared_email_settings(
    db: Session, prepared: PreparedEmailSettingsUpdate
) -> None:
    write_prepared_settings(db, prepared.settings_write)
    if prepared.clear_password:
        delete_setting(db, SMTP_PASSWORD_KEY)


def smtp_connection_settings(
    values: dict[str, Any], *, require_sender: bool = True
) -> SmtpConnectionSettings:
    host = _string(values.get("host"))
    if not host:
        raise EmailSettingsError("请填写 SMTP 主机")
    username = _string(values.get("username"))
    password = str(values.get("password") or "")
    if username and not password:
        raise EmailSettingsError("SMTP 用户名已填写，请同时填写密码")
    if password and not username:
        raise EmailSettingsError("SMTP 密码已填写，请同时填写用户名")
    from_email = _email(values.get("fromEmail"), "发件邮箱", required=require_sender)
    return SmtpConnectionSettings(
        host=host,
        port=_port(values.get("port")),
        security=_string(values.get("security") or "starttls").lower(),
        username=username,
        password=password,
        from_email=from_email,
        from_name=_header(values.get("fromName") or "二毛图书", "发件名称"),
        max_attachment_mb=_max_attachment_mb(values.get("maxAttachmentMb")),
    )


def open_smtp_connection(
    config: SmtpConnectionSettings, *, timeout: int = 30
) -> smtplib.SMTP:
    context = ssl.create_default_context()
    if config.security == "ssl":
        client: smtplib.SMTP = smtplib.SMTP_SSL(
            config.host, config.port, timeout=timeout, context=context
        )
    else:
        client = smtplib.SMTP(config.host, config.port, timeout=timeout)
        client.ehlo()
        if config.security == "starttls":
            client.starttls(context=context)
            client.ehlo()
    if config.username:
        client.login(config.username, config.password)
    return client


def test_smtp_connection(values: dict[str, Any], *, timeout: int = 30) -> None:
    config = smtp_connection_settings(values, require_sender=False)
    client: smtplib.SMTP | None = None
    try:
        client = open_smtp_connection(config, timeout=timeout)
        client.noop()
    finally:
        if client is not None:
            try:
                client.quit()
            except (OSError, smtplib.SMTPException):
                client.close()
