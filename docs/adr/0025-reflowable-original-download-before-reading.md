# ADR 0025: 可重排原文件下载后阅读

- 状态：Accepted
- 范围：Web、Android、iOS、KMP Reader 与 Downloads
- 相关：安全由 [ADR 0026](0026-versioned-reader-safety-policy-contract.md) 统一定义；
  原生 PDFium 交付由 [ADR 0027](0027-pdfium-transparent-original-materialization.md) 补充；
  progress 由 [ADR 0028](0028-reader-v5-opaque-position-report.md) 定义。

## 决策

`EPUB`、`FB2`、`TXT`、`MOBI`、`AZW`、`AZW3` 和 `PRC` 在第一方 Reader 中使用完整
原文件。`packages/reader-core/src/format-capabilities.ts` 将这些可重排格式映射到
`DOWNLOAD_ORIGINAL`。Native Reader 启动时取得授权的 asset 描述，缺失、过期或不合格时
由共享 Downloads 用例传输并校验原文件；完成原子发布后，平台本地 parser 创建内存
Publication。Web 复用同一原文件 contract，通过 Reader 私有 Cache Storage adapter 管理
浏览器缓存。

原文件是唯一持久化正文。任何路径都不得生成派生 EPUB、ZIP 或持久解包目录；安全、MIME、
格式、长度、容量和 parser/engine 失败按 ADR 0026 的稳定 rule ID 与错误类别处理。Reader
本身不启动第二套下载、修复或在线回退流程。

漫画格式与 `image_dir` 继续使用有界流式 manifest/page 交付。PDF 普通请求优先 Range，
当 PDFium 按 ADR 0027 需要完整原件时透明复用 Downloads 的合格 artifact；Web PDF 与
漫画的既有在线合同不因此改变。有声书使用播放器能力和同一安全 contract，不隐式创建
可重排下载任务。

Reader v5 bootstrap 提供授权的资源、asset、格式和状态上下文；可重排内容的正文、reading
order、TOC 与 positions 来自本地原文件和 parser。Library 的 `reading-units` 是详情元数据
projection，按 [ADR 0012](0012-publication-navigation-cache.md) 懒加载当前 asset，不是
Reader 正文或 manifest/positions 传输。

Web 只使用账号授权命名空间下的 Reader Cache Storage adapter；它不创建原生 Downloads
中心的任务状态机。Native Downloads 由共享 `DownloadResourceRuntime` 唯一拥有，单项、批量
和 Downloads UI 都调用同一用例。

## 验收约束

必须验证慢传输完成前 Reader 不打开、完整工件命中不重复传输、取消和截断不发布可读文件、
删除缓存后按相同资源/asset 版本重建，以及打开可重排内容不会请求远程正文章节。验证须
覆盖实际平台；Android/iOS 物理设备证据不能由编译或模拟器替代。

## 当前证据

Reader v5 route and Web adapter use `/api/reader/v5`; `reader-core` format capabilities expose
the delivery modes above; Downloads and PDFium adapters implement the ownership split. Safety
and generated bindings remain owned by `packages/reader-contracts/reader-safety-policy.json`.
