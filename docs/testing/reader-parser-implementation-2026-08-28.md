# 阅读链路：解析器决定、保留真实失败原因

日期：2026-08-28。状态：**部分路径已迁移；全链路未验收**。

本次是用户明确授权后的实现。早先的只读审计记录保留为历史证据，不再代表当前代码。工作区原有其他移动端、下载与字号改动没有回退，也未提交、推送或部署。

## 单一实现与迁移范围

| 能力所有者 | 本次迁移的调用方与删除项 |
| --- | --- |
| 各平台现有 TXT 字符解码器、KMP `TxtPublicationNormalizer` | Python、Foundation、Android 解码器保留编码选择；删除 NUL 拒绝、尾部 NUL 清理，KMP 不再重复拒绝。无内容由 normalizer/实际分章实现报告。 |
| 原有 Publication 格式适配器 | TXT/FB2 仍使用内存 Publication；FB2 原文由 ElementTree/Foundation/SAX 解析。去掉生成章节的第二套 XML 验证、iOS 额外未声明前缀拒绝及图片签名匹配；Base64 实际解码仍执行。 |
| 各平台现有安全策略中的 CSP/head 模板 | TXT/FB2 自有模板直接引用同一 CSP，不再把已经生成的整章交给通用 XML 验证器。原始 EPUB/MOBI/在线章节仍有受限项，见下节。没有第二套 CSP 常量或替代阅读器。 |
| `ermao_mobi.c` / 固定 libmobi | 删掉 libmobi 前的 C preflight、加载失败后猜测分类的分支、成功加载后的额外格式预判；保留文件访问、分配、边界和资源预算。保留已有 KF8→KF7 同格式解析回退；不生成 EPUB。 |
| 原有原生 Publication Store | 保存、路径/账号隔离、原子发布继续保留；去掉 EPUB/PDF/TXT/漫画/MOBI 预解析。零字节文件可进入解析器，容量准入不再把零字节叫作超限。 |
| 各入口最终 PDF 引擎 | iOS 本地删除 PDFKit 预开，交给 Readium/Core Graphics；Web 删除 `%PDF-` 文件头检查，交给 PDF.js。原生 PDFium 256 次推进预算用独立错误码，不再称为 Range 无效。 |
| 既有漫画归档与图片解码器 | iOS/Android 去掉页数据签名预判；Android 不再在打开时读取每页文件头。远程页面错误回调保留鉴权/归档/资源原因。iOS 本地归档映射调用 KMP 的稳定错误映射，删除字符串猜测分类的重复实现。 |
| 公共 `ApiClient`、`readerErrorCodeForFailure` 与 Reader API adapter | 继续使用原有鉴权、取消、预算、版本检查；AppError、在线会话、ReaderError 保留内部 cause。安全上下文携带 code/stage/source，界面不显示原始异常、路径、URL 或响应正文。 |
| `packages/reader-contracts/reader-http-error-statuses.json` | Web 直接消费，KMP 由脚本生成，消除手工维护的错误码/HTTP 状态白名单副本。非成功响应只读有限错误头并取消正文，不等待 EOF；不接受 401/403 携带的伪造超限码。 |

服务端 TXT 解码、空内容、XML/包结构、读取、DRM、解析器预算/内存、资源缺失有独立稳定码。维持原有 404 防枚举契约，限额错误不随意改为 413；普通解析失败不进入 Download Center。只有已声明在线能力限额和 Range 不支持可选择现有可见下载流程。所有新可见文案提供中英文。

## 保留且未完成的路径

1. **原始章节安全隔离**：原生原始 EPUB/MOBI 和远程重排章节仍经过通用安全装饰器。其初次 XML、单一 head/body 检查仍在；正文投影复验和装饰后第二次 XML 解析已删除。固定 SDK 的公开接口尚未验证能在这些入口完全替代现有隔离，按用户要求停止迁移，不悄悄开放脚本/外联。此处安全失败明确标记为安全边界失败，不当作最终格式解析器的判断。
2. **在线含 NUL 的 TXT**：服务端会保留并交付 NUL；原生在线章节仍可能在上项安全 XML 边界失败，实际 XHTML 引擎也可能拒绝。不能宣称这类文件现在必定能在 iOS 在线阅读。没有重新引入过滤或改写字符。
3. **iOS 漫画图片解码**：固定 Readium `ImageViewController` 中 `UIImage(data:)` 失败只写日志，没有失败回调。未修改 SDK，未加入预解码、超时判坏或日志推断。资源传输回调完善不等于图片解码问题已解决。
4. **Web 漫画**：`img.error` 没有 HTTP 状态/解码异常详情。界面如实提示浏览器未提供具体原因；仍未改造成统一可观测的页面字节加载链路。没有为了诊断再发送一次请求猜测首次失败原因。
5. **全格式真机与故障矩阵**：不是每种格式都完成真实在线首屏、后续页失败、密码、取消/重试/重开与恢复验收。Android 没有连接真机；未启动模拟器。编译和共享层测试不能替代这些证据。
6. **错误契约完成度**：本文列出的资源与解析路径已保留 code/stage/source/cause；部分既有本地打开、SDK 导航及下载切换 UI 仍只消费错误类别，没有完整阶段与内部 cause 的呈现/诊断链。未把未知 SDK 异常猜成断网或文件损坏，但这不是全路径诊断完成。

## 安全与副作用

- 原文件未写回；章节分章和已有换行标准化保留，NUL 不清理。
- 路径、账号隔离、XXE、CSP、资源预算、HTTP/Range/版本检查保留。
- TXT/FB2 模板输出仍转义正文；新 CSP 变体仅用于应用生成模板，不用于不可信原始章节。
- 没有引入 SDK 修改、转换产物、全书自动下载/预热、自动删除下载文件/进度、字号重排验证或 Navigator 重建。
- 本次改动不等于对旧下载清理、全部既有重试/恢复行为重新验收；共享会话和协调器测试验证普通失败不请求原件、不分流下载，物理路径仍按上节列为缺口。

## 验证记录

- TXT 共用 26 例：UTF-8/UTF-16/GB18030，内部/尾部/纯 NUL，截断编码、空内容、空白。Foundation 的两项 UTF-16 行为差异以原生 decoder override 明确记录，不模拟跨平台一致性。
- 后端：全量 **1,090 项通过**（273.44 秒），随后新增零字节 TXT HTTP 样例及相关用例 **6 项通过**；此前 Publication/HTTP/Media 定向 96 项通过。原始 NUL HTTP 回归检查正文字符和原文件 hash。原问题 1,539,839 字节副本只读解码保留全部 160 个尾部 NUL，SHA-256 仍为 `92af8c57eb9fdcad8254e078a62c40ac9da894e7e3199ce03f873b7a2db75d3e`。没有把此只读解码称为完整设备在线验收。
- Web：**406 项测试通过**；全量 lint、typecheck 和 i18n 通过（2,069 个中英消息）。新增实际 Reader 页面 403 错误与重新打开 E2E 在 **Chromium、WebKit 各 1 项通过**，验证错误正文不显示、原件接口没有请求。该场景使用受控 HTTP 故障，不是生产服务实测。
- KMP/Android：**348 项共享主机测试、169 项 App 单元测试通过**；androidTest Kotlin 编译通过，无跳过。未连接 Android 设备。
- C/libmobi：ASan+UBSan host corpus 和 C++ header **2 项通过**，含正常 corpus、负例和 1000 次打开/关闭。负例期望依据实际 libmobi 结果更新，未跳过失败样例。另以当前源码构建独立动态库并由 Python `_MobiCore`/`MobiPublicationAdapter` 实际加载，验证损坏负例返回 `PUBLICATION_PARSE_FAILED`、加密负例返回 `PUBLICATION_DRM_PROTECTED`，中文 AZW3 打开并读出首章。
- iOS：实体 iPhone 17 Pro Max，iOS 26.6；未用 Simulator。首轮定向 10 项通过；扩展 ReaderSecurityTests + LocalizationTests **21 项中 20 项通过、1 项失败**。新 WebKit 内联脚本/事件/外联/嵌入隔离、六格式空/不可解析原件保存重开、TXT/FB2 与错误回传测试通过。失败为既有 `testNativeTextControlsRenderBundledFontsAndThemesOnPhysicalDevice` 的连续滚动布局断言（仍为分栏），非字号提交失败；保留测试，未跳过、降低断言或增加 Navigator 重建。结果包：`/tmp/ermao-reader-device-build/Logs/Test/Test-ErmaoLibrary-2026.08.28_15-23-08-+0800.xcresult`。
- 新共享 JSON schema/fixture 验证、KMP 生成文件 `--check`、`git diff --check` 通过。读取原文件、SDK 版本与源代码未被本次更改。
- 后端修改范围 Ruff check/format（36 个文件）通过；**全仓 Ruff check 仍有 2 个既有 import 排序问题、format 有 14 个未修改文件不合规；mypy 有 3 个未修改 Library metadata 文件中的 7 个既有错误**。没有扩展任务去重排或重构这些能力，也没有屏蔽规则。
- 既有 Starlette/httpx、固定 Readium CBZ、未修改的 ReaderPersistenceTests Sendable 捕获等警告仍在；未升级 SDK 或屏蔽告警。全仓质量门禁并非全绿。

复现命令：

```sh
python3 packages/reader-contracts/generate-reader-http-errors.py --check
cd apps/api-python
.venv/bin/pytest tests/unit/modules/publications tests/contract/api/test_reader_publication_http.py tests/unit/modules/media -q
cd ../web
pnpm lint
pnpm typecheck
pnpm test
pnpm i18n:check
cd ../mobile
ANDROID_HOME=/Users/guyu/Library/Android/sdk ./gradlew :shared:testAndroidHostTest :androidApp:testDebugUnitTest :androidApp:compileDebugAndroidTestKotlin --console=plain
```

## 后续验收条件

本次未重启/部署服务端。原始章节安全隔离替代必须先在固定 SDK 的真实导航路径证明内联脚本、事件属性、外联和嵌入内容都被阻止，再删除前置 XML 规则。iOS 漫画无回调路径需要用户重新决定 SDK 边界后才能继续。Web 漫画完整原因传递需要沿用现有 Reader API/有界传输建立页加载所有者并保持懒加载、取消和内存窗口；当前没有用独立下载管线替代它。其他真机矩阵完成前不得把本记录改成全链路完成。
