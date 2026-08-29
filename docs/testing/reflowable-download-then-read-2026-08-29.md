# 可重排原文件下载后阅读验收记录（2026-08-29，2026-08-30 收口）

## 当前契约

- EPUB、FB2、TXT、MOBI、AZW、AZW3、PRC 使用
  `DOWNLOAD_ORIGINAL`：授权与最新描述符校验、完整原文件下载、工件校验、本地解析。
- PDF 与漫画使用 `STREAM`；有声书留在播放器；三者不创建 Reader 隐式下载任务。
- 原文件身份是授权 namespace、`resourceId`、`assetId` 与
  `sizeBytes:mtimeMs`，并校验实际格式、MIME 与长度。
- 可重排 Reader v4 bootstrap 不返回服务端 manifest、positions 或章节资源 URL。
  本地 Publication 独占目录、reading order、positions 与精确跳转。
- 禁止在线章节回退、格式转换、派生 EPUB/ZIP、持久化解包目录和解析失败循环重下。

## 实现所有权

- KMP `DownloadResourceRuntime.ensure` 是原生 Reader 与 Download Center 唯一的
  资源下载、恢复、失效清理和重建用例。
- Android/iOS Reader 只拥有加载过渡和任务观察；下载中心已有任务不由 Reader
  擅自停止。Reader 自建任务退出时暂停并保留。
- 原生普通 Library 入口在服务器无权威响应时，可打开当前账号 namespace 与
  `resourceId` 下最新的已验证可重排工件；只允许网络不可达、超时、TLS、服务不可用
  或服务端失败进入该路径。鉴权、禁止、资源不存在、版本冲突和协议错误绝不回退，
  PDF、漫画与有声书也不进入该路径。服务器可达时仍以最新描述符精确匹配版本。
- Web `BrowserPublicationStore` 使用账号授权 namespace 隔离的专用 Cache Storage；
  不创建下载列表或暂停/续传状态。取消、短响应、容量/MIME/版本/长度失败均删除
  未完成条目，下次从零开始。
- Web EPUB 使用完整原文件 Blob 上的 ZIP Fetcher；TXT/FB2 在 Worker 解析；
  MOBI-family 使用 Emscripten 3.1.74 构建的唯一 mobi-core C ABI，并以 WORKERFS
  挂载 Blob。

## 后端与测试书库证据

- Ruff format/check 与 `mypy app` 通过。pytest 收集 1,141 项；排除 Windows 不具备的
  7 个 POSIX symlink、FIFO 和反斜杠文件名语义用例后，1,134 项全部通过，没有新增
  skip、xfail 或放宽断言。
- 当前 API 与 worker 已用本工作区代码重启，`GET /api/health` 返回 200。七种测试资源
  的 Reader v4 bootstrap 均返回精确实际格式、单一原文件描述符、空 `units`，且没有
  `publication`；旧 manifest、positions 与 chapter 路由全部返回 404。
- 测试数据库中 `format=KINDLE`、资源 `adapterId=kindle`、源解释
  `adapterId=kindle` 均为 0。EPUB、FB2、TXT、MOBI、AZW、AZW3、PRC 测试资源均为
  `READY`；四种 MOBI-family 资源统一使用 `mobi-family` 适配器并保存各自实际格式。
- 七个测试文件的观察 `size + mtimeMs` 与磁盘一致。逐一通过媒体端点下载后，长度与
  SHA-256 均和 `books` 下的原文件一致，扩展名与 MIME 精确：EPUB
  `application/epub+zip`，FB2 `application/x-fictionbook+xml`，TXT `text/plain`，
  MOBI/PRC `application/x-mobipocket-ebook`，AZW/AZW3
  `application/vnd.amazon.ebook`。没有生成派生 EPUB、ZIP 或解包出版物。

## Web 证据

- 固定 Emscripten 3.1.74 工具链的 mobi-core ABI/hash 校验、lint、typecheck、
  i18n（2,071 条中英文消息）与 `pnpm test` 均通过；单测 414/414。
- Chromium 与 WebKit 的 Reader 定向回归 50/50 通过：七种真实原文件均验证本地
  TOC、positions、跳转与恢复；损坏/DRM MOBI、恶意 EPUB/FB2 失败关闭；打开后的
  manifest、positions、chapter 请求数为 0。
- WASM 运行产物 SHA-256：module
  `3edb97889238c2d92518120ec6f30391b21ba406c6b5fbc699cf36f06e0019f7`，wasm
  `48940214c74fcc9be2a18784e61dd2ceae39f068ee483cf7cd2c6a1bb311befc`。
- 仓库全量 118 条 Playwright 并发运行是 102 通过、16 失败；Reader 相关 50 条全部
  通过。其余失败位于既有详情页尺寸/菜单、响应式书架、设置懒加载与首次设置流程，
  包含并发导航超时，未把它们改成 skip，也不作为 Reader 通过证据。

## 原生与物理 Android 证据

- KMP `:shared:testAndroidHostTest` 350/350 通过；覆盖确保/重建任务、精确版本、
  `DOWNLOAD_ORIGINAL | STREAM | UNSUPPORTED`、无权威服务器响应时的已验证工件离线
  复开，以及权威错误绝不回退。Android 单测与 `assembleDebug` 通过。
- 物理目标是 `9e896bbc`，Xiaomi `M2102K1AC`，Android 12。首次部署因设备旧包签名
  不同，按测试数据可丢弃授权卸载旧包并清空其数据，随后安装成功。
- 真机实测从详情阅读进入可见下载加载页（0% 起始），完整下载后打开本地 EPUB。
  工件长度 189,231 字节，SHA-256
  `6b79b8f4f74d18134ef4d654b4e43f0655079f8fce7c96aee7823357b759629c`，与
  `books/公开格式测试 - EPUB.epub` 一致。仅删除该工件后再次点击阅读，任务自动重建
  一次并以同一长度与 SHA-256 打开；Android crash buffer 为空。
- navigator prepare/bind 竞态已通过跨配置状态持有者修复并在真机复测后稳定打开。
- 最终 APK 位于
  `apps/mobile/androidApp/build/outputs/apk/debug/androidApp-debug.apk`，大小
  74,067,542 字节，SHA-256
  `0BCE48F44135E929A1EF42BC646A4F6CA3C7577A40D25F934D7D6BF01AA04AC9`。
  2026-08-30 01:03 再次 `adb install -r` 成功，包 `com.ermao.library` 的
  `lastUpdateTime` 已更新且启动后 crash buffer 为空。设备随后处于图案锁定状态，
  因而最后一项“普通 Library 入口断网复开”的新增修复仅完成共享测试，未绕过锁屏做
  新一轮触控验收；此前下载、缺失重建和本地解析真机证据仍有效。

## 唯一待物理验收项

- 当前主机是 Windows，无 `xcodebuild`，没有执行 iOS 原生编译、XCTest、安装或
  物理 iPhone/iPad 验收。必须在明确选择的物理 iPhone/iPad 上完成，不能以模拟器、
  KMP host 测试或静态 revision 校验替代。
