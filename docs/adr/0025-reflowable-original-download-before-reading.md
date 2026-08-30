# ADR 0025: 可重排原文件下载后阅读

- 状态：采用；物理设备验收进行中
- 日期：2026-08-29
- 范围：Web、Android、iOS、Reader v4 与共享 Downloads
- 取代：ADR 0024 中的可重排 online-first／Web online-only 决策

## 决策

`EPUB`、`FB2`、`TXT`、`MOBI`、`AZW`、`AZW3`、`PRC` 在所有第一方
Reader 中统一使用完整原文件：启动时验证本地工件，缺失或版本过期时显示
Reader 加载页和真实传输进度，完整校验成功后由本地解析器创建内存
Publication。阅读入口与详情文案不暴露新的产品模式。

PDF 和漫画继续使用现有页面／Range 在线交付，不因在线错误隐式下载；有声书
继续由播放器能力负责。通用在线可读性判定、可重排 RWPM／positions／章节
交付以及 `OnlineLimit`／`RangeUnsupported` 下载回退被删除。

下载工件以 `namespace + resourceId + assetId + size:mtime` 标识，并校验实际
格式、MIME 与长度。原文件是唯一持久化 Reader 正文；不得转换、持久化解包
目录或生成派生出版物。2 GiB 准入以及 DRM、XML、ZIP、图片、分配和解析器硬
限制继续生效。

## 所有权

原生完整传输、断点续传、任务状态、重建、原子发布和完成登记仍只有共享
Downloads 一个 owner。Reader 通过公共用例创建或观察卷册任务。缺失工件由
同一用例清除失效任务并按最新描述重建；本地解析失败不触发重新下载。

Web 复用同一 Library／媒体原文件合同，但只实现 Reader 私有的 Cache Storage
adapter，不建立下载中心、暂停、续传或账号切换任务状态机。取消删除未完成
缓存并从零开始；缓存按账号授权命名空间及精确资产版本隔离。冷启动仍需要
在线授权和同步 bootstrap。

正文来自本地与进度／书签同步相互独立。已下载的原生文件可以先离线打开，
认证会话继续使用现有非阻塞同步；Web 已打开的会话不再依赖正文网络请求。

## 接口后果

Reader v4 的可重排 bootstrap 只提供授权、元数据、进度和书签上下文，不生成
导航，也不返回 manifest、positions 或章节资源 URL。本地 Publication 的
reading order、目录和 positions 为客户端正文权威来源。服务端保存进度时只
校验有界、相对且与资源形态匹配的 Locator 合同，不为 href 校验重新打开或
解析可重排原文件。服务端解析基础设施只保留给导入和元数据等仍有消费者的
能力。Library 的卷册 `reading-units` 接口属于详情元数据能力，按 ADR 0012
在首次访问时同步解析缺失目录并按当前 `assetId` 缓存；它不向 Reader 提供正文、
manifest、positions 或章节资源，也不改变下载后阅读契约。

共享启动策略公开 `DOWNLOAD_ORIGINAL | STREAM | UNSUPPORTED`，替代
`canOpenOnline`。七种可重排格式映射到 `DOWNLOAD_ORIGINAL`，PDF／漫画映射到
`STREAM`。任何平台都不得用在线正文作为可重排失败回退。

## 验证

验收必须证明：慢速响应未完成时进度已更新且 Reader 未打开；完成工件命中不
重复传输；取消不能发布部分文件；删除文件或浏览器缓存后按同一 `resourceId`
和最新资产版本重建；打开后没有可重排 manifest／positions／章节请求；PDF、
漫画和音频未创建隐式任务；三端原文件长度和 SHA-256 与媒体端点一致且没有
派生出版物。Android 与 iOS 最终证据必须来自明确选择的物理设备。
