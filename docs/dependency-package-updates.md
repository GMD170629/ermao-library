# 包级依赖更新（D1）

D1 建立协议 2 的目录、可信种子、身份清单与启动基础，不实现协议 2 更新安装器。首次启用必须换用包含新固定入口的基础镜像。管理员下载、安装两次确认、单容器、停机安装和失败保护继续作为后续实现约束。

## 固定目录与职责

| 位置 | 职责 |
| --- | --- |
| `/opt/shuku-launcher` | 固定解释器启动的标准库入口、基础环境指纹、初始化工具；不由应用更新覆盖 |
| `/opt/shuku-dependency-seed` | 目标平台的 `requirements.txt`、完整 `wheels/`、逐实例 `node/` 制品及 `manifest.json`；仅初始化或显式转换使用 |
| `STORAGE_ROOT/runtime` | 应用程序；保留真实 standalone 相对部署布局 |
| `STORAGE_ROOT/dependencies/python` | 在最终路径创建、不继承全局 site-packages 的业务 venv |
| `STORAGE_ROOT/dependencies/installed.json` | 完整目标身份及 Python 安装 RECORD 核对结果；不属于程序覆盖范围 |
| `STORAGE_ROOT/update-tmp` | 既有锁、更新状态、失败标记和备份；转换备份为 `database-before-dependency-conversion.sqlite3` |

`runtime/.initialized` 仍仅标记程序初始化。数据库、密钥、配置、封面与书库位置不变。API、Worker、迁移、业务预检使用固定入口设置的绝对 `SHUKU_BUSINESS_PYTHON`；不依赖 PATH，不设置 NODE_PATH 或 preserve-symlinks。普通启动不下载、不扫描、不清空、不同步依赖。初始化失败保留现场并拒绝隐式重试。

构建工具（uv、pip）使用镜像固定环境；`install-python-runtime.sh ... --wheel-seed` 复用 `uv.lock` 的完整生产导出，由目标平台 pip 下载并按锁定哈希验证二进制 wheel。用户设备只离线安装，不编译源码，不复制开发 venv。

## 身份、归属与清理边界

`dependency_packages.py` 从实际 wheel 和 standalone 生成协议 2 完整清单，包含间接依赖。Python 身份为规范化分发名、版本、wheel 标签、下载大小和 SHA-256。wheel 的 RECORD 是制品内归属；实际安装位置、大小、SHA-256 与原 RECORD 校验由业务解释器执行 `dependency_records.py`，二者不可互换。

Node 身份包含部署位置、名称、版本、内容摘要及每实例 tar 的大小和 SHA-256；位置不同即为不同实例。登记所有实际 `node_modules` 子树和相对链接。文件归最近的实际包根，父包不包含嵌套包文件，包内 vendored 文件归该包。bundle 内编译内容仍归应用。拒绝外部／悬空链接和无归属普通文件，不将整个 node_modules 当作包。

后续清理必须先排除登记的 Node 子树及固定入口的 `.initialized`，再全量替换应用代码；Python 目录与 installed.json 不在 runtime 清理范围内。新增／变化依赖整包替换、删除依赖同步卸载、未变化依赖不下载不卸载不重装。D1 不执行这些新协议覆盖动作；旧清空复制入口拒绝协议 2 runtime、目标或准备产物，旧打包器也拒绝协议 2 application.json。准备和安装阶段核验完整性，不添加日常扫描。

基础指纹只保留解释器与 ABI、架构、系统包、固定原生库、Web 基础路径及启动协议。应用版本或业务依赖变化不改变它。D1 不更新解释器、系统库、启动器环境或固定原生阅读库。不实现文件差分、包内补丁、自动安装、多版本、自动回滚、外部服务或通用包管理平台。

## 已有部署显式转换

先停止旧容器，再用新基础镜像、相同挂载和 UID/GID，运行 `/usr/local/bin/python3.11 /opt/shuku-launcher/container-entry.py --convert-legacy`。入口取得既有 launcher 和 prepare 排他锁，运行中或未完成更新一律拒绝。只接受协议 1、同平台、完全相同程序版本与 uv.lock、匹配种子的 Node 布局；不是升级入口，不能降级。

转换备份数据库后复用业务环境初始化，在业务解释器中调用既有 `verify_current_schema`，不改写数据库版本。最后仅更新已知启动脚本与程序协议标识。失败保留备份与现场，需人工检查；无自动回滚或历史迁移框架。转换成功后正常启动，不自动启动业务。本轮仅在隔离部署验证。

## 验证入口

普通夹具：`python3 -m unittest discover -s scripts -p 'test_dependency_packages.py'`，另运行已有 container entry/install 和 runtime install 定向测试。真实 Linux 容器显式冒烟：`python3 scripts/smoke-container-runtime.py --image shuku-d1:local`，不纳入后端默认测试。构建使用 `docker build -f apps/web/Dockerfile.prod -t shuku-d1:local .`。

本轮 Linux ARM64 真实镜像登记 39 个 Python 包、20 个 Node 实例和 34 条链接。隔离容器使用 UID/GID `12345:12345`，全程断网；验证 API/Worker 的实际进程命令、业务环境隔离、迁移成功、Web 200、种子不可用时重启、依赖记录不变、停机退出码 143、锁拒绝、旧布局转换及未知 schema 拒绝。数据库、密钥、配置、封面及外部书库哨兵保留。未验证 Linux AMD64、fnOS 实机和正式部署；未执行全量回归、发布或协议 2 更新安装。

本轮修改文件按职责列示（路径均相对仓库根）：

| 职责 | 文件 |
| --- | --- |
| 构建与部署 | `.dockerignore`、`apps/web/Dockerfile.prod`、`docker-compose.yml`、`docker-compose.prod.yml`、`deploy/fnos/app/docker/docker-compose.yaml` |
| 清单与业务环境 | `scripts/dependency_packages.py`、`scripts/dependency_environment.py`、`scripts/dependency_records.py`、`scripts/install-python-runtime.sh`、`scripts/build-runtime-environment.py` |
| 固定入口与协议隔离 | `scripts/container-entry.py`、`scripts/container_install.py`、`scripts/start-unified-app.sh`、`apps/api-python/app/modules/updates/infrastructure/environment.py` |
| 验证 | `scripts/test_dependency_packages.py`、`scripts/test_container_entry.py`、`scripts/test_install_python_runtime.py`、`scripts/smoke-container-runtime.py`、`scripts/verify-python-backend-migration.mjs`、`apps/api-python/tests/integration/modules/updates/test_preparation.py` |
| 文档 | 本文、`docs/container-runtime.md`、`docs/application-update-preparation.md` |
