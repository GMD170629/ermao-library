from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from importlib import metadata as importlib_metadata
from typing import Any, Protocol
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from sqlalchemy.orm import Session

from app.bootstrap.metadata import ensure_metadata_sources
from app.modules.metadata.application.rate_limits import AutomaticMetadataRequestGate
from app.modules.metadata.domain.providers import BUILTIN_MANIFESTS, ProviderManifest
from app.modules.metadata.infrastructure.providers import (
    clear_media_kind_pipelines,
    ensure_pipeline_row,
    get_provider_source,
    list_enabled_provider_ids,
    list_included_pipelines,
    list_metadata_sources,
    list_pipelines_for_provider,
    set_provider_pipelines_enabled,
    update_pipeline_row,
    update_source_config,
    update_source_enabled_priority,
    update_source_test_result,
)

LOGGER = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "shuku_starship.metadata_providers"
METADATA_MEDIA_KINDS = ("EBOOK", "COMIC", "AUDIOBOOK")


def _now() -> datetime:
    return datetime.now(UTC)


def _json_value(value: Any, fallback: Any = None) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list, bool, int, float)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class MetadataProviderPlugin(Protocol):
    manifest: ProviderManifest

    def search(
        self,
        db: Session,
        context: dict[str, Any],
        query: str | None = None,
        *,
        config: dict[str, Any],
        force: bool = False,
        use_cache: bool = True,
    ) -> dict[str, Any]: ...

    def test(self, config: dict[str, Any]) -> dict[str, Any]: ...


class BuiltinMetadataProvider:
    def __init__(self, manifest: ProviderManifest) -> None:
        self.manifest = manifest

    def search(
        self,
        db: Session,
        context: dict[str, Any],
        query: str | None = None,
        *,
        config: dict[str, Any] | None = None,
        force: bool = False,
        use_cache: bool = True,
        automatic_request_gate: AutomaticMetadataRequestGate | None = None,
    ) -> dict[str, Any]:
        from app.services.organize_service import metadata_search_candidates

        return metadata_search_candidates(
            db,
            context,
            self.manifest.id,
            query,
            config=config or {},
            force=force,
            use_cache=use_cache,
            automatic_request_gate=automatic_request_gate,
        )

    def test(self, config: dict[str, Any]) -> dict[str, Any]:
        provider_id = self.manifest.id
        if provider_id == "douban":
            request = UrlRequest(
                "https://book.douban.com/",
                headers={
                    "Accept": "text/html,*/*",
                    "User-Agent": str(
                        config.get("userAgent")
                        or _default_config(self.manifest).get("userAgent")
                        or "ShukuStarship/0.1"
                    ),
                },
            )
        elif provider_id == "bangumi":
            base_url = str(config.get("baseUrl") or "https://api.bgm.tv").rstrip("/")
            headers = {
                "Accept": "application/json",
                "User-Agent": str(
                    config.get("userAgent")
                    or _default_config(self.manifest).get("userAgent")
                    or "ShukuStarship/0.1"
                ),
            }
            if str(config.get("accessToken") or "").strip():
                headers["Authorization"] = (
                    f"Bearer {str(config['accessToken']).strip()}"
                )
            request = UrlRequest(f"{base_url}/v0/subjects/1", headers=headers)
        else:
            base_url = str(config.get("baseUrl") or "").rstrip("/")
            api_key = str(config.get("apiKey") or "").strip()
            if not base_url or not api_key:
                return {"ok": False, "message": "请先填写 API 地址和 API Key"}
            request = UrlRequest(
                f"{base_url}/models",
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
            )
        with urlopen(request, timeout=10) as response:
            status = int(getattr(response, "status", 200) or 200)
        return {
            "ok": 200 <= status < 400,
            "message": "连接正常" if status < 400 else f"服务返回 HTTP {status}",
        }


class MetadataProviderRegistry:
    def __init__(self) -> None:
        self._plugins: dict[str, MetadataProviderPlugin] = {}
        for manifest in BUILTIN_MANIFESTS:
            self.register(BuiltinMetadataProvider(manifest))
        self._load_entry_points()

    def register(self, plugin: MetadataProviderPlugin) -> None:
        manifest = plugin.manifest
        if not manifest.id or manifest.id in self._plugins:
            if manifest.id in self._plugins:
                raise ValueError(f"重复的元数据插件 id：{manifest.id}")
            raise ValueError("元数据插件 id 不能为空")
        self._plugins[manifest.id] = plugin

    def _load_entry_points(self) -> None:
        try:
            entry_points = importlib_metadata.entry_points()
            selected = (
                entry_points.select(group=ENTRY_POINT_GROUP)
                if hasattr(entry_points, "select")
                else entry_points.get(ENTRY_POINT_GROUP, [])
            )
        except Exception:
            LOGGER.exception("failed to discover metadata provider entry points")
            return
        for entry_point in selected:
            try:
                loaded = entry_point.load()
                plugin = loaded() if isinstance(loaded, type) else loaded
                self.register(plugin)
            except Exception:
                LOGGER.exception(
                    "failed to load metadata provider entry point name=%s",
                    getattr(entry_point, "name", "unknown"),
                )

    def get(self, provider_id: str) -> MetadataProviderPlugin | None:
        return self._plugins.get(provider_id)

    def require(self, provider_id: str) -> MetadataProviderPlugin:
        plugin = self.get(provider_id)
        if not plugin:
            raise ValueError("不支持的元数据来源")
        return plugin

    def all(self) -> list[MetadataProviderPlugin]:
        return list(self._plugins.values())

    def ids(self) -> set[str]:
        return set(self._plugins)


_REGISTRY: MetadataProviderRegistry | None = None


def metadata_provider_registry() -> MetadataProviderRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = MetadataProviderRegistry()
    return _REGISTRY


def _default_config(manifest: ProviderManifest) -> dict[str, Any]:
    return {
        field.key: field.default
        for field in manifest.config_fields
        if field.default is not None
    }


def ensure_metadata_provider_sources(db: Session) -> list[dict[str, Any]]:
    registry = metadata_provider_registry()
    ensure_metadata_sources(db, (plugin.manifest for plugin in registry.all()))
    sources = list_metadata_sources(db)
    if sources:
        db.commit()
    return sources


def ensure_metadata_provider_pipelines(db: Session) -> None:
    from sqlalchemy import inspect

    if not inspect(db.connection()).has_table("MetadataProviderPipeline"):
        return
    sources = ensure_metadata_provider_sources(db)
    source_by_provider = {str(item.get("providerType")): item for item in sources}
    now = _now()
    for plugin in metadata_provider_registry().all():
        source = source_by_provider.get(plugin.manifest.id) or {}
        for media_kind in plugin.manifest.media_kinds:
            ensure_pipeline_row(
                db,
                media_kind=media_kind,
                provider_id=plugin.manifest.id,
                enabled=bool(source.get("enabled")),
                position=int(
                    source.get("priority") or plugin.manifest.default_priority
                ),
                now=now,
            )
    db.commit()


def list_metadata_provider_pipelines(db: Session) -> list[dict[str, Any]]:
    ensure_metadata_provider_pipelines(db)
    providers = {str(item["id"]): item for item in list_metadata_providers(db)}
    rows = list_included_pipelines(db)
    by_kind: dict[str, list[dict[str, Any]]] = {
        media_kind: [] for media_kind in METADATA_MEDIA_KINDS
    }
    for row in rows:
        provider = providers.get(str(row.get("providerId")))
        media_kind = str(row.get("mediaKind") or "")
        if not provider or media_kind not in by_kind:
            continue
        by_kind[media_kind].append(
            {
                "providerId": provider["id"],
                "name": provider["name"],
                "description": provider["description"],
                "enabled": bool(row.get("enabled")),
                "position": int(row.get("position") or 0),
                "lastTestStatus": provider.get("lastTestStatus"),
                "lastError": provider.get("lastError"),
            }
        )
    return [
        {"mediaKind": media_kind, "providers": by_kind[media_kind]}
        for media_kind in METADATA_MEDIA_KINDS
    ]


def _sync_provider_source_from_pipelines(
    db: Session, provider_id: str, now: datetime
) -> tuple[bool, int]:
    rows = list_pipelines_for_provider(db, provider_id)
    enabled = any(bool(item.get("enabled")) for item in rows)
    enabled_positions = [
        int(item.get("position") or 9999) for item in rows if item.get("enabled")
    ]
    priority = (
        min(enabled_positions)
        if enabled_positions
        else min([int(item.get("position") or 9999) for item in rows] or [9999])
    )
    update_source_enabled_priority(
        db, provider_id, enabled=enabled, priority=priority, now=now
    )
    return enabled, priority


def update_metadata_provider_pipeline(
    db: Session, media_kind: str, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    normalized = str(media_kind or "").strip().upper()
    if normalized not in METADATA_MEDIA_KINDS:
        raise ValueError("不支持的读物类型")
    if not isinstance(items, list):
        raise ValueError("数据源顺序格式不正确")
    ensure_metadata_provider_pipelines(db)
    registry = metadata_provider_registry()
    provider_ids = [
        str(item.get("providerId") or "").strip()
        for item in items
        if isinstance(item, dict)
    ]
    if (
        len(provider_ids) != len(items)
        or not all(provider_ids)
        or len(set(provider_ids)) != len(provider_ids)
    ):
        raise ValueError("数据源列表包含无效或重复项目")
    for item, provider_id in zip(items, provider_ids):
        plugin = registry.get(provider_id)
        if not plugin or normalized not in plugin.manifest.media_kinds:
            raise ValueError(f"数据源 {provider_id} 不支持{normalized}")
        if bool(item.get("enabled")):
            source = _provider_source(db, provider_id)
            errors = _validate_config(
                plugin.manifest, _source_config(source, plugin.manifest), True
            )
            if errors:
                raise ValueError(f"{plugin.manifest.name}：{'；'.join(errors)}")
    now = _now()
    clear_media_kind_pipelines(db, normalized, now)
    for index, (item, provider_id) in enumerate(zip(items, provider_ids), start=1):
        update_pipeline_row(
            db,
            media_kind=normalized,
            provider_id=provider_id,
            included=True,
            enabled=bool(item.get("enabled")),
            position=index * 100,
            now=now,
        )
    for provider_id in {str(plugin.manifest.id) for plugin in registry.all()}:
        _sync_provider_source_from_pipelines(db, provider_id, now)
    db.commit()
    return list_metadata_provider_pipelines(db)


def _provider_source(db: Session, provider_id: str) -> dict[str, Any] | None:
    ensure_metadata_provider_sources(db)
    return get_provider_source(db, provider_id)


def _source_config(
    source: dict[str, Any] | None, manifest: ProviderManifest
) -> dict[str, Any]:
    value = _json_value((source or {}).get("config"), {})
    return {**_default_config(manifest), **(value if isinstance(value, dict) else {})}


def _secret_fields(manifest: ProviderManifest) -> set[str]:
    return {field.key for field in manifest.config_fields if field.secret}


def _provider_public_view(
    source: dict[str, Any], plugin: MetadataProviderPlugin
) -> dict[str, Any]:
    manifest = plugin.manifest
    config = _source_config(source, manifest)
    secrets = _secret_fields(manifest)
    public_config = {key: value for key, value in config.items() if key not in secrets}
    configured_secrets = {
        key: bool(str(config.get(key) or "").strip()) for key in secrets
    }
    return {
        "id": manifest.id,
        "sourceId": source.get("id"),
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "mode": manifest.mode,
        "mediaKinds": list(manifest.media_kinds),
        "fields": list(manifest.fields),
        "capabilities": list(manifest.capabilities),
        "automaticRateLimit": (
            asdict(manifest.automatic_rate_limit)
            if manifest.automatic_rate_limit is not None
            else None
        ),
        "configFields": [asdict(field) for field in manifest.config_fields],
        "config": public_config,
        "configuredSecrets": configured_secrets,
        "enabled": bool(source.get("enabled")),
        "priority": int(source.get("priority") or manifest.default_priority),
        "lastTestAt": source.get("lastTestAt"),
        "lastTestStatus": source.get("lastTestStatus"),
        "lastError": source.get("lastError"),
    }


def list_metadata_providers(db: Session) -> list[dict[str, Any]]:
    sources = ensure_metadata_provider_sources(db)
    registry = metadata_provider_registry()
    result = []
    for source in sources:
        plugin = registry.get(str(source.get("providerType") or ""))
        if plugin:
            result.append(_provider_public_view(source, plugin))
    return result


def get_metadata_provider(db: Session, provider_id: str) -> dict[str, Any] | None:
    plugin = metadata_provider_registry().get(provider_id)
    source = _provider_source(db, provider_id) if plugin else None
    return _provider_public_view(source, plugin) if source and plugin else None


def _validate_config(
    manifest: ProviderManifest, config: dict[str, Any], enabled: bool
) -> list[str]:
    errors: list[str] = []
    allowed = {field.key for field in manifest.config_fields}
    unknown = sorted(set(config) - allowed)
    if unknown:
        errors.append(f"包含未知配置项：{', '.join(unknown)}")
    if enabled:
        for field in manifest.config_fields:
            if field.required and not str(config.get(field.key) or "").strip():
                errors.append(f"{field.label}不能为空")
    return errors


def update_metadata_provider(
    db: Session, provider_id: str, payload: dict[str, Any]
) -> dict[str, Any]:
    plugin = metadata_provider_registry().require(provider_id)
    source = _provider_source(db, provider_id)
    if not source:
        raise ValueError("元数据插件配置不存在")
    current_config = _source_config(source, plugin.manifest)
    incoming = payload.get("config")
    if incoming is not None and not isinstance(incoming, dict):
        raise ValueError("插件配置格式不正确")
    next_config = {**current_config}
    if isinstance(incoming, dict):
        for field in plugin.manifest.config_fields:
            if field.key not in incoming:
                continue
            value = incoming[field.key]
            if field.secret and (value is None or str(value).strip() == ""):
                continue
            next_config[field.key] = value
    clear_secrets = payload.get("clearSecrets") or []
    if not isinstance(clear_secrets, list):
        raise ValueError("清除凭据格式不正确")
    for key in clear_secrets:
        if str(key) in _secret_fields(plugin.manifest):
            next_config.pop(str(key), None)
    enabled = bool(payload.get("enabled", source.get("enabled")))
    errors = _validate_config(plugin.manifest, next_config, enabled)
    if errors:
        raise ValueError("；".join(errors))
    try:
        priority = int(
            payload.get(
                "priority", source.get("priority") or plugin.manifest.default_priority
            )
        )
    except (TypeError, ValueError):
        raise ValueError("插件优先级格式不正确") from None
    priority = min(max(priority, 1), 9999)
    now = _now()
    update_source_config(
        db,
        str(source["id"]),
        enabled=enabled,
        priority=priority,
        config=_json_text(next_config),
        now=now,
    )
    if "enabled" in payload:
        ensure_metadata_provider_pipelines(db)
        set_provider_pipelines_enabled(db, provider_id, enabled, now)
        enabled, priority = _sync_provider_source_from_pipelines(db, provider_id, now)
    db.commit()
    updated = _provider_source(db, provider_id)
    if not updated:
        raise ValueError("元数据插件配置不存在")
    return _provider_public_view(updated, plugin)


def test_metadata_provider(
    db: Session, provider_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    plugin = metadata_provider_registry().require(provider_id)
    source = _provider_source(db, provider_id)
    if not source:
        raise ValueError("元数据插件配置不存在")
    config = _source_config(source, plugin.manifest)
    validation = _validate_config(plugin.manifest, config, True)
    if validation:
        result = {"ok": False, "message": "；".join(validation)}
    else:
        try:
            result = plugin.test(config)
        except Exception as exc:
            result = {"ok": False, "message": str(exc)}
    now = _now()
    update_source_test_result(
        db,
        str(source["id"]),
        status="ok" if result.get("ok") else "failed",
        error=None
        if result.get("ok")
        else str(result.get("message") or "连接测试失败"),
        now=now,
    )
    db.commit()
    provider = get_metadata_provider(db, provider_id)
    return result, provider or {}


def provider_supports_media_kind(
    manifest: ProviderManifest, media_kind: str | None
) -> bool:
    value = str(media_kind or "").strip().upper()
    return value in manifest.media_kinds


def enabled_metadata_provider_ids(
    db: Session, media_kind: str | None = None
) -> list[str]:
    from sqlalchemy import inspect

    if not inspect(db.connection()).has_table("MetadataProviderPipeline"):
        providers = list_metadata_providers(db)
        registry = metadata_provider_registry()
        return [
            str(provider["id"])
            for provider in providers
            if provider.get("enabled")
            and (
                media_kind is None
                or provider_supports_media_kind(
                    registry.require(str(provider["id"])).manifest, media_kind
                )
            )
        ]
    ensure_metadata_provider_pipelines(db)
    if media_kind is None:
        return list_enabled_provider_ids(db)
    return list_enabled_provider_ids(db, str(media_kind).strip().upper())


def metadata_provider_runtime_config(
    db: Session, provider_id: str, media_kind: str | None = None
) -> dict[str, Any] | None:
    """Return the canonical configuration only when the provider is enabled."""

    plugin = metadata_provider_registry().require(provider_id)
    source = _provider_source(db, provider_id)
    if not source:
        return None
    enabled = (
        provider_id in enabled_metadata_provider_ids(db, media_kind)
        if media_kind
        else bool(source.get("enabled"))
    )
    return _source_config(source, plugin.manifest) if enabled else None


def search_with_metadata_provider(
    db: Session,
    context: dict[str, Any],
    provider_id: str,
    query: str | None = None,
    *,
    force: bool = False,
    use_cache: bool = True,
    automatic_request_gate: AutomaticMetadataRequestGate | None = None,
) -> dict[str, Any]:
    from sqlalchemy import inspect

    plugin = metadata_provider_registry().require(provider_id)
    if not inspect(db.connection()).has_table("Source"):
        config = _default_config(plugin.manifest)
        if isinstance(plugin, BuiltinMetadataProvider):
            return plugin.search(
                db,
                context,
                query,
                config=config,
                force=force,
                use_cache=use_cache,
                automatic_request_gate=automatic_request_gate,
            )
        return plugin.search(
            db, context, query, config=config, force=force, use_cache=use_cache
        )
    media_version = (
        context.get("mediaVersion")
        if isinstance(context.get("mediaVersion"), dict)
        else {}
    )
    media_kind = media_version.get("mediaKind")
    config = metadata_provider_runtime_config(
        db, provider_id, str(media_kind) if media_kind else None
    )
    if config is None:
        return {
            "provider": provider_id,
            "enabled": False,
            "added": 0,
            "cacheHit": False,
            "message": f"{plugin.manifest.name}未在当前读物类型中启用",
            "candidates": [],
            "suggestions": [],
        }
    if isinstance(plugin, BuiltinMetadataProvider):
        return plugin.search(
            db,
            context,
            query,
            config=config,
            force=force,
            use_cache=use_cache,
            automatic_request_gate=automatic_request_gate,
        )
    return plugin.search(
        db, context, query, config=config, force=force, use_cache=use_cache
    )


def reset_metadata_provider_registry_for_tests() -> None:
    global _REGISTRY
    _REGISTRY = None
