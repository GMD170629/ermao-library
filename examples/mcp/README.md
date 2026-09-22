# 二毛图书 MCP / Ermao Library MCP

MCP 服务内置于现有后端，地址是网站根地址加 `/api/mcp`；例如 `https://books.example/books/api/mcp`。没有独立容器或新增公开端口。服务默认关闭。

The MCP service runs inside the existing backend at your public base URL plus `/api/mcp`, including any deployment prefix. It is disabled by default; no additional container or public port is required.

## 配置 / Connect

1. 管理员在「设置 → 自动化授权 → MCP 服务」开启服务，填写公开根地址（含部署前缀，不含 `/api/mcp`），选择可授权能力。HTTP 和 HTTPS 均支持域名、IP 与端口，无额外 HTTP 开关。
2. 「授权服务」默认显示授权列表，右上角「创建授权」展开表单。默认全部书库（动态），包含账户当前及未来可访问书库；也可选择指定书库固定范围。旧授权不会自动扩展。服务关闭时请管理员先开启。
3. 每条授权的「复制配置」打开该授权的配置面板，默认 Codex，可切换 LM Studio / Cursor，预览、复制或下载完整配置。配置包含令牌，请勿分享或提交仓库。刷新后可再次取回；关闭面板或离开分区会清除浏览器内存令牌，不保存在浏览器存储中。
4. 过期或撤销的授权不能取回配置。历史摘要令牌仍可使用，但无法取回；需要完整配置时重新创建授权。操作列表提供原有任务状态、逐项结果、刷新和取消。

Administrators enable MCP in Settings → Automation access → MCP service. HTTP and HTTPS support domains, IPs, ports and deployment prefixes without an extra HTTP opt-in. The Access grants tab defaults to the grant list. Create a grant for all currently and subsequently accessible libraries (dynamic), or explicitly select fixed libraries. Existing grants remain fixed. Each row opens its own complete client configuration, defaulting to Codex, with LM Studio and Cursor options. Secrets can be retrieved again after reload but are never persisted in browser storage. Revoked or expired grants cannot export configuration; legacy hash-only tokens cannot be recovered. The Operations tab preserves task status, per-file results, refresh and cancellation.

服务端令牌采用 AES-GCM 加密保存，同时保留认证摘要。请持久化并独立备份 `storage/secrets/automation-token.key`（权限 0600），与数据库配套恢复。密钥丢失、损坏或权限不安全时明确报错，不覆盖已有密钥；已有密文时也不生成替代密钥。密钥错误不影响已有摘要令牌的认证。仅本人有效 Cookie 会话可通过带合法 Origin 的 `POST /api/automation/grants/{id}/reveal` 取回有效令牌，响应禁止缓存，审计不记录秘密。

Persist and separately back up `storage/secrets/automation-token.key` with mode 0600, and restore it alongside the database. Tokens are encrypted with AES-GCM and authenticated by their existing digests. A missing or invalid key causes an explicit recovery error; the server never replaces an existing key or generates a replacement while encrypted grants remain. Only the owner’s valid Cookie session and Origin can reveal an active token. Responses are not cached and audit events contain no secrets.

[LM Studio 官方配置](https://lmstudio.ai/docs/app/mcp) 支持远程 URL 和请求头，可选择自己的本地模型。[Cursor MCP 配置](https://cursor.com/docs/mcp) 支持远程 URL 和环境变量请求头；Cursor 不保证本地推理。示例 Cursor 模板从**客户端进程**的 `ERMAO_MCP_TOKEN` 环境变量读取，终端设置变量不一定传给已启动的桌面应用。LM Studio 模板使用显式占位符。

LM Studio can use a local model with remote MCP tools. Cursor does not guarantee local inference. The Cursor example reads `ERMAO_MCP_TOKEN` from the client process environment, which may differ from your terminal. Replace the LM Studio placeholder explicitly. Use a model that supports tool calls.

## Codex 接入 / Connect with Codex

可直接从授权行复制完整配置到 Codex 的 `config.toml`。仓库提供的 `codex.example.toml` 和以下命令则使用环境变量方式注册连接。也可将授权令牌安全地注入 **Codex 进程**的 `ERMAO_MCP_TOKEN` 环境变量，再启动客户端。已启动的桌面应用不会自动继承另一个终端后来设置的变量。保留客户端的工具确认设置；非交互模式如果禁止确认而写工具需要确认，会拒绝写入。

Merge `codex.example.toml` into your Codex configuration, or register the connection below. Securely supply `ERMAO_MCP_TOKEN` to the Codex process before starting it. An already-running desktop app does not inherit variables later set in another terminal. Retain client tool approvals; non-interactive runs that prohibit prompts reject tools requiring approval.

```sh
codex mcp add ermao --url 'https://books.example/books/api/mcp' --bearer-token-env-var ERMAO_MCP_TOKEN
```

连接后可以要求 Codex：「查看我授权书库的图书，先预览整理方案；经我确认后执行并查询最终结果。」实际写操作仍受服务端书库、scope、版本和冻结方案限制。Codex 接入不代表本地模型推理；本地模型需另行配置和验收。[OpenAI 官方 MCP 配置说明](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

After connecting, ask Codex to inspect the authorized library and preview a plan before execution, then poll the final result. Server-side library scopes, revisions and frozen plans still apply. Connecting Codex does not establish local inference; that requires separate model configuration and validation.

## Python 示例 / Python examples

从仓库的 `apps/api-python` 目录执行，使用锁定的官方 `mcp==2.2.0` 及项目环境。不要另装无版本约束的 SDK。`.env.example` 是变量说明，脚本不会自动加载 `.env`，也不会把令牌写入文件。

Run from `apps/api-python` using the repository's locked environment (`mcp==2.2.0`). Scripts read environment variables; they do not automatically load `.env` or save credentials.

```sh
export ERMAO_MCP_URL='https://books.example/books/api/mcp'
# Set ERMAO_MCP_TOKEN securely in your shell; never commit it.
uv run --locked python ../../examples/mcp/smoke_read.py
uv run --locked python ../../examples/mcp/create_shelf_example.py --name 'Reading list'
uv run --locked python ../../examples/mcp/update_metadata_example.py --target-type book --target-id BOOK_ID --set 'title="New title"'
uv run --locked python ../../examples/mcp/move_books_example.py --node-id NODE_ID --destination-library-id LIBRARY_ID --destination-path 'Author/Title'
uv run --locked python ../../examples/mcp/writeback_metadata_example.py --target-type book --target-id BOOK_ID --node-id NODE_ID --mode opf --field title
```

以上默认只读取或预览，不修改图书记录和书库文件；文件预览会保存短期方案。写入必须追加 `--execute --request-id YOUR_STABLE_KEY`。书架、系统修改即时返回结果；文件任务提交后最多查询五分钟。退出或网络中断不会取消后台任务。通过设置页或 `get_operation` 查看真实逐项结果；`cancel_operation` 只取消尚未发布的文件。

All examples default to reads or previews. File previews persist temporary plans but do not modify library files. Writes require `--execute --request-id YOUR_STABLE_KEY`. File examples poll for up to five minutes; disconnecting does not cancel server work. Inspect results with `get_operation` or the settings page. Cancellation only affects unpublished work.

超时重试须保留同一个请求标识、方案标识和参数，不能换键反复提交。文件示例可直接使用已打印的方案：

Keep the original request ID, plan ID and arguments when retrying; do not create a new operation after a timeout:

```sh
uv run --locked python ../../examples/mcp/move_books_example.py --plan-id ORIGINAL_PLAN_ID --execute --request-id ORIGINAL_REQUEST_ID
uv run --locked python ../../examples/mcp/writeback_metadata_example.py --plan-id ORIGINAL_PLAN_ID --execute --request-id ORIGINAL_REQUEST_ID
```

系统元数据示例重试时还应传 `--expected-revision ORIGINAL_REVISION`，其余字段与原请求一致。`--clear FIELD` 明确清空，`--override FIELD` 明确覆盖保护字段且需要独立权限；未选字段保持不变。不要向脚本传令牌命令行参数。

For an exact system-metadata retry, also supply `--expected-revision ORIGINAL_REVISION` and keep the original fields. `--clear FIELD` explicitly clears a nullable field; `--override FIELD` requires separate permission to overwrite a protected field. Do not pass tokens as command-line arguments.

## 能力与限制 / Capabilities and limits

- 系统更新：输入值 → 数据库。刷新：文件 → 数据库。写回：已确认的系统值 → 指定文件。三个方向独立；系统更新权限不会触发文件自动写回。
- 移动：固定书库内的安全相对路径；完整图书可明确授权跨库/跨盘。保持图书和资源 ID；单资源不能隐式拆书或换归属。目录和伴随文件先展开清单。禁止任意路径、脚本及覆盖现有目标。
- OPF/EPUB/ComicInfo 选择字段写入，未选字段和正文保持。实际支持字段以 `get_metadata_schema` 和 `read_file_metadata` 返回为准。
- MP3/M4A/M4B/FLAC、PDF 当前只写标题、作者、简介。PDF 最大 64 MiB，签名或加密拒绝。PDF 使用增量修订，清空只影响最新元数据，**旧修订仍保留原值，不是敏感信息擦除**。
- MP3 仅受支持的 ID3v2.3/v2.4 结构；拒绝共存 ID3v1 或需要调整绝对章节偏移的文件。未知结构、无法保真保存、只读源、空间不足都拒绝写入。
- 查询每页最多 50，元数据批次最多 20；文件方案最多 100 个顶层移动，展开最多 10,000 项/100 GiB，有效期 15 分钟。写回方案最多 20 项。
- 文件原件恢复副本保留两天；移动和写回共用 100 GiB 恢复预算。到期仅在验证目标与备份未被改动后清理。校验失败保留待核查，不能把目录中的备份手工当作普通书籍导入。

System updates, file-to-system refresh, and system-to-file writeback are separately authorized. Moves preserve identities and reject implicit ownership changes, arbitrary paths and overwrites. OPF/EPUB/ComicInfo writes are selective. Audio/PDF support is limited to title, authors and description. PDF writes append a revision; clearing current metadata does **not** erase old revisions. Unsupported, signed, encrypted, read-only or unsafe structures fail closed. Limits are 50 query items, 20 metadata/writeback targets, 100 top-level moves, 10,000 expanded entries and 100 GiB per move plan; plans expire after 15 minutes. Recovery backups share a 100 GiB quota, retain originals for two days, and require verification before cleanup.

## 排错与恢复 / Troubleshooting and recovery

先调用 `get_context` 检查有效权限和范围。401 检查令牌、有效期、撤销、服务开关；权限错误检查当前账户、授权书库及 sidecar/embedded 子权限。403 Origin 错误通常说明管理页面地址或代理可信配置不一致，不能通过关闭校验解决。部署前缀必须同时体现在网站和 MCP 地址；远程客户端的 `localhost` 指它自身，容器内 `localhost` 也不是宿主机。

Start with `get_context`. For authentication failures check token expiry/revocation and service status; for authorization failures check current user permissions, fixed library scope and writeback subpermissions. Management Origin errors require a consistent public/proxy configuration. A remote client's `localhost` refers to that client, and a container's `localhost` refers to that container.

方案过期、元数据版本变化或源文件变化应重新预览并核对，再以新操作执行。若原操作已经受理，只查原任务，勿因等待超时重新建任务。`RECOVERY_REQUIRED` 表示文件被保留但一致性尚需核对：保留任务标识及备份，由管理员检查原路径、目标和任务记录；不要覆盖目标、删除临时槽或修改数据库状态来“强制成功”。有完整发布证明的任务会在 worker 重启时按租约恢复必要索引；未知部分写入保留人工核查。

Expired or changed plans require a new reviewed preview. If an operation was already accepted, inspect that operation instead of submitting again. `RECOVERY_REQUIRED` retains files for review: preserve the operation ID and backups, and have an administrator reconcile source, destination and recorded results. Do not overwrite targets, delete staging slots or edit database state to force success. On worker restart, operations with verified publication proofs can repair the index under their lease; uncertain partial writes remain for manual review.

封面可用 `get_metadata_schema` 中的 `cover_references` 选择，通过系统字段 `cover_ref` 更新。仅列出当前图书已保存的不可变本地封面，最多 50 项；不接受 URL、文件路径或其他图书的引用，不复制图片。`values.cover_ref` 表示当前值，不一定是可重新选择的候选。清空封面仍须显式选择并满足人工保护权限。

For covers, select a `cover_references` entry returned by `get_metadata_schema` and update the system field `cover_ref`. Only up to 50 immutable local covers already saved for this book are eligible. URLs, filesystem paths and other books' references are rejected; no image is copied. The current `values.cover_ref` is not necessarily an eligible candidate. Clearing requires explicit selection and the applicable protected-field permission.

已完成任务的恢复副本尚未验证清理时，相关文件及其父目录移动返回 `RECOVERY_BACKUP_PENDING`，避免改变恢复位置；其他图书不受影响。正常保留期为两天，目标被改动而无法验证时继续保留，需核查任务记录。标准元数据写回更新文件修改时间，使阅读缓存识别新版本；纯移动保留原修改时间。ID3v2.3 使用标准斜线分隔多个作者，作者名字自身包含斜线时拒绝写入，以免读回歧义。

While a completed operation retains an unverified recovery backup, moves of the affected file or its parent return `RECOVERY_BACKUP_PENDING`; unrelated books remain movable. The normal retention is two days; changed targets retain backups for review. Metadata writeback advances the file modification time to invalidate reader caches; moves preserve it. ID3v2.3 uses slash-separated authors and rejects author names containing literal slashes to prevent ambiguous round trips.
