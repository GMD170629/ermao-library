# 当前代码结构与维护入口

本文保留原文件名供仓库规则引用，描述当前实现位置。新代码的分层、复用、事务、类型和测试要求以 [AGENTS.md](../AGENTS.md) 为准；本文不再维护历史重构阶段表，也不把目标架构视为已全部实现。

## 运行与能力边界

| 范围 | 当前入口与职责 |
| --- | --- |
| Web | `apps/web/app` 提供 Next.js 路由，`features` 承载业务功能；存量 `components`、`lib` 与 `i18n` 仍存在。 |
| 后端 | `apps/api-python/app/main.py` 启动 FastAPI；`bootstrap` 装配能力，`modules` 按业务组织，`worker` 执行后台任务。 |
| 数据库 | `apps/api-python/app/db` 保存 SQLAlchemy 模型、Alembic 版本链及启动校验。 |
| Mobile | `apps/mobile/shared` 的 KMP 模块共享业务与网络契约；Android Compose 和 iOS SwiftUI 各自拥有原生 UI 与 SDK 适配器。 |
| Reader | `packages/reader-core` 保存共享阅读契约及原生核心；`packages/reader-contracts` 保存机器契约、生成器和一致性样例。 |
| 视觉 | `packages/design-contracts` 保存跨端视觉 token 的机器源。 |

后端已有 auth、backup、download、imports、kindle、library、media、metadata、mobile、opds、organize、publications、reader、shelf、system 能力。每个能力的实际目录不完全一致，修改前应从 `public.py`、路由装配和调用方追踪归属，不能假定所有存量代码都已完成目标分层。

## 当前关键所有权

- 书库身份为 SourceNode／Book／ReadableResource／ResourceAsset，见[书库结构](library-root-layout.md)。
- 导入的发现、资源识别和任务处理由 imports 能力与 bootstrap 装配协作，HTTP 与 Worker 复用应用入口。
- 第一方阅读进度使用 Reader v5。引擎 Locator 保持不透明，展示进度另行传递，见[Reader 架构](mobile-reader-architecture.md)。
- 章节识别复用[共享章节核心](reader-chapter-consistency.md)，不在详情页和各端 Reader 各写一套解析规则。
- Reader 安全规则唯一源为 `packages/reader-contracts/reader-safety-policy.json`；生成绑定不手改。

## 修改与验证

先寻找同一行为的现有实现与调用方，再在其所属能力内扩展。跨能力通过公开 API 或应用端口协作；依赖装配放在 composition root。不能借局部修复引入新的同义实现，也不能因为目录已经存在就认定依赖方向正确。

[测试执行分层](testing/test-execution-policy.md) 说明检查入口；[手工验收](manual-acceptance.md) 说明运行路径。当前工作区的编译、单元测试结果与物理设备验收分开记录；历史通过次数不能作为当前版本通过的依据。
