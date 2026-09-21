# MCP v2 验收记录（2026-09-21）

实现范围见 [执行计划](../plans/mcp-integration-v2.md)，用法见 [模板与示例](../../examples/mcp/README.md)。M0–M7 已实现；M8 已完成下列自动化验证，**尚未全部验收通过**。真实桌面模型调用和部分组合场景仍缺证据，不能据此宣称最终发布通过。

## 环境与结果

- macOS arm64；Python 3.11.15；官方 MCP SDK 2.2.0、Mutagen 1.48.1、pypdf 6.14.2；临时 SQLite 和隔离样本文件。
- 跨盘使用实际挂载的独立 APFS 测试文件系统，包含复制、发布后中断、源备份后中断，测试结束卸载；不是仅模拟 EXDEV。Linux 平台未运行。
- 后端联合定向检查 **264 passed**。随后增加活跃 HTTP 读取和跨库进度断言，受影响测试 **16 passed**；两次结果有重叠，不相加。
- Web 桌面/窄屏 Chromium **6 passed**；类型检查、定向 ESLint、2279 条 zh-CN/en-US 消息检查通过。Node 22.15.0，仓库声明 22.23.1，工具链未更换。
- 最后变更的 11 个核心 Python 文件局部 Mypy 通过（follow-imports=silent），相关变更 Ruff 通过。架构/事务约束在联合定向集中通过。
- 所有写操作只针对临时书库。未发布、未替生产开启 MCP、未操作用户真实图书。没有运行全仓回归或原生 App 构建。

## 48 项证据矩阵

“已验证”仅指列出的实现路径和有界样本；“部分”明确标出尚未实测的组合，不以代码推断冒充运行证据。下表简写 A = `apps/api-python/tests/integration/modules/automation/`，M = `apps/api-python/tests/unit/modules/metadata/`，L = `apps/api-python/tests/unit/modules/library/`。

| 项目 | 状态 | 运行证据与具体边界 |
| --- | --- | --- |
| A01 服务关闭/维护 | 部分 | A/test_management_http.py 覆盖默认关闭及管理员开启；维护切换与正在执行文件任务的完整组合未实测。 |
| A02 Cookie 不替代 token | 已验证 | A/test_mcp_catalog.py、test_sdk_transport.py 的真实 SDK/HTTP 身份边界。 |
| A03 普通用户高权限伪造 | 已验证 | A/test_management_http.py、test_grants.py，创建及当前权限降级检查。 |
| A04 固定书库隔离 | 已验证 | A/test_mcp_catalog.py、test_file_reads.py、test_metadata_patches.py，范围过滤和混入外库目标拒绝。 |
| A05 整批授权预检 | 已验证 | A/test_metadata_patches.py、L/test_file_moves.py，未授权批次无写入/文件检查副作用。 |
| A06 不自动扩展权限 | 已验证 | A/test_grants.py，固定 grant 范围与当前账户交集。 |
| A07 撤销/过期/降级 | 已验证 | A/test_grants.py、test_move_execution.py、test_standard_write_execution.py、test_operation_management.py。 |
| A08 DB-only 无文件副作用 | 已验证 | A/test_metadata_side_effects.py、test_writes.py、test_cover_references.py；开启自动写回仍只改数据库。 |
| A09 sidecar/embedded 分权 | 已验证 | A/test_writeback_plans.py 与范围/目标类型校验；不通过 sidecar 授权调用 embedded。 |
| A10 文件授权不修改系统保护 | 已验证 | A/test_writeback_plans.py 的仅文件写权限预览/执行；test_metadata_patches.py 的独立 override 检查。 |
| A11 同 key 并发及重放 | 部分 | A/test_writes.py 真实并发重复创建、test_move_plans.py/test_writeback_plans.py 持久计划重放；每种写工具的网络断线并发组合未逐一实测。 |
| A12 异参/旧方案重放 | 已验证 | A/test_writes.py、test_writeback_plans.py，receipt 摘要冲突和冻结目标。 |
| A13 fill/patch/clear | 已验证 | A/test_metadata_patches.py、test_writeback_plans.py、M/test_selective_opf.py。 |
| A14 保护/人工空值 | 已验证 | A/test_metadata_patches.py、test_cover_references.py，逐字段权限、版本与人工保护。 |
| A15 覆盖后再扫描 | 部分 | 更新保留其他字段及保护状态已有检查；MCP override 后完整重扫同一本书的串联验收未运行。 |
| A16 元数据版本冲突 | 已验证 | A/test_metadata_patches.py 两个真实数据库会话；test_refresh.py 读取期间版本变化。 |
| A17 本地刷新来源 | 已验证 | A/test_file_reads.py、test_refresh.py，来源歧义明确拒绝、显式选择、不请求外网。 |
| A18 多 Resource 精确写回 | 部分 | A/test_metadata_patches.py 的资源字段归属及 test_writeback_plans.py 物理目标冲突已验；同书多个完整格式版本逐一写回的全组合未跑。 |
| A19 预览无文件写入 | 已验证 | A/test_move_plans.py、test_writeback_plans.py、M/test_standard_publication.py，对比前后目录与文件字节。 |
| A20 同盘移动保留身份 | 已验证 | A/test_move_plans.py 实际跨库目录移动，Book/Resource/Asset/SourceNode/书架及阅读进度位置、revision 保留。 |
| A21 跨盘完整校验 | 已验证 | A/test_cross_device_moves.py 独立 APFS 文件系统正常及两个中断变体，验证复制后保留恢复源。 |
| A22 跨库双端权限 | 已验证 | L/test_file_moves.py、A/test_move_execution.py，整批目标授权与禁止隐式资源换归属。 |
| A23 新库 ACL | 部分 | 实际移动后四类记录库归属已验证；不同普通账户移动前后读取同书的完整 HTTP 串联尚未运行。 |
| A24 路径/符号链接 | 已验证 | A/test_file_reads.py、L/test_file_moves.py，根锚定、绝对/穿越路径、源/父符号链接和身份变化拒绝。 |
| A25 冲突/大小写/重叠 | 已验证 | L/test_file_moves.py、A/test_move_execution.py，Unicode/大小写碰撞、独占目标和大小写中间槽恢复。 |
| A26 伴随文件/共享 OPF | 已验证 | L/test_move_companions.py，明确伴随列表、共享/同 stem 歧义拒绝。 |
| A27 只读/空间/权限 | 部分 | M/test_standard_publication.py 覆盖只读源和空间不足无输出；真实只读挂载、不同系统账户权限不足未实测。 |
| A28 扫描/移动并发 | 部分 | 持久冲突查询与扫描 claim 排斥已有验证，移动后稳定进度已验证；完整扫描器与逐文件移动同时执行的压力场景未运行。 |
| A29 旧写回冲突 | 已验证 | A/test_standard_write_execution.py、既有写回队列/claim 测试；恢复副本未清理时禁止移动相关节点。 |
| A30 OPF 保留未选字段 | 已验证 | M/test_selective_opf.py，扩展、角色和未知元数据保留；损坏原件不重建覆盖。 |
| A31 EPUB 正文/结构 | 已验证 | M/test_archive_writeback.py，EPUB 2/3 成员顺序、正文哈希及未选元数据保持。 |
| A32 CBZ/ComicInfo | 已验证 | M/test_archive_writeback.py，图像字节、ZIP 顺序、Pages 映射保持。 |
| A33 图片目录 sidecar | 部分 | ComicInfo 格式处理与 SourceNode 目标归属已覆盖；独立图片目录经 MCP 写回后逐图哈希端到端未运行。 |
| A34 音频四格式 | 已验证 | M/test_audio_writeback.py、A/test_file_reads.py，ffprobe 编码数据包 SHA-256/时间/章节、多作者读回、ID3v2.3 UTF-16 简介与未选帧。 |
| A35 PDF | 已验证 | M/test_pdf_writeback.py，Info/XMP 及页面、书签、表单、附件、未知元数据保持；增量写入不承诺擦除历史修订。 |
| A36 签名/加密/未知格式 | 已验证 | M/test_archive_writeback.py、test_pdf_writeback.py、test_audio_writeback.py，输出前拒绝且原件保留。 |
| A37 发布前版本变化 | 已验证 | M/test_standard_publication.py、A/test_refresh.py、test_move_execution.py，冻结文件/系统身份及发布前复核。 |
| A38 中断恢复 | 已验证 | A/test_move_execution.py、test_cross_device_moves.py、test_standard_write_execution.py，真实发布后中断；M/test_standard_publication.py 两步独占发布恢复。 |
| A39 多文件部分失败 | 部分 | 逐项持久结果及部分发布恢复实现已验；每种混合格式多目标故障组合尚未全部实测。 |
| A40 取消/执行中撤权 | 已验证 | A/test_move_execution.py、test_standard_write_execution.py、M/test_standard_publication.py，发布前复核、未发布撤销、已发布最小恢复。 |
| A41 恢复预算/清理 | 已验证 | A/test_move_plans.py、test_cross_device_moves.py、test_standard_write_execution.py，预算、变更后保留、验证后释放、受保护恢复位置。 |
| A42 恢复故障隔离 | 部分 | worker 独立会话/失败边界在阶段验证通过；完整主服务反复重启并注入所有恢复错误未运行。 |
| A43 活跃读取/缓存 | 部分 | M/test_standard_publication.py 真实 HTTP response 句柄：旧请求完整旧字节、旧版本新请求 412、新请求新版本；跨库进度保持。原生 App 活跃阅读未实测。 |
| A44 网关/前缀/Origin/Host | 已验证 | A/test_mcp_catalog.py 直连及 /books 网关、test_sdk_transport.py 错误 Host/Origin，test_management_http.py Cookie Origin。 |
| A45 Web 授权配置 | 已验证 | apps/web/e2e/automation-settings.spec.ts 六项桌面/窄屏检查，分组、一次性 token、显式导出、撤销、取消和英文普通用户；已查看截图。 |
| A46 示例/模板 | 已验证 | A/test_cli_examples.py 五个独立 CLI 经真实 HTTP/SDK/worker，默认预览、显式系统更新/移动/写回/书架创建与状态轮询。 |
| A47 真实桌面模型 | 阻塞 | 见下节，未把工具发现或 Python SDK 当作真实模型验收通过。 |
| A48 既有客户端相邻行为 | 部分 | Reader progress API、资源来源查询、OPDS、既有写回队列/claim 和架构约束通过；未做原生 App 真机、全 Web/批量操作全量回归。 |

## 桌面客户端实际结果

Cursor **3.20.21 arm64**，模型选择 **Cursor Grok 4.6 Medium**。仅在临时工作区连接临时 MCP，服务日志确认 initialize、tools/list、prompts/list、resources/list。发送查询/更新/移动/OPF 写回的验收指令后，Cursor 提示账户 usage limit，未发生 tools/call。未升级订阅或购买额度。配置方式参考 [Cursor MCP 文档](https://cursor.com/docs/mcp)。

LM Studio **0.4.24 build 1** 已安装，Apple 公证验证通过；首次启动在接受 [LM Studio 使用条款](https://lmstudio.ai/app-terms) 的页面停止。电脑操作工具要求接受法律条款前当次确认，已请求用户确认，尚未收到；没有点击接受、下载或运行模型。配置参考 [LM Studio MCP 文档](https://lmstudio.ai/docs/app/mcp)。

临时服务已停止，临时授权已撤销，包含令牌的 Cursor 配置已删除。后续桌面验收须重新创建隔离服务和凭证；不保留可用测试令牌。Web 测试服务器也已停止。

## 可复现命令

后端在 `apps/api-python` 运行：

```sh
uv run --extra dev --locked pytest tests/integration/modules/automation tests/unit/modules/metadata/test_audio_writeback.py tests/unit/modules/metadata/test_pdf_writeback.py tests/unit/modules/metadata/test_standard_publication.py tests/unit/modules/metadata/test_selective_opf.py tests/unit/modules/metadata/test_archive_writeback.py tests/unit/modules/library/test_file_moves.py tests/unit/modules/library/test_move_companions.py tests/test_metadata_writeback_queue.py tests/integration/modules/metadata/test_writeback_claims.py tests/test_capability_architecture.py tests/architecture/test_write_transaction_contract.py tests/contract/api/test_reader_v5_progress.py tests/contract/api/test_opds_http.py tests/integration/modules/reader/test_resource_source_queries.py -q
uv run --extra dev --locked pytest tests/unit/modules/metadata/test_standard_publication.py tests/integration/modules/automation/test_move_plans.py -q
```

Web 使用已有 Webpack 开发模式提供端口 3100，运行 `e2e/automation-settings.spec.ts`；不启动完整全仓回归。阶段记录保留历史检查结果，本记录的未验证项在取得新运行证据前不能改为通过。
