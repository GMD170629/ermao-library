# TXT 在线失败与错误原因传递 — 2026-08-28

> 历史诊断/第一阶段修复记录。其末尾 NUL 兼容处理已被后续授权实现删除；当前状态和未完成项见 [解析器职责实现记录](reader-parser-implementation-2026-08-28.md)。下文旧测试数据不是当前全链路验收结论。

## 确认的根因

失败书目的 TXT 原件为 GB18030、1,539,839 字节，末尾有 160 个 NUL 字符。服务端原件与从真机只读取得的副本 SHA-256 一致：`92af8c57eb9fdcad8254e078a62c40ac9da894e7e3199ce03f873b7a2db75d3e`。

旧 `_decode_txt` 在严格解码成功后，只要见到 NUL 就自行抛 `PublicationCorruptError`。这不是 Readium、iOS 或 Python codecs 返回的解析失败。服务端又把该异常与 not-found 合并成 404／`PUBLICATION_NOT_FOUND`；原生二进制请求丢失具体原因，iOS 再显示“已下载的图书不再可用”。所以旧下载记录兼容问题不能解释本次在线解析失败。

TXT 服务端链路是自写适配器，没有等待接收原 TXT 的独立第三方解析器。内存绕过预判后，自写分章／XHTML 构造能处理该原文；若再实际交给 ElementTree／Expat，含 NUL 的 XHTML 会由 XML parser 本身返回 invalid-token 错误。正常 TXT 服务端接口并不调用该正文 XML parser，不能把删除一个预判等同于已经贯通最终解析错误。

## 本轮修改与复用

- 服务端 `_decode_txt` 与既有原生解码行为对齐：成功解码后忽略末尾 NUL 填充，不先裁剪源字节、不改原件。**内部 NUL 的旧拒绝规则尚未删除；这不代表已实现用户要求的全格式解析职责调整。**
- Publication 三个 HTTP 入口复用同一安全错误映射，区分 not-found、unsupported、corrupt、TXT 编码／NUL／空内容。保留原 HTTP 状态及无权限／不存在的防枚举行为，不返回原异常文本或内部路径。
- 复用通用 `typed_http_error_handler` 输出合法的 `X-Error-Code`。KMP `ApiClient` 根据 Publication adapter 提供的代码／状态白名单读取错误头，立即取消错误正文，不等待正文结束，也不增加另一条下载管线。
- `OnlinePublicationSession` 保留错误码、manifest／positions／chapter／resource 阶段及解析异常 cause。原生 Readium 元数据解析错误复用同一个共享分类工厂；不增加内容或排版验证。
- Android/iOS 显示原因和阶段。未知 `TRANSPORT_FAILURE` 不再猜成断网。原生 UI 不显示原始异常、书籍内容或服务端内部路径。
- 已删除原来的任意 `MISSING`／`NOT_FOUND` 字符串兜底，以及把 retryable 当作网络故障的推断。下载和在线选择策略、原始文件、Readium 版本均未改变。

## TXT 解码回归样例

三个消费者直接读取 `packages/reader-contracts/fixtures/txt-decoding-v1.json`，不复制样例内容。23 项覆盖 UTF-8、GB18030、UTF-16LE/BE、BOM、末尾 NUL、内部 NUL 和编码错误；仅使用合成短文本。

首次 iOS 真机运行发现两个新增样例的“所有 codec 均拒绝截断 UTF-16”假设不成立：Foundation 对 `fffe410042` 和 `feff004100` 返回 `A`，Python／Android codec 拒绝。因此 fixture 显式记录固定 `apple-foundation` decoder override，保留全部 23 项及所有 NUL 覆盖。没有为了通过测试增加 iOS 字节数预校验，没有按运行结果动态选择期望，也没有修改生产解码器。该 fixture 记录当前兼容行为，不应把旧 NUL 拒绝当作未来设计要求。

## 验证结果与未完成项

| 检查 | 结果 |
| --- | --- |
| 服务端相关回归 | 子任务最终 100 项通过；随后主代理对 TXT、Publication HTTP、OpenAPI 三个文件再跑 47 项通过。 |
| 真实原件解析 | 修正后 184 章全部生成，章节输出无 NUL；原 SHA-256 未变。属于真实文件解析，不替代实际在线／设备验收。 |
| 共享 KMP／Android | 首轮聚焦 43 项、全部共享 host 测试 346 项和 Android 单测 23 项通过。补充修改后，共享六个聚焦测试类、Android TXT 23 项及 `compileDebugKotlin`、`compileDebugAndroidTestKotlin` 再次通过；没有重跑全部共享测试。新增 Android SDK 失败测试只编译，未运行 Android 真机测试。 |
| iOS 首轮真机 XCTest | 6 项测试，5 项通过；TXT fixture 一项有两个断言失败，原因是上述 Foundation 行为差异。11 种在线失败原因／阶段／原 cause／无原件读写断言及双语文案断言通过。 |
| iOS 最后补充改动 | codec override 消费、原生 Readium metadata 错误和附带错误码文案尚未完成再次构建／真机运行；不得把首轮结果当作最终版本通过。 |
| 实际本地服务 | 仅重启本地 API，内存保留既有启动参数、环境、登录配置与存储根；没有重建数据库或修改原件。网关健康检查 200，未登录 manifest 请求 401 且 `X-Error-Code: UNAUTHORIZED`。 |
| 原 TXT 真机在线重新打开 | **未完成**：iPhone 在继续验证前变为 unavailable，停止 iOS 运行门禁，没有使用 Simulator。 |
| Web i18n | 2052 条 zh-CN/en-US 消息检查通过；移除已被英文兼容 API 消息替代的旧中文错误词条。 |
| 静态检查 | 后端 7 个修改文件的离线 Ruff check／format、`git diff --check` 通过；最新 Swift 源文件以 iphoneos／arm64 目标做语法解析通过，但未做最终类型检查、链接或真机运行。完整项目门禁未重跑。 |

后端有既有 Starlette/httpx site-packages 弃用警告；iOS 首轮构建有未触及代码的 SDK 弃用、旧测试 Sendable、方向配置、AppIntents 提示。没有为了验收加入跳过或警告抑制。

## 本地证据

- `/tmp/ios-reader-online-errors-unit-20260828-1410.log` 与同名 `.xcresult`。
- `/tmp/ios-reader-online-errors-backend-final-20260828.log`。
- `/tmp/reader-error-fidelity-shared-android-20260828.log`、`/tmp/reader-error-fidelity-all-host-tests-20260828.log`、`/tmp/reader-error-fidelity-followup-20260828.log`。
- `/tmp/txt-decoding-conformance-android-20260828.log`。
- `/tmp/ios-reader-online-errors-i18n-20260828.log`。
- `/tmp/ios-reader-online-api-live-20260828.log`。
- `/tmp/ios-reader-online-errors-devices-final-20260828.json`：设备 unavailable。

全格式只读审计见 `docs/audits/reader-parser-boundaries-2026-08-28.md`。除明确列出的在线错误修改外，其他解析预判与错误归因问题尚未修复。

Ruff 复核使用已有工具缓存的 `uv tool run --offline ruff check` 和 `uv tool run --offline ruff format --check`；项目 `.venv/bin` 没有独立 Ruff 可执行文件。API 最终进程为 85361，继续使用原来的 127.0.0.1:8000，经既有 3000 网关提供服务。
