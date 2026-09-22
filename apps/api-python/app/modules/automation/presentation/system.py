"""Typed system tools; no arbitrary setting keys or transport forwarding."""

from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field, StrictBool
from starlette.concurrency import run_in_threadpool

from app.contracts.http import HttpContractModel
from app.modules.automation.application.runtime import (
    AutomationRequest,
    AutomationRuntime,
    SystemInvocation,
)
from app.modules.automation.application.system import ConfigurationGroup
from app.modules.automation.domain.access import Scope


class SiteSettings(HttpContractModel):
    language: Literal["zh-CN", "en-US"]


class SmtpSettings(HttpContractModel):
    host: str | None = Field(default=None, max_length=253)
    port: int | None = Field(default=None, ge=1, le=65535)
    security: Literal["starttls", "ssl", "none"] | None = None
    username: str | None = Field(default=None, max_length=512)
    password: str | None = Field(default=None, max_length=4096, repr=False)
    fromEmail: str | None = Field(default=None, max_length=320)
    fromName: str | None = Field(default=None, max_length=191)
    maxAttachmentMb: float | None = Field(default=None, ge=1, le=50)


class KindleSettings(HttpContractModel):
    email: str = Field(max_length=320)


class EmailSettings(HttpContractModel):
    kindle: KindleSettings | None = None
    smtp: SmtpSettings | None = None
    clearSmtpPassword: StrictBool = False


class OpdsSettings(HttpContractModel):
    enabled: StrictBool
    publicBaseUrl: str = Field(max_length=2048)


class LibrarySettings(HttpContractModel):
    name: str | None = Field(default=None, min_length=1, max_length=191)
    description: str | None = Field(default=None, max_length=191)
    rootPath: str | None = Field(default=None, max_length=2048)
    organizationMode: Literal["FLAT", "VOLUMES"] | None = None
    enabled: StrictBool | None = None
    ignorePatterns: str | None = Field(default=None, max_length=20000)
    ignoreHidden: StrictBool | None = None
    minFileSizeBytes: int | None = Field(default=None, ge=0)
    allowEmptyLibraryCleanup: StrictBool | None = None


class OrganizeRules(HttpContractModel):
    unrecognized: StrictBool = True
    missingMetadata: StrictBool = True


class OrganizeSettings(HttpContractModel):
    enabled: StrictBool | None = None
    scheduleMode: Literal["MANUAL", "INTERVAL"] | None = None
    intervalMinutes: int | None = Field(default=None, ge=15, le=10080)
    autoRunOnNew: StrictBool | None = None
    rules: OrganizeRules | None = None
    writeMetadataToFiles: StrictBool | None = None
    preferLocalMetadata: StrictBool | None = None
    localMetadataPriority: list[Literal["SIDECAR_OPF", "EMBEDDED", "PATH"]] | None = (
        Field(default=None, min_length=3, max_length=3)
    )


def register_system(
    server: MCPServer, runtime: AutomationRuntime, snapshot: AutomationRequest
) -> None:
    if not snapshot.access.can_manage_system:
        return
    read = ToolAnnotations(
        read_only_hint=True, destructive_hint=False, idempotent_hint=True
    )
    write = ToolAnnotations(
        read_only_hint=False, destructive_hint=True, idempotent_hint=True
    )

    async def invoke(operation: SystemInvocation) -> dict[str, object]:
        try:
            return await run_in_threadpool(runtime.system, snapshot.access, operation)
        except ValueError:
            raise ToolError(
                "SYSTEM_REQUEST_REJECTED: 系统请求被拒绝 / System request rejected"
            ) from None
        except Exception:  # noqa: BLE001 - redact credentials and filesystem diagnostics
            raise ToolError("INTERNAL_ERROR: 操作失败 / Operation failed") from None

    @server.tool(annotations=read)
    async def list_import_queue(
        page: int = 1, page_size: int = 20
    ) -> dict[str, object]:
        """查询授权书库导入队列 / List import tasks in granted libraries."""
        return await invoke(
            lambda service, access: service.import_queue(access, page, page_size)
        )

    @server.tool(annotations=read)
    async def get_system_queue_status() -> dict[str, object]:
        """查看系统队列状态 / Read system queue status."""
        return await invoke(lambda service, access: service.queue_status(access))

    @server.tool(annotations=read)
    async def list_system_logs(page: int = 1, page_size: int = 20) -> dict[str, object]:
        """分页查询脱敏系统事件 / List redacted system events."""
        return await invoke(
            lambda service, access: service.logs(access, page, page_size)
        )

    @server.tool(annotations=read)
    async def get_system_configuration(
        group: ConfigurationGroup, library_id: str | None = None
    ) -> dict[str, object]:
        """查看脱敏配置；全局配置限系统管理者 / Read redacted configuration, restricted to system managers."""
        return await invoke(
            lambda service, access: service.configuration(access, group, library_id)
        )

    if Scope.SYSTEM_MANAGE not in snapshot.access.permissions.scopes:
        return

    @server.tool(annotations=write)
    async def update_site_settings(settings: SiteSettings) -> dict[str, object]:
        """修改站点设置 / Update site settings."""
        return await invoke(
            lambda service, access: service.configure(
                access, "site", None, settings.model_dump(exclude_unset=True)
            )
        )

    @server.tool(annotations=write)
    async def update_email_settings(settings: EmailSettings) -> dict[str, object]:
        """修改邮件配置，不返回密码 / Update email settings without returning secrets."""
        return await invoke(
            lambda service, access: service.configure(
                access, "email", None, settings.model_dump(exclude_unset=True)
            )
        )

    @server.tool(annotations=write)
    async def update_opds_settings(settings: OpdsSettings) -> dict[str, object]:
        """修改 OPDS 配置 / Update OPDS settings."""
        return await invoke(
            lambda service, access: service.configure(
                access, "opds", None, settings.model_dump(exclude_unset=True)
            )
        )

    @server.tool(annotations=write)
    async def update_library_settings(
        library_id: str, settings: LibrarySettings
    ) -> dict[str, object]:
        """修改授权书库配置；根路径修改不会移动文件 / Update granted library settings; root changes do not move files."""
        return await invoke(
            lambda service, access: service.configure(
                access, "library", library_id, settings.model_dump(exclude_unset=True)
            )
        )

    @server.tool(annotations=write)
    async def update_organize_settings(settings: OrganizeSettings) -> dict[str, object]:
        """修改智能整理识别策略 / Update automatic organization policy."""
        return await invoke(
            lambda service, access: service.configure(
                access, "organize", None, settings.model_dump(exclude_unset=True)
            )
        )
