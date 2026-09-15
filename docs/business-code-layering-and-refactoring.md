# 当前代码结构与维护入口

本文保留原文件名供仓库规则引用，描述当前实现位置。全仓行为以 [AGENTS.md](../AGENTS.md) 为准，实现细则见 [工程实现规范](engineering-standards.md)，测试选择见 [测试执行策略](testing/test-execution-policy.md)；本文不再维护历史重构阶段表，也不把目标架构视为已全部实现。

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
- 章节识别复用[共享章节核心](mobile-reader-architecture.md#统一章节核心)，不在详情页和各端 Reader 各写一套解析规则。
- Reader 安全规则唯一源为 `packages/reader-contracts/reader-safety-policy.json`；生成绑定不手改。

## 修改与验证

先寻找同一行为的现有实现与调用方，再在其所属能力内扩展。跨能力通过公开 API 或应用端口协作；依赖装配放在 composition root。不能借局部修复引入新的同义实现，也不能因为目录已经存在就认定依赖方向正确。

[测试执行分层](testing/test-execution-policy.md) 说明检查入口；[手工验收](testing/test-execution-policy.md#手工验收) 说明运行路径。当前工作区的编译、单元测试结果与物理设备验收分开记录；历史通过次数不能作为当前版本通过的依据。

## 运行入口

生产统一镜像由固定入口 scripts/container-entry.py 首次初始化并复用 STORAGE_ROOT/runtime，再调用其中的 scripts/start-unified-app.sh 启动 Web、FastAPI、Worker 和单端口网关；业务数据仍位于 STORAGE_ROOT 原有子目录，原书目录单独挂载。目录与验证见[容器程序启动说明](container-runtime.md)。API/Worker 开始工作前验证 schema，初始化与升级遵循架构决策，不在 Web 路由建立第二套后端。

Windows 使用 start-windows.cmd 或 pnpm dev:test:windows，基础解释器在 .runtime-windows/python，环境在 apps/api-python/.venv-windows，日志与 PID 在 .tmp/windows-dev；启动前检查依赖再停止旧实例，Ctrl+C 结束全部服务，不调用 WSL。按 apps/api-python/.python-version 用 uv 安装基础 Python，再设置 UV_PROJECT_ENVIRONMENT 同步 --extra dev --locked；移动目录或删除基础解释器后重建环境，不能只复制 python.exe。独立后端设置见[API README](../apps/api-python/README.md)。

移动 Web 调试用 pnpm dev:ios，Service Worker 调试用 pnpm pwa:ios 的 production 服务，SW 仅 production 注册且需 HTTPS/localhost。真机用服务器局域网地址／HTTPS，不能用设备 localhost；?debug=1/0 控制调试面板，网络与存储通过 Safari Web Inspector 查看。仅启动 Web 不足以验证登录与 API。
