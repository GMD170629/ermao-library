# 容器内持久化程序目录与停机安装

第 1 批提供固定启动入口和唯一持久化程序目录。[第 2 批](application-update-preparation.md) 增加应用包与后台下载准备，第 3 批增加下述固定入口停机安装；开发脚本、单独 API 镜像仍沿用原有启动方式，不支持应用内安装。

## 目录与启动

| 位置 | 职责 |
| --- | --- |
| `/opt/shuku-launcher/container-entry.py` | 镜像内固定入口，仅依赖 Python 标准库，不导入业务代码 |
| `/opt/shuku-image/` | 镜像携带的初始完整程序：Next standalone、静态资源、Python 应用与迁移、现有启动脚本及网关 |
| `STORAGE_ROOT/runtime/` | 唯一运行程序目录；首次复制后创建 `.initialized` 标记 |
| `STORAGE_ROOT/update-tmp/launcher.lock` | 固定入口持有的进程互斥锁，进程退出自动释放，不通过删除文件解锁 |
| `STORAGE_ROOT/database`、`covers`、`indexes`、`logs`、`secrets` | 继续保存原有业务数据；书库继续通过原挂载路径访问 |

Python 依赖继续安装在镜像的 `/opt/shuku-python`，Node/Python 解释器及原生库留在镜像固定位置，不复制进 runtime。Web 的运行依赖和资源随 standalone 程序复制。程序目录的工作路径由入口强制指定，API 与 Worker 的 cwd 为 runtime 下的 `apps/api-python`。

启动顺序复用 `start-unified-app.sh`：prestart 初始化／迁移并校验数据库 → API 就绪 → Worker、Web、网关。数据仍通过原 `STORAGE_ROOT` 查找，已有会话密钥继续使用，Compose 环境变量保持生效。

后续启动只运行 runtime；即使镜像初始程序变化或不可用，也不重新复制。启动失败不会清空 runtime 或数据库。复制失败留下无完成标记的目录，下一次启动拒绝继续，需检查容器日志、可用空间、文件完整性及部署 UID 的写入权限后人工修复；不要通过手写完成标记来绕过检查。

## 部署入口与权限

生产 Dockerfile CMD、根目录两份 Compose 的 web 服务和 fnOS 模板均调用：

```text
python /opt/shuku-launcher/container-entry.py
```

首次采用本批代码需部署包含该入口的新镜像，并同步 Compose command。现有存储挂载和图书挂载不变。默认 `STORAGE_ROOT=/app/storage`。目录须允许配置的 PUID/PGID（fnOS 为 TRIM_UID/TRIM_GID）创建程序副本和状态目录；复制文件归运行用户所有，入口不递归改权限或属主，也不修改书库权限。

入口会转发停止信号，启动脚本等待直接业务进程退出；Linux 入口回收被收养的子进程，并结束同组遗留工具。Compose 给普通停止预留 60 秒；这不代表安装时的安全停机验收，安装使用下述独立的 120 秒停止等待。普通停止不会触发入口自动重启业务。

## 定向验证

```sh
apps/api-python/.venv/bin/python -m unittest scripts.test_container_entry scripts.test_install_python_runtime -v
pnpm --filter @shuku/web build
apps/api-python/.venv/bin/python scripts/smoke-container-runtime.py
sh -n scripts/start-unified-app.sh
docker compose -f docker-compose.prod.yml config --quiet
docker compose -f docker-compose.yml config --quiet
```

冒烟脚本只使用隔离临时目录，要求 8000、3001、18300 空闲以及已安装的 API 依赖、Node、lsof。它使用真实构建产物，检查四个服务、迁移先行、Worker 实际 cwd、数据库与密钥保留，并移除测试镜像种子后再次启动，验证 runtime 不被覆盖。它不模拟更新，也不修改正式版本或用户书库。

第 1 批最初仅完成宿主验证。第 3 批已启动 Docker Desktop，并完成 Linux ARM64 的真实应用更新、PID 1/孤儿回收、普通停止及断网重启；fnOS 安装运行仍未执行。镜像使用 Python 3.11.15、Node 22.23.1。完整生产镜像首次构建成功；后续 Docker Hub 元数据请求 EOF，因此最终验收复用该镜像的真实 Web/依赖产物，复制本批最新程序和固定入口并重新生成环境信息后执行，未重新安装运行依赖。

## 已准备应用包的停机安装（第 3 批）

管理员可向 `POST /api/updates/install` 提交 `{"version":"目标版本"}`，仅接受第 2 批已准备完成的包；页面的一次确认接线仍在第 4 批。返回 202 后请求独立落盘，关闭浏览器不取消安装。没有固定安装入口的部署不支持此操作。

固定入口使用 `prepare.lock` 消费 `update-tmp/install-request.json`，不等待其自身常驻的 `launcher.lock`。请求存在期间新的准备被拒绝，安装源不会被并行准备替换。安装前离线重验清单、摘要、固定环境标识、版本、空间和路径，复用原解压器重新生成已验证的临时程序目录；不安装依赖或联网下载。

停止范围包括网关、Web、API、独立 Worker，以及下载、Kindle、日志维护、导入、元数据、扫描/监听和整理任务。先停止入口与后台领取，再等待现有请求/任务及收养的工具子进程退出。停止最多等待 120 秒；超时记录 `STOP_TIMEOUT`，不复制、不强杀任务后继续安装，也不重复启动旧服务。剩余进程可继续结束，但系统不声称旧服务已恢复，需要人工检查。

旧业务全部退出后，使用 SQLite 原生备份 API（包括 WAL）保存一致性快照；现有手工备份为逻辑导出，因此本流程不以它替代完整迁移前快照。备份成功才写失败阻止标记，然后只清理并复制唯一 runtime，保留 `.initialized`。目标目录中的链接只删除链接本身；用户数据库、图书、封面、配置、密钥及固定入口均不在复制范围。

重启复用原 prestart，先迁移及校验，再启动服务。成功检查包含实际 API OpenAPI 版本、API/网关健康、Web 响应及本次启动的新 Worker PID/进程组；每次启动清除旧就绪文件。停机前复核限时 300 秒，数据库备份 60 秒，迁移/服务就绪合计 180 秒。失败不自动回滚、降级、续装或重新初始化数据库。

持久化文件均在 `STORAGE_ROOT/update-tmp/`：

- `preparation.json`：原准备状态加 requested/checking/stopping/backup/copying/starting/success/failed，包含目标、时间、失败阶段和原因码。
- `installation.log`：最近更新的安装阶段日志，同时输出到容器日志。
- `database-before-update.sqlite3`：最近一次迁移前数据库快照，权限 0600。
- `installation-incomplete`：覆盖开始后的失败阻止标记，仅完成文件复制、迁移及服务检查后清除。
- `install-request.json`：未完成请求；失败时保留，拒绝普通启动自动重试。

覆盖、迁移或启动失败后，应停止容器，检查日志、程序完整性、目标环境、数据库版本与备份，再人工修复完整应用和数据库之间的一致性。不要直接删除失败标记或清空数据库来绕过错误。未完成标记或请求存在时，固定入口拒绝普通业务启动。普通 SIGTERM/SIGINT 始终表示停止容器，不触发更新后重启。

存储文件系统必须支持可靠的 POSIX 文件锁和原子重命名。Docker Desktop 的部分 macOS 宿主临时目录挂载不能保持所需锁语义；显式验收使用独立 Docker 本地卷，并在结束时删除测试容器和卷。

### 定向验证

```sh
apps/api-python/.venv/bin/python -m pytest apps/api-python/tests/integration/modules/updates/test_preparation.py -q
apps/api-python/.venv/bin/python -m unittest discover -s scripts -p 'test_container_*.py' -q
# 显式真实验收；预先构建镜像，脚本不会拉取镜像。
docker build -f apps/web/Dockerfile.prod -t shuku-update-acceptance:local .
python3 scripts/accept_container_update.py --image shuku-update-acceptance:local
```

真实验收脚本复用镜像中的真实 Web/Python 产物和固定环境信息，仅在容器临时产物中创建 B 版本、可观察的 API 行为与测试迁移。通过受控本地 HTTP 连接注入运行生产准备链路，再经真实管理员 HTTP 安装入口执行。验证容器/镜像 ID、迁移、旧文件删除、数据库阅读记录与配置、图书与密钥、PID 1、普通停止及离线重启。不会修改正式版本或迁移链，不发布测试版本。日志写入宿主 `/tmp/shuku-container-update-acceptance.log`。
