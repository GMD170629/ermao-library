# React Native + Expo 客户端实施计划

> 状态：Active
> 基线日期：2026-08-08
> 目标平台：Android 手机/平板、iPhone、iPad
> 当前目标：先完成与 Web、FastAPI 和 `reader-core` 同源的移动端基线，再继续界面与业务功能开发

## 1. 唯一实现基线

移动端不保留独立的旧业务模型，也不为历史移动端原型增加兼容分支。所有新增实现必须直接使用仓库当前公开契约：

- 业务层级是 `work -> mediaVersion -> volume`；
- 阅读入口是 volume-first Reader v3；
- 身份认证复用现有 Cookie Session 和 `/api/auth/*`；
- 阅读控制、位置和偏好以 `packages/reader-core` 为唯一平台无关来源；
- FastAPI OpenAPI 是 HTTP wire contract 的唯一来源；
- `zh-CN`、`en-US`、根版本号和现有授权规则与 Web 保持一致。

移动端直接切换到当前存储格式。旧移动快照不读取、不转换、不回写；发现不符合当前 schema 的快照时将其明确拒绝为不兼容本地数据，由后续界面提供清理并按当前契约重新建立 profile、会话状态和阅读进度。不得增加旧字段映射、双写或临时迁移层。

## 2. 当前契约

### 2.1 内容数据模型

所有书库、详情、阅读、下载和进度功能使用以下稳定标识：

```text
workId
  -> mediaVersionId
      -> volumeId
```

- `work` 表示作品及书名、作者、封面等作品级信息；
- `mediaVersion` 表示电子书、漫画或有声书媒体版本；
- `volume` 是阅读、阅读状态、书签、进度和文件访问的直接目标；
- 文件与阅读单元由 Reader bootstrap 返回，不由客户端从路径或文件名推断；
- 用户可见性和资源级授权继续由服务端按当前 actor 校验。

移动端路由和状态命名必须使用 `workId`、`mediaVersionId`、`volumeId`，不得引入另一套内容主键。

### 2.2 Reader v3

当前阅读接口：

```text
GET /api/reader/v3/volumes/{volumeId}/bootstrap
PUT /api/reader/v3/volumes/{volumeId}/progress
PUT /api/reader/v3/volumes/{volumeId}/reading-status
GET /api/reader/v3/volumes/{volumeId}/bookmarks
PUT /api/reader/v3/volumes/{volumeId}/bookmarks
```

Reader bootstrap 提供：

- `book`、`mediaVersion`、当前 `volume` 和 `availableVolumes`；
- `files`、`units`、`fileUrl`；
- `readerType`、`sourceFormat` 和能力矩阵；
- `contentFingerprint`、恢复位置和阅读百分比；
- 电子书、漫画、PDF 和音频位置的显式联合类型。

Reader v3 HTTP payload 的 `schemaVersion` 当前为 3。客户端必须在 feature API 边界校验 `unknown` 响应，并通过 mapper 转换为移动端 model 或 `reader-core` 类型。生成类型不可直接作为可编辑 UI 状态。

### 2.3 `reader-core`

`packages/reader-core` 当前 `READER_SCHEMA_VERSION` 为 4。移动端直接复用：

- `ReaderKind`、`ReaderLocation`、`ReaderSource`；
- `ReaderPreferences` 的完整当前结构；
- `ReaderCommand`、`ReaderCapabilities`；
- `ReaderAdapter`、事件、operation token 和 session 状态机；
- 默认偏好、当前输入归一化和 schema 4 校验规则。

必须区分两个独立版本：Reader v3 HTTP contract 使用 schema 3，`reader-core` 偏好模型使用 schema 4。任何映射都应位于 `features/reader/api` 或 reader application 边界，不能靠类型断言混用。

视觉阅读器当前覆盖 `reflowable`、`comic`、`pdf`。有声书由独立 audio capability 管理，不扩充视觉 `ReaderKind`。

### 2.4 Cookie Session

移动端复用现有认证接口：

```text
GET  /api/auth/setup/status
POST /api/auth/login
GET  /api/auth/me
POST /api/auth/logout
```

统一 transport 使用 `credentials: include`，由平台网络栈维护会话 Cookie。客户端不定义第二套认证协议，不把 Cookie 注入 Reader WebView、URL、日志、本地 JSON 或崩溃上下文。

身份 application 层负责：

- 检查服务端初始化状态；
- 登录并把 wire session 映射为显式用户模型；
- App 启动或回到前台时通过 `/api/auth/me` 恢复会话；
- 注销、401 失效和服务器切换时清理内存中的用户态数据；
- 按稳定错误码处理未初始化、凭据错误和账号停用。

### 2.5 服务入口和媒体

App 只保存用户在浏览器中访问二毛图书时使用的 Web 根地址，绝不要求用户填写独立的 API/后台地址或内部端口。移动端保留反向代理 base path，并从该前台地址同源派生 `GET /api/health`、`/api/auth/*` 和后续业务 API。profile 当前按规范化 `baseUrl` 标识，不引入新的服务端身份接口。

Reader 返回的封面、文件和页面地址保持相对 URL，由已验证的 server profile 解析。媒体访问继续复用当前 `/api/files/{fileId}`、`/api/volumes/{volumeId}/file` 及 Reader 返回的资源地址，并遵守 GET、HEAD、Range、ETag、Last-Modified 和资源级授权语义。

## 3. 产品范围

### 3.1 在线阅读 Beta

- 手工输入或扫描书库前台地址；
- 服务健康和初始化状态检查；
- Cookie Session 登录、恢复与注销；
- 书库首页、搜索、筛选、书架和作品详情；
- 从 media version 中选择 volume；
- EPUB/其他可重排格式、漫画和 PDF 在线阅读；
- 阅读偏好、阅读状态、书签、本地恢复和服务端进度；
- 手机和平板自适应布局；
- `zh-CN`、`en-US`；
- 深色模式、字体缩放、VoiceOver/TalkBack 和横竖屏支持。

### 3.2 后续范围

- EPUB、PDF、漫画和音频离线下载；
- 有声书后台播放、系统媒体控制、中断恢复、倍速和睡眠定时；
- 下载暂停、恢复、校验、容量处理和失效处理；
- 多服务器 profile；
- iPad 和 Android 平板双栏或三栏；
- TestFlight 和 Google Play Internal Testing；
- App 数据升级与分阶段发布。

### 3.3 不在移动端实现

- Python、Worker 或服务端 SQLite；
- 服务端系统管理、备份恢复和元数据提供方配置；
- 完整导入任务、监控目录和下载器管理；
- Web 页面套壳或 Web 私有 feature 复用；
- 修改或 patch EPUB.js；
- 默认采集书籍内容或用户阅读内容。

## 4. 架构与依赖方向

```text
index/composition
  -> app-shell
      -> feature UI
          -> feature application
              -> feature model

feature api/files adapters
  -> application ports and explicit model types

reader host
  -> reader-core + format adapter
```

硬约束：

1. `apps/mobile` 不导入 `apps/web/**`。
2. `apps/web` 不依赖移动端代码、生成物或原生模块。
3. feature 外部只能经该 feature 的 `public.ts` 使用能力。
4. UI、页面和 reducer 不直接调用 `fetch`、文件系统或持久化 API。
5. 网络、存储和 URL 输入先按 `unknown` 校验，再映射为显式类型。
6. `generated/**` 只由脚本生成，禁止手改。
7. `reader-core` 保持无 React 和平台运行时依赖。
8. 不新增顶层 `utils`、`helpers`、`managers` 或通用 `services`。
9. 每个异步流程支持取消或陈旧结果拒绝。
10. 用户可见文案同时完成中英文和无障碍标签。

目标结构按真实代码逐步创建：

```text
apps/mobile/
├── generated/                       # 提交的 OpenAPI 生成物
├── scripts/                         # 契约、i18n、runtime 门禁
├── src/
│   ├── app-shell/                   # 根布局和自适应导航组合
│   ├── bootstrap/                   # composition root
│   ├── features/
│   │   ├── server-connection/
│   │   ├── identity/
│   │   ├── library/
│   │   ├── reader/
│   │   ├── reader-progress/
│   │   ├── downloads/
│   │   └── audio/
│   └── shared/
│       ├── api/
│       ├── files/
│       ├── i18n/
│       ├── infrastructure/
│       ├── ui/
│       └── validation/
├── app.json
├── index.ts
├── package.json
└── tsconfig.json
```

## 5. API 和生成契约

FastAPI OpenAPI 是生成物的输入。移动端 Reader 生成流程：

1. 使用 `apps/api-python/scripts/export_openapi.py` 导出当前 OpenAPI；
2. 由 `apps/mobile/scripts/generate-reader-api.mjs` 选择 Reader v3 所需 schemas；
3. 生成 `apps/mobile/generated/reader-v3.ts`；
4. `api:check` 重新导出、生成并检查工作树无 drift；
5. feature wire decoder 对字段集合、联合类型、边界值和响应大小做运行时校验；
6. mapper 把 wire DTO 转为 volume-first model 和 `reader-core` 类型。

生成器必须确定性输出。后端 reader、auth、library、media、共享 HTTP contract 或 OpenAPI 导出逻辑变化时，Mobile CI 必须运行。

后续增加 library client 时沿用相同原则，不创建重复的移动端专用服务端接口。

## 6. 网络和身份边界

`shared/api` 是唯一 JSON transport，负责：

- base path 安全拼接；
- `credentials: include`；
- GET、POST、PUT、PATCH、DELETE；
- JSON 编码和 Content-Type；
- AbortSignal、超时和最大响应体限制；
- 手动重定向策略；
- 网络、取消、超时、无效 JSON 和超限响应归一化。

feature API adapter 负责 endpoint、运行时 schema、wire mapper 和稳定 outcome。UI 只处理 named outcome，不按原始 status 或本地化 message 决策。

服务器切换、用户注销和 session 失效时必须取消请求并清理用户态内存缓存。日志不得包含密码、Cookie、响应 body、书籍内容或本地路径。

## 7. 本地持久化

当前基础设施使用 App 私有文档目录和版本化快照：

- 临时文件写入；
- 写后回读和运行时 schema 校验；
- 原子移动发布；
- 当前和上一份有效快照；
- 损坏回退；
- 同目录操作串行化。

当前文档：

| 文档 | 当前 schema | 所有权 |
| --- | ---: | --- |
| `shuku.server-profiles` | 2 | `server-connection` |
| `shuku.reader-progress` | 3 | `reader-progress` |
| `ReaderPreferences` | 4 | `reader-core` 定义，reader feature 持久化 |

旧移动快照没有迁移路径。codec 只接受当前字段集合、当前 schema 和当前不变量；不匹配时作为不兼容数据拒绝，不尝试恢复旧字段。此决策适用于开发阶段已有的服务器 profile、阅读进度和偏好快照。

阅读进度槽位按以下维度隔离：

```text
profileId + baseUrl + owner + workId + mediaVersionId
+ volumeId + contentFingerprint + readerKind
```

本地进度必须支持 schema 4 中的可重排位置，包括 `foliate` 精确恢复快照。漫画位置必须绑定同一个 `volumeId`。容量、字段长度、重复槽位、序列单调性和最坏文件大小继续由测试覆盖。

服务端同步阶段在现有本地模型上增加持久 outbox：

```text
记录本地位置
-> 持久化待发送 mutation
-> 按 clientSequence 发送 Reader v3 progress
-> compare-delete
-> 更新本地 head
```

`applied: false`、内容指纹冲突、401、取消和网络错误都必须成为显式状态，不得 fallback-to-success。

## 8. App 壳和界面基础

当前壳层职责：

- Safe Area 和状态栏；
- 系统明暗主题；
- 独立 `zh-CN` / `en-US` catalog；
- compact 底部导航和 expanded 侧栏；
- 可访问的共享文字、按钮、图标按钮、卡片、通知、加载状态和页面脚手架；
- Expo Router 的 `(connection)`、`(auth)`、`(main)` 受保护 route group；
- 由 app-flow state 统一决定连接、身份和已登录主界面的访问边界；
- 启动与前台会话恢复、前序异步操作取消和陈旧结果拒绝；
- 服务端确认注销后才退出已登录态，注销失败时保留会话并报告 warning。

壳层不是已完成页面。B1 连接页面已接入 feature application；登录、书库和阅读仍须按阶段替换占位 route，不在占位组件中直接堆叠网络和持久化逻辑。

按可用窗口宽度自适应，而不是按设备名称分支：

```text
compact   < 760
expanded  >= 760
```

实现时覆盖安全区、横竖屏、分屏、系统返回、键盘、pointer、触摸、字体缩放、reduced motion 和屏幕阅读器。

## 9. 阅读器实现

Reader host 持有 session、adapter、operation token、取消、dispose、controls 可见性、当前 source 和进度 application。Reader UI 只发送用户意图。

### 9.1 漫画

首个完整阅读垂直切片：

```text
volume bootstrap
-> wire validation and mapper
-> ReaderSource
-> reader-core session
-> 原生图片 adapter
-> 本地进度
-> Reader v3 progress
```

覆盖单页/双页、LTR/RTL、横滑、点击区、工具栏、进度跳转、缩放互斥、有限预取、旋转、内存预算和隐藏 controls 恢复。

### 9.2 可重排格式

使用本地 WebView runtime 和官方阅读引擎，通过版本化 bridge 传递命令、事件、位置、偏好和小型元数据。WebView 不持有 Cookie，不加载远程脚本，不接受未校验消息。

实现 CFI/href/progression/foliate、目录、分页/滚动、主题、字体、排版和重建恢复，并完整映射 schema 4 `ReaderPreferences`。

### 9.3 PDF

使用本地 PDF runtime，支持 page、zoom、fit、rotation、continuous/paged、文本层、Range、本地文件和渲染预算。上层只依赖 `ReaderAdapter`，允许以后替换渲染实现。

### 9.4 音频

audio capability 独立管理 track、章节、position、系统媒体控制、后台播放和中断恢复。Reader v3 bootstrap 和 progress 仍提供音频服务端契约，但不把音频塞入视觉 reader state。

## 10. 国际化和可访问性

- 所有 UI 文案使用 Mobile 自有 i18n API；
- `zh-CN` 和 `en-US` 在同一变更中完成；
- 校验缺失键、多余键、中文残留和 placeholder 不一致；
- 日期、时间、数字、百分比使用当前 locale；
- 用户书名、作者、标签、书架和文件名保持原样；
- 权限说明、错误、空状态、toast 和 accessibility label 均双语；
- 交互目标满足 44pt/48dp，支持字体缩放和读屏；
- 隐藏阅读 controls 后必须始终存在可发现的恢复方式。

## 11. 安全要求

- 公网地址要求 HTTPS；LAN HTTP 仅允许明确的私有地址范围；
- 不关闭 TLS 校验，不接受任意证书；
- 重定向由 transport 拒绝或显式重新验证；
- WebView 默认只加载本地 runtime 和受控内容；
- 文件路径由受控 ID 构造并限制在 App 私有根目录；
- 不信任 filename、MIME、长度或相对资源 URL；
- 每个服务端资源操作继续执行 actor 范围授权；
- 账号和服务器切换不得复用旧用户的请求、缓存或进度队列。

## 12. 实施路线图

### B0：基线迁移

交付：

- Expo SDK 57 工程与严格 TypeScript；
- capability-first 基础设施；
- Cookie Session identity gateway；
- Reader v3 生成契约、wire validation 和 mapper；
- volume-first 本地进度；
- schema 4 位置支持；
- 双语、自适应、安全区 App 壳；
- Mobile CI 契约与构建门禁。

退出条件：lint、typecheck、test、`api:check`、`i18n:check`、`doctor` 和双平台 export 全通过，旧移动快照没有读取或迁移代码。

### B1：连接服务器

状态：已完成（2026-08-08）。代码、自动化测试和 Android/iOS 双平台 export 的最终门禁均已通过。

- 手工地址、二维码扫描、相机权限和重新扫描 UI；
- 手工与 QR 共用同一地址规范化和安全边界，保留反向代理 base path；
- 健康、初始化、超时、取消、不兼容响应和错误恢复状态；
- 原子 `ServerProfileCatalog`，以及 load、select、delete、reset-corrupt application use case；
- 选择已有 profile 前重新健康检查，并发删除不得被迟到的选择结果复活；
- 删除 active profile 后将 active 置空，不自动回退到其他服务器；
- 有效旧快照可恢复并向上报告 warning，全部受管快照损坏时才允许显式原子重置；
- 手机/平板、自适应布局、双语、无障碍及 Router/UI 聚合测试。

完成记录：`reader-core` typecheck、`api:check`、Mobile lint、production/unit/UI typecheck、Node 测试 104/104、UI/Router 测试 7 个 suite 共 12/12、i18n 4/4、Doctor 20/20，以及 Android/iOS `export:check` 均通过。

当前环境未执行真机扫码、相机权限设置跳转、冷启动杀进程恢复、Cookie 前后台恢复、真实注销、LAN HTTP、HTTPS 和反向代理 base path 部署验证。上述场景仍保留在后续真机与部署验收矩阵中，不将自动化测试结果表述为已完成真机验证。

### B2：登录与会话

状态：部分完成。会话恢复和确认注销框架已接入，登录表单仍是下一阶段。

- 已完成启动和前台恢复、无会话跳转、会话刷新失败保留 stale session warning；
- 已完成服务端确认注销后退出，注销失败保留已登录态；
- 已完成受保护身份/主界面 route、操作取消和陈旧结果拒绝；
- 待完成登录表单、登录错误与账号停用 UI、401 全链路跳转；
- 待完成服务器切换的会话/缓存清理验收，以及 iOS/Android Cookie 生命周期真机验证。

### B3：只读书库

- dashboard、作品列表、搜索、筛选和书架；
- work 详情和 media version/volume 选择；
- 分页、取消、陈旧结果拒绝、封面和空状态；
- 手机单栏、平板列表加详情布局。

### B4：Reader host 与漫画

- Reader v3 bootstrap client；
- reader-core session 和 adapter host；
- 漫画输入、工具栏、目录/跳页和进度；
- 生命周期、旋转、杀进程恢复和内存测试。

### B5：可重排格式与 PDF

- 本地 WebView runtimes；
- 版本化 bridge 和运行时校验；
- schema 4 偏好完整映射；
- EPUB、MOBI 系列、FB2、TXT 和 PDF 的格式专项测试。

### B6：进度、书签和同步硬化

- 持久 outbox；
- AppState 和网络恢复唤醒；
- Reader v3 reading-status、progress 和 bookmarks；
- 指纹冲突、幂等、序列、重试和隔离测试。

完成 B6 后进入在线阅读 Beta。

### B7：离线与音频

- 下载清单由现有 volume/file 资源组合产生；
- 临时文件、Range resume、校验和原子发布；
- 下载状态恢复、空间和账号隔离；
- 音频后台、锁屏、耳机和系统中断。

### B8：发布硬化

- iPhone、iPad、Android 手机/平板矩阵；
- 性能、内存、无障碍和大字体；
- E2E 主旅程；
- TestFlight、Play Internal、升级和回滚；
- 根/Web/Python/Mobile 版本一致性。

## 13. CI 与质量门禁

Mobile PR 至少执行：

```bash
pnpm install --frozen-lockfile
pnpm --filter @shuku/reader-core typecheck
pnpm --filter @shuku/mobile api:check
pnpm --filter @shuku/mobile check
pnpm --filter @shuku/mobile test
pnpm --filter @shuku/mobile i18n:check
pnpm --filter @shuku/mobile run doctor
pnpm --filter @shuku/mobile export:check
```

`check` 覆盖契约漂移、lint、严格类型检查、测试、双语和 Expo 健康；CI 另行执行聚合 `test`（单元测试加 Jest 原生 UI/Expo Router 测试），并显式执行契约、双语、doctor 和双平台 export，使各类失败能单独定位。

CI path filter 必须覆盖：

- `apps/mobile/**`；
- `packages/reader-core/**`；
- backend reader/auth/library/media modules；
- backend auth、authorization、bootstrap、HTTP contracts 和 OpenAPI exporter；
- 根依赖、workspace 和 Mobile workflow。

涉及后端公开契约的变更还应运行对应 Python contract tests。涉及共享包或根依赖时继续运行适用的 Web 回归门禁，不以 Mobile CI 代替现有 Web/Python CI。

## 14. Definition of Done

当前基线只有在以下条件全部满足时完成：

- 移动端只使用 `work -> mediaVersion -> volume`；
- 所有阅读网络调用只面向 Reader v3 volume routes；
- 身份只使用现有 Cookie Session `/api/auth/*`；
- FastAPI OpenAPI、生成类型、wire decoder 和 mapper 无 drift；
- Reader v3 schema 3 与 `reader-core` schema 4 显式分层；
- `ReaderPreferences` 当前字段在移动端没有缩减版重复类型；
- 本地进度包含 `workId`、`mediaVersionId`、`volumeId` 和 `contentFingerprint`；
- 旧移动快照不迁移、不双写；
- App 壳具备双语、主题、安全区和自适应导航；
- 页面和 reader 尚未实现的能力在进度文档中明确标记；
- 所有适用门禁通过，且没有测试跳过、警告掩盖或未说明兼容层。

## 15. 官方工程参考

- Expo monorepo 与 pnpm：<https://docs.expo.dev/guides/monorepos/>
- Expo Development Build：<https://docs.expo.dev/workflow/overview/>
- Expo SDK 版本：<https://docs.expo.dev/versions/latest/>
- EAS monorepo 构建：<https://docs.expo.dev/build-reference/build-with-monorepos/>
- Expo FileSystem：<https://docs.expo.dev/versions/latest/sdk/filesystem/>
- Expo Audio：<https://docs.expo.dev/versions/latest/sdk/audio/>
