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
class AutomaticRateLimit:
    requests: int
    period_seconds: float

    def __post_init__(self) -> None:
        if self.requests <= 0:
            raise ValueError("requests must be greater than zero")
        if self.period_seconds <= 0:
            raise ValueError("period_seconds must be greater than zero")

    @property
    def minimum_interval_seconds(self) -> float:
        return self.period_seconds / self.requests


@dataclass(frozen=True)
class ProviderManifest:
    id: str
    name: str
    version: str
    description: str
    mode: str
    fields: tuple[str, ...]
    capabilities: tuple[str, ...]
    config_fields: tuple[ProviderConfigField, ...]
    default_priority: int
    enabled_by_default: bool = False
    automatic_rate_limit: AutomaticRateLimit | None = None
    participation_modes: tuple[str, ...] = ("OFF", "MANUAL_ONLY")
    query_types: tuple[str, ...] = ("title",)
    match_levels: tuple[str, ...] = ("UNKNOWN",)


BUILTIN_MANIFESTS: tuple[ProviderManifest, ...] = (
    ProviderManifest(
        id="douban",
        name="豆瓣图书",
        version="builtin",
        description="通过豆瓣读书网页获取图书信息。",
        mode="search",
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
        participation_modes=("OFF", "MANUAL_ONLY", "AUTO_AND_MANUAL"),
        query_types=("isbn", "title", "author", "source-id"),
        match_levels=("WORK", "VOLUME", "EDITION"),
        # Douban's robots policy publishes Crawl-delay: 5 guidance.
        # https://www.douban.com/robots.txt
        automatic_rate_limit=AutomaticRateLimit(requests=1, period_seconds=5.0),
    ),
    ProviderManifest(
        id="bangumi",
        name="Bangumi",
        version="builtin",
        description="通过 Bangumi 官方 API 获取条目与别名。",
        mode="search",
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
        participation_modes=("OFF", "MANUAL_ONLY", "AUTO_AND_MANUAL"),
        query_types=("title", "alias", "source-id"),
        match_levels=("WORK", "VOLUME"),
        # Bangumi's server defaults to 3,000 requests per 10 minutes. Keep
        # 20% headroom below that published implementation ceiling.
        # https://github.com/bangumi/server/blob/master/config/config.go
        automatic_rate_limit=AutomaticRateLimit(requests=4, period_seconds=1.0),
    ),
    ProviderManifest(
        id="google-books", name="Google Books", version="builtin",
        description="Google Books 官方书目 / Official bibliographic API", mode="search",
        fields=("title", "author", "description", "isbn", "publisher", "publishedAt", "language", "coverUrl"),
        capabilities=("automatic", "manual-search", "cover"),
        config_fields=(ProviderConfigField(key="apiKey", label="API Key", kind="password", secret=True, required=True),),
        default_priority=120, automatic_rate_limit=AutomaticRateLimit(1, 1.0),
        participation_modes=("OFF", "MANUAL_ONLY", "AUTO_AND_MANUAL"),
        query_types=("isbn", "title", "author", "source-id"), match_levels=("EDITION",),
    ),
    ProviderManifest(
        id="open-library", name="Open Library", version="builtin",
        description="仅单目标人工查询 / Explicit single-target manual queries only", mode="search",
        fields=("title", "author", "description", "isbn", "publisher", "publishedAt", "language", "coverUrl"),
        capabilities=("manual-search", "cover"),
        config_fields=(ProviderConfigField(key="userAgent", label="User-Agent", required=True,
            default="ErmaoLibrary/1.0 (https://github.com/GMD170629/ermao-library)"),),
        default_priority=130, automatic_rate_limit=AutomaticRateLimit(1, 1.0),
        query_types=("isbn", "title", "author", "source-id"), match_levels=("WORK", "EDITION"),
    ),
    ProviderManifest(
        id="ai",
        name="AI 元数据识别",
        version="builtin",
        description="有证据引用的查询建议与候选消歧 / Evidence-bound query and candidate assistance",
        mode="assist",
        fields=(),
        capabilities=("manual-assistance", "ambiguous-assistance"),
        config_fields=(
            ProviderConfigField(key="assistanceMode", label="辅助模式 / Assistance mode", default="SUGGEST_ONLY"),
            ProviderConfigField(key="authentication", label="认证方式 / Authentication", default="bearer"),
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
        automatic_rate_limit=AutomaticRateLimit(1, 1.0),
    ),
)
