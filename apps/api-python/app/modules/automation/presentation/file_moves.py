"""MCP schemas for bounded move inputs and immutable task references."""

from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from app.modules.automation.application.runtime import (
    AutomationRequest,
    AutomationRuntime,
    DeletionInvocation,
    FileInvocation,
    OperationInvocation,
)
from app.modules.automation.domain.access import Scope
from app.modules.library.public import MoveRequest, render_move_template

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
        return await run_in_threadpool(runtime.deletions, snapshot.access, operation)

    @server.tool(
        annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False)
    )
    async def plan_file_deletions(
        source_node_ids: Annotated[
            list[Identifier], Field(min_length=1, max_length=100)
        ],
    ) -> dict[str, object]:
        """预览永久删除目标；目录包含执行时的全部内容 / Preview permanent deletion targets; directories include all contents present at execution."""
        return await delete_invoke(
            lambda service, access: service.plan(access, tuple(source_node_ids))
        )

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False, destructive_hint=True, idempotent_hint=True
        )
    )
    async def execute_file_deletions(plan_id: Identifier) -> dict[str, object]:
        """使用系统能力永久删除所选文件或完整目录；已完成任务不会重复删除 / Permanently delete selected files or entire directories using system operations; completed tasks are not repeated."""
        return await delete_invoke(
            lambda service, access: service.execute(access, plan_id)
        )

    async def invoke(operation: FileInvocation) -> dict[str, object]:
        return await run_in_threadpool(runtime.files, snapshot.access, operation)

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
            """提交已有方案，由系统移动文件并更新原图书位置；重试复用 request_id / Enqueue an existing plan to move files using system operations and update existing book locations; reuse request_id on retry."""
            return await invoke(
                lambda commands, access: commands.execute(access, plan_id, request_id)
            )

    async def invoke_operation(operation: OperationInvocation) -> dict[str, object]:
        return await run_in_threadpool(runtime.operations, snapshot.access, operation)

    @server.tool(annotations=read)
    async def get_operation(operation_id: Identifier) -> dict[str, object]:
        """查询本人授权范围内文件任务的真实阶段与逐项结果 / Read the actual stages and per-target results of an owned file operation."""
        return await invoke_operation(
            lambda commands, access: commands.progress(access, operation_id)
        )

    @server.tool(annotations=write)
    async def cancel_operation(operation_id: Identifier) -> dict[str, object]:
        """取消尚未开始的文件项目；已执行的文件操作不会撤回 / Cancel unstarted file targets; file operations already performed are not undone."""
        return await invoke_operation(
            lambda commands, access: commands.cancel(access, operation_id)
        )
