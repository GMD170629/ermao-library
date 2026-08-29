# 流式阅读与统一 Downloads：验证记录

> 历史记录：ADR 0025 已于 2026-08-29 将可重排流式阅读替换为
> “验证完整原文件后本地解析”。本文仅保存当时证据；PDF／漫画的有界在线
> 交付证据在当前架构明确保留的范围内继续有效。

更新时间：2026-08-28。**代码已修改，全端验收未完成。** 这里区分自动化、浏览器实测、服务器测量和真机证据，不将其中一种替代另一种。

## 已运行检查

| 检查 | 结果 |
| --- | --- |
| 后端 `pytest --cov=app --cov-report=term-missing` | 1068 通过；总覆盖率 78% |
| 最终 Publication/导入漫画聚焦测试 | 51 通过 |
| Publication 相关 Ruff 格式与规则检查 | 通过 |
| KMP `:shared:testAndroidHostTest` | 322 通过，0 跳过 |
| Android `:androidApp:testDebugUnitTest` | 146 通过，0 跳过 |
| Android Debug APK、仪器测试 APK | 构建通过 |
| Web `pnpm test` | 399 通过，0 跳过；包含 PWA/service-worker 缓存回归 |
| Web `pnpm typecheck`、`pnpm lint`、`pnpm i18n:check` | 通过；2047 条中英文消息 |
| Web `pnpm build` | 通过；隔离输出目录，未覆盖正在使用的开发构建 |
| Web standalone 生产冒烟 | Chrome 可显示实际 EPUB 第一章；不等于 PWA 安装态验收 |
| 原生漫画主机测试 | libarchive 3.8.9，ZIP/CBZ/RAR5/CBR 各读取两页 |
| 提交空白检查 | 源文件通过；完整暂存检查报告依赖补丁的 13 个空白上下文标记，按 unified diff 格式原样保留 |

`mypy app` 仍失败：3 个未由本任务修改的元数据识别文件中有 7 个类型错误，分别位于 `recognized_metadata.py` 的 application/infrastructure 实现及 `source_node_metadata_recognition.py`。没有降低严格度、增加忽略或改动这些其他任务的文件。

回归覆盖包括：不结束响应也能在头部拒绝错误 Range/超限；关闭客户端取消未完成正文；实际 PDF.js 工作器在其他字节区间被阻断时读取指定页；章节窗口淘汰、并发请求合并、原文件变化、下载暂停恢复/去重/发布后恢复，以及多个 MOBI 元数据别名共用同一原生解析实例。新增章节版本响应同时覆盖 GET 和无正文 HEAD。

## 实际 EPUB

样本为原始《末日生存方案供应商》EPUB，12,870,965 字节、1284 个阅读单元，未生成转换文件。

- 新解析器实例的服务器测量：解析约 139.9 ms；解析后取得首章约 33.75 ms；正文 8185 字节。Python 分配峰值约 6.74 MB，不是客户端缓存峰值。
- 重启测试 API 后，在 Chrome 禁用 HTTP 缓存，并阻断其他 1283 个章节及原文件接口：仍能显示第 1 章，只请求一个 XHTML 正文章节，未请求原文件。
- 观察到首个可读正文约 4082 ms；完成的 Reader 响应合计 2,557,800 字节，含启动/导航元数据、样式和图片。取消请求没有完成字节计数，不计入该合计。
- 网络事件记录未截断。客户端正文缓存峰值尚未测得，不能用配置上限代替测量。
- 另用隔离的 standalone 生产服务完成实际 EPUB 正文冒烟，第一章可见；上面的网络计数仍对应开发服务，未混记成生产性能数据。

原始计数见 [web-epub.json](web-epub.json)；服务器数据见 [server-samples.json](server-samples.json)。浏览器采样结束后已恢复网络阻断和缓存设置。

## 独立 TXT

可重复生成的 1000 章 TXT 为 7,628,893 字节。服务器冷解析约 162.87 ms，首章生成约 0.36 ms、8332 字节；Python 分配峰值约 30.52 MB。其客户端首次可读时间、实际传输量和缓存峰值仍待测量。

另对书库已有的 `7--影子女孩.txt` 进行了浏览器在线功能检查，原文件接口被阻断时正文可见。该文件只有 48 字节，**不能作为大 TXT 性能验收**。

服务器样本可重跑：

```bash
cd apps/api-python
PYTHONPATH=. .venv/bin/python scripts/benchmark_streaming_reader.py \
  --epub '../../books/【多看版】《末日生存方案供应商》作者：_板面王仔（软校全本·L2）V1.0【书眸精制】.epub' \
  --epub-href OEBPS/Text/Vol01-Chapter001.xhtml \
  --output ../../docs/verification/2026-08-27-streaming-reader/server-samples.json
```

## 真机状态

Android 使用物理设备 `9e896bbc`（M2102K1AC），曾执行保留数据的替换安装、冷启动及实际 EPUB 阅读；[android-epub.png](android-epub.png) 是该阶段的正文截图。观察到章节及关联资源请求，未观察到创建 Downloads 目录。

第一轮 Reader 仪器测试 20 项中 9 项失败，不能视为通过。已针对这些失败修复字体安全策略、旧字号断言、进度升级及令牌轮换，并补入 PDFium 三种 ABI、可重复生成的原始 RAR5/CBR 样本。固定版本原生漫画主机测试已通过，**这些修复尚未完成 Android 真机复测**。

后续手机锁屏，已请求用户解锁；没有绕过锁屏或改用模拟器。最新 APK 在 `apps/mobile/androidApp/build/outputs/apk/debug/androidApp-debug.apk`，SHA-256 为 `2F4E56BE9278FE5FA35EDACC6B8ECD6F80B4755CEE3F9F065422F70D88F6A63C`，不能将构建成功写成真机通过。

iOS 没有可用的物理设备/Xcode 运行环境。Swift/KMP 绑定、原生 PDFium 和 Reader 场景仍待编译及真机验收，未运行模拟器。

## 未完成验收

- Android 修复后的完整 Reader、下载入口、空间不足/失败恢复，以及旋转、无障碍和进程恢复真机回归。
- iOS 编译、安装和全部物理设备检查。
- 全格式冷启动、重开、精确恢复、取消、断网重试、账号隔离及资源变化的实网矩阵。
- 大 TXT 客户端测量与各端正文缓存峰值；显式下载所有入口的实网与真机验证。
- PWA 安装态与生产版本的完整端到端检查；生产构建及 EPUB 冒烟不能替代它们。

旧 Reader 下载端口、整文件启动路径、旧状态/文案和相关调用已从本任务的生产代码及规范中移除。其他任务的历史 QA 输出和无关工作树修改保留，不以删除它们制造“全工作树零匹配”的结论。
