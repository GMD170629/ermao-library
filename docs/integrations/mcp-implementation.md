# MCP 实施记录

规格唯一来源为 [v2 执行计划](../plans/mcp-integration-v2.md)。本文记录代码证据和阶段进度，不改变交付范围。

## M0（2026-09-21）

基线 `7737f424c155174185810d71bee26e3151d24bb9`，启动时工作区干净；先前临时范围摘要已被用户提供的 v2 原文件完整替换。

### 能力映射与直接缺口

以下路径以 `apps/api-python/app/` 为根。

| 能力 | 当前归属 | 复用和缺口 |
| --- | --- | --- |
| 当前用户权限 | `core/authorization.py` | 管理权限与库范围可复用；管理员 predicate 全库放行，自动化必须生成无管理员绕过的范围上下文 |
| 会话认证 | `core/auth.py`、`api/deps.py` | 授权管理复用 Cookie；MCP 单独 Bearer，不把自动化凭证加入普通 REST 认证 |
| 标签批量修改 | `modules/library/application/bulk_operations.py`、`infrastructure/bulk_operations.py` | 已有事务、标签增删与操作记录；需要授权预检、保护字段规则和同事务回执；当前此 adapter 未入队写回 |
| 书架 | `modules/shelf/public.py`、`application/commands.py` | 创建命令拥有 commit；成员 replace 不能直接用作范围受限增量操作；回执需纳入现有用例事务 |
| 系统元数据事务 | `modules/library/application/request_mutations.py`、`infrastructure/request_mutations.py` | Book/Bulk/Apply 命令携带写回意图，adapter 消费；自动化使用可信 DB-only 策略并阻止生成／登记意图 |
| 目录展示元数据 | `modules/library/application/source_node_commands.py`、`infrastructure/source_node_commands.py` | 当前 adapter 根据全局设置直接生成 OPF 意图，必须透传应用层副作用策略 |
| 字段保护 | `modules/library/application/metadata_ownership.py` | 复用 protected/protect 字段集合，包括标题／作者派生字段；显式覆盖后保持保护，不新建 AI 所有权 |
| 写回准备与队列 | `modules/metadata/application/writeback.py`、`infrastructure/writeback_queue.py` | 复用快照、幂等键、CAS 与租约；尚无自动化 grant/user 执行上下文、选定字段与格式目标 |
| OPF writer | `modules/metadata/infrastructure/file_writeback.py` | `prepare_writeback` 会建临时文件且 `_publish_sidecar_cover` 提前发布封面，不能用于预览；损坏现有 OPF 会退回重新序列化，不符合新显式写回的保留要求 |
| 写回 worker | `services/metadata_file_writeback.py` | 已有 prepare/publish/complete、租约丢失与不确定结果保留；恢复不扫描文件，维护按所有权清理；需要自动化关键阶段重新授权、恢复点及多文件阶段 |
| 文件移动 | `modules/library/application/commands/manage_source_tree.py` | `RelocateLibraryRoot` 仅修改配置；没有可直接包装为本规格实体移动的用例 |
| 扫描协调 | `bootstrap/library_scan_runtime.py`、`modules/imports/application/readable_resource/scan_source_tree.py` | 复用单消费者扫描和短事务；需让扫描、移动及写回共同检查持久的冲突范围，不新增平行扫描队列 |
| 稳定身份 | `modules/reader/infrastructure/persistence/models.py`、`models/shelf.py` | 阅读记录关联 Resource，书架关联 Book；移动必须原位改路径／库关系，不能删记录重导入 |
| 组织模式 | `modules/library/domain/book_placement.py`、`domain/organization_modes.py` | FLAT 每资源成书，VOLUMES 首层目录成书；改变归属／合并／拆分的移动需拒绝 |
| 封面引用 | 目录编辑用例当前接受受控上传和已有 cover_path | MCP 不暴露路径；需要在所属能力增加已授权封面引用解析，不能直接复用路径参数作为外部输入 |
| Web 入口 | `apps/web/features/settings/center`（仓库根相对） | 复用 SettingsCenterShell、导航、双语和现有样式；自动化授权页尚未实现 |
| HTTP 入口 | `scripts/unified-http-gateway.mjs`（仓库根相对） | 复用 `/api` 和部署前缀；实际网关、授权与客户端联合验证留 M2/M8 |

读取器存在不代表 writer 已实现。OPF、EPUB、ComicInfo、音频、PDF 的新增选择性写回仍全部待实现和保真验收。

### 固定执行上限

依规格采用查询默认 20／最多 50，元数据批次最多 20，文件计划最多 100 个顶层目标。展开另限 10,000 个文件及 100 GiB，总体方案默认 15 分钟有效。超限整批预检拒绝，不截断后执行；清单分页返回。限制是初始安全边界，不是性能承诺，后续实现在同一权威定义中使用。

### SDK 实验

- PyPI 实際核验并锁定 `mcp==2.2.0`，支持 Python >=3.10；本项目 Python 3.11.15 解析与安装成功，更新 `pyproject.toml` 和 `uv.lock`。
- 使用安装版本的 `mcp.server.MCPServer`、`streamable_http_app(json_response=True, stateless_http=True)`、`session_manager.run()` 与 `mcp.Client`；v2 Python 属性为 snake_case（如 `is_error`）。
- 新测试通过真实 loopback TCP 启动 Uvicorn/FastAPI，挂载 `/api/mcp`，验证工具发现、中文参数调用、SDK 生命周期正常退出、非法 Host 421、非法 Origin 403。未关闭 DNS rebinding 防护。
- 命令（工作目录 `apps/api-python`）：`uv run --extra dev --locked pytest -q tests/integration/modules/automation/test_sdk_transport.py`：1 passed；对应 `ruff check` 通过。
- 该探针只证明 SDK 最小集成；没有上线业务工具，也没有证明 Bearer、网关前缀、真实 LM Studio/Cursor 或文件操作通过。

M0 已完成（提交 `3a16e61a`）；应用服务未启用 MCP，未操作生产书库，未发布。

## M1：授权基础与 DB-only 边界（进行中）

已落地：

- `modules/automation/domain/access.py` 为八个 scope、固定库范围、sidecar/embedded、跨库选项和当前权限交集的唯一规则；`domain/tools.py` 固定 23 工具名称与最小权限、执行上限，尚未注册业务工具。
- `application/grants.py` 实现创建、本人列表、撤销、Bearer 校验与持久操作重检入口。有效期限定 30/90/365 天，秘密只在创建返回，授权没有原地扩权方法。
- `infrastructure/credentials.py` 使用 32 字节随机秘密，`infrastructure/grants.py` 只存 SHA-256 摘要，不缓存有效身份。迁移 `0021_automation_grants` 创建独立授权表，不生成默认授权，不改现有用户权限。
- `auth/infrastructure/automation_identity.py` 复用现有用户授权；`library/infrastructure/automation_access.py` 查询真实可见库 ID。`bootstrap/automation.py` 只接线。实际授权始终与 grant 的固定库集合取交集。
- `library/application/metadata_effects.py` 定义可信 DB-only 策略。Book/Bulk/Apply 元数据事务在调用持久层前拒绝该策略下的文件意图；目录元数据用例将策略传至意图生成点，跳过全局自动写回。原 Web 默认行为保留。
- ADR 0031 记录本次跨能力归属与执行边界。

验证（工作目录 `apps/api-python`）：

```text
uv run --extra dev --locked pytest -q tests/integration/modules/automation tests/unit/modules/automation tests/test_capability_architecture.py tests/unit/modules/library/test_mutation_use_cases.py tests/unit/modules/metadata/test_source_node_writeback.py tests/integration/modules/library/test_request_mutations.py tests/architecture/test_write_transaction_contract.py
88 passed
```

覆盖：新／既有数据库升级与重复启动、默认无授权、令牌摘要及重开／撤销／到期、实际管理员库限制与权限降级、跨库和写回子权限、保护／标签权限交叉、目录 DB-only 更新且原件不变、原 Web 自动入队、预构造文件意图拒绝、模块边界及事务约束。改动文件 Ruff 通过；新授权模块、接线与身份适配器 Mypy 局部检查通过（15 个源文件）。

授权基础与 DB-only 边界提交：`d4ccde1b`。

### 会话管理接口与服务配置

新增 `/api/automation/grants` GET/POST、`/api/automation/grants/{grant_id}` DELETE，以及 `/api/automation/settings` GET/PUT。请求／响应有严格 Pydantic 契约；管理仅接受现有 Cookie 会话，修改必须同源 Origin。授权返回 `no-store`，明文仅创建时返回，列表没有 token/digest；用户不能列出或撤销其他人的授权。

服务设置保存在既有 SystemSetting 中，默认关闭，仅真正的管理员可开启。配置验证公开地址、部署前缀、HTTPS；非回环 HTTP 需要显式选项，不执行 URL 探测。通用系统设置读写不暴露／修改该嵌套配置，避免绕过专用授权与校验。

创建、撤销、服务设置与既有 SystemEvent 审计在同一事务提交，记录 actor、动作和目标 ID，不记录明文或摘要；审计失败回滚授权。日志按当前系统语言生成 zh-CN/en-US。

最新验证（工作目录 `apps/api-python`）：

```text
uv run --extra dev --locked pytest -q tests/integration/modules/automation tests/unit/modules/automation tests/test_capability_architecture.py tests/architecture/test_write_transaction_contract.py tests/contract/api/test_auth_system_contract_regressions.py tests/contract/api/test_system_management_authorization.py tests/test_response_dto_schemas.py
187 passed
```

新增服务配置／HTTP／审计和身份接线的 Mypy 局部检查通过（21 个源文件），对应 Ruff 通过。未运行无关全仓回归。

M1 仍有后续接线验证：最近使用时间在 M2 实际 MCP 调用中记录；当前 operation 授权入口已存在，但尚未与文件任务 worker 接线，待 M4–M6 引入带 grant 的实际任务后验证关键阶段撤权。只读挂载的真实文件行为也需在文件用例实现后验证。M2–M8 未开始，不应将这些基础测试视为整套 MCP 功能已交付。

## M2：实际 MCP 传输与范围查询（进行中）

已接入 `/api/mcp`：官方 SDK 无状态 JSON 传输，逐 HTTP 请求隔离工具定义与配置，逐工具调用重新验证用户／令牌／库权限和维护状态。仅 Bearer 认证，无会话回退，响应禁止缓存；公开 Host 和 Origin 使用管理员配置。数据库访问在线程池中使用独立会话，异常在协议边界脱敏。成功调用记录最近使用时间，遥测存储失败不把已完成操作变成失败。

已开放七个查询工具：get_context、list_libraries、search_books、get_books、list_facets、list_shelves、get_shelf。返回既有 Catalog 投影（无正文、下载地址或绝对路径），允许暂无可读资源的 Book。批量指定目标中存在不可见／不存在项时整批拒绝。

修复两个共用查询入口：Catalog facet 的名称和计数均按可见 Book 连接；智能书架在用户规则求值后再次按调用上下文过滤，再统计／分页。显式空 book_ids 现在匹配零项，修正旧测试中与其测试名称相反的扩大范围断言。未新建并行图书／书架查询逻辑。

真实统一网关此前覆写 Host 为内部上游地址，与公开域名校验冲突；网关现在保留请求 authority，网络连接目标仍由固定配置决定。实际测试分别使用直接 HTTP 及 Node 统一网关 `/books/api/mcp`，经官方 SDK 验证工具发现、中文元数据、管理员限定库、静态和智能书架计数、范围外拒绝、即时撤销、无 Cookie 回退以及恶意 Host／Origin 拒绝。

验证：授权／MCP／领域／架构／事务检查 91 passed；受影响 Catalog／Shelf／OPDS／智能筛选及真实网关集成 24 passed；Node 网关现有 5 项测试通过。M2 的基础写工具、文件只读／schema 仍待实现，M3–M8 尚未完成。没有运行生产文件操作或发布。
