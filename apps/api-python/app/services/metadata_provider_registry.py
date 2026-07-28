from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime, timezone
from importlib import metadata as importlib_metadata
from typing import Any, Protocol
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from sqlalchemy.orm import Session

from app.modules.metadata.infrastructure.providers import (
    clear_work_type_pipelines,
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
from app.bootstrap.metadata import ensure_metadata_sources
from app.bootstrap.system import list_settings, upsert_setting
from app.modules.metadata.public import BUILTIN_MANIFESTS, ProviderManifest

LOGGER = logging.getLogger(__name__)
ENTRY_POINT_GROUP = "shuku_starship.metadata_providers"
METADATA_WORK_TYPES = ("ebook", "comic", "audiobook")


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


def _bool(value: Any, fallback: bool = False) -> bool:
    parsed = _json_value(value, value)
    if isinstance(parsed, bool):
        return parsed
    if isinstance(parsed, (int, float)):
        return parsed != 0
    if isinstance(parsed, str):
        return parsed.strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return fallback


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
    ) -> dict[str, Any]:
        from app.services.organize_service import metadata_search_candidates

        return metadata_search_candidates(
            db,
            context,
            self.manifest.id,
            query,
            force=force,
            use_cache=use_cache,
        )

    def test(self, config: dict[str, Any]) -> dict[str, Any]:
        provider_id = self.manifest.id
        if provider_id == "douban":
            request = UrlRequest(
                "https://book.douban.com/",
                headers={
                    "Accept": "text/html,*/*",
                    "User-Agent": str(config.get("userAgent") or _default_config(self.manifest).get("userAgent") or "ShukuStarship/0.1"),
                },
            )
        elif provider_id == "bangumi":
            base_url = str(config.get("baseUrl") or "https://api.bgm.tv").rstrip("/")
            headers = {
                "Accept": "application/json",
                "User-Agent": str(config.get("userAgent") or _default_config(self.manifest).get("userAgent") or "ShukuStarship/0.1"),
            }
            if str(config.get("accessToken") or "").strip():
                headers["Authorization"] = f"Bearer {str(config['accessToken']).strip()}"
            request = UrlRequest(f"{base_url}/v0/subjects/1", headers=headers)
        else:
            base_url = str(config.get("baseUrl") or "").rstrip("/")
            api_key = str(config.get("apiKey") or "").strip()
            if not base_url or not api_key:
                return {"ok": False, "message": "请先填写 API 地址和 API Key"}
            request = UrlRequest(
                f"{base_url}/models",
                headers={"Accept": "application/json", "Authorization": f"Bearer {api_key}"},
            )
        with urlopen(request, timeout=10) as response:
            status = int(getattr(response, "status", 200) or 200)
        return {"ok": 200 <= status < 400, "message": "连接正常" if status < 400 else f"服务返回 HTTP {status}"}


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
            selected = entry_points.select(group=ENTRY_POINT_GROUP) if hasattr(entry_points, "select") else entry_points.get(ENTRY_POINT_GROUP, [])
        except Exception:
            LOGGER.exception("failed to discover metadata provider entry points")
            return
        for entry_point in selected:
            try:
                loaded = entry_point.load()
                plugin = loaded() if isinstance(loaded, type) else loaded
                self.register(plugin)
            except Exception:
                LOGGER.exception("failed to load metadata provider entry point name=%s", getattr(entry_point, "name", "unknown"))

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
    return {field.key: field.default for field in manifest.config_fields if field.default is not None}


def _legacy_values(db: Session) -> dict[str, Any]:
    return {
        key: value
        for key, value in list_settings(db).items()
        if key.startswith("metadata.")
    }


def _legacy_provider_config(provider_id: str, values: dict[str, Any], manifest: ProviderManifest) -> dict[str, Any]:
    config = _default_config(manifest)
    for field in manifest.config_fields:
        key = f"metadata.{provider_id}.{field.key}"
        if values.get(key) not in (None, ""):
            config[field.key] = values[key]
    return config


def ensure_metadata_provider_sources(db: Session) -> list[dict[str, Any]]:
    registry = metadata_provider_registry()
    ensure_metadata_sources(db, (plugin.manifest for plugin in registry.all()))
    sources = list_metadata_sources(db)
    if sources:
        db.commit()
    return sources


def ensure_metadata_provider_pipelines(db: Session) -> None:
    from sqlalchemy import inspect

    bind = db.get_bind()
    if bind is None or not inspect(bind).has_table("MetadataProviderPipeline"):
        return
    sources = ensure_metadata_provider_sources(db)
    source_by_provider = {str(item.get("providerType")): item for item in sources}
    now = _now()
    for plugin in metadata_provider_registry().all():
        source = source_by_provider.get(plugin.manifest.id) or {}
        for work_type in plugin.manifest.work_types:
            ensure_pipeline_row(
                db,
                work_type=work_type,
                provider_id=plugin.manifest.id,
                enabled=bool(source.get("enabled")),
                position=int(source.get("priority") or plugin.manifest.default_priority),
                now=now,
            )
    db.commit()


def list_metadata_provider_pipelines(db: Session) -> list[dict[str, Any]]:
    ensure_metadata_provider_pipelines(db)
    providers = {str(item["id"]): item for item in list_metadata_providers(db)}
    rows = list_included_pipelines(db)
    by_type: dict[str, list[dict[str, Any]]] = {work_type: [] for work_type in METADATA_WORK_TYPES}
    for row in rows:
        provider = providers.get(str(row.get("providerId")))
        work_type = str(row.get("workType") or "")
        if not provider or work_type not in by_type:
            continue
        by_type[work_type].append(
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
    return [{"workType": work_type, "providers": by_type[work_type]} for work_type in METADATA_WORK_TYPES]


def _sync_provider_source_from_pipelines(db: Session, provider_id: str, now: datetime) -> tuple[bool, int]:
    rows = list_pipelines_for_provider(db, provider_id)
    enabled = any(bool(item.get("enabled")) for item in rows)
    enabled_positions = [int(item.get("position") or 9999) for item in rows if item.get("enabled")]
    priority = min(enabled_positions) if enabled_positions else min([int(item.get("position") or 9999) for item in rows] or [9999])
    update_source_enabled_priority(db, provider_id, enabled=enabled, priority=priority, now=now)
    return enabled, priority


def update_metadata_provider_pipeline(db: Session, work_type: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized = str(work_type or "").strip().lower()
    if normalized not in METADATA_WORK_TYPES:
        raise ValueError("不支持的读物类型")
    if not isinstance(items, list):
        raise ValueError("数据源顺序格式不正确")
    ensure_metadata_provider_pipelines(db)
    registry = metadata_provider_registry()
    provider_ids = [str(item.get("providerId") or "").strip() for item in items if isinstance(item, dict)]
    if len(provider_ids) != len(items) or not all(provider_ids) or len(set(provider_ids)) != len(provider_ids):
        raise ValueError("数据源列表包含无效或重复项目")
    for item, provider_id in zip(items, provider_ids):
        plugin = registry.get(provider_id)
        if not plugin or normalized not in plugin.manifest.work_types:
            raise ValueError(f"数据源 {provider_id} 不支持{normalized}")
        if bool(item.get("enabled")):
            source = _provider_source(db, provider_id)
            errors = _validate_config(plugin.manifest, _source_config(source, plugin.manifest), True)
            if errors:
                raise ValueError(f"{plugin.manifest.name}：{'；'.join(errors)}")
    now = _now()
    clear_work_type_pipelines(db, normalized, now)
    for index, (item, provider_id) in enumerate(zip(items, provider_ids), start=1):
        update_pipeline_row(
            db,
            work_type=normalized,
            provider_id=provider_id,
            included=True,
            enabled=bool(item.get("enabled")),
            position=index * 100,
            now=now,
        )
    for provider_id in {str(plugin.manifest.id) for plugin in registry.all()}:
        enabled, _priority = _sync_provider_source_from_pipelines(db, provider_id, now)
        source = _provider_source(db, provider_id)
        if source:
            _sync_legacy_provider_settings(db, provider_id, enabled, _source_config(source, registry.require(provider_id).manifest), now)
    db.commit()
    return list_metadata_provider_pipelines(db)


def _provider_source(db: Session, provider_id: str) -> dict[str, Any] | None:
    ensure_metadata_provider_sources(db)
    return get_provider_source(db, provider_id)


def _source_config(source: dict[str, Any] | None, manifest: ProviderManifest) -> dict[str, Any]:
    value = _json_value((source or {}).get("config"), {})
    return {**_default_config(manifest), **(value if isinstance(value, dict) else {})}


def _secret_fields(manifest: ProviderManifest) -> set[str]:
    return {field.key for field in manifest.config_fields if field.secret}


def _provider_public_view(source: dict[str, Any], plugin: MetadataProviderPlugin) -> dict[str, Any]:
    manifest = plugin.manifest
    config = _source_config(source, manifest)
    secrets = _secret_fields(manifest)
    public_config = {key: value for key, value in config.items() if key not in secrets}
    configured_secrets = {key: bool(str(config.get(key) or "").strip()) for key in secrets}
    return {
        "id": manifest.id,
        "sourceId": source.get("id"),
        "name": manifest.name,
        "version": manifest.version,
        "description": manifest.description,
        "mode": manifest.mode,
        "workTypes": list(manifest.work_types),
        "fields": list(manifest.fields),
        "capabilities": list(manifest.capabilities),
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


def _validate_config(manifest: ProviderManifest, config: dict[str, Any], enabled: bool) -> list[str]:
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


def _upsert_legacy_setting(db: Session, key: str, value: Any, _now: datetime) -> None:
    upsert_setting(db, key, value)


def _sync_legacy_provider_settings(db: Session, provider_id: str, enabled: bool, config: dict[str, Any], now: datetime) -> None:
    _upsert_legacy_setting(db, f"metadata.{provider_id}.enabled", enabled, now)
    for key, value in config.items():
        _upsert_legacy_setting(db, f"metadata.{provider_id}.{key}", value, now)
    if provider_id in {"douban", "bangumi"}:
        sources = ensure_metadata_provider_sources(db)
        external_enabled = any(bool(item.get("enabled")) and str(item.get("providerType")) in {"douban", "bangumi"} for item in sources)
        _upsert_legacy_setting(db, "metadata.external.enabled", external_enabled, now)


def update_metadata_provider(db: Session, provider_id: str, payload: dict[str, Any]) -> dict[str, Any]:
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
        priority = int(payload.get("priority", source.get("priority") or plugin.manifest.default_priority))
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
    _sync_legacy_provider_settings(db, provider_id, enabled, next_config, now)
    db.commit()
    updated = _provider_source(db, provider_id)
    if not updated:
        raise ValueError("元数据插件配置不存在")
    return _provider_public_view(updated, plugin)


def test_metadata_provider(db: Session, provider_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
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
        error=None if result.get("ok") else str(result.get("message") or "连接测试失败"),
        now=now,
    )
    db.commit()
    provider = get_metadata_provider(db, provider_id)
    return result, provider or {}


def provider_supports_work_type(manifest: ProviderManifest, work_type: str | None) -> bool:
    value = str(work_type or "").strip().lower()
    normalized = "comic" if value in {"comic", "cbz", "zip"} else "audiobook" if value in {"audiobook", "audio", "m4b", "m4a", "mp3"} else "ebook"
    return normalized in manifest.work_types


def enabled_metadata_provider_ids(db: Session, work_type: str | None = None) -> list[str]:
    from sqlalchemy import inspect

    bind = db.get_bind()
    if bind is None or not inspect(bind).has_table("MetadataProviderPipeline"):
        providers = list_metadata_providers(db)
        registry = metadata_provider_registry()
        return [
            str(provider["id"])
            for provider in providers
            if provider.get("enabled")
            and (
                work_type is None
                or provider_supports_work_type(registry.require(str(provider["id"])).manifest, work_type)
            )
        ]
    ensure_metadata_provider_pipelines(db)
    if work_type is None:
        return list_enabled_provider_ids(db)
    value = str(work_type or "").strip().lower()
    normalized = (
        "comic"
        if value in {"comic", "cbz", "zip"}
        else "audiobook"
        if value in {"audiobook", "audio", "m4b", "m4a", "mp3"}
        else "ebook"
    )
    return list_enabled_provider_ids(db, normalized)


def search_with_metadata_provider(
    db: Session,
    context: dict[str, Any],
    provider_id: str,
    query: str | None = None,
    *,
    force: bool = False,
    use_cache: bool = True,
) -> dict[str, Any]:
    from sqlalchemy import inspect

    plugin = metadata_provider_registry().require(provider_id)
    bind = db.get_bind()
    if bind is None or not inspect(bind).has_table("Source"):
        return plugin.search(
            db,
            context,
            query,
            config=_default_config(plugin.manifest),
            force=force,
            use_cache=use_cache,
        )
    source = _provider_source(db, provider_id)
    work = context.get("work") if isinstance(context.get("work"), dict) else {}
    work_type = work.get("workType") if isinstance(work, dict) else None
    provider_enabled = (
        provider_id in enabled_metadata_provider_ids(db, str(work_type))
        if work_type
        else bool(source and source.get("enabled"))
    )
    if not source or not provider_enabled:
        # Legacy SystemSetting toggles still enable search when Source seed is disabled.
        legacy = _legacy_values(db)
        legacy_enabled = _bool(legacy.get(f"metadata.{provider_id}.enabled"), False)
        if legacy_enabled or (
            _bool(legacy.get("metadata.external.enabled"), False) and provider_id in {"douban", "bangumi"}
        ):
            config = _legacy_provider_config(provider_id, legacy, plugin.manifest)
            return plugin.search(db, context, query, config=config, force=force, use_cache=use_cache)
        return {
            "provider": provider_id,
            "enabled": False,
            "added": 0,
            "cacheHit": False,
            "message": f"{plugin.manifest.name}未在当前读物类型中启用",
            "candidates": [],
            "suggestions": [],
        }
    return plugin.search(db, context, query, config=_source_config(source, plugin.manifest), force=force, use_cache=use_cache)


def reset_metadata_provider_registry_for_tests() -> None:
    global _REGISTRY
    _REGISTRY = None
