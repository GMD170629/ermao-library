# 阅读器解析职责与错误保真审计 — 2026-08-28

> **历史审计快照**：以下内容描述实现前状态。用户随后授权实施；当前已迁移路径、SDK/安全受限项和验证结果见 [实现记录](../testing/reader-parser-implementation-2026-08-28.md)。不能用本页旧校验描述作为新代码依据。

## 结论与范围

**当前没有全部符合“由实际解析器判断可解析性，失败返回真实原因”的原则。**

本记录区分用户要求的目标与已有实现。已有 NUL、XML 结构或文件头检查不是保留这些规则的理由。此次跨格式工作是只读审计；已授权的代码修改仅涉及 TXT 在线失败兼容和在线错误传递，没有据此删除各阅读器的安全控制、替换解析器或修改所有格式的打开行为。

目标是把格式容错和解析成功与否交给实际使用的解析器，不用单个字符、结构猜测或另一套验证器抢先判定文件损坏。应用可以保留明确的权限、路径、外部实体、执行隔离、传输协议和资源预算边界，但应报告实际触发的边界，不能把它们包装成“解析失败”。未知原因也不能猜成断网、文件损坏或下载丢失。

## iOS：正常打开路径

| 格式 | 当前判断链 | 尚未符合的部分 |
| --- | --- | --- |
| TXT | Foundation 字符解码 → 自写 TXT/KMP normalizer → XHTML → Readium | 原生解码器检查内部 NUL，KMP 又检查一次；本地工厂异常合并为 `CORRUPT_FILE`。在线还受服务端自己的 TXT 判断影响。 |
| EPUB | 本地 Readium opener／在线 Publication → 自写章节安全装饰 → Readium Navigator | 章节装饰承担编码、NUL、XML、head/body 数量检查，且装饰前后重复解析；部分资源错误最终仅显示通用阅读器错误。 |
| FB2 | Foundation XMLParser → 自写 FB2 adapter → XHTML → Readium | 应用额外拒绝未声明 namespace prefix，另检查 Base64／图片头，生成章节再过 XML 验证；大部分错误合并为文件损坏。 |
| MOBI / AZW / AZW3 / PRC | 自有 C ABI preflight → libmobi → 内存章节 → Readium | C 层在 libmobi 前检查文件头、记录偏移、加密和文本声明；其中安全边界与内容预判需分别处理。章节还经过 XML 检查，部分错误被合并。 |
| PDF | 在线 PDFium；本地 PDFKit 预开 → Readium 默认 Core Graphics parser | 本地不是只调用最终解析器；PDFKit 的 `isEncrypted` 或 `isLocked` 都会提前拒绝。在线 Range 异常没有完整映射到 Swift 的真实原因；推进预算耗尽也被归为 Range 无效。 |
| 漫画 | libarchive／在线页面 → Readium → UIImage | 本地按扩展名和文件头匹配筛选；固定 Readium 的图片解码失败分支仅记录日志后返回，不能保证界面显示明确错误。 |

关键证据：

- `apps/mobile/iosApp/ErmaoLibrary/Features/Reader/IosTxtPublicationFactory.swift`：`IosStrictTxtDecoder.decode`。
- `apps/mobile/shared/src/commonMain/kotlin/com/ermao/library/shared/modules/reader/domain/TxtPublicationNormalizer.kt`：重复 NUL 判断。
- `apps/mobile/iosApp/ErmaoLibrary/Features/Reader/IosMobiContentSanitizer.swift`：`IosPublicationSecurityPolicy.decorate/decode/validate`，严格 XML 解析、恰好一个 head/body、正文投影比较。
- `apps/mobile/iosApp/ErmaoLibrary/Features/Reader/IosReadiumRuntime.swift`：本地格式打开、PDFKit 预开与错误合并。
- `apps/mobile/iosApp/ErmaoLibrary/Features/Reader/IosFb2PublicationFactory.swift`：自写 namespace、图片输入检查。
- `apps/mobile/native/mobi-core/Sources/CLibMobi/src/ermao_mobi.c`：`ermao_preflight` 先于 `mobi_load_filename`。
- `apps/mobile/iosApp/ErmaoLibrary/Features/Reader/IosPdfiumDocument.swift`：Range 桥接、推进预算与错误映射。
- `apps/mobile/iosApp/ErmaoLibrary/Features/Reader/IosCbzPublicationFactory.swift`：图片头和类型匹配。
- 固定 Readium Swift revision `f7d10d2bf5876408feae14d634416f69d1473fd8` 的 `Sources/Navigator/CBZ/ImageViewController.swift`：`UIImage(data:)` 失败只记录日志。已核对本机 checkout 和 `Package.resolved`，未修改依赖。

`IosManagedPublicationStore.importPublication` 的 EPUB mimetype 首项及 PDF 文件头检查，当前只找到测试调用；正常已完成下载使用 `bindCompleted`。不能把闲置导入检查当作每次阅读必经步骤。

## Android／共享层：已核对的公共路径

Android 重排资源同样经过 `EpubContentSecurityPolicy`：自写 NUL 拒绝、DocumentBuilder XML 解析、head/body 数量检查及装饰后正文投影验证。TXT 的 `StrictTxtDecoder` 与共享 `TxtPublicationNormalizer` 也都有内部 NUL 判断。因此 Android 至少这条公共路径并非完全交给最终 Readium renderer 决定。

共享 `OnlinePublicationSession` 的 UTF-8／JSON及 href 安全检查早已存在；本轮仅补充它们的错误码、阶段和 cause。`ReaderLaunchCoordinator` 的下载分流只接受明确 OnlineLimit／RangeUnsupported；401/403/404 携带伪造超限错误头也不会触发下载，错误正文立即取消。

本轮未完成 Android PDF／漫画等每一种原生入口的完整调用链审计，不能把公共路径检查或 Android 编译通过称作全平台全格式验收。共享 C/libmobi 绑定结论可复用，但并不替代 Android 上层错误呈现审计。

## 服务端与 Web

| 格式／入口 | 当前情况 |
| --- | --- |
| 服务端 EPUB | 自写 ZIP/OPF/目录适配器调用 ZipFile、ElementTree；正常正文直接返回，没有逐章验证全部 XHTML。必要包结构解析与“额外再验正文”不同。 |
| 服务端 TXT | 没有独立第三方 TXT 解析器；codecs 解码、自写分章、拼接 XHTML。内部 NUL 仍由应用显式拒绝；当前接口不会把所有生成章节交给 XML parser。 |
| 服务端 FB2 | ElementTree 解析原文；生成章节经 `decorate_markup_head` 在 CSP 装饰前后各做一次 XML 验证。图片另有签名判断。 |
| 服务端 MOBI | C 绑定加 libmobi；Python 把 DRM、unsupported、limit 等合并为 unsupported，其他多种失败合并为 corrupt。 |
| 服务端 PDF | 原件接口仅鉴权、文件/版本检查与 Range 传输，不预解析 PDF；最终解析在客户端。此结论不能覆盖客户端前置检查。 |
| 服务端漫画 | Manifest 依赖持久化页索引；缺索引属于导航依赖缺失，不证明图片不可解析。原页通过 ZipFile/rarfile 解包；多个损坏、加密、解压后端失败被合并为页面不存在。 |
| Web 重排阅读 | 使用实际 Readium `Manifest.deserialize`，但 HTTP wrapper 把大部分非成功状态合并为资源不可用；没有保留本轮新增的服务端细分错误码。缺 CSP 响应头还被文案说成“文件包含不安全的内容”，证据与提示不符。 |
| Web PDF | `PdfRangeByteSource.prepare` 在 PDF.js 前自行检查前 1024 字节的 `%PDF-`；未知异常最终默认归成 `PDF_INVALID`，HEAD 的非成功状态被归成网络不可用。 |
| Web 漫画 | 图片由浏览器实际解码，但 `img.error` 只有“漫画页面加载失败”，无法区分网络、权限和图片解码；目前不能宣称原因完整。 |

关键证据：

- `apps/api-python/app/modules/publications/infrastructure/{epub_adapter,txt_adapter,fb2_adapter,mobi_adapter,locator_dom}.py`。
- `apps/api-python/app/modules/reader/presentation/v4.py` 的漫画 manifest；`apps/api-python/app/modules/media/infrastructure/http_streaming.py` 的漫画页失败映射。
- `apps/web/features/reader/v3/adapters/readium-publication-security.ts` 的 `createSecurePublicationFetch`；`reader-engine-runtime.tsx` 的 `readerErrorMessage`。
- `apps/web/features/reader/v3/adapters/pdf-range-transport.ts` 的 `prepare/validateHead`；`pdf-adapter.ts` 的 `pdfErrorCode`。
- `apps/web/features/reader/v3/adapters/comic-track.ts` 的图片 error 处理。

## 不能混淆的边界

鉴权与防枚举、路径穿越／符号链接防护、禁止外部实体和书籍脚本／外联、账号隔离、版本一致性、Range 协议、明确资源预算都不由文档解析器负责，不能无差别删除。

在线 TXT/FB2 的文件常量是 64 MiB，但 TXT/FB2/MOBI 快照权重为源大小 ×8、默认预算 128 MiB，实际更早受约 16 MiB 原件预算约束。章节交付另有 8 MiB、其他资源 32 MiB 上限。这些是应用在线能力限制，不能说成最终解析器证明文件损坏。多个 `adapter.open` 也可能复用同一快照，不能仅凭调用次数认定重复完整解析。

## 验证性质

这是实际调用链和固定 SDK 源码审计，不是所有格式的运行验收。iOS 各格式及服务端／Web 已检查主要入口，Android 仅确认上述公共路径，仍有完整性边界。TXT 额外做过原文件与 Expat 实验；各格式并未全部注入失败样例。后续移除预判必须验证正常打开、真实解析失败、取消、重开、在线／本地和安全边界，不能靠删掉一个 if 就宣称全链完成。

相关修复与测试状态见 `docs/testing/reader-online-errors-2026-08-28.md`。全格式解析职责调整尚未实施。
