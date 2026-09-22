"""Pure MCP chunk transport; attachment bytes must be supplied by the client."""

from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from starlette.concurrency import run_in_threadpool

from app.contracts.automation_upload import UploadError, UploadSpec
from app.modules.automation.application.runtime import (
    AutomationRequest,
    AutomationRuntime,
    UploadInvocation,
)
from app.modules.automation.application.uploads import BOOK_BYTES, CHUNK_BYTES
from app.modules.automation.domain.access import AutomationAccessError, Scope

Identifier = Annotated[str, Field(min_length=1, max_length=191)]
UploadId = Annotated[str, Field(pattern=r"^[a-f0-9]{32}$")]


def register_uploads(
    server: MCPServer, runtime: AutomationRuntime, snapshot: AutomationRequest
) -> None:
    if (
        not {Scope.FILES_UPLOAD, Scope.BOOKS_WRITE, Scope.FILES_MODIFY}
        & snapshot.access.permissions.scopes
    ):
        return

    async def invoke(operation: UploadInvocation) -> dict[str, object]:
        try:
            return await run_in_threadpool(runtime.uploads, snapshot.access, operation)
        except (UploadError, AutomationAccessError) as error:
            raise ToolError(f"{error}: 请求被拒绝 / Request rejected") from None
        except ValueError:
            raise ToolError("INVALID_ARGUMENT: 参数无效 / Invalid argument") from None
        except Exception:  # noqa: BLE001 - no filesystem paths, data or credentials in tool errors.
            raise ToolError(
                "INTERNAL_ERROR: 上传操作失败 / Upload operation failed"
            ) from None

    write = ToolAnnotations(
        read_only_hint=False,
        destructive_hint=True,
        idempotent_hint=True,
        open_world_hint=False,
    )

    @server.tool(annotations=write)
    async def begin_upload(
        purpose: Literal["book", "cover", "replace"],
        filename: Annotated[str, Field(min_length=1, max_length=255)],
        size_bytes: Annotated[int, Field(strict=True, gt=0, le=BOOK_BYTES)],
        sha256: Annotated[str, Field(pattern=r"^[a-fA-F0-9]{64}$")],
        request_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9_.:-]{1,128}$")],
        library_id: Identifier | None = None,
        directory_node_id: Identifier | None = None,
        book_id: Identifier | None = None,
        expected_revision: Identifier | None = None,
        override: bool = False,
        source_node_id: Identifier | None = None,
        expected_source_version: Identifier | None = None,
    ) -> dict[str, object]:
        """开始上传真实附件：book 指定书库，cover 指定图书及修订。客户端必须读取原始字节，不接受路径/URL，不由模型重建文件 / Begin a real attachment upload: book requires a library; cover requires a book and revision. Client must provide original bytes, never paths, URLs or model-reconstructed data."""
        spec = UploadSpec(
            purpose,
            filename,
            size_bytes,
            sha256,
            library_id,
            directory_node_id,
            book_id,
            expected_revision,
            override,
            source_node_id,
            expected_source_version,
        )
        return await invoke(
            lambda commands, access: commands.begin_upload(access, spec, request_id)
        )

    @server.tool(annotations=write)
    async def upload_chunk(
        upload_id: UploadId,
        offset: Annotated[int, Field(strict=True, ge=0)],
        data_base64: Annotated[
            str, Field(min_length=1, max_length=(CHUNK_BYTES + 2) // 3 * 4)
        ],
    ) -> dict[str, object]:
        """按返回的偏移发送最多 256 KiB 原始字节的 Base64 分块；相同块可重试 / Send up to 256 KiB of original bytes as Base64 at the acknowledged offset; identical retries are safe."""
        return await invoke(
            lambda commands, access: commands.chunk(
                access, upload_id, offset, data_base64
            )
        )

    @server.tool(
        annotations=ToolAnnotations(
            read_only_hint=False,
            destructive_hint=True,
            idempotent_hint=True,
            open_world_hint=False,
        )
    )
    async def complete_upload(upload_id: UploadId) -> dict[str, object]:
        """校验并提交附件：同名图书拒绝覆盖，封面检查权限和修订；通过 get_operation 查询真实结果 / Verify and submit an attachment: books never overwrite existing names; covers check authority and revision. Query get_operation for actual results."""
        return await invoke(
            lambda commands, access: commands.complete(access, upload_id)
        )
