"""MCP schemas for bounded move inputs and immutable task references."""

from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from app.contracts.automation_upload import UploadError
from app.modules.automation.application.runtime import (
    AutomationRequest,
    AutomationRuntime,
    DeletionInvocation,
    FileInvocation,
    OperationInvocation,
)
from app.modules.automation.domain.access import AutomationAccessError, Scope
from app.modules.library.public import FileMoveError, MoveRequest, render_move_template
from app.modules.metadata.public import StandardMetadataError

Identifier = Annotated[str, Field(min_length=1, max_length=191)]
RelativePath = Annotated[str, Field(min_length=1, max_length=4096)]
TemplateField = Literal["author", "title", "resource_title", "index", "ext"]


class FileMoveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_node_id: Identifier
    destination_library_id: Identifier
    destination_relative_path: RelativePath | None = None
    template: Annotated[str, Field(min_length=1, max_length=1000)] | None = None
    template_values: dict[TemplateField, Annotated[str, Field(max_length=500)]] = Field(
        default_factory=dict
    )

    @model_validator(mode="after")
    def one_destination(self) -> "FileMoveInput":
        if (self.destination_relative_path is None) == (self.template is None):
            raise ValueError("Specify either destination_relative_path or template")
        if self.template is None and self.template_values:
            raise ValueError("Template values require a template")
        return self

    def command(self) -> MoveRequest:
        destination = self.destination_relative_path
        if destination is None:
            destination = render_move_template(
                self.template or "",
                {str(key): value for key, value in self.template_values.items()},
            )
        return MoveRequest(
            self.source_node_id, self.destination_library_id, destination
        )


def register_file_moves(
    server: MCPServer, runtime: AutomationRuntime, snapshot: AutomationRequest
) -> None:
    read = ToolAnnotations(
        read_only_hint=True,
        destructive_hint=False,
        idempotent_hint=True,
        open_world_hint=False,
    )
    write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    )

    async def delete_invoke(operation: DeletionInvocation) -> dict[str, object]:
        try:
            return await run_in_threadpool(
                runtime.deletions, snapshot.access, operation
            )
        except (AutomationAccessError, FileMoveError) as error:
            raise ToolError(f"{error}: 请求被拒绝 / Request rejected") from None
        except Exception:  # noqa: BLE001 - redact filesystem diagnostics
            raise ToolError("INTERNAL_ERROR: 操作失败 / Operation failed") from None

    @server.tool(
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False)
    )
    async def plan_file_deletions(
        source_node_ids: Annotated[
            list[Identifier], Field(min_length=1, max_length=100)
        ],
    ) -> dict[str, object]:
        """冻结永久删除清单，包含所选目录中的文件 / Freeze a permanent deletion inventory, including files inside selected directories."""
        return await delete_invoke(
            lambda service, access: service.plan(access, tuple(source_node_ids))
        )

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        )
    )
    async def execute_file_deletions(plan_id: Identifier) -> dict[str, object]:
        """永久删除方案内文件；不会删除执行时新增的文件 / Permanently delete frozen targets; never delete newly added files."""
        return await delete_invoke(
            lambda service, access: service.execute(access, plan_id)
        )

    async def invoke(operation: FileInvocation) -> dict[str, object]:
        try:
            return await run_in_threadpool(runtime.files, snapshot.access, operation)
        except (AutomationAccessError, FileMoveError) as error:
            raise ToolError(f"{error}: 请求被拒绝 / Request rejected") from None
        except ValueError:
            raise ToolError("INVALID_ARGUMENT: 参数无效 / Invalid argument") from None
        except Exception:  # noqa: BLE001 - redact infrastructure diagnostics.
            raise ToolError("INTERNAL_ERROR: 操作失败 / Operation failed") from None

    if {Scope.SYSTEM_READ, Scope.FILES_MODIFY} <= snapshot.access.permissions.scopes:

        @server.tool(annotations=read)
        async def plan_file_operations(
            moves: Annotated[list[FileMoveInput], Field(min_length=1, max_length=100)],
        ) -> dict[str, object]:
            """预览并保存明确移动或固定模板整理方案，不改动书库文件；模板值由客户端明确提供 / Preview explicit moves or fixed templates without changing library files; supply template values explicitly."""
            return await invoke(
                lambda commands, access: commands.plan(
                    access, tuple(item.command() for item in moves)
                )
            )

    if Scope.FILES_MODIFY in snapshot.access.permissions.scopes:

        @server.tool(annotations=write)
        async def execute_file_operations(
            plan_id: Identifier,
            request_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")],
        ) -> dict[str, object]:
            """提交已有方案到后台执行；重试复用 request_id，不接受替换路径 / Enqueue a frozen plan; reuse request_id on retry, without replacing paths."""
            return await invoke(
                lambda commands, access: commands.execute(access, plan_id, request_id)
            )

    async def invoke_operation(operation: OperationInvocation) -> dict[str, object]:
        try:
            return await run_in_threadpool(
                runtime.operations, snapshot.access, operation
            )
        except (
            AutomationAccessError,
            FileMoveError,
            StandardMetadataError,
            UploadError,
        ) as error:
            raise ToolError(f"{error}: 请求被拒绝 / Request rejected") from None
        except Exception:  # noqa: BLE001 - redact infrastructure diagnostics.
            raise ToolError("INTERNAL_ERROR: 操作失败 / Operation failed") from None

    @server.tool(annotations=read)
    async def get_operation(operation_id: Identifier) -> dict[str, object]:
        """查询本人授权范围内文件任务的真实阶段与逐项结果 / Read the actual stages and per-target results of an owned file operation."""
        return await invoke_operation(
            lambda commands, access: commands.progress(access, operation_id)
        )

    @server.tool(annotations=write)
    async def cancel_operation(operation_id: Identifier) -> dict[str, object]:
        """取消尚未执行的文件项目；已发布项目完成必要的一致性修复 / Cancel unstarted file targets; published targets finish required consistency repair."""
        return await invoke_operation(
            lambda commands, access: commands.cancel(access, operation_id)
        )
