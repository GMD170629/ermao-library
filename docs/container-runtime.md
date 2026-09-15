# 容器内持久化程序目录（第 1 批）

本批提供固定启动入口和唯一持久化程序目录。尚不提供应用内下载、安装或覆盖更新；开发脚本、单独 API 镜像仍沿用原有启动方式，不支持应用内安装。

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

入口会转发停止信号，启动脚本等待直接业务进程退出；Linux 入口回收被收养的子进程，并结束同组遗留工具。Compose 给普通停止预留 60 秒；这不代表安装时的安全停机验收，后台任务排空与安装超时处理属于第 3 批。普通停止不会触发入口自动重启业务。

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

本批宿主验证通过：Python 3.11.15；Web 构建与真实应用两次启动使用 Node 22.15.0。镜像固定 Node 为 22.23.1。Docker daemon 不可连接，因此完整镜像构建、Linux PID 1/孤儿回收、真实 `docker stop`、断网容器启动及 fnOS 安装运行仍待验收；宿主结果不替代这些证据。
