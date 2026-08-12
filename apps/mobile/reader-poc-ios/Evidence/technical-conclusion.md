# 阶段性技术结论

当前结论：**有条件继续**。

核心链路已经得到真机证据：libmobi 可把自制 MOBI6/KF8/AZW3 提取为内存资源，适配器可构建 EPUB profile 的 Readium Publication，Readium 3.11.0 EPUB Navigator 能稳定消费全部 10 本夹具，包括百万 CJK 字符单章。没有生成伪 EPUB，也没有运行时落盘转换。

但本轮证据不足以宣称“可产品化”：新的 DOM 细项探针、完整 Release 耐久矩阵和报告内存/延迟门槛尚未在重连真机后闭合；合法真实样本也不在本次自制夹具范围内。

## 夹具矩阵

| # | 夹具 | 提取/Manifest/预检 | Navigator 首屏 | 细项与压力证据 | 当前口径 |
|---|---|---|---|---|---|
| 1 | 普通 MOBI6 | Pass | Pass | 章节 marker、顺序、TOC Pass；完整耐久待测 | Pass（功能） |
| 2 | KF8/AZW3 | Pass | Pass | 500 翻页 Release 复验待测 | Pass（功能） |
| 3 | CSS AZW3 | Pass | Pass | computed style 探针已实现、待复验 | Awaiting evidence |
| 4 | 内嵌字体 | Pass | Pass | `document.fonts.check` 探针已实现、待复验 | Awaiting evidence |
| 5 | 图片 | Pass | Pass | PNG/JPEG 引用预检 Pass；natural size 探针待复验 | Awaiting evidence |
| 6 | 脚注 | Pass | Pass | 同章/跨章引用和 fragment 预检 Pass；UI 往返待复验 | Awaiting evidence |
| 7 | 复杂 TOC | Pass | Pass | 三级层级、顺序、重复标题和 fragment golden Pass | Pass（功能） |
| 8 | 中文书 | Pass | Pass | UTF-8、生僻字、非 BMP marker 和百万字计数测试 Pass | Pass（功能） |
| 9 | 日文竖排 | Pass | Pass | RTL metadata Pass；computed `vertical-rl`/ruby 待复验 | Awaiting evidence |
| 10 | 超长章节 | Pass | Pass | 100 万 CJK 与首屏 Pass；500 翻页/内存门槛待测 | Awaiting evidence |

`Awaiting evidence` 不是 Fail，也不等同于 Degraded；它表示实现和自动断言已经存在，但因真机连接中断没有完成本次运行证据。只有复验后才能按计划归为 Pass/Degraded/Fail。

## 已确认的实现价值

- OPF spine 是 reading order 第一来源，缺失时才退回 markup 顺序并产生稳定 warning code。
- NCX 解析保留层级、顺序、重复标题和 fragment；标题不承担程序标识职责。
- libmobi 的 markup/flow/resource 名称保留，相对 CSS、图片和字体引用可以直接通过内存 Container 服务。
- Publication 构建前会读取全部资源，并检查 HTML/CSS 内部引用、路径越界和 HTML fragment。
- DRM/KFX/AZW4/损坏输入不会静默“尽量打开”。C 对象在成功和失败路径均由 bridge 统一释放。
- `MobiPublicationParser`、`MobiFormatSniffer` 和 `InMemoryMobiContainer` 已拆成可迁移到正式 Reader capability 的边界类型。

## 下一道决策门

物理设备恢复后，应保持依赖和夹具 SHA 不变，按以下顺序闭合证据：

1. 重跑 10 本 DOM 探针；CSS、字体、图片、脚注、竖排任何失败先归因到 libmobi 输出、Container MIME/路径或 Navigator publisher style。
2. Release 运行 `basic-kf8` 与 `long-chapter` 500 次翻页，导出 `ReaderPOCReports`，先验证延迟和内存采样链路。
3. 运行完整 10 本耐久矩阵和 20 次冷开关；确认关闭后无持续线性内存增长。
4. 若全部基础项 Pass，再加入合法取得的非 DRM 真实 MOBI/AZW3 样本；真实样本通过前不要把适配器接入正式 Reader v3。

若竖排只能 Degraded，但基础 MOBI/KF8/CSS/图片/中文/长章均 Pass，可以继续产品化并单列竖排兼容修复；若长章出现数据丢失、不可控内存增长或 Navigator 持续无响应，应放弃直接 Publication 映射路径。
