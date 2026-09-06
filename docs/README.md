# 项目文档

这里维护当前工作区的运行方式、实现边界与使用规则。代码、配置和机器契约是事实来源；文档中的验收要求不等于已经通过验收。

## 部署与开发

- [部署与数据库初始化](DEPLOYMENT.md)
- [Python API、Worker 与 Windows 开发环境](python-backend-runtime.md)
- [书库根目录、来源树与资源](library-root-layout.md)
- [当前代码结构与维护入口](business-code-layering-and-refactoring.md)
- [iOS Safari／PWA 调试](ios-pwa-debug.md)
- [测试执行分层](testing/test-execution-policy.md)与[手工验收](manual-acceptance.md)

## 阅读与收听

- [Reader 架构、下载、进度与设置](mobile-reader-architecture.md)
- [统一章节解析](reader-chapter-consistency.md)
- [Reader v5 位置报告](adr/0028-reader-v5-opaque-position-report.md)
- [原文件下载后阅读](adr/0025-reflowable-original-download-before-reading.md)
- [原生 PDFium 透明物化](adr/0027-pdfium-transparent-original-materialization.md)
- [安全契约](adr/0026-versioned-reader-safety-policy-contract.md)与[尚待完成的安全验收](reader-safety-v4-verification.md)
- [原生目录面板与验收状态](mobile-reader-toc-verification.md)
- [移动有声书播放器](mobile-audio-player-phase-0-1.md)

Reader 的安全、设置与跨端 wire 定义见 [reader-contracts](../packages/reader-contracts/README.md)，章节核心见 [reader-chapter-consistency](reader-chapter-consistency.md)。不要在说明文档中另建规则或数值目录。

## 移动端

部分文件保留原有 phase 文件名，供既有仓库规则引用；内容按当前功能组织，不再作为从零建设的阶段计划。

- [功能与实现入口](mobile-app-phase-1-web-to-app-functional-baseline.md)
- [导航与信息架构](mobile-app-phase-2-information-architecture.md)
- [用户流程与页面结构](mobile-app-phase-3-user-flows-and-wireframes.md)
- [Warm Page 视觉规范](mobile-app-phase-4-visual-master.md)
- [主要页面构图](mobile-app-phase-5-high-fidelity-anchors.md)
- [服务器与认证](mobile-app-phase-6-server-auth-high-fidelity.md)
- [书库搜索、分组与筛选](mobile-app-phase-7-library-discovery-high-fidelity.md)
- [原生 UI 开发边界](mobile-app-development-global-guidelines.md)与[组件入口](mobile-cross-platform-component-registry.md)
- [图书内容导航](mobile-book-content-navigation.md)与[书架布局](mobile-shelves-row-layout.md)

`assets` 中仍被当前规范使用的图片是设计参考，不是已实现或已验收的证明。
`adr` 保留仍适用的决策与实现边界；已被替代的设计、一次性审计、测试日志和旧设备快照从当前目录移除，需要追溯时查 Git 历史。
