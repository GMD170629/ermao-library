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

### M2 基础写入与持久回执

新增五个已实现工具：create_shelf、add_shelf_books、remove_shelf_books、add_book_tags、remove_book_tags；根据当前授权逐请求注册。读授权不会因服务开启写 scope 或其他授权调用而获得写工具。

迁移 `0022_automation_receipts` 保存 grant/request_id、动作、规范化参数摘要与结果；唯一约束串行化同一请求。既有 CreateShelf、ExecuteBulkShelfMembership、ExecuteBulkMetadata 通过小型结果回执端口在自身提交前保存结果，没有新增并行业务实现或隐藏事务。参数不一致拒绝重用 request_id，回执失败连同业务回滚；重放再次验证当前资源可见性。

书架操作保持本人静态书架及增量成员语义。标签沿用既有批量元数据和 facet 更新，自动化要求显式保护策略，目前受保护标签拒绝；M3 将接入带具体字段和版本的覆盖。原 Web 默认手动编辑策略不变。标签工具不构造或登记文件写回意图。

验证：并发同键创建仅一个书架、回执失败回滚、重放一致、参数冲突、智能书架写入拒绝、增量移除不损失范围外成员、全局自动写回开启时标签仍仅改数据库。相关迁移／架构／事务和原批量 API 共 74 passed；真实 SDK 直接及 `/books` 网关读写、授权隔离及专门事务测试 6 passed。新能力与被改用例 Mypy 局部检查通过（26 个源文件）。M2 文件只读／schema 与 M3–M8 继续待完成。

## M3：系统元数据补丁（进行中）

新增 get_metadata_schema 和 update_metadata：按 Book／Resource／SourceNode 返回实际字段、当前值、保护状态和元数据内容版本。版本含元数据和保护状态及数据库毫秒时间，不使用阅读心跳；根目录实际同步的 Book 状态也纳入版本和保护校验。输入严格拒绝结构字段、隐式 null 清空、无版本和未知选项。

实现 patch、fill_missing、单独 clear_fields 和 override_fields；人工空值不填回，保护覆盖需要独立 scope 与具体字段，覆盖后保留保护。标签字段更新额外要求 tags:write；独立标签工具也支持精确 tags 覆盖和逐书版本，标签授权无需借用完整 metadata:write。

新用例在 Library 归属，复用既有 Book／Resource／SourceNode／facet 持久入口；全批预检后修改，回执与业务同事务提交，既有操作记录保存 grant 与逐字段改前改后值。目录补丁明确公布会同步的 Book，重叠目标拒绝。对原目录入口增加选择字段，避免标题修改顺带保护或覆盖简介；原 Web 默认行为保留。原 Book 持久入口同步修复标题更新遗漏 normalized_title 的问题。

验证：官方 SDK 经直接 HTTP 和 `/books` 网关完成 schema→版本补丁→同键重放→旧版本拒绝；覆盖 Book／Resource／Node、指定保护覆盖、保护空值、精确清空、原字段保留、根目录关联保护、关联 Book 非空时不补写、外部会话修改后旧版本拒绝，以及全局自动写回下业务文件保持原字节且无队列任务。相关授权／补丁／既有用例／批量 API／架构／事务检查 117 passed；局部 Mypy 28 个源文件通过。

本阶段尚未完成 refresh_metadata（依赖只读文件元数据入口）和已授权封面引用。M2 目录／文件只读与 M4–M8 仍继续实施，不能视为全阶段完成。

### M2 目录与本地元数据只读入口

新增 list_source_nodes、read_file_metadata。目录分页复用 SourceNodeRepository 的直接子节点查询，计数和父节点均限制当前库；响应仅含相对位置与节点标识。文件访问逐级使用目录文件描述符及 no-follow，拒绝穿越、反斜杠、非普通文件和符号链接；解析器使用有读取预算的已打开描述符，不在检查路径后重新按字符串打开文件。

read_file_metadata 明确 embedded／sidecar，报告真实来源相对文件、格式和文件版本。多个有效伴随文件返回歧义，必须指定关联候选；不执行来源优先级合并、封面提取、数据库刷新或写回。读取中源文件版本改变会拒绝返回。已通过 OPF、EPUB、ComicInfo、PDF Info、MP3 ID3、MP4（M4A/M4B）及 FLAC 的实际只读样本；PDF XMP 等完整读写映射继续在格式阶段补齐。writable_fields 当前为空，不把已能读取宣传成已能安全写入。

为避免复制解析机制，将既有有限读取、严格 PDF xref 读取和 OPF 伴随路径规则提到共享基础设施；迁移全部现有调用方，删除旧有限读取模块。EPUB 元数据条目读取和 ComicInfo 解析同样复用原解析入口。读取预算和原导入行为保持不变。

验证：真实 SDK 经 `/books` 网关读目录／OPF 后，系统标题保持原值；纯读取不生成文件或写回记录。四种音频容器使用 FFmpeg 生成的短音频实际解析并比较全文件字节；目录／文件 symlink、穿越、伴随歧义和中途修改验证拒绝。MCP 全部现有集成、导入有限读取／PDF／OPF／漫画、SourceNode 仓储相邻契约及架构／事务检查共 156 passed；局部 Mypy 33 个源文件通过。

### M3 文件刷新与提交时授权

新增 refresh_metadata：调用方必须给出系统版本、文件版本、来源、目标和字段；来源必须属于目标图书／资源／目录。只投影明确字段，不把源中缺失值解释为清空，不擅自补足日期精度。操作记录包含来源节点、相对文件、文件版本和格式。重复请求读取已提交回执，不重新读取后来变更的文件。

文件读取在写事务前完成；领取回执后再次检查当前服务、用户、授权及资源范围。创建书架、成员、标签和系统补丁同步采用提交前检查。元数据读取强制刷新 ORM 状态，避免慢解析期间沿用旧对象覆盖其他会话的新值。

验证：刷新来源绑定、文件旧版本拒绝、精确字段、来源审计、全文件字节不变、重放不再读文件；读取期间撤权拒绝提交，读取期间系统元数据被修改则版本冲突；创建书架预检后撤权同样不创建业务数据和回执。真实 SDK 直接和带前缀网关刷新成功。相关集成、领域、既有用例、架构和事务测试 122 passed；局部 Mypy 30 个源文件及 Ruff 通过。封面引用和 M4–M8 仍待完成。

## M4：文件方案基础（进行中，尚未开放执行工具）

新增 Library 归属的纯方案用例与真实文件清单检查，复用 SourceNode 相对路径、图书归属判定和目录描述符访问。预览限制顶层目标、文件数、总字节与深度；检查父子重叠、Unicode／大小写冲突、设备名称、symlink、特殊文件、硬链接和嵌套挂载，记录 inode／时间／大小／链接数。目标预览列出缺失目录而不创建目录。模板仅允许固定标量占位符，替换值不能注入子目录或表达式。

拓扑检查纳入节点／Book／Resource／Asset 关联与组织模式版本，复用 decide_book_anchor_for_resource 判断移动后是否更换 Book 归属。当前先接完整图书单元；不满足的局部移动明确拒绝，后续需按同一归属规则扩展。源／目标授权在文件读取前整批预检。

验证：路径、模板注入、重叠与名称冲突、真实目录清单、伴随文件、目标不创建、symlink／硬链接／FIFO 拒绝及既有只读／刷新／架构／事务检查共 93 passed；实际 ORM 拓扑与领域检查 21 passed，Mypy 5 个源文件通过。尚未接入持久方案、执行／恢复、共享扫描冲突边界，不能将该基础视为文件移动已可用。

### M4 持久意图与现有队列协调基础

迁移 0023 添加固定方案、移动操作和逐项目标记录；方案唯一执行，保留 grant/user/request、阶段、取消及恢复信息。计划可完整持久化往返，客户端投影不含内部根路径。尚未开放提交工具，待执行与恢复链完整后接入。

扫描／导入和 OPF 目标领取复用同一持久冲突查询：排队移动阻止新的冲突任务，已开始写回允许先完成；移动领取反向等待运行中的导入／写回。扫描领取在同一条件 UPDATE 再检查，竞争失败延迟而不执行 I/O。协调粒度当前为源、目标整库，不是仅进程内锁。

新增不可覆盖目标的同盘发布原语：Linux renameat2 RENAME_NOREPLACE 与 macOS renameatx_np RENAME_EXCL；不支持时拒绝，不降级到覆盖式 rename。真实临时文件／目录验证目标已有内容不被覆盖；冻结源改变和恢复目标被修改均拒绝。已打开目录 FD 控制相对发布，发布后刷新目录并检查 inode。该原语尚未接入完整 worker，不表示文件任务已交付。

参考：[Linux rename 手册](https://man7.org/linux/man-pages/man2/rename.2.html)、[Apple 独占重命名能力](https://developer.apple.com/documentation/foundation/urlresourcevalues/volumesupportsexclusiverenaming)。

局部 Mypy 新增 4 个持久／发布源文件通过。扩到既有扫描队列／worker 时有 6 个既有类型错误；已用 HEAD 原文件逐项复现（scan_gating 参数类型及异常别名收窄），未新增忽略或削弱检查。

本批定向验收（持久移动、迁移重入／回退、文件发布、现有扫描／写回领取和 worker、架构／事务）114 passed；对应 Ruff 通过。

### M4 同盘执行与中断恢复用例

新增应用层阶段执行用例：全批预检、持久 PREPARING、文件发布、索引和依赖队列同事务更新、完成。所有文件 I/O 前释放数据库读事务，复制／发布期间不持有 SQLite 写锁。同盘跨库索引使用既有 composite ON UPDATE CASCADE，保留 Book／Resource／Asset／SourceNode 和书架 ID；元数据操作记录沿用既有 LibraryOperation，含 grant 和源目标相对位置。

恢复检查冻结目标 inode 和完整目录清单，区分发布成功但尚未确认的情况；错误保留可恢复阶段。撤权后不启动未发布项，只允许已发布项的最小索引收尾。取消未开始项不改源文件。移动时清除旧路径的待处理 OPF 意图（运行中意图拒绝），迁移扫描检查点并安排新位置局部扫描，保持无关范围。

实际测试涵盖同盘跨库 ID／书架关联、发布后模拟异常、重新进入恢复且不二次移动、已发布后撤权允许收尾、发布前真实授权撤销不改文件、取消以及旧写回失效。相关执行／计划／文件原语／扫描／写回／架构／事务共 110 passed，新增／修改执行源文件局部 Mypy 5 个文件通过，Ruff 通过。

当前执行用例仅完成既有目录中的同盘完整图书单元。跨盘、新目录、局部资源移动、实际 worker 装配与 MCP 工具仍待接入；M4 尚未完成，M5–M8 未完成。

### M4 新目录与真实跨文件系统复制

新目录按预览路径逐个创建并记录目录身份，发布后批量写入 SourceNode，关联既有父节点；方案仍不可变，执行准备数据保存在目标恢复记录。文件作用域的目录描述符上下文只转换打开失败，不再把调用者的磁盘写满／目标已存在错误误归为读取失败。

跨盘先以 1 MiB 块复制至计划中服务端生成的独占暂存槽，复读 SHA-256、校验整个源清单未变化，保存复制证明后才能发布。发布与索引阶段完成后，再以独占 rename 将源暂存为恢复副本；恢复利用已存证明，不重复复制。受控 source／target 槽由扫描的共用忽略规则排除，与用户是否显示隐藏文件无关，外部移动输入也禁止占用这些名称。

复制核对 UID/GID、mode、mtime 和有界扩展属性；macOS 同时读写并核对原生 ACL 与文件 flags。不支持保留时拒绝而保留源，不退化为只复制正文。预检检查源父目录和目标已存在父目录可写、文件系统非只读。Linux 适配分支尚未在 Linux 实机验收，不将 macOS 证据当作另一平台证明。

实际跨盘测试通过 hdiutil 创建临时 APFS 磁盘映像，断言 source/target st_dev 不同，测试完成自动卸载。覆盖正常完成、目标发布后异常、源暂存后异常，三种情况均保持内容、ACL/xattr、业务 ID，恢复仅复制一次。分块复制的磁盘写满、源变化和暂存槽已存在检查保留原文件。

相关 MCP／移动／属性复制／忽略规则／架构／事务 157 passed，Ruff 通过；本批局部 Mypy 相关源文件通过。跨盘恢复副本配额、到期清理、实际 worker 与 MCP 文件入口仍待接入；局部资源移动仍待扩展，M4 尚未完成。

### M4 后台接线、恢复配额与 SDK 文件任务

迁移 0024 为恢复副本预留量增加持久字段，并从旧方案回填跨盘属性及字节数。入队在同一写事务检查 100 GiB 恢复配额；已完成源副本保留两天，后台每分钟最多检查五个到期项，重新核对目标内容和备份身份后清理。目标或副本被修改时保留副本、配额和原因，一天后再检查；部分暂存复制和取消后的暂存副本不会按成功清理处理。

文件执行接入现有单消费者 worker，拥有独立会话、启动恢复游标、失败隔离和退出清理。运行中的不确定任务不会热循环重放；在下一次进程启动进行有边界的恢复。共享新目录按本任务已记录的目录身份复用；新增完整 Resource 在原 Book 内重命名支持，拒绝改变归属和局部跨库。发布前再次检查数据库归属版本和目标根配置。

MCP 新接入 plan_file_operations、execute_file_operations、get_operation、cancel_operation，提交复用既有 receipt，固定方案仅执行一次。模板只接受固定字段和有界字符串，模板值由客户端明确提供。计划不改书库文件；后台执行不依赖客户端连接。真实官方 SDK 在直连及 /books 网关两种路径完成模板预览、幂等提交、worker 执行、状态查询和排队取消，完整目录中 OPF 内容与 Book ID 保留。

本批局部 Mypy 12 个相关文件通过，Ruff 通过；集成与相邻 worker/文件/架构/事务测试结果见本批提交。单文件外部伴随文件与大小写重命名仍待补齐，M4 尚未完成；M5–M8 仍待实现。

### M4 伴随文件与大小写重命名

单文件方案展开明确的同 stem OPF 与其安全封面引用，封面保留原文件名以保持 OPF href；目录内文件沿完整清单搬运。已有伴随 SourceNode 同步移动，主 Book/Resource 归属保持。同 stem 多格式、共享目录 OPF、共享或越界封面引用拒绝单独搬运，不隐式写改 OPF 内容。每个物理项目有独立日志；已有伴随项目发布后剩余项目中断，保留恢复状态而不宣称取消全部成功。

同目录仅大小写不同的文件名通过服务端固定中间槽分两次独占 rename；恢复识别原名、中间槽、目标名的实际目录条目及冻结文件身份。临时目录测试覆盖正常完成和第一步 rename 后中断重启，业务 ID 和目录内容保持，不依靠大小写不敏感文件系统的 exists 判断。

本批相关自动化／文件／架构／事务 147 passed；新伴随识别、规划、发布和索引相关 6 个文件局部 Mypy 通过，Ruff 通过。此前 worker 接线批次为 144 passed。M5 标准格式选择性写回、M6 音频/PDF、M7 Web 配置与示例、M8 全阶段验收继续实施。

### M5 核心格式编辑器（接线前）

新增选择字段的 OPF、ComicInfo 和 EPUB/CBZ 容器编辑器。OPF 保留未选字段、次标题、标识 ID、非作者创作者与扩展；共同解析入口识别 EPUB 3 role refinements，避免把插画者读成作者。ComicInfo 保留 Pages 页序映射和未知节点。EPUB 通过既有 container.xml 定位包内 OPF，保持成员顺序、正文哈希、压缩方式和归档注释；拒绝签名/加密标记，检查必需元数据。ZIP 逐块写入独立空预备流、复读所有未改成员哈希，限制结构读取、成员数和展开量。

既有 OPF writer 在发现损坏、过大或符号链接旁车时，先失败再处理封面，不再吞掉解析错误并重建覆盖；现有写回行为相关测试通过。

本批格式样本、既有 OPF/导入、文件读取、架构和事务测试 110 passed；5 个相关文件局部 Mypy 与 Ruff 通过。以上是格式编辑器验证，尚未接入 MCP 标准写回方案和既有队列，writable capability 仍未对外开放，不能视为 M5 完成。

格式依据：[EPUB 3.3](https://www.w3.org/TR/epub-33/)。

### M5：冻结方案、既有队列与真实文件发布（续）

- 新增迁移 0025：不可变方案与持久逐项结果；执行仍进入既有 MetadataWriteback 队列，共用容量计数、租约和后台消费者，没有第二条写回队列。系统元数据写权限与文件写回权限独立。
- 预览校验源节点归属、系统版本、sidecar/embedded 授权、同路径与共享 OPF 冲突；只选系统已确认值，空值要求 clear_fields 明确选择。最多 20 项、15 分钟方案，返回具体文件与字段前后值，不产生书库文件副作用。
- `plan_metadata_writeback`、`execute_metadata_writeback` 已注册；get/cancel_operation 按原操作类型和本人 grant 范围分发。receipt 与入队在同事务中，重试不重复提交。
- 新文件通过受控槽位创建、逐成员验证、原属性保留、SHA-256 校验后独占发布；原文件保留两天。已发布后崩溃允许完成最小索引与审计修复；有完整 proof 的不确定任务经既有租约队列恢复，未知部分文件保留待核查。取消已验证但尚未发布的准备可以恢复原件并清理明确所属的槽位。
- 扫描与写回使用共同的持久冲突查询，移动等待运行中或待核查的写回。移动使旧路径的排队写回失效时，保留 MCP 失败结果。移动与写回共用恢复空间预算；到期清理必须再次验证新文件与旧备份，失败保留且延后重试。
- 跨能力复用的原子独占重命名、文件身份和属性复制移入业务中立基础设施；移动与标准写回调用同一实现。源节点观察与文件写回审计归 Library，事务与副作用顺序归 Metadata 应用用例。
- 真实 Python SDK 已通过直连与 `/books` 网关前缀完成标准写回预览、幂等提交、后台执行及 get_operation；OPF/EPUB/ComicInfo 查询开始返回真实可写字段。音频和 PDF 保持不可写声明，M6 待实现。
- 仍需 M6 完整格式与恢复验收、M3 已授权封面引用、M7 Web 配置与模板示例、M8 真实桌面客户端和最终矩阵。未发布，未操作真实书库。

验证：自动化能力集加架构约束 118 passed（随后扩展网关写回测试 2 passed）；写回、迁移、格式保真、文件目标、既有队列及架构定向集 96 passed；扫描/写回互斥、撤权、备份校验和恢复走真实存储与文件。当前暂存 Python 57 文件 Ruff 检查与格式检查通过，新增应用/存储/接线与受影响读取/队列文件定向 mypy 通过。未运行全仓回归，未将这些测试视为桌面客户端验收。

## M6：音频与 PDF 有限字段写回

- 锁定当前已安装并验证的 `mutagen==1.48.1`、`pypdf==6.14.2`，未升级其他依赖。参考 [Mutagen ID3 API](https://mutagen.readthedocs.io/en/latest/api/id3.html)、[MP4 API](https://mutagen.readthedocs.io/en/latest/api/mp4.html) 与 [pypdf 元数据说明](https://pypdf.readthedocs.io/en/6.7.3/user/metadata.html)，实际实现以本地固定版本源码和运行测试为准。
- MP3/M4A/M4B/FLAC 的本批可写字段明确限定标题、作者、简介，不将系列或资源序号误写入音轨编号。ID3 v2.3/v2.4 只替换选定帧，其余帧原字节保留；拒绝需要调整绝对章节字节偏移、ID3v1 共存和不支持的头结构。MP4 验证音轨结构、相对媒体块偏移、章节与未选标签；FLAC 验证未改块及编码流。
- PDF 明确限定 64 MiB、50,000 个克隆对象、100,000 对象编号上限；只写标题、作者、简介的 Info/XMP 映射。保留原文件修订，以固定版本增量写入和有界复制添加新修订，只允许 Info、XMP 和必要目录引用成为新增修订对象。签名/加密、无法安全解析或超限结构拒绝。
- 音频、PDF 复用同一预览/授权/准备/独占发布/备份/索引/队列恢复用例。准备空间保守计入每项 8 MiB 元数据增量；只读源文件在预览和准备阶段拒绝。查询按实际解析出的受支持结构返回可写字段。
- 94 项定向检查通过（真实 SDK/网关、文件读取、方案/执行、音频/PDF/发布及架构）；随后只读文件与空间不足等发布检查 10 passed。七个变更核心文件 mypy、Ruff 检查通过。音频测试通过 ffprobe 比较编码数据包 SHA-256、时间与章节；PDF 验证表单、附件、书签、页面、未知元数据与 Info/XMP，另有签名/加密输出前拒绝样本。
- 尚未完成全部 M8 异常矩阵、桌面客户端验收；持续保留但发生后续用户改动的恢复副本不会自动删除。以上不等于发布验收完成。
