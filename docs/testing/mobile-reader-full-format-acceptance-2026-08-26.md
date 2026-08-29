# Mobile Reader 全格式真机验收记录（2026-08-26）

> 历史证据说明：本记录中的泛化 `KINDLE` 目录兼容与清理行为已被当前架构
> 契约取代。现行系统不接受或迁移 `KINDLE`，而是从导入开始直接持久化
> `MOBI`、`AZW`、`AZW3`、`PRC`；本文件保留旧结果仅用于追溯当时验收。

## 范围与判定

本记录覆盖 Reader 的原始格式 EPUB、MOBI、AZW、AZW3、PRC、FB2、TXT、
PDF、CBZ、ZIP、CBR、RAR 与 IMAGE_DIR。音频不在本次范围内。文件只通过
FLAT/VOLUMES 书库落盘与正式 `SCAN_LIBRARY` 队列导入；没有直接写数据库，
也没有生成派生 EPUB、ZIP 或解包出版物目录。

`READY` 只证明正式扫描、识别和 Asset 导入成功，不等同于真机阅读验收。
每一格式必须在物理 iPhone 和物理 Android 上分别完成在线阅读、翻页/跳转、
进度恢复、下载、断网本地阅读及冷启动恢复后，才能标记为 `ACCEPTED`。

## 正向语料与导入结果

| 格式 | 正式扫描相对路径 | 来源与授权记录 | SHA-256 | Resource ID | 扫描结果 |
| --- | --- | --- | --- | --- | --- |
| EPUB | `祈祷落幕时_东野圭吾_z_library_sk__1lib_sk__z_lib_sk.epub` | 用户本地书库文件；不随仓库再分发，授权状态不作断言 | `a0ca2523808d749d433e2ef2b4239f0e5fe7b47800f9895a8c923e529b651091` | `py_db7f936c9cda4a5a865892029c18d1ff` | READY |
| MOBI | `Reader Sample 01.mobi` | 仓库自编 Calibre 测试语料，见 `test-data/library/mobi/CORPUS.md` | `43ddc428751b26d116c2a39e12e94802fdf4a2f915bf8c965b26964e0d7b95cd` | `py_595610912b194b62b5ed6249e8f10ff1` | READY |
| AZW | `Reader Sample 02.azw` | 上述自编 MOBI6 原始容器的扩展名变体 | `43ddc428751b26d116c2a39e12e94802fdf4a2f915bf8c965b26964e0d7b95cd` | `py_bd18d6965bea45148b5ed6249e8f10ff1` | READY |
| AZW3 | `Reader Sample 03.azw3` | 仓库自编 Calibre 测试语料，见 `test-data/library/mobi/CORPUS.md` | `528c43db8b2df3190dbf42f96fe6be68391d9239a186fb77d0670dda832863dc` | `py_35ecd0b1eb7b4e90ad34f38fdbff4465` | READY |
| PRC | `Reader Sample 04.prc` | 上述自编 MOBI6 原始容器的扩展名变体 | `43ddc428751b26d116c2a39e12e94802fdf4a2f915bf8c965b26964e0d7b95cd` | `py_ebca357a7b514141a4a1b1fb6fe02965` | READY |
| FB2 | `source_test_book_fb2.fb2` | `sample_reading_media`，LGPL-2.1；固定提交与路径见 `test-data/library/fb2/CORPUS.md` | `309f2293575c8165291e89165ed77a57095cd20727a57eb1ba227364ae79a693` | `py_8186253e6f534ff8a79ff9eac97d9697` | READY |
| TXT | `[综英美]哥谭市长模拟器.txt` | 用户本地书库文件；不随仓库再分发，授权状态不作断言 | `92af8c57eb9fdcad8254e078a62c40ac9da894e7e3199ce03f873b7a2db75d3e` | `py_8614f4706d094ec3812e1480d7556b2c` | READY |
| PDF | `矛盾论 (毛泽东).pdf` | 用户本地书库文件；不随仓库再分发，授权状态不作断言 | `31d6989e79cd42b2c2609b2e067ed366c8fb33a299ca194f3a5c8a76f09c4deb` | `py_33433bef4ed54276b4be9a054df68587` | READY |
| CBZ | `星港巡夜人/01 启航.cbz` | 仓库本地漫画测试语料；仅用于本项目测试，未声明对外再分发许可 | `8f7d9f9295b9d622b042034f457e6e7b318699f411cca506ea35a06c4c54444b` | `py_6d0a58e2f90d41f5bcb278615f6b3b4f` | READY |
| ZIP | `山海邮差/01 青鸟来信.zip` | 仓库本地漫画测试语料；仅用于本项目测试，未声明对外再分发许可 | `0b2f0ed9a8319bcf83a02e69439aaaec6fe7bf759d493dbe7c5addc4ca874607` | `py_ffc151b4bf1644d89cac6e8fb6313d03` | READY |
| CBR | `星港巡夜人/单行本/02 雾港来客.cbr` | 仓库本地漫画测试语料；仅用于本项目测试，未声明对外再分发许可 | `ff24166523e45cbc537a734c4cfa3c8313ae73be8eb2ca596b7dbe664d9192d6` | `py_e6501e8c51844820b08919deea9254ab` | READY |
| RAR | `山海邮差/单行本/02 雨师借伞.rar` | 仓库本地漫画测试语料；仅用于本项目测试，未声明对外再分发许可 | `c44581fefb77796942e4ede80c82ed1654fe4d7b8ceaeb54c5876b594268a19f` | `py_a483abf2783142ec8a3301153294580e` | READY |
| IMAGE_DIR | `星港巡夜人/原始图片目录`（`01.png`、`02.png`） | 仓库本地原始 PAGE 测试语料；仅用于本项目测试，未声明对外再分发许可 | 两页均为 `427461f2fcbf52582b54a99e6ba0f08dd2bd9fa11f594ee0858db4b0bb46a36d` | `py_c157833c02c448e58d4a884c1a9f0760` | READY（2 PAGE） |

当前契约要求 MOBI、AZW、AZW3、PRC 在数据库和 Reader v4 边界均使用精确
格式，不再从泛化资源族或文件名恢复。对应 `sourceFormat` 依次为
`mobi`、`azw`、`azw3`、`prc`；对应 canonical MIME 依次为
`application/x-mobipocket-ebook`、`application/vnd.amazon.ebook`、
`application/vnd.amazon.ebook`、`application/x-mobipocket-ebook`。

## 真机证据状态

| 平台 | 设备 | 当前状态 | 验收结论 |
| --- | --- | --- | --- |
| iOS | iPhone 17 Pro Max，iOS 26.6，设备标识 `00008150-0011112211A0C01C` | 已完成在线阅读、13 格式原始下载、服务端关闭后的 Download Center 本地打开、翻页/滑动、强制终止与冷启动恢复 | ACCEPTED；全部证据来自签名 `iphoneos` 应用和物理 iPhone，未使用 Simulator |
| Android | 物理设备 | `adb devices -l` 当前无设备 | PENDING；未启动或选择 AVD |

## iOS 真机点击结果

本轮使用签名的 `iphoneos` Debug 应用 `1.0.0 (1)`。以下均来自上述物理
iPhone 的作品详情“阅读”入口，而不是编译或 Simulator：

| 格式 | 在线正文/页面 | Download Center 断网打开与冷启动 | 导航操作 | 当前判定 |
| --- | --- | --- | --- | --- |
| EPUB | 已渲染 | PASS | 下一页、横向滑动、退出及恢复已执行 | ACCEPTED |
| MOBI | 已渲染 | PASS | 控制层恢复、下一页、横向滑动、退出及恢复已执行 | ACCEPTED |
| AZW | 已渲染 | PASS | 控制层恢复、下一页、横向滑动、退出及恢复已执行 | ACCEPTED |
| AZW3 | 已渲染 | PASS | 下一页、横向滑动、进度跳转、退出及恢复已执行 | ACCEPTED |
| PRC | 已渲染 | PASS | 下一页、横向滑动、退出及恢复已执行 | ACCEPTED |
| FB2 | 已渲染 | PASS | 下一页、横向滑动、进度跳转、退出及恢复已执行 | ACCEPTED |
| TXT | GB18030 尾部 NUL 兼容修复后已渲染真实正文 | PASS | 下一页、横向滑动、进度跳转、退出及恢复已执行 | ACCEPTED |
| PDF | 已渲染 | PASS | 下一页、横向滑动、退出及恢复已执行 | ACCEPTED |
| CBZ / ZIP / CBR / RAR | 均已渲染真实漫画页面 | PASS | 下一页、横向滑动、退出及恢复已执行 | ACCEPTED |
| IMAGE_DIR | 已通过 Reader v4 PAGE 流渲染 | PASS | 下一页、横向滑动、退出及恢复已执行 | ACCEPTED |

iOS 的 `ACCEPTED` 只表示本节所列物理 iPhone 验收完成；Android 仍必须由物理
ADB 设备独立执行同一旅程，不能用 iOS、JVM 单测或模拟器证据替代。

## 进度、构建与崩溃证据

- 真机 Reader v7 数据库显示 EPUB、PDF、CBZ、ZIP、CBR、RAR、IMAGE_DIR 已有
  `confirmedRevision`；证明这些格式的精确位置已通过 Reader v4 服务端校验。
- AZW3 与 FB2 的旧 pending 记录曾为 `READER_LOCATOR_RESOURCE_INVALID`。根因分别
  是验收 API 漏传 pinned libmobi 动态库，以及 FB2 原始样本声明
  `xmlns:xlink` 却使用 `l:href`。API 已按正式启动契约加载 pinned runtime；FB2
  仅在内存解析边界重绑定该标准链接属性，原始文件保持不变，其他未绑定前缀仍
  会失败。MOBI 与 FB2 精确进度 HTTP 合约现已通过。
- 后端全量：`1062 passed, 1 warning`；Reader/Publication 聚焦套件：
  `68 passed`；四个修改文件的 Ruff format/check 通过。
- 精确物理 destination 的 iOS `build-for-testing` 已完成并签名：
  `** TEST BUILD SUCCEEDED **`。这不是运行时验收替代品。
- 物理 iPhone 上，TXT 尾部 NUL 解码与作品描述纯 Swift HTML-to-text 的三项修复
  回归测试通过，证据为
  `Test-ErmaoLibrary-2026.08.26_14-58-00-+0800.xcresult`。
- 物理 iPhone 上，AZW3、FB2、TXT 的修复后在线 Reader 旅程（真实正文、下一页、
  横向滑动与截图）通过，证据为
  `Test-ErmaoLibrary-2026.08.26_14-58-29-+0800.xcresult`；TXT 的进度跳转、关闭重开
  与恢复旅程通过，证据为
  `Test-ErmaoLibrary-2026.08.26_15-02-48-+0800.xcresult`；AZW3 的同等进度/重开旅程
  通过，证据为
  `Test-ErmaoLibrary-2026.08.26_15-15-14-+0800.xcresult`。
- 物理 iPhone 上，旧目录中 4 条泛化 `KINDLE` 记录及原始工件已在目录加载时删除；
  不进行格式推断或迁移。精确格式与删除回归测试通过，证据为
  `Test-ErmaoLibrary-2026.08.26_16-09-58-+0800.xcresult`。
- 物理 iPhone 上，13 种格式的正式原始下载旅程全部通过，证据为
  `Test-ErmaoLibrary-2026.08.26_16-10-47-+0800.xcresult`。设备目录独立复制校验为
  13 条 `completed + verified` 记录，期望字节数与接收字节数一致，工件均存在且没有
  `KINDLE`：MOBI/AZW/AZW3/PRC 分别保存为 `.mobi`、`.azw`、`.azw3`、`.prc`；
  IMAGE_DIR 为 v4 `OriginalPageSet`，包含按序验证的两个原始 PNG PAGE 成员。
- Download Center 已改为纯本地入口：已验证工件不再请求 Reader bootstrap，也不创建
  远程进度或书签同步端口；精确位置仍写入设备本地数据库。下载行已设置完整矩形命中
  区域，修复点击行中间透明区域不触发打开的问题。
- 物理 iPhone 上，本地进度不产生待上传任务、精确 Kindle 家族格式保留、旧泛化
  `KINDLE` 下载直接删除的 3 项测试通过，证据为
  `Test-ErmaoLibrary-2026.08.26_16-50-03-+0800.xcresult`。
- 服务端保持关闭时，物理 iPhone 的 13 格式 Download Center 完整旅程全部通过：逐格式
  点击、真实正文/页面、下一页、横向滑动、截图、强制终止、冷启动及再次本地打开均成功，
  且没有中英文“无法打开图书”错误。证据为
  `Test-ErmaoLibrary-2026.08.26_16-50-34-+0800.xcresult`，耗时 227 秒、1 个旅程通过、
  0 失败；结果包内含 13 张 `live-reader-<format>-offline` 截图。
- Android 目录加载同样会删除泛化 `KINDLE` 记录、已完成工件与精确关联的 partial/bundle；
  capability registry 只接受 MOBI/AZW/AZW3/PRC。Android 全量 JVM 单元测试通过。
- Android debug APK、androidTest APK 与相关全格式策略/TXT 聚焦单元测试已构建
  通过；因 `adb devices -l` 无物理设备，未安装、未运行 instrumentation。
- Android `lintDebug` 仍被 4 个既有、非 Reader 错误阻断，首个为
  `AndroidCoverSelectionReader.kt` 的旧 `android.media.ExifInterface` 用法；未降低规则，
  也未在本次 Reader 能力内扩展修复。
- 真机崩溃目录有一条 `2026-08-25 13:42:33` 的 Retired 历史记录，堆栈位于
  `WorkDetailView.normalizedDescription` 的 UIKit HTML 转换，而非 Reader 引擎。
  该入口已改为纯 Swift、有边界的 HTML-to-text 处理，完全移除该 Objective-C
  易崩调用。完成上述 13 格式断网冷启动旅程后再次枚举系统崩溃目录，仍只有这一条
  `2026-08-25` Retired 历史记录，没有 `2026-08-26` 新增 ErmaoLibrary crash 或 ANR。

连接 Android 真机后，每个格式还需分别记录作品详情在线阅读和 Download Center
断网打开的点击时间、正文/页面截图、前后导航、目录/页码跳转、进度与冷启动恢复
结果，以及本轮之后的 crash/ANR 日志。未完成这些记录前不得把本文件状态改为
双平台 `ACCEPTED`。
