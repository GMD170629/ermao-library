"""Identity event reporting used by the managed import application flow."""

from __future__ import annotations

from pathlib import Path

from app.modules.imports.application.dto import (
    BookIdentityDTO,
    ImportSystemEvent,
)
from app.modules.imports.application.ports import ImportOrchestrationServices


def _record_identity_system_events(
    services: ImportOrchestrationServices,
    task_id: str,
    identity: BookIdentityDTO,
    source_path: Path,
) -> None:
    metadata = {
        "sourcePath": str(source_path),
        "logicalPath": identity.logical_path,
        "recognitionMethod": identity.source,
        "title": identity.title,
        "author": identity.author,
        "volumeIndex": identity.volume_index,
        "confidence": identity.confidence,
        "fallbackReason": identity.fallback_reason,
        "fallbackCode": identity.fallback_code,
        "cacheHit": identity.cache_hit,
    }
    if identity.cache_hit:
        services.stage_system_event(
            ImportSystemEvent(
                source="import",
                action="identity.cache.hit",
                target_type="importTask",
                target_id=task_id,
                message=f"应用路径识别缓存：{source_path.name} → 《{identity.title}》 / {identity.author}",
                metadata=metadata,
            )
        )
        return
    if identity.fallback_reason:
        ai_failed = identity.fallback_code in {
            "AI_BILLING_REQUIRED",
            "AI_REQUEST_FAILED",
        } or identity.fallback_reason.startswith("AI identity recognition failed:")
        services.stage_system_event(
            ImportSystemEvent(
                source="import",
                action="identity.ai.failed" if ai_failed else "identity.ai.unavailable",
                level="warning",
                target_type="importTask",
                target_id=task_id,
                message=(
                    f"正则结果不完整，AI 兜底识别失败，已保留正则结果：{source_path.name}"
                    if ai_failed
                    else f"正则结果不完整，AI 识别配置不可用，已保留正则结果：{source_path.name}"
                ),
                metadata=metadata,
            )
        )
    method_label = {
        "ai": "AI",
        "regex": "正则匹配",
        "requested": "用户输入",
        "epub_opf": "EPUB 元数据",
        "pdf_metadata": "PDF 元数据",
        "comic_info": "ComicInfo 元数据",
    }.get(identity.source, "多来源裁决")
    services.stage_system_event(
        ImportSystemEvent(
            source="import",
            action=f"identity.{identity.source}.completed",
            target_type="importTask",
            target_id=task_id,
            message=f"{method_label}识别文件信息：{source_path.name} → 《{identity.title}》 / {identity.author}",
            metadata=metadata,
        )
    )
