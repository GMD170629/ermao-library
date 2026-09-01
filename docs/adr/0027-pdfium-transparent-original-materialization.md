# ADR 0027: PDFium 透明完整原件物化与全局串行执行

- 状态：采用；物理设备流程验收待完成
- 日期：2026-09-01
- 范围：Android、iOS、KMP Reader、原生 PDFium wrapper 与共享 Downloads
- 修订：ADR 0024、ADR 0025 中“原生 PDF 始终仅使用 Range、不会创建完整下载”的部分

## 决策

Web 继续使用 pdf.js 的在线 Range 阅读，不改变其首屏无需完成整文件传输的
合同。Android 与 iOS 的 PDFium 请求不再直接等同于一次 HTTP Range：引擎可
请求来源文件边界内任意正 `Long` 区间；KMP 只拒绝零长度、溢出和越界。
实际 HTTP transport 仍拆为不超过 1 MiB 的强版本校验 `206` 请求，易失 Reader
缓存仍最多 8 MiB，Range 接口仍禁止用 `200` 返回整文件。

当 PDFium 请求整文件、当前工作集超过易失缓存，或本会话的引擎必需区间覆盖
完整文件时，`PdfRangeLoader` 返回 `CompleteOriginalRequired`。这是存储路由
结果，不是 `PDF_RANGE_INVALID`。Reader 离开 PDFium executor 后调用账号持有的
Downloads 公共用例，创建或加入相同资源及版本的唯一任务；不拼接 Range 缓存，
不实现第二套完整下载、续传、校验或发布流程。

Downloads 完成并验证身份、版本和长度后，平台在同一 PDFium document handle
中把 byte source 原子切到本地随机访问文件，关闭 Range loader、清除易失缓存，
再重试原 document/page step。Reader 不重建页面，不增加下载进度 UI；首次打开
保持加载态，翻页触发时保留已显示页面。完整原件由下载中心持有，Reader 关闭
只取消自身等待与渲染，不删除或取消已创建的普通下载任务。

物化失败、空间不足、版本变化、账号变化或本地读取失败会终止当前 Reader
操作；当前会话不回退远程 Range、不重复启动物化。显式重新打开可创建新会话，
并优先复用已有合格 artifact。

## 线程模型

原生 wrapper 对初始化、创建、推进、页面查询、渲染、关闭和 shutdown 使用
进程级互斥，保证所有 PDFium API 最大并发数为 1。Android 另使用应用级单线程
dispatcher；iOS 使用进程级后台串行 executor。网络、Downloads 等待和文件准备
均在离开 PDFium executor 后执行，本地 source 安装再回到 executor 排队。

PDFium 的同步回调只登记区间、查询已缓存状态或复制内存／本地文件字节；不得
联网、等待下载、访问 UI 或重入 wrapper。主线程只提交 Reader 状态与最终图像。

## 所有权与验证

`DownloadResourceRuntime` 及其平台 adapter 仍是完整原件传输、任务去重、断点
续传、版本校验和原子发布的唯一 owner。`PdfRangeLoader` 只拥有 Range acquisition
和易失缓存路由；平台 PDFium adapter 只拥有 byte-source 切换与线程调度。

自动化必须证明：16,395,773 字节整文件请求返回物化路由且不发送超大 Range；
小区间仍为不超过 1 MiB 的 `206`；非法边界不访问网络；切源后旧响应不能回写；
重复大请求只触发一次会话物化；PDFium API 最大并发为 1；Web 在线 PDF 回归不变。
物理设备还必须检查慢下载期间返回／关闭响应、同一页面继续显示，以及完成后
下载中心可离线重开。构建或模拟器结果不能替代这项设备验收。
