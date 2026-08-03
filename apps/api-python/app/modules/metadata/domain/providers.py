"""Stable metadata provider descriptors shared by bootstrap and runtime."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderConfigField:
    key: str
    label: str
    kind: str = "text"
    required: bool = False
    secret: bool = False
    placeholder: str | None = None
    help: str | None = None
    default: object = None


@dataclass(frozen=True)
class ProviderManifest:
    id: str
    name: str
    version: str
    description: str
    mode: str
    media_kinds: tuple[str, ...]
    fields: tuple[str, ...]
    capabilities: tuple[str, ...]
    config_fields: tuple[ProviderConfigField, ...]
    default_priority: int
    enabled_by_default: bool = False


BUILTIN_MANIFESTS: tuple[ProviderManifest, ...] = (
    ProviderManifest(
        id="douban",
        name="豆瓣图书",
        version="builtin",
        description="用于电子书和有声书，通过豆瓣读书网页获取图书信息。",
        mode="search",
        media_kinds=("EBOOK", "AUDIOBOOK"),
        fields=(
            "title",
            "author",
            "description",
            "tags",
            "seriesName",
            "coverUrl",
        ),
        capabilities=("automatic", "manual-search", "cover"),
        config_fields=(
            ProviderConfigField(
                key="baseUrl",
                label="站点地址",
                required=True,
                default="https://book.douban.com",
            ),
            ProviderConfigField(
                key="userAgent",
                label="User-Agent",
                required=True,
                default="ShukuStarship/0.1 (+https://github.com/GMD170629/ermao-library)",
                help="豆瓣网页请求使用的客户端标识。",
            ),
        ),
        default_priority=100,
        enabled_by_default=True,
    ),
    ProviderManifest(
        id="bangumi",
        name="Bangumi 漫画",
        version="builtin",
        description="用于电子书和漫画，通过 Bangumi 官方 API 获取条目与别名。",
        mode="search",
        media_kinds=("EBOOK", "COMIC"),
        fields=(
            "title",
            "author",
            "description",
            "tags",
            "seriesName",
            "coverUrl",
        ),
        capabilities=("automatic", "manual-search", "cover", "aliases"),
        config_fields=(
            ProviderConfigField(
                key="baseUrl",
                label="API 地址",
                required=True,
                default="https://api.bgm.tv",
            ),
            ProviderConfigField(
                key="userAgent",
                label="User-Agent",
                required=True,
                default="ShukuStarship/0.1 (https://github.com/GMD170629/ermao-library)",
            ),
            ProviderConfigField(
                key="accessToken",
                label="Access Token",
                kind="password",
                secret=True,
                help="可选；用于提高 API 可用性。",
            ),
        ),
        default_priority=110,
        enabled_by_default=True,
    ),
    ProviderManifest(
        id="ai",
        name="AI 元数据识别",
        version="builtin",
        description="使用 OpenAI-compatible Chat Completions 推断缺失元数据。",
        mode="infer",
        media_kinds=("EBOOK", "COMIC", "AUDIOBOOK"),
        fields=(
            "title",
            "author",
            "description",
            "tags",
            "seriesName",
            "seriesIndex",
        ),
        capabilities=("automatic", "manual-search", "fallback"),
        config_fields=(
            ProviderConfigField(
                key="baseUrl",
                label="API 地址",
                required=True,
                placeholder="https://api.openai.com/v1",
            ),
            ProviderConfigField(
                key="model", label="模型", required=True, placeholder="gpt-4.1-mini"
            ),
            ProviderConfigField(
                key="apiKey",
                label="API Key",
                kind="password",
                required=True,
                secret=True,
            ),
        ),
        default_priority=900,
    ),
)
