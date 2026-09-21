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

M0 已完成；M1–M8 待实施。应用服务未启用 MCP，未操作生产书库，未发布。
