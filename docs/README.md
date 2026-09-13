# 核心架构与现行决策

- [架构决策](architecture-decisions.md)：数据库、导入、会话、Reader、安全与发布约定。
- [工程规范](engineering-standards.md)：依赖方向、事务、类型、错误和国际化边界。
- [代码结构](business-code-layering-and-refactoring.md)：能力归属与运行入口。
- [书库模型](library-root-layout.md)：物理路径、图书、资源与部署挂载。
- [Reader 架构](mobile-reader-architecture.md)：引擎、章节、进度、下载与音频会话。
- [移动端边界](mobile-app-development-global-guidelines.md)：原生 UI、共享状态、书库与书架行为。
- [内容导航](mobile-book-content-navigation.md)：图书、目录、资源、管理与返回语义。

[测试策略与验收](testing/test-execution-policy.md)规定验证范围；`testing/fixtures` 保留代码实际读取的一致性样例。精确安全与视觉规则分别由 `packages/reader-contracts` 和 `packages/design-contracts` 的机器契约拥有。历史设计图、阶段计划和运行报告不再作为当前依据。
