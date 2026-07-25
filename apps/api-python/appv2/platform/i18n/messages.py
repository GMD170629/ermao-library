from __future__ import annotations

from typing import Literal

Locale = Literal["zh-CN", "en-US"]

_MESSAGES: dict[str, dict[Locale, str]] = {
    "invalid_request": {
        "zh-CN": "请求参数无效。",
        "en-US": "The request is invalid.",
    },
    "authentication_required": {
        "zh-CN": "请先登录。",
        "en-US": "Authentication is required.",
    },
    "permission_denied": {
        "zh-CN": "当前账户无权执行此操作。",
        "en-US": "The current account is not allowed to perform this action.",
    },
    "not_found": {
        "zh-CN": "请求的资源不存在。",
        "en-US": "The requested resource does not exist.",
    },
    "conflict": {
        "zh-CN": "资源状态与当前操作冲突。",
        "en-US": "The resource state conflicts with this operation.",
    },
    "internal_error": {
        "zh-CN": "服务暂时无法完成请求。",
        "en-US": "The service could not complete the request.",
    },
    "maintenance": {
        "zh-CN": "系统正在维护，请稍后重试。",
        "en-US": "The system is under maintenance. Try again later.",
    },
}


def translate(message_key: str, locale: Locale) -> str:
    messages = _MESSAGES.get(message_key, _MESSAGES["internal_error"])
    return messages[locale]
