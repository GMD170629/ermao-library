from __future__ import annotations

from html import escape
import os
from pathlib import Path
from urllib.parse import quote

from app.core.config import Settings


RESET_FILE_NAME = "reset-password.html"


def password_reset_url(app_base_url: str, token: str) -> str:
    return f"{app_base_url.rstrip('/')}/reset-password#token={quote(token, safe='')}"


def password_reset_file_path(settings: Settings) -> Path:
    return (settings.resolved_monitor_root or (settings.resolved_storage_root / "password-reset")) / RESET_FILE_NAME


def write_password_reset_file(settings: Settings, reset_url: str) -> Path:
    target = password_reset_file_path(settings)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    safe_url = escape(reset_url, quote=True)
    document = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>重置二毛图书密码</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f1ed; color: #242220; font: 16px/1.7 system-ui, sans-serif; }}
    main {{ width: min(520px, calc(100% - 48px)); padding: 36px; border: 1px solid #e2ddd6; border-radius: 24px; background: #fffdfa; box-shadow: 0 24px 70px rgba(62,48,38,.1); }}
    h1 {{ margin: 0 0 12px; font-size: 28px; }}
    p {{ color: #6f6a65; }}
    a {{ display: inline-block; margin-top: 14px; padding: 12px 20px; border-radius: 12px; background: #ff4f2a; color: white; text-decoration: none; }}
  </style>
</head>
<body>
  <main>
    <h1>重置密码</h1>
    <p>此链接在创建后 30 分钟内有效，并且只能使用一次。</p>
    <a href="{safe_url}">打开二毛图书并设置新密码</a>
  </main>
</body>
</html>
"""
    temporary.write_text(document, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return target
