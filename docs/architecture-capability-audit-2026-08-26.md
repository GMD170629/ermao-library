# 当前代码能力面、文档与测试产物审计报告

> 审计日期：2026-08-26  
> 审计对象：工作树当前状态，基线提交 `6ac56642`，包含用户未提交改动  
> 审计方式：只读代码/依赖/文档检查，后端与 Web 可重复门禁，移动端静态与既有证据核验  
> 严重度：P0 阻断已声明核心闭环或越过已接受产品边界；P1 高概率造成错误交付、契约破坏或门禁失真；P2 结构债务、验证缺口或中风险错误；P3 低风险遗留与命名债务

## 1. 结论摘要

当前系统已经从横向技术目录迁出相当一部分代码，后端形成 15 个能力模块，Web 多数 Next 路由保持薄入口，Reader Core 保持框架无关，Book / ReadableResource / ResourceAsset 与 Reader v4 已成为主要实现方向。后端全量测试和 Web 静态门禁均通过。

但仓库尚不能被判定为符合 `AGENTS.md` 的目标结构或其 Definition of Done。主要原因不是测试数量不足，而是四类事实同时存在：

1. Mobile 的已声明 P0 产品闭环和范围边界有真实问题：Shelves 为空、Audio/Now Playing 缺失，并暴露了权威基线规定为 Web-only 的高风险系统管理；此外，在线可重排阅读仍可能被错误转入下载流程。
2. 权威文档互相覆盖但没有清除旧条款：离线授权、数据身份、Work Detail 管理范围、Reader 进度和旧路由状态均存在双重真相。
3. 能力目录已经建立，但后端 `presentation/bootstrap/services/models`、Web 全局 `fetch`/DOM 翻译器和 Mobile 根壳仍绕过能力边界。
4. 测试绿灯包含假阳性：架构测试漏掉 4 个后端能力，PWA E2E 全局屏蔽 Service Worker，i18n 检查不能识别语义损坏，Mobile smoke 只看到了空 Shelves 页的测试标签。

本次确认：

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| P0 | 3 | Mobile P0 闭环和产品范围阻断 |
| P1 | 15 | 契约、边界、门禁和文档权威性问题 |
| P2 | 11 | 结构债务、不可复核证据、不可达代码和体验缺口 |
| P3 | 3 | 兼容命名、重定向和低风险残留 |

## 2. 审计范围与可重复结果

### 2.1 覆盖范围

- 后端：`apps/api-python/app`、Alembic、Worker、后端测试与 CI。
- Web/PWA：`apps/web/app`、`features`、`components`、`lib`、i18n、Playwright、`packages/reader-core`。
- Mobile：KMP shared、Android、iOS、Reader、下载、Work Detail、导航、设置与设备验收产物。
- 文档：根 README、`AGENTS.md`、架构规范、ADR、Mobile Phase 1–7、Reader 架构、测试与设计 QA 产物。

### 2.2 实际执行

| 检查 | 结果 |
| --- | --- |
| 后端 `uv run --no-sync pytest -q` | `1062 passed, 1 warning`，333.97 秒 |
| Web `pnpm test` | `384 passed, 0 failed` |
| Web `pnpm typecheck` | 通过 |
| Web `pnpm lint` | 通过，`--max-warnings=0` |
| Web `pnpm i18n:check` | 通过，2054 条消息；但存在本报告 P1-05 的语义漏检 |
| Playwright 收集 | 192 项、7 文件；本次未运行浏览器 E2E |
| Markdown 本地链接扫描 | 未发现缺失目标；代码路径事实仍存在过时项 |
| Ruff / Mypy | 命令无法启动，项目环境未声明可执行依赖 |
| Android 设备门禁 | 当前 shell 无 `adb` 命令；未启动 AVD |
| iOS 设备门禁 | Xcode 26.6 可见一台 paired/available 物理设备；只读审计未安装或运行 App |

后端唯一警告来自 FastAPI TestClient 的 Starlette/httpx 弃用兼容。它不是业务失败，但应在升级计划中消除。

## 3. 能力面垂直切片结论

| 能力面 | 入口/交付 | 应用与领域 | 基础设施 | 当前判定 |
| --- | --- | --- | --- | --- |
| Library / Import | 后端能力路由已统一；Web/两端 Mobile 均有入口 | 新导入管线和部分 Library 规则已分层 | ORM 化程度高，但共享根 models 与跨能力 schema 仍多 | 半迁移；测试强，边界未闭合 |
| Reader / Publications / Media | Reader v4 为主；旧路由实际未注册 | Reader Core 和 Publication domain 较清晰 | Publications 深导 Library 私有 ORM；Web/Mobile adapter 复杂 | 主方向正确，契约文档冲突 |
| Auth / Session | Web、后端、Mobile 均有真实流程 | Mobile VerifiedSessionRecord 符合 ADR 0015 | 后端 bootstrap/presentation 仍做 ORM 与业务编排 | 半迁移 |
| Shelf | 后端与 Web 可用 | 后端有应用命令 | Mobile 两端一级页面为空 | Mobile P0 未交付 |
| Audio | Web 能力较完整 | shared 有类型 | Mobile 平台播放器、mini player、Now Playing 缺失 | Mobile P0 未交付 |
| Download | 后端、Web、Mobile 均有实现 | 本地工件和原格式策略总体正确 | Android 可重排在线入口仍可能强制下载 | 部分错误 |
| Metadata / Organize | 后端与 Web 可用 | 有部分命名用例 | 仍强依赖全局 services；Web UI 直接 fetch | 半迁移 |
| System / Backup / OPDS | 后端和 Web 可用 | Backup application 泄漏 SQLAlchemy | System/OPDS bootstrap 承担业务服务职责 | 边界弱 |
| Mobile Administration | 两端已有真实导航和大量实现 | KMP 有 typed repository | 产品基线仍规定 Web-only | 实现与权威范围冲突 |
| PWA / Offline | Web 有 SW、更新与离线页面 | 有纯规则测试 | E2E 禁用 SW，普通页面不写入 page cache | 验证缺口与文案错误 |

## 4. P0 发现

### P0-01 Mobile Shelves 一级能力在 Android 与 iOS 均为空壳

- Android 将 Shelves 导向空页面：[MainShell.kt](../apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/shell/MainShell.kt#L514)，实现仅为带测试标签的 `Box`：[MainShell.kt](../apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/shell/MainShell.kt#L925)。
- iOS Shelves 返回 `Color.clear`：[MainTabView.swift](../apps/mobile/iosApp/ErmaoLibrary/Features/Shell/MainTabView.swift#L286)。
- Phase 1 将静态书架、智能书架浏览和书架集合列为 P0：[mobile-app-phase-1-web-to-app-functional-baseline.md](mobile-app-phase-1-web-to-app-functional-baseline.md#L102)。
- Android smoke 只断言 `tab-shelves` 标签，因此空页面也通过：[AndroidShellSmokeTest.kt](../apps/mobile/androidApp/src/androidTest/kotlin/com/ermao/library/AndroidShellSmokeTest.kt#L139)。

影响：四个一级 Tab 中一个完全不可用，现有 smoke 产生完成假象。

### P0-02 Mobile P0 Audio / Mini Player / Now Playing 未实现

- shared 访问策略把 Audio 固定为不支持：[ReaderAccessPolicy.kt](../apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/downloads/domain/ReaderAccessPolicy.kt#L45)，测试将其锁定为 `READER_TYPE_NOT_SUPPORTED`：[ReaderAccessPolicyTest.kt](../apps/mobile/shared/src/commonTest/kotlin/com/ermao/library/shared/modules/downloads/domain/ReaderAccessPolicyTest.kt#L36)。
- iOS 支持矩阵同样令 audio 为 false：[DownloadModels.swift](../apps/mobile/iosApp/ErmaoLibrary/Features/Downloads/DownloadModels.swift#L208)。
- 仓库未发现 Android MediaSession 或 iOS AVAudio/MPNowPlaying 的正式生产链。
- Phase 1 明确要求全局 mini player、Now Playing、后台播放和系统控制：[mobile-app-phase-1-web-to-app-functional-baseline.md](mobile-app-phase-1-web-to-app-functional-baseline.md#L120)。

影响：有声书无法形成发现、播放、恢复的 P0 闭环。

### P0-03 Mobile 暴露了权威基线列为 Web-only 的高风险系统管理

- Phase 1 把用户、书库根、整理/元数据、OPDS、备份、健康和日志列为 Web-only：[mobile-app-phase-1-web-to-app-functional-baseline.md](mobile-app-phase-1-web-to-app-functional-baseline.md#L131)。根规范也保留相同限制：[AGENTS.md](../AGENTS.md#L520)。
- Android Me 打开 Administration：[MainShell.kt](../apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/shell/MainShell.kt#L523)，并注册真实用户、来源、导入、整理、备份、日志等路由：[MainShell.kt](../apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/shell/MainShell.kt#L643)。
- iOS Me 显示管理入口：[MeRootView.swift](../apps/mobile/iosApp/ErmaoLibrary/Features/Me/MeRootView.swift#L92)，主导航连接真实管理页面：[MainTabView.swift](../apps/mobile/iosApp/ErmaoLibrary/Features/Shell/MainTabView.swift#L414)。
- 较低层级的设计资产 README 声称“用户批准范围优先”：[Mobile Native Settings README](assets/mobile-app-settings-native-v1/README.md#L3)，但没有 Accepted ADR 或 Phase 1 修订，无法合法覆盖根规范。

影响：高风险、批量、可破坏操作面被扩大；产品范围、安全验收和实现互相矛盾。应先裁决产品范围，再决定关闭导航还是修订权威基线并补齐安全/恢复验收。

## 5. P1 发现

### P1-01 Python 静态质量门禁在干净依赖环境不可执行

- `dev` 依赖只有 pytest/httpx：[pyproject.toml](../apps/api-python/pyproject.toml#L30)。
- Mobile CI 却直接调用 locked Ruff/Mypy：[mobile.yml](../.github/workflows/mobile.yml#L91)。
- 本次 `uv run --no-sync ruff` 和 `mypy` 均返回 `Failed to spawn`；lock 中也没有 ruff、mypy、pytest-cov。
- fnOS 后端门禁仅运行 pytest：[fnos-package.yml](../.github/workflows/fnos-package.yml#L252)。

影响：目标规范中的 Ruff、Mypy、coverage 不是可复现的持续门禁，Mobile CI 静态步骤在干净 Runner 存在直接失败风险。

### P1-02 后端架构测试漏掉真实能力并固化例外

- `CAPABILITIES` 只列 11 项，漏掉 `backup/mobile/opds/publications`：[test_capability_architecture.py](../apps/api-python/tests/test_capability_architecture.py#L8)。
- presentation/public 边界检查基于不完整清单：[test_capability_architecture.py](../apps/api-python/tests/test_capability_architecture.py#L23)。
- 测试明确允许 Imports 深导 Library domain 私有文件：[test_capability_architecture.py](../apps/api-python/tests/test_capability_architecture.py#L631)。
- 未被守卫拦住的实例包括：`mobile.public` 导 infrastructure、`opds.public` 导 presentation、Publications 深导 Library ORM、Backup 深导 Shelf ORM、System presentation 深导 Backup application。

影响：架构专项测试全绿仍不能证明依赖方向正确。

### P1-03 后端 application、presentation 与 bootstrap 仍越层

- Backup application 直接携带 SQLAlchemy `Executable`：[restore.py](../apps/api-python/app/modules/backup/application/restore.py#L8)。
- Library presentation 内直接执行 ORM 查询：[views.py](../apps/api-python/app/modules/library/presentation/views.py#L70)。
- Auth presentation 仍执行 ORM 和业务规则：[users.py](../apps/api-python/app/modules/auth/presentation/users.py#L176)。
- Auth/System/OPDS bootstrap 不只是 wiring；例如 OPDS bootstrap 同时承担授权、目录查询、URL、进度与媒体适配：[opds.py](../apps/api-python/app/bootstrap/opds.py#L119)。

影响：同一用例分散在 application、presentation、bootstrap 和 services，HTTP/Worker/CLI 无法稳定复用同一应用边界。

### P1-04 跨能力私有 ORM/schema 导入已形成真实耦合

- Publications 导入 Library 私有 schema：[source_repository.py](../apps/api-python/app/modules/publications/infrastructure/source_repository.py#L11)、[navigation_cache.py](../apps/api-python/app/modules/publications/infrastructure/navigation_cache.py#L12)。
- Backup 导入 Shelf infrastructure model：[persistence.py](../apps/api-python/app/modules/backup/infrastructure/persistence.py#L72)。
- System presentation 导入 Backup 私有 application：[http.py](../apps/api-python/app/modules/system/presentation/http.py#L36)。

影响：Library/Shelf 内部 ORM 变更会破坏 Publication/Backup，违背跨能力只走 public/port/contract 的硬规则。

### P1-05 稳定后端错误缺少 code，英文目录同时存在语义损坏

- 通用 `fail()` 允许不传稳定 code：[responses.py](../apps/api-python/app/schemas/responses.py#L32)；能力模块存在大量无 code 调用。
- Kindle/SMTP/Download 的可预期错误直接返回中文 message，例如 [kindle/http.py](../apps/api-python/app/modules/kindle/presentation/http.py#L140)、[download/http.py](../apps/api-python/app/modules/download/presentation/http.py#L140)。
- 英文目录存在确认损坏：有声书启动错误 [en-US.json](../apps/web/i18n/messages/en-US.json#L425)、密码错误 [en-US.json](../apps/web/i18n/messages/en-US.json#L852)、密码重置 [en-US.json](../apps/web/i18n/messages/en-US.json#L860)、未保存书库 [en-US.json](../apps/web/i18n/messages/en-US.json#L1108)、登录服务错误 [en-US.json](../apps/web/i18n/messages/en-US.json#L1434) 被翻为无关的临时目录/同步文案。
- i18n 检查只检查 key、CJK 和 `{placeholder}`，不拒绝多余 `%s` 或语义污染：[generate-i18n-catalog.mjs](../apps/web/scripts/generate-i18n-catalog.mjs#L225)。

影响：英文用户会看到错误信息；客户端无法用稳定 code 判断失败；当前双语绿灯是误报。

### P1-06 Web 网络边界未落地，并依赖两套全局 fetch monkey-patch

- 不存在目标结构要求的 `apps/web/shared/api`。
- UI/page/provider 仍有大量直接 fetch；代表位置包括 [app-shell.tsx](../apps/web/components/layout/app-shell.tsx#L293)、[setup-page.tsx](../apps/web/features/settings/setup-page.tsx#L57)、[settings-page.tsx](../apps/web/features/settings/settings-page.tsx#L89)、[metadata-providers-panel.tsx](../apps/web/features/organize/metadata-providers-panel.tsx#L77)。
- 为兼容 basePath，根 layout 改写 `window.fetch`：[layout.tsx](../apps/web/app/layout.tsx#L14)；认证层再次改写：[auth-session.ts](../apps/web/lib/auth-session.ts#L46)。

影响：basePath、401、envelope、取消和响应验证依赖隐式全局加载顺序，Request/URL/string 行为不一致。

### P1-07 PWA E2E 全局禁用 Service Worker

- Playwright 配置设置 `serviceWorkers: 'block'`：[playwright.config.ts](../apps/web/playwright.config.ts#L10)。
- `responsive-pwa-shell.spec.ts` 因而不能证明 SW fetch、缓存、离线与升级生命周期。
- Service Worker 单测主要是源码字符串断言：[service-worker.test.ts](../apps/web/lib/pwa/service-worker.test.ts#L9)。

影响：PWA E2E 名称与实际覆盖范围不一致，无法作为发布期离线/更新证据。

### P1-08 i18n DOM 观察器可能改写用户提供的元数据

- Provider 遍历并改写 DOM 文本/属性：[provider.tsx](../apps/web/i18n/provider.tsx#L44)、[provider.tsx](../apps/web/i18n/provider.tsx#L167)。
- 只有 `data-i18n-skip` 能保护用户内容；部分书名/操作前后值未加保护：[library-batch-actions.tsx](../apps/web/features/library/library-batch-actions.tsx#L449)。

影响：当书名、作者或标签恰好等于目录 key 时，切换英文会篡改用户数据的显示，违反用户内容不翻译规则。

### P1-09 Mobile 可重排在线阅读仍可能被强制下载

- `Reflowable` 无条件返回 `NeedsDownload`：[ReaderAccessPolicy.kt](../apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/downloads/domain/ReaderAccessPolicy.kt#L36)。
- 生产 runtime 调用该策略：[DownloadsRuntime.kt](../apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/downloads/application/DownloadsRuntime.kt#L49)。
- Android 映射成 `DownloadRequired` 并进入下载准备：[DownloadActionsViewModel.kt](../apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/downloads/application/DownloadActionsViewModel.kt#L177)、[DownloadPreparationViewModel.kt](../apps/mobile/androidApp/src/main/kotlin/com/ermao/library/features/downloads/application/DownloadPreparationViewModel.kt#L105)。
- 当前真源明确要求阅读在线优先，下载是独立动作：[AGENTS.md](../AGENTS.md#L431)。

影响：在线点击 EPUB/MOBI/FB2/TXT 可能被错误转为完整下载。

### P1-10 Mobile 身份、Work Detail 管理范围和路由模型互相冲突

- ADR 0020 唯一身份为 Book/ReadableResource/ResourceAsset，并删除 Version：[ADR 0020](adr/0020-mobile-book-resource-asset-cutover.md#L18)。
- Phase 2 仍公开 `workId/volumeId/chapterId` 路由：[phase-2](mobile-app-phase-2-information-architecture.md#L579)。
- Phase 3 下载层级仍为 directory version → volume：[phase-3](mobile-app-phase-3-user-flows-and-wireframes.md#L294)。
- Phase 4 说 ADR 0020 关闭原生 Book Detail 管理：[phase-4](mobile-app-phase-4-visual-master.md#L275)，Phase 2 新修订又说管理入口跟随 Web：[phase-2](mobile-app-phase-2-information-architecture.md#L12)。

影响：实现、Fixture、深链和高风险动作没有单一真源。

### P1-11 ADR 0015 已废止离线 entitlement，但活跃模型和验收仍保留

> 处理状态（2026-08-26）：已解决。ADR 0015 现为 Mobile 会话恢复与 GET 失败的唯一真源；根规范、Phase 1/2/3/6/7 和 Stage 1/Phase 7/Reader 骀收已收口到 `VerifiedSessionRecord`、局部网络错误和分页保留。Shared、Android、iOS 已删除页面快照、stale 与 downloaded-only 模型，废止 ADR/方案和三张视觉资产已移除，并增加自动防回归检查。以下内容保留为原始审计发现。

- ADR 0015 明确无离线模式、30 天宽限和 GET 页面快照：[ADR 0015](adr/0015-mobile-v1-verified-session-without-offline-mode.md#L12)。
- 根规范仍写“401 后允许 30 天下载内容访问”：[AGENTS.md](../AGENTS.md#L511)。
- Phase 2 文件头说旧条款全部被取代，但正文仍定义已废止的离线授权结构：[phase-2](mobile-app-phase-2-information-architecture.md#L600)。
- Stage 1 验收仍要求写入和验证 30 天 entitlement：[mobile-stage-1-acceptance.md](testing/mobile-stage-1-acceptance.md#L141)。

影响：实现者可能重新引入已废止授权模型；当前代码实际采用 VerifiedSessionRecord，与根规范残留条款相反。

### P1-12 Reader 进度规范同时保留两套状态机

> 处理状态（2026-08-26）：已解决。Reader v4 架构现为唯一权威；Phase 1 已删除旧 outbox 状态机，Web 启动阻断选择已移除，三端统一采用确定性恢复、500ms debounce、revision 和 single-flight latest slot。以下内容保留为原始审计发现。

- Phase 1 仍要求约 1.5 秒 debounce、租约、clientSequence、compare-delete、quarantine：[phase-1](mobile-app-phase-1-web-to-app-functional-baseline.md#L236)。
- Reader 权威文档要求 500ms、v4 revision、single-flight latest slot：[mobile-reader-architecture.md](mobile-reader-architecture.md#L169)。
- 同一 Reader 文档一处禁止 local/cloud/cancel 阻断对话框：[mobile-reader-architecture.md](mobile-reader-architecture.md#L193)，另一处测试要求仍保留该 decision：[mobile-reader-architecture.md](mobile-reader-architecture.md#L264)。

影响：客户端可能实现不兼容的同步/冲突行为。

### P1-13 旧 Reader 路由的 404/410 契约冲突

- Reader 架构声称 v1–v3 返回 410：[mobile-reader-architecture.md](mobile-reader-architecture.md#L117)。
- 当前测试明确要求 v2/v3 未注册并返回 404：[test_reader_v4.py](../apps/api-python/tests/test_reader_v4.py#L1188)、[test_reader_v4.py](../apps/api-python/tests/test_reader_v4.py#L1679)。
- ADR 0019 也采用未注册 404；历史 API 审计仍把 v1/v2 的 410、v3 的 200 当事实。
- 手工验收仍以 Reader V2 为发布门槛：[manual-acceptance.md](manual-acceptance.md#L12)。

影响：客户端升级判断、运维排障和契约测试会选择不同语义。

### P1-14 Mobile/PWA 验收产物使用了被新政策降级的证据

- Mobile P2 记录写“Android accepted”：[mobile-reader-p2-format-acceptance.md](testing/mobile-reader-p2-format-acceptance.md#L4)，实际仅使用 `emulator-5554`：[同文件](testing/mobile-reader-p2-format-acceptance.md#L34)。
- 当前根政策规定 emulator 只能补充，不能替代物理 Android：[AGENTS.md](../AGENTS.md#L452)。
- Mobile CI 正式 job 仍命名并运行 emulator smoke：[mobile.yml](../.github/workflows/mobile.yml#L189)。

影响：历史 AVD 结果可能被误当当前 Android release acceptance。

### P1-15 数据库迁移权威文档与验证矩阵过时

- Runtime 文档仍称 Alembic head 为 `0002_library_scan_queue_uniqueness`：[python-backend-runtime.md](python-backend-runtime.md#L29)。
- 实际 head 为 `0004_remove_media_kind`，测试也这样断言：[test_sqlite_database.py](../apps/api-python/tests/test_sqlite_database.py#L321)。
- `0004` 和 fresh baseline 均不可 downgrade：[0004_remove_media_kind.py](../apps/api-python/app/db/alembic/versions/0004_remove_media_kind.py#L19)、[0001 baseline](../apps/api-python/app/db/alembic/versions/0001_library_topology_baseline.py#L2220)。
- 现有测试主要从 0001 一次升 head，缺 0002/0003 单独路径、中途失败和正式回滚策略证据。

影响：部署/回滚人员会按错误 head 工作，数据库前进迁移与应用回滚的关系没有完整证明。

## 6. P2 发现

### P2-01 后端全局 `services/` 与根 `models/` 仍是主要耦合面

`app/services` 仍有 21 个模块；API 生命周期和 Worker 直接依赖 queue、metadata、organize services：[main.py](../apps/api-python/app/main.py#L38)、[worker/main.py](../apps/api-python/app/worker/main.py#L34)。能力目录已经存在，但事务、模型所有权和运行时编排仍横向共享。

### P2-02 兼容代码缺少 owner 与可验证退出条件

- Download DTO 仍提供并被 presentation 使用的 `to_legacy_dict()`：[dto.py](../apps/api-python/app/modules/download/application/dto.py#L24)。
- Metadata worker owner 仍名为 `metadata-lookup-compat`：[metadata_lookup_queue.py](../apps/api-python/app/services/metadata_lookup_queue.py#L75)。
- Library scan 仍从旧毫秒键回退到新分钟键：[library_scan_schedule.py](../apps/api-python/app/modules/imports/domain/library_scan_schedule.py#L33)。

### P2-03 Web feature 公共边界不完整

13 个 feature 中 6 个没有 `public.ts`。跨能力私有导入包括 Books 直取 Reader 私有规则：[chapter-reading-state.ts](../apps/web/features/books/chapter-reading-state.ts#L1)，Settings 直取 Import Tasks、Management、Organize 内部页面：[library-import-settings-page.tsx](../apps/web/features/settings/center/library-import-settings-page.tsx#L6)、[organize-settings-page.tsx](../apps/web/features/settings/center/organize-settings-page.tsx#L5)。

### P2-04 Web 外部输入仍有 unchecked cast、non-null assertion 和 Hooks 局部绕过

- Metadata provider 直接 `response.json() as ProvidersResponse` 并使用 non-null assertion：[metadata-providers-panel.tsx](../apps/web/features/organize/metadata-providers-panel.tsx#L139)。
- Users/permissions 把未验证 payload 直接 cast：[users-permissions-page.tsx](../apps/web/features/settings/center/users-permissions-page.tsx#L73)。
- 同文件局部禁用 `react-hooks/exhaustive-deps`：[users-permissions-page.tsx](../apps/web/features/settings/center/users-permissions-page.tsx#L136)。

### P2-05 PWA 离线页面的承诺与实际缓存/重试不符

- `networkFirstPage` 不把成功普通页面写入 cache；预缓存主要是 offline/login/setup：[sw.js](../apps/web/public/sw.js#L26)、[sw.js](../apps/web/public/sw.js#L162)。
- 离线页宣称可查看已缓存页面：[offline/page.tsx](../apps/web/app/offline/page.tsx#L19)。
- “重新检测网络”又链接到 `/offline`：[offline/page.tsx](../apps/web/app/offline/page.tsx#L24)。

影响：普通 Library/Book 页面并不满足文案承诺，联网恢复也不会重试原 URL。

### P2-06 Web 存在生产不可达或仅测试引用的代码岛

静态 import graph 未发现生产入口的代表包括 `components/book/book-card.tsx`、`features/books/application/use-resource-wall-selection.ts`、`features/books/local-reader-progress.ts`；另有只被测试引用的 structure/resource helpers 与 `lib/comic-preload.ts`。这些测试可能保护的是退役实现，不是当前用户路径。

### P2-07 Mobile 仍保留不可达缓存与旧 Book Detail 合同

- shared 曾保留 Home/Books/Grouping/Facet/Detail 页面缓存仓储但未发现生产消费者；该文件已随 P1-11 删除。
- shared 仍公开旧 `LibraryContract.bookDetail`：[public.kt](../apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/library/public.kt#L24)。

### P2-08 Mobile 根壳和 Work Detail 仍承担多能力编排

Android `MainShell.kt` 同时负责 composition、权限、跨 feature route 和页面装配；`WorkDetailScreen.kt` 约 2984 行并深导 work-management 私有实现。iOS `MainTabView.swift` 同时负责四 Tab、Reader 启动和管理控制台。问题依据是状态/依赖所有权混杂，不是单纯行数。

### P2-09 文档“当前状态”已严重过时

- 分层文档仍以已删除的 `compat.py` 和 `worker/importer.py` 为当前 P0：[business-code-layering-and-refactoring.md](business-code-layering-and-refactoring.md#L31)。
- 同文档仍记录 62 个后端文件、342 tests 和 182 Web tests；当前后端 app 有 446 个 Python 文件、1062 tests，Web 有 384 tests。
- 测试策略仍称后端 1161 项且 6 个收集错误：[test-execution-policy.md](testing/test-execution-policy.md#L5)。
- Phase 1 证据索引仍引用不存在的 `features/library/api/works.ts`、`features/works/`、`features/reader/v4/`：[phase-1](mobile-app-phase-1-web-to-app-functional-baseline.md#L361)。

### P2-10 测试产物不可独立复核

- 2026-08-11 全 API 审计把原始证据只放在 `/tmp`：[full API audit README](testing/full-api-audit-2026-08-11/README.md#L51)；本次检查这些目录均不存在。
- 2026-08-26 Mobile 完整格式记录引用多个 `.xcresult`：[full-format acceptance](testing/mobile-reader-full-format-acceptance-2026-08-26.md#L81)，仓库内未找到这些 bundle。
- build tree 的 JVM XML 未绑定 commit SHA 或 dirty tree hash，不能证明当前工作树。

### P2-11 公共 README 与隔离 POC 仍表达旧系统事实

- 中英文 README 仍把 Work/Version/Volume 当当前结构，并称原生 Reader 仍在建设：[README.md](../README.md#L5)、[README.en.md](../README.en.md#L5)。
- Readium Web POC 仍在 workspace 中；其 README 说 exact 要求 hash/parser/normalization 相同：[POC README](../apps/readium-web-poc/README.md#L49)，当前 Reader 架构则规定这些字段仅为诊断、不得拒绝进度：[mobile-reader-architecture.md](mobile-reader-architecture.md#L42)。

## 7. P3 发现

### P3-01 不可达兼容 re-export

`app/services/health.py` 仅 re-export `run_system_health_checks`，全仓未发现生产或测试导入：[health.py](../apps/api-python/app/services/health.py#L1)。确认无外部 Python 插件依赖后可删除。

### P3-02 Reader v3 命名仍承载 v4 正式实现

Web v4 页面从 `v3/reader-v3-page` re-export，Reader 下大量生产文件仍在 `v3/`，E2E selector 也保留 `data-reader-shell="v3"`。这是命名/迁移债，不是本次确认的运行错误，但会持续误导依赖边界和文档。

### P3-03 旧 URL redirect 与历史 QA 资产未统一标记退役

例如 `app/management/folders/page.tsx` 是仓内无调用的旧 URL redirect；Mobile 仓库仍保存以 emulator 为基准以及 Work/Version/Volume 命名的历史验收记录。历史运行证据需要统一 `historical/superseded` 元数据，避免被当成当前真源；P1-11 的三个废止视觉状态已直接删除。

## 8. 文档与测试产物矛盾矩阵

| 主题 | 当前高优先级规则 | 冲突材料 | 实现事实 |
| --- | --- | --- | --- |
| Mobile 会话与 GET 失败 | ADR 0015：VerifiedSessionRecord、普通 Shell、无 GET 页面回退 | 无活跃冲突材料；P1-11 原发现已关闭 | Shared/Android/iOS 已移除页面快照、stale 与 downloaded-only 模型 |
| Mobile 身份 | ADR 0020：Book/Resource/Asset，无 Version | Phase 2/3 的 workId/volumeId/version 层级 | 主实现已大体切新身份 |
| Work Detail 管理 | Phase 4：关闭原生管理；根规范：跟随当前 Web | Settings 设计资产称用户批准原生全管理 | Android/iOS 已实现真实管理 |
| Reader 进度 | Reader architecture：500ms、revision、single-flight、确定性非阻断恢复 | 无活跃冲突材料；P1-12 原发现已关闭 | Web、Android、iOS 统一采用 Reader v4 状态机 |
| Reader v1–v3 | Reader architecture：410 | ADR 0019/当前 tests：404；历史 audit：v3 200 | 当前实际为未注册 404 |
| Android acceptance | 根规范：最终必须物理设备 | P2 acceptance 标 Android accepted，但证据是 AVD | 当前完整格式 Android=PENDING |
| PWA acceptance | 应覆盖 SW、离线和升级 | Playwright 全局 block Service Worker | 只有源码级 SW 单测 |
| i18n 完整性 | zh-CN/en-US 语义完整、用户内容不翻译 | 目录检查只验证结构；DOM observer 改文本 | 门禁通过但英文有坏翻译 |
| 后端静态门禁 | Ruff/Mypy/Coverage | dev lock 未包含工具 | pytest 通过，静态命令不可运行 |

## 9. 已确认的正向结果

- 后端入口已统一到能力路由：[router.py](../apps/api-python/app/api/router.py#L4)。
- 未发现业务代码或 Alembic migration 使用手写 DML/DDL SQL；SQLite PRAGMA 位于内核 adapter：[sqlite.py](../apps/api-python/app/db/sqlite.py#L35)。
- 后端全量 1062 tests 通过，迁移 head、ORM metadata、授权、API contract、事务已有较强测试基础。
- Web 多数 `app/**/page.tsx` 是薄装配；384 unit、typecheck、lint 均通过。
- `packages/reader-core` 未发现 React、Next、browser global、fetch 或 ORM 依赖，保持框架无关。
- Mobile Reader 静态上未发现把 MOBI/TXT/FB2 转为 EPUB/ZIP/解包目录的路径；原始格式和多格式 registry 主方向符合 Reader 架构。
- 最新完整格式记录诚实标记 iOS 为 PARTIAL、Android 为 PENDING，没有把缺失真机证据伪装为双端 accepted。

## 10. 整改顺序

### 波次 A：先冻结产品与契约真源

1. 用 Accepted ADR 裁决 Mobile Administration 是关闭还是正式进入产品；在裁决前不要继续扩展入口。
2. 以 ADR 0015、ADR 0020、Reader v4 为准，一次性清除 Phase 1–3 和测试中的离线 entitlement、Work/Volume route、旧进度算法。
3. 统一旧 Reader 路由为 404 或 410，并同步后端 tests、Reader 文档、手工验收和历史产物 banner。
4. 把历史审计、AVD 和旧设计资产标为 `historical/superseded`，不得参与当前 acceptance 汇总。

### 波次 B：修复已声明 P0 闭环

1. 实现真实 Shelves 页面与数据/操作测试；smoke 必须断言内容和用户动作。
2. 交付 Audio/Mini Player/Now Playing，或把 Phase 1 P0 范围正式下调；不能保留“P0 已完成”的暗示。
3. 把可重排 Reader 改为本地工件优先、否则在线打开；下载保持独立动作。
4. 移除 Reader Notes/Annotations 占位，直到真实数据、同步和测试合同具备。

### 波次 C：恢复可信工程门禁

1. 固定 Ruff、Mypy、pytest-cov 并建立 Python 全量 CI。
2. 后端架构测试动态发现全部能力、递归扫描所有层，默认禁止跨能力私有导入。
3. 增加稳定错误 code 契约测试；修复坏英文翻译并增加关键 copy snapshot。
4. 新建允许 Service Worker 的 production PWA Playwright project，覆盖安装、离线、升级和 basePath。
5. Mobile evidence manifest 绑定 commit、dirty hash、设备 serial、OS、locale、测试 bundle 与 crash/ANR 时间窗。

### 波次 D：按能力小步收敛结构

1. 后端优先收敛 Auth、System/Backup/OPDS、Metadata/Organize、Download queue、Publications/Library。
2. Web 建立 shared transport，再按 Settings、Organize、App Shell、Reader 顺序迁移 fetch 和 runtime validation。
3. Mobile 将 composition 从 MainShell/MainTabView 移出，为 Work Detail、Reader、Administration 暴露 public facade。
4. 删除确认不可达代码、旧缓存、兼容 re-export 和测试专用死岛；每个暂留兼容项记录 owner、调用者、截止版本和退出测试。

## 11. 最终判定

当前代码不是“整体失控”，而是处于功能快速扩张超过架构与文档治理速度的中后期迁移状态。后端 ORM 化、Reader v4、跨端原格式、Web 基础门禁是可靠基础；最危险的部分是权威规则存在多版本、测试门禁无法识别自己的盲区，以及 Mobile 对外表现与 Phase 1 声明不一致。

在 P0 三项关闭、P1 的产品/契约冲突裁决、静态/PWA/i18n 门禁恢复之前，不建议把当前工作树声明为符合目标架构或完成 Mobile Phase 1。后续重构应一次只处理一个能力面，保持现有 API、授权、数据和双语合同，避免把产品范围裁决与大规模目录搬迁混在同一变更中。
