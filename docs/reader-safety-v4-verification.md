# Reader 安全实现与待验收项

文件名中的 v4 指安全策略版本，不是阅读进度协议。当前进度协议为 Reader v5。
安全规则唯一源是 [reader-safety-policy.json](../packages/reader-contracts/reader-safety-policy.json)；绑定、样例与检查入口见 [Reader contracts](../packages/reader-contracts/README.md)。

## 当前实现

- 未知声明、标签、实体名称和 MIME 元数据本身不导致安全拒绝；以具体风险黑名单处理，在内存中清理可恢复内容。
- Web、后端、KMP 与原生适配器复用生成规则；XML、归档、引擎和平台防护在各自适配器执行。
- 原生控制文档在 PublicationOpener 打开前通过受保护容器，正文和延迟资源复读使用同一保护入口。
- 安全、解析、解密、完整性、容量和平台实现失败分别归类；不为生成报告引入生产规则事件历史或出版物图重分类框架。
- 原文件、原始下载缓存和 Reader v5 进度不因清理而改变。详细语义见 [ADR 0026](adr/0026-versioned-reader-safety-policy-contract.md)。

## 尚未闭合的验收证据

以下是 2026-09-05 工作记录留下的缺口，不代表本次文档整理重新执行了测试：

- 原生实际图书验收尚未完成；移除 trace-only 实现后的版本尚未重新安装到 Android 真机验证。
- iOS 适配器审查与实际执行仍未完整闭合，需要物理设备，不能用 KMP 报告替代。
- Windows WebKit 在重载后丢失 Cache Storage；独立最小案例也能复现。真实 iPhone Safari／PWA 的重开不重复下载证据仍需补齐。
- 较广的 Chromium／WebKit Reader UI 套件仍有六项失败：两个 Locator 字段断言和一个竖排设置断言分别影响两种引擎，尚需归因。
- 两个后端符号链接测试受 Windows 创建链接权限限制，尚需在可创建链接的环境执行。

复验应运行生成器 `--check`、Reader safety boundary checker、对应平台适配器与真实阅读链路，验证可读输出、无外部危险请求、原始字节不变、缓存重开及取消／重试。历史通过次数与本机日志路径不作为当前版本通过证明。
