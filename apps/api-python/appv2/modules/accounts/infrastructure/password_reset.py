from __future__ import annotations

import os
from html import escape
from pathlib import Path

from appv2.modules.accounts.contracts import PasswordResetNoticePort


class LocalPasswordResetNotice(PasswordResetNoticePort):
    """Publishes the one-time reset link to an owner-readable local HTML file."""

    def __init__(self, control_root: Path) -> None:
        self._path = control_root / "reset-password.html"

    @property
    def path(self) -> Path:
        return self._path

    def write(self, *, reset_url: str, locale: str) -> Path:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        if locale == "en-US":
            title = "Reset your Ermao Books password"
            heading = "Reset password"
            description = "This link is valid for 30 minutes and can only be used once."
            action = "Open Ermao Books and set a new password"
        else:
            title = "重置二毛图书密码"
            heading = "重置密码"
            description = "此链接在创建后 30 分钟内有效，并且只能使用一次。"
            action = "打开二毛图书并设置新密码"
        safe_url = escape(reset_url, quote=True)
        document = f"""<!doctype html>
<html lang="{locale}">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    body {{ margin: 0; min-height: 100vh; display: grid; place-items: center;
      background: #f4f1ed; color: #242220; font: 16px/1.7 system-ui, sans-serif; }}
    main {{ width: min(520px, calc(100% - 48px)); padding: 36px;
      border: 1px solid #e2ddd6; border-radius: 24px; background: #fffdfa;
      box-shadow: 0 24px 70px rgba(62,48,38,.1); }}
    h1 {{ margin: 0 0 12px; font-size: 28px; }}
    p {{ color: #6f6a65; }}
    a {{ display: inline-block; margin-top: 14px; padding: 12px 20px;
      border-radius: 12px; background: #ff4f2a; color: white; text-decoration: none; }}
  </style>
</head>
<body>
  <main>
    <h1>{heading}</h1>
    <p>{description}</p>
    <a href="{safe_url}">{action}</a>
  </main>
</body>
</html>
"""
        temporary.write_text(document, encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self._path)
        return self._path

    def clear(self) -> None:
        self._path.unlink(missing_ok=True)
