# 二毛图书 MCP 接入：完整执行计划 v2（文件整理与双向元数据版）

> 后续决策（2026-09-22）：本计划中固定授权范围、令牌仅显示一次和额外 HTTP 授权要求已被用户的新计划取代。当前契约见 [ADR 0031](../architecture-decisions.md#自动化-mcp-接入)，使用说明见 [配置文档](../../examples/mcp/README.md)。


日期：2026-09-21  
仓库：GMD170629/ermao-library  
核对基线：develop / 7737f424c155174185810d71bee26e3151d24bb9  
状态：设计与 Codex 开发规格，尚未实现或运行验收。  
版本含义：v2 是本执行计划的修订号，不是二毛图书产品版本或 MCP 协议版本。

## 0. 修订生效与目标

本文件完整替代上一版《MCP 接入 v1》执行计划。用户已明确要求：本次同时开放图书文件移动、整理、标准格式元数据读写，以及系统元数据覆盖、更新。

删除旧计划中以下范围限制：
- “仅开放 12 个工具、3 个 scope”；
- “不开放源文件操作、标题/作者/简介覆盖”；
- “只能追加标签，受保护字段永远不可显式覆盖”；
- “所有操作都只是短数据库事务，无需持久化文件任务”。

仍然保留：外部 AI 客户端负责模型与决策；二毛图书只提供受控业务能力，不增加聊天、模型代理、通用 Agent、任意 Shell/SQL 或工作流引擎。

完整目标：

```text
用户创建受限授权 → AI 客户端连接 MCP → 查询图书、目录、元数据与格式能力
→ 修改系统元数据 / 从文件刷新 / 生成文件整理或写回方案
→ 执行已授权动作 → 查询逐项真实结果
→ 原 Web/App 能继续访问、阅读与同步 → 撤销授权后停止新的业务动作
```

本次的“标准格式元数据”分为两类，不能混称：
1. 文件内嵌元数据：EPUB 包内 OPF、漫画包内 ComicInfo.xml、音频标签、PDF 文档元数据等。
2. 伴随文件（sidecar）元数据：已有 OPF、目录 ComicInfo.xml 等。

“系统元数据更新”指二毛图书自身保存的图书/可读资源/目录展示元数据，不是升级软件版本或修改系统配置。

开发前记录实际 HEAD；若分支已变化，核对差异，不强制回退。用户未提交修改不得覆盖。执行时将本文件作为仓库 docs/plans/mcp-integration-v2.md 的单一规格；旧文件保留历史提示或加 superseded 指向，不能让两套冲突约束同时生效。

## 1. 服务与客户端决策

| 项目 | 本次决定 |
|---|---|
| 服务位置 | 集成现有 Python/FastAPI 后端、容器、统一网关和公开端口 |
| 外部入口 | `<用户服务地址><部署前缀>/api/mcp` |
| SDK | 官方 Python MCP SDK 当前稳定系列；本次官方文档为 v2，M0 核验并锁定具体发布版本 |
| 协议 | Streamable HTTP，使用 SDK 的标准实现，不手写 JSON-RPC/兼容协议 |
| 授权 | 手工配置的受限 Bearer Token；MCP 不回退 Cookie |
| 授权管理 | 继续使用当前 Web 登录会话，不对整个 REST API 开放自动化令牌 |
| 服务状态 | 默认关闭，管理员开启；新增危险能力不会自动授予旧令牌 |
| 用户客户端 | LM Studio 为本地模型主验收对象；Cursor 提供兼容模板；Python SDK 用于确定性测试 |
| OAuth | 本次不实现完整 OAuth 授权服务器；不宣称兼容仅支持 OAuth 的客户端 |
| 页面 | Web 设置中心新增“自动化授权”，普通用户管理本人授权，管理员额外控制服务和高风险能力 |
| 移动端 | 不新增原生 MCP 配置页，但必须验证移动/写回后既有阅读与资源接口不失效 |
| 任务形态 | 使用现有领域队列/可恢复操作，返回 operation_id；不要求客户端支持实验性 MCP Tasks |
| Skill | 可后续增强业务策略，不作为 MCP 接入前置条件 |

MCP 的传输请求不是文件任务寿命。已持久化且获准执行的操作不因 AI 客户端断开而丢失；客户端断开也不能被当成取消。服务重启后依据操作记录恢复，不依赖内存任务。

## 2. 当前代码证据与复用策略

本次是静态核对，以下不是端到端测试结论：

| 已核对入口 | 当前事实 | 本次处理 |
|---|---|---|
| modules/metadata/infrastructure/file_writeback.py | 当前 writer 写 OPF sidecar；目录使用 metadata.opf，文件使用同 stem .opf；不改源图书容器 | 复用并补齐显式字段写回、冲突与多文件发布；不能冒充已支持内嵌写回 |
| modules/metadata/application/writeback.py | 存在不可变元数据快照、来源版本、持久化写回意图和幂等摘要 | 复用投影/任务结构，增加目标格式、字段选择、授权来源及恢复边界 |
| services/metadata_file_writeback.py | 已存在写回准备、执行和中断恢复相关入口 | M0 完整审计 worker 和恢复，避免新建平行写回系统 |
| modules/library/application/request_mutations.py | BookRecordMutation、BulkBookMutation、MetadataApplyMutation 等可携带 writeback_intents | 必须隔离“只改数据库”与“允许文件写回”的副作用 |
| modules/library/application/commands/manage_source_tree.py | RelocateLibraryRoot 校验并更新配置中的书库根路径，没有搬运实体文件 | 不能把这个入口当作文件移动实现；核验其余能力，缺失时新增领域移动服务 |
| modules/library/application/bulk_operations.py | 已有标签、书架成员及批量业务命令 | 继续复用；补齐 scope 和幂等，不复制实现 |
| modules/library/application/metadata_ownership.py | 已有字段所有权/保护，包括刻意清空值 | 默认保留；新增受限显式覆盖，而非无条件绕过 |
| core/authorization.py | 有管理员书库可见性放行路径 | 自动化身份必须叠加令牌库范围，不可继承全库 bypass |
| modules/shelf/application/commands.py | 部分命令自行提交事务且存在整体成员替换 | 保留事务边界语义；增量操作不得删除令牌看不到的其他成员 |
| scripts/unified-http-gateway.mjs | /api 路由和部署前缀已存在 | 用真实外部入口验证，不只验证内部 Python 端口 |

当前 OPF writer 的准备路径还会处理封面文件；不能直接调用 prepare_writeback 来实现“无副作用预览”。M0 必须追踪这个细节。现有“准备”“发布”名字并不自动保证其中没有落盘副作用。

## 3. 能力范围与工具契约

### 3.1 保留的 12 个工具

| 工具 | 用途 | scope |
|---|---|---|
| get_context | 版本、有效权限、范围、格式能力摘要、上限和业务规则 | library:read |
| list_libraries | 授权书库，不返回 NAS 绝对路径 | library:read |
| search_books | 复用现有搜索/筛选和分页 | library:read |
| get_books | 必要元数据与版本号、Book/Resource 关联摘要 | library:read |
| list_facets | 范围内标签、作者、系列及计数 | library:read |
| list_shelves | 本人书架及授权范围内摘要/计数 | library:read |
| get_shelf | 本人书架详情和授权范围内成员分页 | library:read |
| create_shelf | 本人静态书架 | shelves:write |
| add_shelf_books | 增量添加成员 | shelves:write |
| remove_shelf_books | 增量移除明确成员 | shelves:write |
| add_book_tags | 追加标签，不替换其他标签 | tags:write |
| remove_book_tags | 移除指定关系，不删全局标签 | tags:write |

### 3.2 本次新增 11 个工具（总数 23）

| 工具 | 用途 | 主要权限/约束 |
|---|---|---|
| list_source_nodes | 分页查询指定书库/目录下的源节点、相对位置、类型与可操作性 | files:read；仅书库根内 |
| get_metadata_schema | 返回 Book/Resource/Node 字段、可空性、保护信息、已实现格式与可写字段 | library:read；文件细节需 files:read |
| read_file_metadata | 从明确资源的内嵌或伴随元数据读取候选值，与系统值比较 | files:read；不是任意文件内容读取 |
| update_metadata | 修改/补全/清空/覆盖系统保存的指定字段，默认不写文件 | metadata:write；改标签另需 tags:write；受保护字段另需 metadata:override |
| refresh_metadata | 从明确指定的本地内嵌/伴随来源刷新系统元数据 | files:read + metadata:write，其他字段权限同上 |
| plan_file_operations | 生成明确文件/目录移动、重命名、按模板整理清单 | files:read + files:move；纯预览，不落业务文件 |
| execute_file_operations | 执行已有不可变文件方案，返回 operation_id | files:move，重新校验范围和前置版本 |
| plan_metadata_writeback | 生成内嵌/伴随元数据字段差异和目标文件清单 | files:read + metadata:writeback |
| execute_metadata_writeback | 执行固定写回方案，返回 operation_id | metadata:writeback，重新校验文件状态/格式 |
| get_operation | 查询本人授权产生的任务及逐项结果 | 当前授权及当前数据范围；不能作为任意任务查看器 |
| cancel_operation | 请求停止尚未开始的项目；进行中项目在安全点停止 | 当前操作所有权和对应写 scope；不承诺自动撤销已成功部分 |

工具名为设计契约。命名若需遵从仓库约定，记录映射；不要拆成几十个几乎相同工具。get_operation/cancel_operation 只能访问该授权创建的操作；管理员 Web 恢复入口复用既有会话权限，并独立审计。

### 3.3 本次纳入的文件动作

- 书库内文件或完整图书目录移动。
- 同一目录下重命名，实际通过文件移动领域用例执行。
- 明确授权的跨书库移动，包括跨挂载点复制校验后迁移。
- 按限定命名模板整理成具体路径清单；允许创建必要目标目录。
- 同步搬运明确关联的 .opf、封面、ComicInfo.xml 等伴随文件。
- 整体移动图片漫画目录/有声书目录；不把资源中的单页或单音轨当成独立图书随意拆开。
- 目录内部或多卷册层级调整，必须满足现有组织模式和书籍归属规则；不能通过“整理”隐式合并/拆分 Book 身份。

第一版不提供永久删书工具、任意文件上传/下载、任意根目录浏览、修改容器挂载/系统根配置、格式转换、DRM 绕过、任意 URL 抓取或脚本执行。移动成功后的源文件清理属于该次移动事务的限定步骤，不等于授予通用删除权限。

智能书架创建/规则编辑、书架集合、阅读状态修改继续不包含；本次扩展集中于用户明确提出的文件与元数据管理。

## 4. 授权与配置界面

### 4.1 八个固定 scope

| scope | UI 文案 | 可授权身份 |
|---|---|---|
| library:read | 查看图书和个人书架 | 有对应库访问权的用户 |
| shelves:write | 创建书架、增删成员 | 同上 |
| tags:write | 增删图书标签（共享数据） | 当前系统管理者 |
| files:read | 查看书库目录与文件元数据 | 当前系统管理者 |
| files:move | 移动、重命名、整理源文件 | 当前系统管理者 |
| metadata:write | 更新系统元数据 | 当前系统管理者 |
| metadata:override | 覆盖明确选定的人工保护字段 | 当前系统管理者，显式勾选 |
| metadata:writeback | 写入标准伴随文件或图书内嵌元数据 | 当前系统管理者，显式勾选 |

所有写 scope 需要 library:read。files:move/metadata:writeback 还需要 files:read。metadata:override 不是独立写入口，必须与目标动作权限同时满足。update_metadata/refresh_metadata 涉及 tags 时仍检查 tags:write，不能绕过增删标签工具的权限。

有效权限 = 用户当前权限 ∩ 令牌固定 scope ∩ 部署启用能力。
有效书库 = 用户当前访问范围 ∩ 授权创建时明确选定的书库 ID。

文件写回授权附带 `writeback_targets = [sidecar, embedded]` 子选项；只选 sidecar 的令牌不能修改原始 EPUB/CBZ/PDF/音频容器。文件移动授权附带 `allow_cross_library`（默认 false）；启用后仍必须同时授权源库和目标库。两项均由 UI 设置，不允许工具请求自行扩大。

操作授权不等于操作系统权限：书库以只读卷挂载时必须明确报告 READ_ONLY_SOURCE，不能尝试 chmod、提权或修改 Docker 配置。

旧令牌、新增权限默认缺省即禁用，不能迁移为“全权管理”。库全选只选当前 ID，不涵盖未来新增书库。

### 4.2 只改数据库不能顺带写文件

这是本次门禁：
- update_metadata、add/remove_book_tags 默认只更新系统业务数据。
- 不得因全局“自动写回”设置而隐式入队文件写回。
- 显式写文件只能走 writeback 工具或同等经过授权的业务入口；旧 Web 手工编辑的既有行为不必因此改变。
- 服务端在用例入口决定 side-effect policy，透传到写回意图生成点，不接受模型传入可信授权标志。
- 若现有修改链路不能抑制附带写回，应先最小改造该边界，不允许先带越权副作用发布。
- worker 必须保留 grant_id、user_id、范围/版本上下文，不能退回系统管理员身份无条件执行旧快照。

### 4.3 授权生命周期与网络

沿用旧版高熵 token（至少 32 字节随机 secret）、摘要存储、只显示一次、30/90/365 天有效期、默认只读、过期/撤销、本人授权列表和明确库范围。scope/库范围不原地扩大；扩权新建授权，再撤销旧授权。

授权管理继续使用 Cookie 会话并验证 Origin/CSRF；MCP 仅接收 Bearer，不在缺失或无效时回退 Cookie。自动化 token 不可调用普通 REST 用户管理、授权创建等接口。

传输使用 SDK，验证合法 Origin/Host 和代理信任；桌面合法无 Origin 可用，不关闭 DNS rebinding 防护。正常部署推荐 HTTPS，非回环 HTTP 仅管理员显式允许并提示风险。凭证不进 URL/二维码/日志，敏感响应 no-store。不得缓存跨授权 tools/list、结果或任务内容。

get_operation/回执重放重新校验当前权限；一旦失去目标数据权限，不得借历史日志获取该数据。

### 4.4 Web 页面修改

沿用 `/settings/automation`、SettingsCenterShell、现有暖白与红色视觉、导航和国际化；属于用户设置，管理员显示更多能力。不新增聊天或模型管理。

创建授权分组：

```text
基础访问
  ☑ 查看图书和个人书架
  ☐ 创建书架、增删成员

系统元数据
  ☐ 增删图书标签
  ☐ 更新系统元数据
  ☐ 允许覆盖人工保护字段

源文件
  ☐ 查看目录和文件元数据
  ☐ 移动、重命名与整理文件
      ☐ 允许跨已授权书库移动
  ☐ 写入标准元数据
      ☐ OPF / ComicInfo 等伴随文件
      ☐ EPUB / CBZ / 音频 / PDF 等已支持内嵌格式

书库范围 [明确多选]     有效期 [90 天]
```

危险项默认关闭；摘要用自然语言说明“将修改真实文件”“覆盖共享元数据”“人工保护覆盖”和“跨库移动可能改变其他用户可见性”。不是只显示技术 scope 名。

创建成功当次可复制真实凭证配置；离开后清除内存，之后只能展示占位符。不能用 localStorage 保存明文。模板 URL 可由用户编辑，但不让后端据此执行任意 URL 探测。

新增“操作记录”轻量区域，复用现有任务/日志展示：动作、目标数量、已完成/失败/待处理、当前阶段、是否仍保留源副本、诊断编号、取消/恢复处理说明。禁止伪造连接人数或将最近使用称为在线。

不要求每次文件操作跳回 Web 审批。用户勾选权限后，AI 客户端可连续执行 plan → execute。客户端仍应在范围模糊或破坏性覆盖时向用户说明，但这不替代服务端授权。

## 5. 系统元数据：补全、覆盖与刷新

### 5.1 对象和字段

按现有模型分别处理 `book`、`resource`、`source_node`，不将文件、卷册、图书当成同一目标。通过 schema 返回真实可编辑字段、当前值、保护状态、可空性和 expected_revision。

字段范围以当前 Web 编辑用例为基线：
- Book：标题、作者、简介、标签、系列及序号等已存在字段。
- Resource：标题、简介、出版信息、语言、ISBN/identifier、讲述者、资源序号等已存在字段。
- SourceNode：当前确实存在的目录展示元数据；parent/path/library_id/物理类型不属于元数据字段。
- 封面只引用系统已有、已授权的封面 asset/ref；不接受任意 NAS 路径或外链。若当前缺少安全引用接口，M0 明确最小补齐，不新增任意下载代理。

不存在的字段拒绝，不为模型虚构评分、分类枚举或业务对象。

### 5.2 更新语义

`update_metadata` 接受逐项变更，每项包括 target_type、target_id、expected_revision、mode、fields、clear_fields 和必要的 override_fields；请求有 request_id。

| 模式 | 行为 |
|---|---|
| fill_missing | 仅填未受保护的空字段；人工刻意清空仍视为保护，不自动填回 |
| patch | 仅改明确 fields；遗漏键不清空；非空值可以按明确请求覆盖 |
| clear_fields | 清空单独点名且允许为空的字段；不把未传字段理解为清空 |
| override_fields | 在满足 metadata:override 时允许覆盖列出的保护字段；未列出保护字段仍不变 |

禁止无约束 `force=true`、任意字段 setattr 或全对象替换。覆盖人工保护后也不自动解锁该字段，更不能放宽其他字段的扫描保护。

服务端记录改前/改后值、作用字段、用户与 grant 来源；是否将本次显式修改标记为人工所有权，按现有手动编辑语义固定并测试。不能另起一套与扫描互相覆盖的“AI 元数据真相”。

expected_revision 用实体/元数据专用版本，不用会被阅读心跳更新的无关时间戳制造冲突。有并发修改时返回 CONFLICT，不静默覆盖。

### 5.3 元数据刷新方向

三条链路明确分开：

```text
update_metadata：客户端给出的字段 → 系统数据库
refresh_metadata：指定的内嵌/伴随元数据 → 系统数据库
writeback：系统中已确认的明确版本/字段 → 指定文件目标
```

read_file_metadata 不修改数据库，不创建识别任务；refresh_metadata 明确 source=embedded/sidecar、字段清单和 mode，不做隐式“多来源取最后一个”。来源冲突返回差异，不静默猜测。

本次 refresh 的必交付来源是本地文件；不顺带增加联网模型调用或新的在线刮削器。若后续暴露现有在线识别，需要单独告知网络访问与权限，不将其隐藏在本地刷新里。

## 6. 标准格式元数据读写

### 6.1 本次格式矩阵

下表是本次开发目标，不是当前已实现能力声明。每行必须有真实 writer、读取验证及内容保真测试后才能在 MCP capability 中标为 writable。

| 目标 | 本次交付 | 边界 |
|---|---|---|
| OPF sidecar | 读写文件同 stem .opf、目录 metadata.opf，复用现有投影 | OPF/DC 及系统现有扩展；不将系统扩展宣传为所有阅读器通用 |
| EPUB 2/3 | 读取并更新容器内真实 package metadata | 经 container.xml 定位 OPF；保持 manifest/spine/正文/导航，更新必要规范字段 |
| CBZ/漫画 ZIP | 读取并写入归档内 ComicInfo.xml | 仅已识别漫画资源；保留页图、顺序和未修改信息 |
| 图片漫画目录 | 读写目录 ComicInfo.xml，及原有 OPF 目标 | 两种写入目标显式选择，不能暗中互相覆盖 |
| MP3 | 读写已支持的 ID3 标签 | 不改音频帧、章节等无关数据 |
| M4A/M4B | 读写 MP4 音频元数据 | 不转码，不破坏音轨/章节 |
| FLAC | 读写 Vorbis comment 等已映射字段 | 保留音频流及未修改块 |
| PDF | 读写有限、明示映射的文档信息/XMP | 完整保留页面、书签、附件、表单和其他未改对象，签名/不支持加密拒绝 |
| TXT、MOBI/AZW/AZW3、CBR 等 | 系统元数据及已支持 OPF sidecar；本次不强行内嵌写入 | 明确 reported unsupported，不自动转格式，也不假装写入原容器 |

必须先做 OPF、EPUB、ComicInfo 核心批次，再做音频/PDF，各子批次独立验证。不能只因当前有读取库就声称能安全写入。解析出的格式、实际权限和 reader/writer 能力共同决定 writable。

### 6.2 字段映射

writer 只修改本次选择的字段。对每种格式公布 supported_fields、field_mapping、限制、可清空性以及 unsupported_fields；要求不支持字段时预检返回，不静默丢弃。

EPUB/DC：title、creator（作者角色）、description、subject、language、publisher、date、identifier 等按标准映射；系列等按已选择的规范/扩展说明，不宣称跨软件完全一致。

ComicInfo：Title/Series/Number/Summary/Writer/Tags 等使用所锁定的 schema 版本实际支持字段；不能因为有一个通用“author”就抹掉 Penciller/Inker 等其他作者角色。保留 Pages、阅读方向、未知但合法扩展和未修改字段。

音频：Book 与各音轨字段分开，不能把整本书序号覆盖为每个 track number。保留未修改标签、封面/章节，字符编码及多值映射有往返测试。

PDF：分别处理 Info 和 XMP，避免修改一个后另一个仍旧造成读取冲突。不把系列/有声书讲述者等无对应标准字段悄悄放到不相干字段。

### 6.3 写回方向与文件覆盖

`plan_metadata_writeback` 明确 target=sidecar/embedded、resource_ids、fields、system_revision、write_mode=fill_missing/overwrite_selected、clear_fields。不能仅传 Book ID 就自动覆盖它下面的全部版本。

写回是“已固定的系统字段 → 文件”；直接从 AI 传入任意 XML/二进制内容改文件不开放。用户希望改内容时先 update_metadata，再写回所选字段。

覆盖文件中的已有标准字段由明确 write_mode 控制，与覆盖数据库人工保护是两回事。文件覆盖不自动获得 metadata:override；数据库覆盖也不自动获得 metadata:writeback。

已有 sidecar 无法解析时，不静默重建并抹掉原文件，返回冲突/损坏原因并保留原件；覆盖原 sidecar 同样需要明确方案和恢复点。

同 stem 多格式（例如 Book.epub、Book.pdf 共用 Book.opf）必须查清作用范围。不能在仅选一个资源时写入共用 sidecar 并声称只影响该资源。目录级 metadata.opf/ComicInfo.xml 的归属也必须明确。

### 6.4 保真与发布

1. 在同目标文件系统的临时文件上写入，不原地截断源容器。
2. 写前固定源指纹/系统字段版本，执行前及发布前再校验；有变化不覆盖。
3. 保留已有容器中未修改条目的语义及内容，不能用“重新导出整本书”替代局部元数据编辑。
4. EPUB：检查容器规则、metadata、manifest、spine、资源可定位；不改变包唯一标识从而破坏字体混淆等关联。EPUB 签名、DRM 和不支持的加密明确拒绝；不能看到 encryption.xml 就未经区分地认定所有加密机制均同类。
5. ComicInfo：XML 解析禁外部实体/网络；ZIP entry 路径、重复 entry、解压炸弹有边界；图片数据哈希不变，页序不变。
6. 音频/PDF：使用所选稳定库实际支持能力，独立读取验证且比较未修改音频/文档内容；不能只检查文件能打开。
7. 原件恢复点必须在覆盖发布前可靠保留，空间不足不能先覆盖再报错。硬链接不能被当作允许原地编辑时可靠的独立备份。
8. 临时文件验证成功后再执行平台支持的原子替换；这仅是单文件发布，不等于数据库与多个文件原子提交。
9. OPF、封面和其他关联产物分别记录阶段；预览不复制封面，不创建目标目录，不覆盖已存在文件。
10. 只读卷、不可保真格式、复杂签名/encryption、空间不足、目标正在变化应明确返回，不强行成功。

系统字段只改标题时，不应重新写入全部作者/标识符/封面。M0 需特别检查当前 OPF writer 的全字段投影是否会意外清空未选字段。

## 7. 文件移动与整理

### 7.1 受限路径，而不是任意 filesystem MCP

源对象通过 source_node_id 指定；目标通过已授权 library_id、目标目录节点或根内 relative_path 指定。模型不传可信绝对路径，不选择备份/临时目录。

拒绝路径穿越、绝对路径、盘符/UNC、嵌入分隔符的文件名、NUL、设备/FIFO/socket、祖先/子孙循环移动、同一批的父子重复目标。检查 Unicode 归一化、大小写不敏感冲突、保留名称与长度；不静默把冲突改名为不可预期值。

仅能访问应用实际配置并挂载的书库根。源与目标均校验归属、当前令牌、操作系统可写性；目标未授权即拒绝。不能为了跨库移动自动给令牌或其他用户追加库权限。

符号链接/挂载点/硬链接场景必须有明确策略。保护不能只靠一次 resolve().relative_to()；执行/发布时要重新核对父目录和对象身份，使用平台可用的 dir_fd/no-follow 等机制。无法保证路径安全的部署路径拒绝执行，不声称防护成立。

同目录多硬链接源修改需提示 link_count 及 replacement 语义；默认不对不明关联内容原地编辑。目录树里越界 symlink/挂载点不递归跟随。

### 7.2 方案清单

plan_file_operations 支持两种有限输入：
- 明确移动清单：节点 → 目标库/相对目录/文件名；
- 固定模板整理：明确目标集合 + 已允许占位符，如 author/title/resource_title/index/ext。

模板只做数据格式化与文件名清洗，不执行 Python/Jinja/JS 或正则替换脚本。AI 自行构造的复杂布局也必须展开成明确移动项，再由服务端检查现有组织模式。

方案返回并持久化：plan_id、作者/grant、过期时间、源实体版本/指纹、每项源目标相对位置、伴随文件清单、必要建目录动作、碰撞、字节规模、同盘/跨盘、资源归属影响、可见性影响、恢复策略、blocking_errors。

默认方案 15 分钟有效（可按部署配置调整）。计划保存到数据库不算业务文件变更；预览不得写临时源文件、移动文件、触发扫描或生成封面。

execute 只能接收 plan_id + request_id，不能在执行时替换路径/模板/目标列表。变化则重新生成计划。plan_id 是被冻结的操作内容，不是用户批准证明。

### 7.3 授权与人工确认

已获得 files:move 的客户端可自动连续调用 plan 和 execute，不强制每次在 Web 点确认。授权授予时的文件操作提示和客户端明确用户意图共同构成使用流程；安全边界由服务端限制。

跨书库还须 allow_cross_library=true，且计划包含源目标库。预览说明书库权限变化可能让其他用户看到/失去该书；不能修改那些用户的 ACL 来维持旧可见性。

### 7.4 同文件系统与跨文件系统

同文件系统优先使用不可覆盖目标的安全 rename；大小写变更/目录重排需要明确中间步骤和日志。目标已存在时默认拒绝，不能把 metadata overwrite 权限当作覆盖其他图书文件的权限。

跨文件系统固定顺序：

```text
记录意图并取得目标/源资源排他权
→ 冻结并检查源文件/伴随文件清单
→ 复制到目标盘临时位置（有界内存）
→ 刷盘、校验目标内容及源未变化
→ 发布目标，记载 FILES_PUBLISHED
→ 短事务更新 node/path/library、资源引用、操作阶段
→ 再校验源身份，清理或暂存源副本
→ 更新状态并恢复扫描
```

源文件删除必须晚于目标内容验证和目录/数据库阶段可恢复。目标失败、磁盘满、权限变化时保留源。文件系统复制可能无法完整保留 owner/ACL/xattr，必须检测并报告，不能只调用 copy2 就宣称全部属性保留。需要保留的权限无法满足时阻断，不能提权绕过。

不能只写 `shutil.move()` 然后更新数据库并宣称原子、安全、可恢复。rename 与跨盘 copy/delete 的故障阶段不同；M4 必须分别测试。

### 7.5 保持书库身份与阅读状态

迁移应保持既有 Book/Resource/Asset/SourceNode 的稳定业务标识（在现有模型允许保持身份的操作中）。不能靠删除源记录、重新导入来“实现移动”，否则既有阅读和书架关联无法得到保证。

目标结构必须符合现有文件组织模式。会产生 Book 合并/拆分或资源归属变化的操作，不静默处理：本次先拒绝并说明，不伪造“任意布局完美兼容”。授权的完整 Book/目录单元跨库移动需原位更新关联 library_id、路径及所有现有引用。

数据更新覆盖：节点相对路径/父节点、资源/资产指向、关联 sidecar、扫描检查点、已排队旧路径任务、缓存引用。逻辑 ID 保持；底层 inode 在跨盘时可变化，不要求物理 inode 恒定。

阅读缓存按实际内容/元数据版本失效，但不重置阅读进度、书签或用户书架关联。跨库后用户访问由新库权限决定。存在活跃读取时采用明确 reader lease/busy 或保留旧已打开文件策略，禁止页面与资源引用混用新旧版本。

## 8. 文件任务的可恢复性与并发

### 8.1 一套领域操作记录，不造工作流平台

优先扩展已有 metadata writeback operation/targets 与现有任务机制。缺少移动记录时新增最小领域操作及 targets 表，不为 MCP 做平行通用队列。

至少记录：operation_id、plan_id、grant/user、request_id、规范化参数摘要、目标 ID、源/目标库、前置版本、阶段、恢复点/备份引用、每项结果、错误诊断、取消请求、时间。绝对路径仅内部受控记录，MCP 不返回。

阶段建议：PLANNED → QUEUED → PREPARING → FILES_PUBLISHED → INDEX_UPDATED → COMPLETED；分支 FAILED / PARTIAL / CANCELLED / RECOVERY_REQUIRED。允许符合当前队列的命名，但要能区别“目标文件已发布”和“索引已提交”。

操作返回 `accepted` 不等于成功。多目标失败要逐项报告；权限和输入预检发现非法项时不开始整个请求。运行中 I/O 失败可能部分完成，不能宣称跨文件全局事务。

### 8.2 幂等与短事务

所有写工具使用 request_id；同 grant 同 key 同参数返回原操作/回执，同 key 异参拒绝。相同 key 在进程重启和并发时仍去重。不能使用 JSON-RPC request id 作为业务 key。

纯数据库动作：业务变更与成功回执同事务。
文件动作：业务意图/入队与 request_id 关联同事务，先持久化再做 I/O；文件发布与数据库更新不可能靠一笔 SQL 事务包住，使用阶段日志、备份/校验和可恢复步骤。

禁止持有 SQLite 写锁等待文件复制、模型、外部网络、长时间 XML/ZIP 重写。日志/last_used 的失败不能把已提交动作伪装成失败并诱发重复。

### 8.3 扫描和写回协调

同资源或重叠子树的文件移动、sidecar/内嵌写回、扫描导入需要共享冲突边界。只给 MCP 添加一把锁、扫描 worker 不理会它，不算解决。

使用现有或最小可持久化 lease/reservation；多进程环境必须有效，不能仅内存 asyncio.Lock。扫描延迟冲突范围、忽略受控临时/备份目录，操作完成后做局部 reconcile，而不是触发全库重建。

移动中的旧路径写回任务必须暂停、重绑定或失效；不能在新路径完成后又写出旧 .opf。恢复孤儿临时文件时识别活跃操作，不能按文件年龄直接清掉正在执行的大文件任务。

外部 SMB/其他进程写文件并不受应用锁控制，所以复制/发布前后仍要校验源身份和版本。有不可消解变化时停止，不能靠拿到应用锁假定文件未变化。

### 8.4 取消、撤销授权、重启

排队任务每次开始及关键发布/清理前检查用户与 grant 当前权限。令牌过期/撤销后不再启动新的目标操作。

进行中的单项达到安全点后停止。取消不是恢复旧版本，已经成功项不自动撤回；返回 completed/skipped/cancelled/recovery_required 的实际数量。

若文件已发布后权限撤销，不能为了遵守“立即停止”把库留在永久坏状态。只允许内部恢复程序完成已授权动作的最小一致性收尾或回退，不能扩大目标或继续新项；记录 recovery 原因和 actor。

服务重启后根据源/目标/恢复点指纹和持久化阶段重建状态。恢复失败不应升级为主服务启动失败，不应无限扫描全部大库；隔离并标记 RECOVERY_REQUIRED。

恢复点有容量配额、保留期和清理规则；活跃/未解决任务的唯一恢复副本不得自动清除。只恢复版本仍匹配的具体目标，不能用整库快照覆盖用户后续修改。不承诺任意操作永久可撤销，本次不新增通用 undo MCP 工具。

## 9. 配置模板、示例代码与说明

### 9.1 客户端连接方式保持不变

```json
{
  "mcpServers": {
    "ermao-library": {
      "url": "https://YOUR_LIBRARY_HOST/api/mcp",
      "headers": {
        "Authorization": "Bearer REPLACE_WITH_YOUR_TOKEN"
      }
    }
  }
}
```

LM Studio 使用经过官方文档和实际版本验证的字段。Cursor 可单独提供 `${env:ERMAO_MCP_TOKEN}` 的 headers 模板，但不能把一个客户端的变量语法强加给另一个。合并配置时保留其他服务，不覆盖完整配置文件。

新增能力由 token 及工具发现控制，用户不安装第二个“文件 MCP”，不需要把 NAS 文件挂载到 AI 客户端。模型只得到查询结果，文件 I/O 在二毛图书主机发生。

### 9.2 本次须交付的代码

```text
examples/mcp/README.md
examples/mcp/lm-studio.example.json
examples/mcp/cursor.example.json
examples/mcp/.env.example
examples/mcp/smoke_read.py
examples/mcp/create_shelf_example.py
examples/mcp/update_metadata_example.py
examples/mcp/move_books_example.py
examples/mcp/writeback_metadata_example.py
```

smoke 默认只读。所有写示例默认仅查询/预览，明确 `--execute`、指定目标及 `--request-id` 才可执行。移动/写回示例先生成真实服务端计划、展示范围，再执行该 plan 并查询完成状态。

update 示例展示填缺、覆盖普通字段、显式清空；保护覆盖单独示例及权限错误，不鼓励全库 force。文件脚本不得自动选择所有图书，不因超时生成新 key 重跑。

代码使用锁定 SDK，类型提示、配置校验、超时和错误退出码齐全。不得声称本计划内 JSON 片段本身是已运行的客户端实现；Codex 必须实现和运行这些脚本。

### 9.3 用户帮助内容

文档覆盖：服务开启、授权创建、客户端配置、实际支持版本、权限范围、库间可见性变化、只读挂载、sidecar vs embedded、系统字段 vs 文件字段、保护覆盖、格式限制、部分失败、取消与恢复、存储空间、备份保留、request_id 重试、部署前缀/TLS/localhost/容器网络和凭证泄露排查。

不得宣传“所有元数据标准都完全兼容”“所有格式都能安全重写”“MCP 保证本地推理”或“任何移动都瞬间原子完成”。

自然语言示例：

```text
只修改这两本书在二毛图书中的标题，不写 OPF，也不改源文件。
读取这本 EPUB 内嵌的作者，与系统作者比较，不做修改。
将系统中已确认的标题和作者写回这本 EPUB，不改正文和其他字段。
把选定漫画目录移到已授权的目标书库，先列出所有文件和伴随文件的移动清单。
按作者/书名整理这些图书；存在同名目标或会合并图书身份的项不要执行。
用我指定的值覆盖这本书受保护的简介，仅覆盖简介，不解锁其他字段。
```

## 10. 开发落点和范围控制

- MCP/auth 仍放 automation 模块及其 bootstrap，不复制 books/shelves/tags 实体表。
- 系统元数据修改放原 library/metadata 用例，MCP 只做可信上下文传递和调用适配。
- 标准 writers 放 metadata 模块，与 Web/队列可复用，格式分发是固定注册映射，不建设插件市场。
- 文件整理放 library 的有限 file operation 领域用例，不让 MCP 层直接任意 os/shutil 操作。
- 只为可靠执行所需新增最小计划/操作目标记录，不引入通用 DAG、审批引擎、事件溯源平台。
- 现有恢复、调度、锁、诊断可用则复用；不足时只补已验明的缺口，不重构全部导入系统。
- 测试只针对新能力及受影响旧路径；不用海量与目标无关的测试基础设施替代实际交付。

建议仓库文档：docs/plans/mcp-integration-v2.md、docs/integrations/mcp.md、docs/integrations/mcp-metadata-formats.md。工具/schema/权限/帮助尽量共享轻量定义，避免手工维护互相矛盾的多套字段。

## 11. Codex 分阶段执行计划

### M0：重新冻结范围与能力映射

任务：读 AGENTS.md/模块/发布规范，记录 HEAD 和工作树；冻结 23 工具、8 scope、格式矩阵；核对 SDK 生命周期；逐条定位现有编辑、写回、扫描和文件操作；区分已实现、可复用但缺防护、新增能力。

必须查明：DB 修改是否自动生成写回、当前 OPF 覆盖和封面准备副作用、目录层级/身份规则、worker 授权和恢复、移动是否真实搬文件、事务/队列所有权、标注/阅读的稳定 ID 关联。

验收：一份能力映射及真实代码路径；不把读取支持当写入支持、不把 root relocate 当搬运；完整 v2 入库且旧限制失效；SDK 最小接入真实运行。

提交建议：docs(mcp): expand scope to file operations and metadata writes

提示词：
```text
执行 M0，用户已明确扩展文件与元数据能力。本次用 v2 计划替代 v1，
不继续引用旧的只读源文件、仅 12 工具/3 scope 限制。
核实每条能力的代码和副作用；特别检查系统元数据更新是否自动写 OPF。
核对文件身份、组织模式、扫描、writeback、事务与授权链，记录最小缺口。
只固定契约并完成 SDK 探针，不预先创建大框架，不修改生产数据。
```

### M1：授权与副作用边界

任务：八个 scope、库范围、sidecar/embedded 子选项、跨库选项、token 生命周期、会话管理接口、服务开关；有效范围必须限制管理员；提供可信 execution policy 传递机制。

验收：旧令牌不扩权；DB-only 权限即使遇全局自动写回也不写文件；protected override 无单独权限拒绝；跨库源目标均授权；普通用户无法获得文件写；worker 不能丢失授权来源。

提交建议：feat(automation): add scoped file and metadata permissions

提示词：
```text
执行 M1。沿用原授权设计，扩为文档八个 scope 和两个固定子选项。
认证只对 MCP 生效，管理仍用会话；管理员 token 也受库范围限制。
禁止 metadata:write 隐式产生文件写入，副作用策略必须在应用层执行。
实现受保护字段显式覆盖权限，不使用 force=true 或模型提供的可信身份。
补 scope 交叉、旧令牌、撤销、只读挂载与自动写回越权测试。
```

### M2：传输、只读发现与原有整理工具

任务：官方 SDK、/api/mcp、get_context/schema、目录与文件元数据只读、原有查询、静态书架和标签工具；文件能力按 grant 和真实格式过滤。继续完善原有五个写工具幂等。

验收：经网关/部署前缀读取；无任何 sidecar/临时文件/目录预览副作用；目录、嵌套成员、计数、任务结果无范围外泄露；标签仅改系统不写文件；Web 可读回。

提交建议：feat(mcp): expose scoped catalog and file metadata tools

提示词：
```text
执行 M2，先打通真实传输和只读/基础写工具。
目录查询只返回库内相对位置和节点 ID；read_file_metadata 只读不入队。
能力发现只声明已经实现并可用的格式，不能仅按扩展名宣称 writable。
原书架/标签命令继续复用，所有查询、统计和回执均验证有效范围。
通过真实统一网关验证，不只测内部函数。
```

### M3：系统元数据更新与本地刷新

任务：update_metadata、refresh_metadata；Book/Resource/Node 的真实字段；填缺/patch/显式清空/保护覆盖；字段来源、版本检查、request_id 和改前改后记录。

验收：同字段并发冲突；未传字段不清空；人工空值默认保留；只覆盖点名保护字段；系统更新不修改任何业务文件；本地文件刷新方向明确；扫描不立即冲掉已确认变更。

提交建议：feat(metadata): add scoped patches and explicit protected overrides

提示词：
```text
执行 M3。开放系统元数据覆盖和更新，但不修改结构字段、ID 或 NAS 路径。
实现 fill_missing、patch、clear_fields、override_fields，配合真实版本号。
受保护字段只有 scope 和具体 override_fields 同时满足才可改，覆盖后不自动解锁。
refresh 只从指定本地来源读取，不能自动调用模型/外网。
证明所有 DB-only 请求没有 OPF、封面、文件任务副作用。
```

### M4：文件移动/重命名/模板整理

任务：plan/execute_file_operations、任务查询/取消、持久化阶段和扫描协调；同盘、跨盘、跨授权书库、必要建目录、伴随文件、冲突与身份保留。

验收：预览纯净；旧版本/目标碰撞拒绝；移动后 ID/进度/书架关联保留；越界 symlink/路径穿越失败；跨盘校验后才清理源；断电阶段可恢复；任务失败不退出主服务。

可分两个提交：同盘及领域阶段、跨盘及扫描恢复。不得用“文件改动大”理由把整个能力退回后续版本。

提交建议：feat(library): add recoverable scoped source relocation

提示词：
```text
执行 M4，新增真实文件移动，不复用仅改根路径配置的 RelocateLibraryRoot 冒充。
plan 固定明细和版本；execute 只执行该计划，无须用户每次跳 Web 确认。
同盘和跨盘分别实现，原件在目标验证及状态可恢复前不得删除。
保持 Book/Resource/Asset/Node 身份；无法保持身份的合并拆分行为明确拒绝。
扫描、写回和移动使用共同冲突边界，日志要跨进程、跨重启有效。
故障注入验证每个发布阶段，不使用删库重扫或单次 shutil.move 代替实现。
```

### M5：OPF、EPUB、ComicInfo 标准写回

任务：plan/execute_metadata_writeback；复用既有队列；扩展实际格式 writer；选择字段、标准映射、保护原件、版本冲突、共用 sidecar、完整读回。

验收：OPF 预览不写封面；只改选定字段；EPUB/CBZ 内容和页序不变；源变化不覆盖；复用 sidecar 冲突可识别；临时发布中断后可恢复；DB 与文件状态不冒称原子一致。

可按 OPF、EPUB、ComicInfo 三个子提交推进，每个子提交完成格式样本回归。

提交建议：feat(metadata): add selective sidecar epub and comicinfo writeback

提示词：
```text
执行 M5。当前 OPF sidecar writer 是复用基础，不是 EPUB/CBZ 内嵌支持的证据。
实现真正的包内元数据编辑，不能重新导出整本书抹掉正文结构和扩展。
写入字段由固定方案决定，未知字段/无法解析 sidecar/共用目标不能静默覆盖。
先保留恢复点、写临时文件、独立验证，再发布并更新任务阶段。
用内容哈希/结构和独立读取验证，不以文件能打开或函数无异常作为验收。
```

### M6：音频与 PDF 写回、完整恢复边界

任务：MP3/M4A/M4B/FLAC/PDF 的本次有限标准字段映射、输入限制、保真写入和读回；扩展资源忙/空间不足/不可支持文件/副本保留测试。

验收：音频帧/章节/时长等不被不相关改动破坏；PDF 页结构、书签/表单/附件等保留，Info/XMP 一致；签名和不支持加密拒绝；不支持格式返回真实 capability，不作隐式转换。

提交建议：feat(metadata): add validated audio and pdf metadata adapters

提示词：
```text
执行 M6，将音频与 PDF 纳入同一操作流程，每种格式独立适配和验收。
复用现有依赖但检查具体版本 API，不为支持标签而转码、栅格化或重建正文。
对不支持的签名/加密/复杂结构明确拒绝，错误不能修改原文件。
矩阵中已承诺的标准样本必须通过；未通过行是发布阻塞，不能仅隐藏工具后称全部完成。
记录真正支持字段和限制，不宣传任意格式完全兼容。
```

### M7：完整授权 UI、任务状态、模板与示例

任务：设置页分组权限、风险文案、一次性 token、模板复制下载、状态、格式说明、操作记录/取消；补三份新写示例及原有代码。

验收：普通用户不出现可用文件写权限；DB-only/sidecar-only/embedded 分别正确；含凭证导出明确提示；计划显示实际文件、字节、跨库影响；任务接收不是成功；JSON/代码可解析运行，默认不写。

提交建议：feat(web): expose file automation setup and operation results

提示词：
```text
执行 M7，沿用二毛图书现有设置样式，不做 AI 仪表盘。
权限按基础/系统元数据/源文件分组，默认只读，高风险权限单独勾选。
配置接入方式不变，新增能力由授权和 tools/list 决定，不让用户配置第二个服务。
代码示例默认预览，执行要求明确目标、request_id 和 --execute。
实现逐项任务状态、部分失败与取消说明，凭证只显示一次且不持久化到浏览器。
```

### M8：联合验收、真实客户端与部署

任务：从 Web 创建授权到真实客户端调用、系统/文件读回、重启恢复、撤销；运行下一节门禁及受影响业务回归；核验 SDK/writer 依赖、数据库迁移、只读挂载和更新包交付。

验收：报告实际命令、版本、commit 和通过/失败/未执行；隔离数据、真实网关/前缀；未测试客户端不得称已验证；未改原生端不重建全部平台，但关键 reader 行为要回归。

提交建议：test(mcp): verify file and metadata automation end to end

提示词：
```text
执行 M8，不再扩展功能。完成页面授权→客户端发现→系统修改/文件迁移/标准写回
→直接文件读取和 Web/API 阅读验证→重启/撤销后的行为。
包含失败阶段和跨库权限，不以模型回复成功代替结果。
迁移与依赖按仓库发布规范核验，未经授权不发布、不推镜像、不操作生产图书。
保留未验证事实，输出完整交付报告和必要阻塞。
```

## 12. 验收矩阵（在旧版 24 项基础上重整）

使用隔离书库 L1/L2/L3、管理员/普通用户、多个授权、静态书架、多版本图书、目录漫画/有声书、小型各格式固定样本。跨盘测试使用两个真实测试文件系统或可靠 EXDEV 注入，两者分别说明。测试覆盖有界样本，不跑生产全库。

| 编号 | 场景 | 通过标准 |
|---|---|---|
| A01 | 服务关闭/维护状态 | MCP 不绕过边界，原服务正常 |
| A02 | Cookie 有效、token 无效 | MCP 仍认证失败 |
| A03 | 普通用户伪造文件/元数据高权限 | 创建和调用都拒绝 |
| A04 | 管理员 token 只授权 L1 | L2 的内容/统计/路径/错误信息均不泄露 |
| A05 | 写操作混入未授权目标 | 预检整批拒绝，无业务文件/DB 变更 |
| A06 | 旧 token 或新增书库 | 不自动获得新权限/范围 |
| A07 | 授权撤销/过期/权限降级 | 新调用及未开始任务停止，历史结果重新授权 |
| A08 | scope 与自动写回副作用 | DB-only 更新不生成 sidecar、封面或文件任务 |
| A09 | 只授权 sidecar | embedded 执行拒绝 |
| A10 | 只授权文件写回 | 不能覆盖系统保护字段或修改结构 |
| A11 | 同 key 同参并发/断线/重启 | 只产生同一个业务操作/回执 |
| A12 | 同 key 异参/旧计划重放 | 冲突，不能替换已固定目标 |
| A13 | fill_missing/patch/clear | 语义明确，未指定字段不变 |
| A14 | 人工保护/人工空值 | 默认不改；有权限且逐字段指定才覆盖 |
| A15 | 覆盖保护字段后再扫描 | 已确认结果及其他保护不被破坏 |
| A16 | 元数据并发修改 | expected_revision 冲突，不能丢用户修改 |
| A17 | 本地刷新来源冲突 | 明确来源和差异，不隐式调用外网 |
| A18 | Book 多个 Resource | 写回只作用明确选择资源，不误改所有版本 |
| A19 | 预览文件移动/写回 | 无源文件、封面、目录创建、扫描副作用 |
| A20 | 同盘文件与目录移动 | 实际位置正确，稳定 ID/进度/书架保留 |
| A21 | 跨盘移动校验 | 目标内容验证成功前源不清理 |
| A22 | 跨库无目标权限/无跨库选项 | 拒绝，不扩权 |
| A23 | 跨库可见性 | 用新库 ACL 访问，不泄露其他用户数据，不修改 ACL |
| A24 | 路径穿越/绝对路径/符号链接竞态 | 无根外访问，失败不造成外部变更 |
| A25 | 同名/大小写/父子重叠/目录循环 | 明确冲突，不覆盖其他书 |
| A26 | 伴随文件与同 stem 冲突 | 不遗失关联，不写错共享 OPF |
| A27 | 只读挂载/空间不足/权限不足 | 不提权，原件完好，状态明确 |
| A28 | 扫描与移动并发 | 无重复 Book、旧路径重建或阅读状态丢失 |
| A29 | 移动与旧写回任务冲突 | 暂停/重绑定/拒绝，不写回旧位置 |
| A30 | OPF 选择字段覆盖 | 未选字段和合法扩展保留，损坏原件不被静默重建 |
| A31 | EPUB 包内元数据 | 目标值读回正确，正文/manifest/spine/导航保持 |
| A32 | CBZ/ComicInfo | 图像哈希、页序和未改 XML 信息保持 |
| A33 | 图片目录 ComicInfo | 目录内图片不变，sidecar 归属正确 |
| A34 | MP3/M4A/M4B/FLAC | 标签正确，音频/章节等无关内容保持 |
| A35 | PDF | Info/XMP 正确，页/书签/附件/表单等保留 |
| A36 | DRM/签名/不支持格式 | 拒绝且原件不变，不隐式转格式 |
| A37 | 发布前源/系统字段版本变化 | 冲突，不覆盖较新值 |
| A38 | 临时写、发布后 DB 未更新等故障点 | 重启正确恢复或标记待恢复，无静默丢失 |
| A39 | 两阶段多文件部分失败 | 返回逐项真实结果，不称全局原子成功 |
| A40 | 取消/撤销发生在执行中 | 安全点停止；已完成项如实保留；必要内部恢复受限 |
| A41 | 恢复副本配额/清理 | 不删除唯一恢复点或活跃临时文件 |
| A42 | 恢复失败 | 不导致主服务反复启动退出 |
| A43 | 读取缓存/活跃阅读 | 不混用新旧资源，不重置进度；busy 行为明确 |
| A44 | 网关/前缀/Origin/Host | 正常连接且安全限制生效，无 HTML/错误跳转 |
| A45 | UI scope 分组/风险/一次性 token | 前后端一致，无浏览器持久明文/日志泄露 |
| A46 | Python 示例/模板 | 实际运行，默认无写，执行固定计划并查询真实结果 |
| A47 | 真实 LM Studio/兼容客户端 | 记录真实版本与模型；未运行不标通过 |
| A48 | 原有 Web/App/OPDS/批量操作 | 相关回归通过，系统数据与文件可直接核验 |

批量体量上限是可调安全参数，不是性能宣称：初始查询 20/最多 50；元数据批次 20；文件计划最多 100 个顶层目标，并另限实际展开的文件数/总字节。M0 固定展开上限；不能只按顶层目录数量绕过限制。计划摘要截断要明确并提供分页，不默认返回全文或成千上万个路径。

## 13. 可直接粘贴给 Codex 的总控提示词

```text
本次二毛图书 MCP 开发范围已经扩展，请用
 docs/plans/mcp-integration-v2.md
完整替换上一版仅标签/静态书架的实施约束。

最终目标：外部 AI 客户端和本地模型通过 /api/mcp，使用用户创建的受限授权，
查询书库、管理书架/标签、更新和覆盖系统元数据、从本地元数据刷新，
以及执行真实的文件移动/重命名/模板整理、OPF/ComicInfo 伴随文件与
EPUB/CBZ/音频/PDF 支持格式的内嵌元数据写回。

必须执行：
1. 先读规范和实际 HEAD，不覆盖工作树，不擅自发版或操作生产书库。
2. 按 v2 的 M0–M8 顺序推进，每批验证、独立 commit，失败先修当前阶段。
3. 一共 23 个工具、8 个固定 scope；配置 UI 同步提供文件、系统元数据、保护覆盖权限。
4. 原有查询/书架/标签/编辑/写回/扫描基础尽量复用，不建立第二套业务真相。
5. 当前 OPF sidecar 写回不是内嵌格式写回；RelocateLibraryRoot 不是实体文件搬运。
6. metadata:write 不自动拥有文件副作用；普通更新不能因全局自动写回而越权。
7. 文件读取、移动、伴随/内嵌写回、人工保护覆盖分别控制；管理员 token 仍受库范围限制。
8. 覆盖是明确字段+前置版本；不提供全能 force，不将缺失字段清空。
9. 文件操作先生成固定方案再执行，允许已授权客户端连续调用，不强制 Web 人工审批。
10. 实现源/目标根内校验、同名冲突、sidecar 归属、稳定身份、扫描/写回协调。
11. 跨盘先复制并校验再清理源；原件覆盖前有恢复点，不原地破坏性重写。
12. 纯 DB 写与回执同事务；文件任务采用持久意图、阶段日志、短事务及恢复，
    不能把 SQL 事务宣称成覆盖文件系统的全局原子事务。
13. 所有写工具幂等；已排队任务在执行前/关键阶段重检授权；取消在安全点生效。
14. EPUB/漫画/音频/PDF 的内容、导航/章节/页面等未改数据必须验证保真。
15. 文档列为必交付的标准格式样本未通过是剩余阻塞，不隐藏能力就报全部完成。
16. 不支持格式/签名/加密明确拒绝，不能转格式或冒称 sidecar 就是原件内嵌。
17. 完整交付授权页面、配置模板、5 份可执行示例、格式矩阵与操作帮助。
18. 真实客户端、确定性协议/权限测试、文件内容测试分别报告；未测试就写未测试。
19. 不引入聊天、模型代理、通用工作流/审批、任意 Shell/SQL、永久删书或无关重构。
20. 原 native App 本次不加设置页，不因此全平台重建；关键 reader API 要回归。

最终报告包括：各阶段 commit；23 工具/scope 和实际能力矩阵；复用入口；新增依赖/迁移；
实际命令与通过/失败/未执行结果；每种格式真实样本；同盘/跨盘/故障恢复证据；
页面与模板/代码位置；客户端/SDK 版本；尚未通过的验收与发布阻塞。

完成标准不是返回计划、空页面或让模型说成功：必须能从页面授权出发，
通过真实网关和客户端完成系统数据修改、实体文件变更、内容读回与后续阅读，
并证明无权限、撤销、冲突和异常情况下不会越权或静默损坏数据。
```

## 14. 核验资料（执行时匹配版本）

仓库代码均按已核对 SHA 定位；实现前再核验最新分支。以下是参考入口，不是“已运行”的证明。

```text
# 当前核对的关键仓库文件
https://github.com/GMD170629/ermao-library/blob/7737f424c155174185810d71bee26e3151d24bb9/apps/api-python/app/modules/metadata/infrastructure/file_writeback.py
https://github.com/GMD170629/ermao-library/blob/7737f424c155174185810d71bee26e3151d24bb9/apps/api-python/app/modules/metadata/application/writeback.py
https://github.com/GMD170629/ermao-library/blob/7737f424c155174185810d71bee26e3151d24bb9/apps/api-python/app/modules/library/application/request_mutations.py
https://github.com/GMD170629/ermao-library/blob/7737f424c155174185810d71bee26e3151d24bb9/apps/api-python/app/modules/library/application/commands/manage_source_tree.py

# 官方协议/格式/库说明
https://py.sdk.modelcontextprotocol.io/
https://modelcontextprotocol.io/specification/latest/server/tools
https://modelcontextprotocol.io/specification/latest/basic/authorization
https://www.w3.org/TR/epub-33/
https://anansi-project.github.io/docs/comicinfo/documentation
https://anansi-project.github.io/docs/category/comicinfo
https://mutagen.readthedocs.io/en/latest/user/index.html
https://pypdf.readthedocs.io/en/stable/user/metadata.html
https://docs.python.org/3.11/library/shutil.html
https://lmstudio.ai/docs/app/mcp
https://cursor.com/docs/context/mcp
```

元数据规范之间的字段映射不是天然一一对应；外部格式的扩展字段、编码、多作者角色和多值必须逐种验证。读取支持、写入支持、容器保真和实际已测试客户端四种状态不得混写。
