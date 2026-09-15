# 应用更新包与下载准备（第 2 批）

本批提供检查、下载、校验与解压。`ready` 仅表示包准备完成，不代表已安装。没有停止业务、覆盖 runtime、迁移或重启入口，也没有安装页面。固定入口与程序目录继续遵循[容器运行说明](container-runtime.md)。

## 程序包与构建环境

包为 gzip tar，解压根目录直接对应 runtime。内容来自生产镜像的 `/opt/shuku-image`：Next standalone 的 Web 代码、node_modules、静态资源和 public，Python app（包含迁移），pyproject.toml、uv.lock、统一启动脚本与网关，以及 `application.json`。

只打包允许的程序路径；排除 storage、secrets、`.env*`、`.venv`、`.git`、Python 字节码与 `.next/cache`。固定入口、环境解释器、镜像原生库不进入程序包。打包器拒绝外部或悬空链接、版本不一致的产物，以及已初始化的 runtime；不应对用户运行目录打包。

Dockerfile 在依赖安装和原生库构建完成后调用 `scripts/build-runtime-environment.py`，生成：

- `/opt/shuku-launcher/environment.json`：固定环境描述与构建清单，不参与日常覆盖。
- `/opt/shuku-image/application.json`：应用版本与该产物要求的环境标识。

兼容标识为规范化构建清单的 SHA-256，包含平台／架构、Python 版本与 ABI、解释器和 Node 二进制摘要、已安装 Python 依赖版本及 RECORD 摘要、系统包版本、两个固定原生库摘要和 Web basePath。应用自身版本不参与环境指纹。真实运行依赖或原生库发生变化时会改变标识；不会在线安装依赖以尝试补齐。

后端只读取固定目录的环境信息，且要求 Linux、实际代码位于 runtime、初始化标记存在、固定入口正在持有 launcher.lock。旧部署缺少固定环境信息或没有固定入口时返回不支持，不根据待安装包自报的信息推导本机环境。

### 生成包

使用包含本批代码的现有镜像构建产物，运行打包器（无需重新执行前端构建或安装依赖）：

```sh
python scripts/build-application-package.py \
  --program-root /opt/shuku-image \
  --output-dir /tmp/application-package
```

打包器使用项目 API 依赖环境，脚本在源码工具目录运行。输出 `shuku-<version>-<platform>.tar.gz` 和对应 `.tar.gz.json` 清单，包含版本、格式、环境、受控资产文件名、压缩大小、SHA-256、展开文件大小与条目数。校验 pyproject、API 默认运行版本、Web package.json 与 application.json 的版本一致。

## 官方来源及接口

继续读取固定官方 release-feed 的 `index.json`。现有 `schemaVersion: 1` 和版本字段不变；版本条目可选新增 `appPackages` 数组，数组元素为打包器生成的清单。没有该数组的历史版本返回 `PACKAGE_UNAVAILABLE`，不会猜测下载包存在。正式发布流程写入数组仍属于第 4 批，本批没有修改远程 feed 或发布资产。

资产定位固定为官方仓库的 `releases/download/v<version>/<filename>`。仅 HTTPS，重定向仅接受 GitHub 的 release-assets/objects 下载域名；下载地址、路径、命令不作为接口参数。测试只通过 Python 构造参数注入本地连接，不提供正式 URL 配置项。

| 接口 | 内容 |
| --- | --- |
| `GET /api/updates/check` | 当前版本、部署支持状态、各正式版本是否可准备及原因码 |
| `POST /api/updates/prepare` | JSON `{"version":"1.0.4"}`；返回 202 和持久化初始状态，重复进行中的操作返回 409 |
| `GET /api/updates/status` | 最近一次准备的阶段、目标清单、已下载字节、时间和失败码 |

接口均复用系统管理权限；应用用例也检查授权。保留现有 SameSite=Lax 会话，准备接口拒绝额外 JSON 字段和 cross-site 浏览器请求。未登录及普通成员不能读取状态或触发准备。当前及更旧版本被拒绝，权限委派遵循现有 `can_manage_system` 规则。

## 状态与运行边界

API 生命周期拥有一个准备线程。接受请求后，浏览器断开不取消任务；API 正常退出时会取消并等待该线程，不遗留无主任务。跨请求及跨 API 实例用 `update-tmp/prepare.lock` 互斥。

- `update-tmp/preparation.json`：最近状态，原子写入；阶段为 downloading、verifying、extracting、ready 或 failed。
- `update-tmp/prepared/application.tar.gz`：已下载包。
- `update-tmp/prepared/app/`：仅本次临时解压结果。

中断后，已无持锁者的进行中状态标记为失败，不自动恢复下载。失败记录阶段及稳定原因码，不保存私有路径或签名下载 URL；持久化本身失败时输出明确容器日志。重新准备只清理专用 prepared 目录。

限制：压缩包 512 MiB、文件总展开量 2 GiB、条目 100,000；清单 1 MiB；网络单次阻塞超时 10 秒、包下载总读取期限 600 秒、解压期限 300 秒。解压额外限制 tar 元数据开销。提前检查磁盘余量、实际临时目录写入能力和 runtime 写权限；不向 runtime 写测试文件。所有常规文件写入结束后才创建合法内部链接，拒绝链接逃逸、特殊文件、重复路径和越界名称。

## 定向验收与缺口

```sh
pnpm --filter @shuku/web build
apps/api-python/.venv/bin/python -m pytest apps/api-python/tests/integration/modules/updates/test_preparation.py -q
apps/api-python/.venv/bin/python -m pytest apps/api-python/tests/test_capability_architecture.py apps/api-python/tests/test_openapi_quality.py -q
apps/api-python/.venv/bin/python -m mypy --follow-imports=silent apps/api-python/app/modules/updates apps/api-python/app/bootstrap/updates.py
pnpm --dir apps/web exec tsx --conditions=import --test features/updates/model/release-notes.test.ts
```

真实产物测试将本次 Web 构建与 Python 程序组合为同布局种子，生成实际宿主环境信息并调用正式打包器，经隔离 HTTP 连接注入运行同一官方下载读取、校验与解压代码；逐文件比较内容及链接。其他测试覆盖授权、重复请求、浏览器会话丢弃、版本／环境拒绝、下载与资源限制失败、状态持久化以及程序／数据保护。

当前实测宿主为 macOS、Python 3.11.15、Node 22.15.0；生成的是 Darwin 测试包，不能作为 Linux 安装包发布。没有运行 Docker daemon、拉取镜像或公开测试 Release。生产 Linux 镜像环境生成、Linux 包与官方已发布资产下载仍待有对应产物后验证；保留第 1 批容器验收缺口。
