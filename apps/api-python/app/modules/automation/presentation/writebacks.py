"""Bounded MCP inputs for frozen, selective standard-metadata writeback."""

from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.modules.automation.application.runtime import (
    AutomationRequest,
    AutomationRuntime,
    WritebackInvocation,
)
from app.modules.automation.application.writeback_plans import StandardWriteSelection
from app.modules.automation.domain.access import AutomationAccessError, Scope
from app.modules.library.public import FileMoveError, MetadataPatchError
from app.modules.metadata.public import StandardMetadataError

Identifier = Annotated[str, Field(min_length=1, max_length=191)]
FieldName = Annotated[str, Field(min_length=1, max_length=100)]


class StandardWriteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_type: Literal["book", "resource", "source_node"]
    target_id: Identifier
    expected_revision: Identifier
    node_id: Identifier
    mode: Literal["opf", "comicinfo", "embedded"]
    fields: Annotated[list[FieldName], Field(min_length=1, max_length=20)]
    clear_fields: Annotated[list[FieldName], Field(max_length=20)] = Field(
        default_factory=list
    )

    def command(self) -> StandardWriteSelection:
        return StandardWriteSelection(
            self.target_type,
            self.target_id,
            self.expected_revision,
            self.node_id,
            self.mode,
            frozenset(self.fields),
            frozenset(self.clear_fields),
        )


def register_writebacks(
    server: MCPServer, runtime: AutomationRuntime, snapshot: AutomationRequest
) -> None:
    async def invoke(operation: WritebackInvocation) -> dict[str, object]:
        try:
            return await run_in_threadpool(
                runtime.writebacks, snapshot.access, operation
            )
        except (
            AutomationAccessError,
            StandardMetadataError,
            MetadataPatchError,
            FileMoveError,
        ) as error:
            raise ToolError(f"{error}: 请求被拒绝 / Request rejected") from None
        except ValueError:
            raise ToolError("INVALID_ARGUMENT: 参数无效 / Invalid argument") from None
        except Exception:  # noqa: BLE001 - transport boundary redacts paths and diagnostics.
            raise ToolError("INTERNAL_ERROR: 操作失败 / Operation failed") from None

    if {
        Scope.SYSTEM_READ,
        Scope.FILES_MODIFY,
    } <= snapshot.access.permissions.scopes:

        @server.tool(
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            )
        )
        async def plan_metadata_writeback(
            targets: Annotated[
                list[StandardWriteInput], Field(min_length=1, max_length=20)
            ],
        ) -> dict[str, object]:
            """预览系统已确认字段写入指定文件；清空字段须显式选择，不修改文件 / Preview confirmed system fields written to explicit files; select clears explicitly, without changing files."""
            return await invoke(
                lambda commands, access: commands.plan(
                    access, tuple(target.command() for target in targets)
                )
            )

    if Scope.FILES_MODIFY in snapshot.access.permissions.scopes:

        @server.tool(
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=True,
                idempotent_hint=True,
                open_world_hint=False,
            )
        )
        async def execute_metadata_writeback(
            plan_id: Identifier,
            request_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")],
        ) -> dict[str, object]:
            """提交已保存的文件元数据方案；重试复用 request_id，执行前复核权限及文件版本 / Enqueue a saved file-metadata plan; reuse request_id on retry; recheck authority and file versions before publication."""
            return await invoke(
                lambda commands, access: commands.execute(access, plan_id, request_id)
            )
