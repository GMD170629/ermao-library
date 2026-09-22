# 对话附件上传 / Conversation attachments

二毛图书通过 `begin_upload`、`upload_chunk`、`complete_upload` 接收原始附件。全部使用现有 `/api/mcp` 的 JSON `tools/call`，无需额外 HTTP 上传、命令行或本地脚本。工具参数遵循 [MCP 工具规范](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/tools.mdx)。

The three tools transfer original attachment bytes through MCP JSON calls. No separate upload endpoint, local script or command line is required.

## 客户端能力检查 / Client requirements

客户端必须能从用户附件读取**完整原始字节**、计算 SHA-256、按原始字节偏移切块并编码 Base64。不得由模型根据正文、缩略图或描述重新生成文件。只有私有附件链接、不能将附件内容传入工具的客户端暂不支持。服务端不会读取客户端路径，也不下载附件 URL。

The client must read the original bytes, compute SHA-256, and construct Base64 chunks. A model must never reconstruct a file from text or a thumbnail. Private attachment links alone are insufficient; the server accepts neither client paths nor download URLs. Connecting an MCP server does not by itself prove attachment compatibility.

## 授权与定位 / Authority and target selection

管理员开启新能力后，为客户端明确授权 `files:upload`（图书）或 `books:write`（展示封面）；旧授权不自动增加能力。覆盖受保护封面仍需当前修订版本，且本次请求显式 `override: true`。每次调用和最终提交都重检账户、授权、服务开关及书库范围。

先用 `list_libraries` 定位书库，选择已有子目录时使用 `list_source_nodes`（另需 `system:read`）。不指定目录即书库根目录；首版不创建目录。封面用 `search_books`／`get_books` 确定唯一图书，再用 `get_metadata_schema` 获取 `expected_revision`。

Grant `files:upload` or `books:write` explicitly. Legacy grants reset to basic queries during migration. Protected covers require an explicit override and the current revision. Use existing catalog tools to select a library, optional existing directory, or a specific book and its current revision.

## 纯 MCP 调用顺序 / Pure MCP sequence

以下为 `tools/call` 的 `params`。占位字段由客户端根据真实附件填入，不是可直接执行的虚构文件数据。

These are `tools/call` parameters. Substitute values derived from the actual attachment; placeholders are not file contents.

```json
{
  "name": "begin_upload",
  "arguments": {
    "purpose": "book",
    "library_id": "LIBRARY_ID",
    "directory_node_id": "EXISTING_DIRECTORY_NODE_ID",
    "filename": "图书.epub",
    "size_bytes": 123456,
    "sha256": "SHA256_OF_ORIGINAL_BYTES",
    "request_id": "stable-attachment-request-1"
  }
}
```

响应提供 `upload_id`、相同的 `operation_id`、`chunk_bytes`、`received_bytes` 和 `expires_at_ms`。保存这些值；省略可选 `directory_node_id` 可上传到根目录。按返回的确认偏移继续：

```json
{
  "name": "upload_chunk",
  "arguments": {
    "upload_id": "UPLOAD_ID",
    "offset": 0,
    "data_base64": "BASE64_OF_ORIGINAL_BYTE_CHUNK"
  }
}
```

```json
{"name":"complete_upload","arguments":{"upload_id":"UPLOAD_ID"}}
```

```json
{"name":"get_operation","arguments":{"operation_id":"UPLOAD_ID"}}
```

同一偏移、相同字节可重传；错误偏移或内容不同拒绝。网络中断或服务重启后用 `get_operation` 获取确认偏移，不推测已发送字节是否落盘。相同 `request_id` 必须使用相同初始参数；`complete_upload` 可重复查询已有结果，不重复保存或登记导入。

Identical chunks are retryable. Query the acknowledged offset after disconnect or restart. Reuse the original request ID and arguments. Repeated completion does not publish or enqueue twice.

封面只需替换 `begin_upload` 参数，分块和完成步骤相同：

```json
{
  "name": "begin_upload",
  "arguments": {
    "purpose": "cover",
    "book_id": "BOOK_ID",
    "expected_revision": "REVISION_FROM_METADATA_SCHEMA",
    "filename": "cover.png",
    "size_bytes": 12345,
    "sha256": "SHA256_OF_ORIGINAL_IMAGE_BYTES",
    "request_id": "stable-cover-request-1",
    "override": false
  }
}
```

只接受真实 JPEG、PNG、WebP；更新明确指定 Book 的展示封面及人工保护，不批量更新 Resource，不写入 EPUB／PDF／音频内嵌封面。失败保留原封面；成功返回新 `revision`、`cover_url`，封面地址仍受普通界面认证限制，不是公开下载授权。

Covers accept validated JPEG, PNG and WebP. Only the selected book display cover is changed. Resources and embedded covers are unchanged. Success returns the new revision and authenticated UI cover URL; failure preserves the old cover.

## 限制与结果 / Limits and results

`get_context.limits` 为服务端权威：每块 256 KiB 原始字节；单本 8 GiB；封面 12 MiB；每授权最多 20 个未完成上传、8 GiB 暂存预留；最后有效分块后 24 小时过期。音频还受现有音频上限限制。客户端可使用更小块；大文件需要大量 MCP 调用，限制不代表客户端具有同等附件或上下文容量。

- `RECEIVING`：正在接收；`UPLOADED`：字节传输完成，尚未发布。
- `PUBLISHING`：已记录发布步骤；`SAVED`：文件保存，尚未完成登记。
- 图书 `QUEUED`：原文件已保存、等待导入；`IMPORTING`：现有导入流程执行中。
- `COMPLETED`：图书实际导入完成并返回 Book／Resource ID，或封面已经生效。
- `FAILED`／`EXPIRED`／`CANCELLED`：独立结果；错误码不含文件内容、绝对路径或凭证。

`file_saved` 明确表示已经确认保存；导入失败保留原文件和错误。图书返回书库内 `relative_path`。保存严格拒绝同名，不改名、不覆盖。一项失败不影响其他上传。开始提交后不可取消；过期只清理属于该上传的暂存文件，不删除已保存图书或已生效封面。未确认完成的发布步骤重试核对持久证明。

Limits are server supplied. Files are saved without overwrite or automatic renaming. `UPLOADED` is transfer completion, not import success; `QUEUED` and `IMPORTING` remain unfinished. `file_saved` distinguishes a retained original from a failed transfer. Failures are independent. Cancellation is available before submission; cleanup never deletes published books or active covers.

## 验收范围 / Verification scope

自动化测试使用锁定官方 MCP SDK `2.2.0`，通过真实 HTTP `tools/call` 传输图书与多块图片、断线／服务重启续传，并验证重复块、偏移、上限和日志脱敏。服务用例测试覆盖真实 FLAT／VOLUMES 导入、封面 HTTP 显示、权限与版本、同名拒绝、数据库故障及迁移。

这证明协议与服务端流程，不代表已验收 Codex、ChatGPT、Cursor 或其他聊天客户端的附件字节能力。本次未进行真实聊天客户端附件验收，也未发布版本。

Protocol/server verification and chat-client attachment verification are separate. No specific chat client is certified by these server tests; real client attachment acceptance and release are not included.

## 替换原文件 / Replace an existing file

使用 `purpose: "replace"`，提供授权 `library_id`、`source_node_id` 和 `list_source_nodes` 返回的 `source_version`（传为 `expected_source_version`），`filename` 必须匹配原文件。其他字节传输参数、分块和完成步骤不变。需要 `files:modify`；`files:upload` 不允许覆盖。服务端在分块接收完成时验证摘要与大小，保存前检查原文件版本及当前路径，再复用标准文件替换和现有扫描／导入。保存阶段不重复整文件哈希，也不额外保留恢复原件。通过同一个 upload_id 查询或继续已确认的登记步骤；保存结果不确定时保留任务供核对，不重新覆盖目标。旧执行版本的发布计划需重新准备，不能直接按新语义执行。

Use `purpose: "replace"` with the granted library ID, source node ID and its `source_version` as `expected_source_version`. The filename must match the original. Replacement requires `files:modify`. Complete receipt validates the byte count and SHA-256; saving checks the current source version and path, uses standard file replacement, and requests the existing scan/import flow. Saving does not repeat whole-file hashing or retain an extra original backup. Use the same upload ID to inspect the result or continue confirmed registration steps. An uncertain save is retained for review without overwriting the target again. Publication plans from an older execution version must be prepared again rather than run with new behavior.
