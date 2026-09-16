# 包级依赖更新（D1 / D2 / D3）

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

`shuku_dependencies/packages.py`（`scripts/dependency_packages.py` 保留薄 CLI 入口）从实际 wheel 和 standalone 生成协议 2 完整清单，包含间接依赖。Python 身份为规范化分发名、版本、wheel 标签、下载大小和 SHA-256。wheel 的 RECORD 是制品内归属；实际安装位置、大小、SHA-256 与原 RECORD 校验由业务解释器执行 `dependency_records.py`，二者不可互换。

Node 身份包含部署位置、名称、版本、内容摘要及每实例 tar 的大小和 SHA-256；位置不同即为不同实例。登记所有实际 `node_modules` 子树和相对链接。文件归最近的实际包根，父包不包含嵌套包文件，包内 vendored 文件归该包。bundle 内编译内容仍归应用。拒绝外部／悬空链接和无归属普通文件，不将整个 node_modules 当作包。

后续清理必须先排除登记的 Node 子树及固定入口的 `.initialized`，再全量替换应用代码；Python 目录与 installed.json 不在 runtime 清理范围内。新增／变化依赖整包替换、删除依赖同步卸载、未变化依赖不下载不卸载不重装。D1 / D2 不执行这些新协议覆盖动作；旧清空复制入口拒绝协议 2 runtime、目标或准备产物，打包器默认的旧格式路径仍拒绝协议 2 application.json。准备和安装阶段核验完整性，不添加日常扫描。

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

## D2：独立制品与准备链路

身份和安装记录的唯一实现迁入 `apps/api-python/shuku_dependencies`，由固定入口、构建脚本和业务更新模块共同复用；两个原脚本仅作入口，不维护第二套规则。基础镜像复制该标准库包到固定入口目录，也复制到应用种子。业务模块使用业务解释器的同一包。

在匹配目标平台的 D1 构建环境运行：

```sh
python scripts/build-application-package.py --program-root /path/to/program \
  --dependency-seed /opt/shuku-dependency-seed \
  --fixed-environment /opt/shuku-launcher/environment.json \
  --output-dir /path/to/output
```

本地产物平铺在输出目录：

- `shuku-{version}-{platform}-code.tar.gz`：完整代码，排除所有 node_modules、Python venv、缓存及业务数据；bundle 内容仍保留。附带本地代码描述 JSON。
- `shuku-{version}-{platform}-v2.json`：完整目标清单，含基础指纹、Python ABI、代码制品、完整 Python/Node 身份、文件归属、链接布局及展开空间预算。
- `*.whl`、D1 原名 `node-{位置摘要}-{内容摘要}.tar`：完整独立依赖制品，不重新命名 Node 制品。构建逐一验证种子、实际 standalone、大小、SHA-256、归属与内容后复制。
- `*-v2.json.reference.json`：清单自身的版本、大小和 SHA-256 描述，供后续发布使用。未来 feed 使用独立 `dependencyReleases` 字段，不能塞入旧 `appPackages`；D2 不修改正式 feed 或上传资产。

Node tar 沿用 D1 对时间、UID/GID、所有者名字的规范化；验证时流式重现同一个 tar 摘要，不创建副本。代码 gzip 同样固定时间戳并去掉源文件名。保留文件内容、模式与链接语义。wheel 原样交付，wheel 摘要不能替代安装 RECORD 验证。

管理员第一次确认沿用现有准备线程、prepare.lock 和状态文件。官方 feed 指向经摘要验证的完整目标清单，生产仍仅允许官方 HTTPS 发布资产；测试只在传输适配器注入隔离 HTTP 服务，没有任意 URL 配置。校验基础环境、ABI及所有 wheel 平台后，读取本机 installed.json 并核对业务 venv RECORD、未知文件和完整 Node 归属/链接/摘要；损坏、缺失、未知依赖或记录漂移直接失败，不修复现场。

Python 以规范化分发名为键；Node 以实际部署位置为键，同名多实例独立比较。完整包身份相同为 keep；缺失或版本/制品/归属等身份变化为 install（整包替换）；只在本机存在为 remove。同版本摘要变化也必须下载。比较只依赖经核验的本机状态，不依赖上一个发布版本。`python_records` 是安装记录，明确排除在目标身份摘要之外；准备基线另含安装记录文件摘要。

仅下载目标清单、完整代码与 install 集合。keep 和 remove 均不请求依赖制品。代码只展开到 `update-tmp/prepared/app`；依赖只流式校验归属、链接、内容和展开量，不落入业务环境。累计空间检查包含全部下载、代码暂存及完整依赖展开预算。完成前再次核对本机基线，发现变化拒绝 ready。

| 准备位置 | 内容与上限 |
| --- | --- |
| `update-tmp/preparation.json` | 原小型状态（16 KiB），目标清单摘要、代码摘要、基线、差异数量、累计下载字节、错误及摘要进度；轮询不返回文件清单 |
| `update-tmp/prepared/release.json` | 完整目标清单，独立上限 32 MiB |
| `update-tmp/prepared/plan.json` | 完整差异键、目标身份、本机基线、逐制品大小/摘要及已验证结果；仅供后续安装实现审查 |
| `update-tmp/prepared/` | 完整代码压缩包、选中依赖制品与代码暂存；不覆盖业务目录 |
| `dependencies/installed.json` | 准备阶段只读，独立上限 64 MiB |

另有限制：至多 10,000 个包、100,000 个依赖文件，依赖下载总和与声明展开量各至多 4 GiB；单个制品继续使用既有 512 MiB 边界。准备失败保留受限暂存与错误，重试沿用既有清理范围。关闭浏览器不取消已接受任务，重复点击受同一锁保护。

D2 阶段协议 2 只到 ready：业务用例和准备工作器两处拒绝安装请求，固定旧安装器拒绝新格式；前端显示暂不支持安装且不提供安装按钮。准备不停止服务、不迁移数据库、不卸载或改写依赖、不产生 install-request.json。管理员第二次安装确认保留为 D3 的边界，不自动触发。

### D2 验证结果与复现

普通测试使用小型 wheel/Node 夹具和真实 loopback HTTP 计数，运行：

```sh
PYTHONPATH=apps/api-python apps/api-python/.venv/bin/pytest -q -s \
  apps/api-python/tests/integration/modules/updates/test_dependency_preparation.py \
  apps/api-python/tests/integration/modules/updates/test_preparation.py
PYTHONPATH=apps/api-python apps/api-python/.venv/bin/python -m unittest discover -s scripts -p 'test_dependency_packages.py'
# apps/web 内，使用项目固定 Node：
pnpm exec tsx --conditions=import --test features/updates/application/confirm-update.test.ts features/updates/model/release-notes.test.ts
pnpm exec playwright test e2e/application-updates.spec.ts --project=chrome
```

固定 A1/B1/C1/D1 → A1/B2/D1/E1 样例：清单 2,765 字节、完整代码 957 字节、B2/E1 各 10,240 字节，各请求一次，总计 24,202 字节；A/D/C 依赖请求为零（另外一个 Python 夹具包同样 keep 且零请求）。同一目标分别从 1.0.0、1.0.1、1.0.3 的本机状态计算。覆盖代码独变、仅删除、同版本 Node/wheel 制品变化、多实例、记录漂移、缺包/坏包、ABI、空间、路径逃逸、准备中损坏、重复请求和不轮询仍完成。所有业务文件和链接均比较内容、mtime、模式，包含未变化依赖及 installed.json，不只比较哨兵。

显式真实产物验证（不进入普通后端测试）：

```sh
docker run --rm --network none -v "$PWD:/source:ro" \
  --entrypoint /usr/local/bin/python3.11 shuku-d1:local \
  /source/scripts/accept_dependency_preparation.py
```

本次使用真实 D1 Linux ARM64 镜像、39 个 Python 包、20 个 Node 实例、34 条链接。业务 venv 在隔离最终路径从可信种子离线初始化，业务解释器运行生产准备逻辑。目标使用实际 standalone Web 产物与当前 Python 代码；仅在隔离目标对 client-only 包追加一行，制造同版本制品变化。完整清单 289,176 字节、完整代码 69,451,676 字节、选中 Node tar 10,240 字节，共 69,751,092 字节，三个真实 HTTP 请求各一次；58 keep、1 install、0 remove，所有 keep 制品请求为零。代码包无 node_modules，全部依赖制品和归属在生成时验证，最终 ready，程序/依赖/记录及数据快照完全一致，没有安装请求。

真实验收复用 D1 已构建的 Web 产物，不表示本轮重建了完整镜像或再次启动全部服务；普通 UI 用 Chrome 开发服务器验证。未验证 Linux AMD64、fnOS 实机、Safari/PWA；没有正式协议 2 远程资产，未执行真实网络发布下载、D3 安装、D4 发布、全量回归或 CI。

## D3：管理员确认后的离线差异安装

首次启用 D3 要使用包含新 `dependency_install.py` 及共享校验包的固定入口镜像；应用更新仍不覆盖固定入口。D3 接通安装 API，页面完整操作留到 D4。未携带计划摘要的旧 D2 ready 结果需重新准备，不隐式选择新目标。

`GET /api/updates/status` 的 `summary.plan_sha256` 是服务端对已准备 `plan.json` 的规范 JSON 摘要。第二次管理员确认调用既有 `POST /api/updates/install`，提交 `version`、`sha256`（完整发布清单摘要）和 `plan_sha256`。授权、原有跨站限制保留。用例和工作器在 prepare.lock 内校验三者，复核清单、全部选中制品和实际本机依赖，重新计算差异；计划中的操作列表不直接授权删除。预约落盘后，新准备和重复安装请求均拒绝，不等待 launcher.lock，不依赖浏览器继续在线。

实际顺序：固定入口领取预约 → 当前业务解释器离线预检并重新展开代码到准备目录 → 固定标准库校验基线、制品、代码树、权限及累计空间 → 原有 SIGUSR1 排空并等待整组业务/收养子进程退出 → 再次核验 → SQLite 原生备份 → 写未完成标记 → 保留 `.initialized`、Node 子树和必要父目录，清理并全量复制其他代码 → Python/Node 包级操作 → 完整目标校验、uv check、必要导入检查 → 新业务解释器执行迁移并启动服务 → API 目标版本、Web、Worker、网关就绪 → 再核对实际记录并原子提交 installed.json → 成功状态、清除阻止标记。

固定安装模块仅依赖标准库和固定目录 `shuku_dependencies`。差异规则与安装记录核验提取至共享包，准备阶段继续委托同一实现。开始覆盖后不导入 runtime 的旧 Pydantic/FastAPI；必要导入与迁移是显式的新业务解释器子进程。大清单/计划上限 32 MiB、安装记录上限 64 MiB，状态仍使用原小型边界。

镜像 uv 固定 0.11.29，已用实际命令帮助和执行验证以下调用。所有命令包含 `--offline --no-cache --no-config --no-python-downloads`，并显式 `--python STORAGE_ROOT/dependencies/python/bin/python`：

- `pip uninstall <remove 和 replace 的旧分发名>`；文件删除由 uv 的 RECORD 归属执行。
- 对每个 install/replace：`pip install --no-index --no-deps --no-build <已验证本地 wheel>`。同版本制品变化也先卸载，绝不使用 sync、全局 reinstall 或重建 venv。
- `pip check` 仅作依赖关系检查，不替代完整目标核验；随后新业务 Python 导入 FastAPI、Uvicorn、SQLAlchemy、Alembic、API 与 Worker 模块。

Node 逐实例删除旧归属叶文件，再部署选中 tar 的完整文件；从不 rmtree 父包导致嵌套 keep 丢失。链接在普通文件完成后按目标布局创建，未变化链接不重写，仅清理空的旧目录。路径写入不穿越链接。keep 实例不复制、不解压、不重装，也不通过整套备份恢复来保留。

安装后以完整新目标集合采集真实分发包与 Node 实例，验证 RECORD、未知文件、版本、Node 内容/制品身份与布局；变化 wheel 的内容逐项对应实际安装文件（RECORD/生成脚本采用安装语义），Python keep 的安装记录必须仍与旧记录相同。迁移和启动完成前不提交新 installed.json。依赖失败立即停止，不迁移、不开放业务，保留原记录、失败阶段、日志、预约和未完成标记；普通启动拒绝继续，不自动修复、续装或回滚。原停止超时保持失败，不强杀任务后继续复制；容器 SIGTERM/SIGINT 不触发更新后重启。

### D3 验证

普通测试使用真实 uv 0.11.29、小型 wheel/Node 夹具，移除所有源制品后只给安装器选中制品；uv 禁止网络和缓存。A1/B1/C1/D1 → A1/B2/D1/E1 实际执行卸载 B/C、安装 B2/E1，旧 B 遗留文件消失，A/D 内容、inode、mtime 不变。另覆盖仅代码、仅删除、同版本替换、共享 namespace、同名多位置/嵌套 Node 与链接、预约互斥、计划/摘要变化、确认后再次漂移、缺包、依赖失败与旧协议拒绝。wheel 的 `.data` 最终位置和生成命令入口也在预约前核对，与 keep 文件冲突立即拒绝；固定布局 `python -I` 入口另有回归测试。

```sh
# SHUKU_TEST_UV 指向匹配项目版本的 uv；不在测试内下载工具或依赖。
SHUKU_TEST_UV=/path/to/uv-0.11.29 PYTHONPATH=apps/api-python \
  apps/api-python/.venv/bin/pytest -q \
  apps/api-python/tests/integration/modules/updates/test_dependency_installation.py \
  apps/api-python/tests/integration/modules/updates/test_dependency_preparation.py \
  apps/api-python/tests/integration/modules/updates/test_preparation.py
PYTHONPATH=apps/api-python python3 -m unittest discover -s scripts -p 'test_dependency_packages.py'
PYTHONPATH=apps/api-python python3 -m unittest discover -s scripts -p 'test_container*.py'
# 显式真实容器验收：复用真实 Web/原生库，仅构建隔离入口及代码测试层。
PYTHONPATH=apps/api-python apps/api-python/.venv/bin/python \
  scripts/accept_container_update.py --image shuku-d1:local --dependencies
```

结果：更新准备 64 项、安装 15 项通过；架构/OpenAPI 54 项通过；D1 依赖夹具 9 项通过；容器入口 21 项通过、1 项 Linux 子进程专属检查在 macOS 跳过。Ruff、Mypy 和生成契约的 TypeScript 检查通过。

真实 Linux ARM64、UID/GID 1000:1000 容器，通过真实准备和管理员安装 API 更新隔离程序 1.0.4 → 1.0.5。安装预约前断开容器网络并删除镜像原始 wheels/临时全量 seed，无 keep wheel 可供重装。实际日志：Python 卸载 `d3-b==1`、`d3-c==1`，安装 `d3-b==2`、`d3-e==1`；Node 原路径 `node_modules/.pnpm/client-only@0.0.1/node_modules/client-only` 完整替换，同版本内容发生变化。最终 43 个 Python 包、20 个 Node 实例与完整目标匹配；3,125 个 keep 文件的内容摘要、inode、mtime 一致。

隔离迁移实际导入新 B/E 依赖后建测试表，新 API 响应也证明加载 B2；真实 Worker、Web、网关就绪。Reader bootstrap 与原文件读取成功，管理员会话、数据库阅读记录、配置、密钥和书库内容保留，数据库备份含更新前记录。普通及离线重启仍为目标版本和依赖，容器 ID/镜像 ID 全程不变。测试依赖、目标版本及迁移仅存在于隔离产物，正式版本号和迁移链未改。

未验证 Linux AMD64、fnOS 实机、浏览器渲染阅读及协议 2 页面安装操作；本轮未全量重建 Web、未执行 CI 或全量回归。正式资产上传、feed 接入和页面完善仍留在 D4。
