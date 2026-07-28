# 后台 OpenAPI 全量实际检查

## 结论

已对 OpenAPI 中 **178 个 method + path** 全部发起实际 HTTP 请求，覆盖 **16 个模块**。FastAPI 注册路由、OpenAPI 文档和实测集合均为 178，三者无缺口，也没有隐藏路由。

初次检查发现 **12 个实际 500 接口**，其中多项写接口在数据库提交后才因响应模型不匹配失败。2026-07-28 的修复复测已将这 12 个接口全部恢复为 HTTP 200；同时补查并修复了“存在真实重复组时”的 `GET /api/library/duplicates` 数据型 500。仍有 **40 个接口实际读取请求体但 OpenAPI 没有 requestBody**，本轮按既定范围未处理。

SMTP 检查使用真实连接但测试环境没有 SMTP 服务，因此只确认了失败路径，未声称发信成功。元数据外部提供商同样按实际网络结果记录。下载链路则使用本地 HTTP 服务真实下载 EPUB 并核对文件和数据库状态。

## 模块汇总

| 模块 | 接口数 | 实际 500 | 文档缺陷接口 | 报告 |
|---|---:|---:|---:|---|
| 认证与账号 | 14 | 0 | 0 | [auth.md](auth.md) |
| 用户管理 | 6 | 0 | 0 | [users.md](users.md) |
| 用户偏好 | 2 | 0 | 0 | [preferences.md](preferences.md) |
| 系统管理与备份 | 13 | 0 | 3 | [system.md](system.md) |
| 健康检查与队列控制 | 10 | 0 | 1 | [health.md](health.md) |
| 元数据提供商 | 6 | 0 | 3 | [metadata.md](metadata.md) |
| 导入与监控目录 | 17 | 0 | 5 | [imports.md](imports.md) |
| 媒体文件与封面 | 9 | 0 | 0 | [media.md](media.md) |
| 阅读器 V1 退役接口 | 10 | 0 | 0 | [reader-v1-retired.md](reader-v1-retired.md) |
| 阅读器 V2 | 6 | 0 | 0 | [reader-v2.md](reader-v2.md) |
| 书库管理 | 35 | 0 | 15 | [library.md](library.md) |
| 书架 | 5 | 0 | 2 | [shelf.md](shelf.md) |
| 整理与识别 | 9 | 0 | 1 | [organize.md](organize.md) |
| 外部下载源（退役） | 17 | 0 | 5 | [download-sources.md](download-sources.md) |
| 下载任务 | 9 | 0 | 3 | [download.md](download.md) |
| 邮件与 Kindle | 10 | 0 | 4 | [kindle.md](kindle.md) |

## 高风险发现

1. ✅ 已修复分类重命名、分类合并、分类删除、操作撤销、版本修改、重复作品合并的后置响应序列化 500，并逐步核对数据库写入。
2. ✅ 系统事件 metadata 改为受约束的递归 JSON 契约，事件列表和管理概览可返回系统真实产生的嵌套 metadata。
3. ✅ 书库 facets/categories/duplicates/operations 与整理 runs 的投影已和响应模型重新对齐。
4. 40 个手工解析 `Request` 的写接口没有 requestBody，调用者无法从 OpenAPI 得知请求结构；多个创建接口实际返回 201，但文档只列 200。

## 原始证据

- `actual-results/runtime-full-2026-07-28.json`：189 次请求记录；包含重试和无效参数纠正，178 个唯一 method + path 全覆盖。
- `actual-results/openapi-2026-07-28.json`：本次运行服务的 OpenAPI 快照。
- 每条记录包含实测路径、状态码、响应摘要、是否在 responses 中、响应 envelope 检查和请求前后数据库表摘要差异。

## 验证说明

- 首次隔离库初始化通过 `POST /api/auth/setup` 实际返回 201；随后同接口重复请求按契约返回 409，用于同时验证初始化保护。
- 所有文件类输入均实际构造：TXT、最小 EPUB、CBZ/PNG、封面、下载源文件。
- 对需要特定状态的重试/取消/撤销接口，仅用 ORM 设置测试前置状态；接口行为本身均通过 HTTP 发起，并记录接口导致的数据库变化。

## 修复复测

- 新增契约回归覆盖 system、library、organize 三个故障簇及 13 条数据型接口路径。
- 全量后端测试：`448 passed, 5 skipped`。
- 重启 `localhost:8000` 后使用真实登录会话逐条请求：原 12 条 500 及相邻的重复组查询均返回 HTTP 200。
- ORM 复核确认：分类重命名/合并/删除及撤销、版本名更新、来源作品隐藏、版本迁移和操作状态均正确持久化；旧 `scopeJson={}` 保持原始数据不变，仅在读取投影中补齐默认 scope。
