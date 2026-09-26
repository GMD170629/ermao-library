# 增强元数据识别：执行计划与 M0 契约冻结

核对日期：2026-09-26。M0、M1 已提交；用户现已授权连续完成 M2–M7，每阶段独立提交并沿用推送和 `[skip ci]`。以下分阶段记录有效实现及验证，不把后续计划视为已经实现。

## NAS 当前服务真实联调（2026-09-26）

### 部署版本与执行边界

用户要求更新并使用 NAS 当前服务。现有 Compose 项目 `ermaobooks`、服务 `web`、容器 `shuku-prod-web` 已更新；没有另建应用服务、数据库副本服务或启用新来源。更新前容器 revision 为 `8d81f988ca08b455d60a777a7c8432cf35d5aeef`；更新后受验代码为 develop 合并提交 **`03637c246ca6fa016060acc47763e6625b9a139e`**，镜像为 `gamersgu/shuku-starship-web@sha256:1ca49e9e60e07138e02355b3287e7a4a49e51b01336a879058b03691825893b2`，linux/amd64。应用显示版本仍为 v1.4.3，不能只凭该版本号区分新旧代码。

沿原 Compose 配置更新原容器，复用原网络、挂载、端口和配置。第一次命令因 Compose 默认项目名与现有标签不一致发生容器名称冲突，没有替换原服务；显式指定原项目名后重建成功，首次产生的空网络已清理。镜像的 [Actions 运行](https://github.com/GMD170629/ermao-library/actions/runs/36250786266) 已通过预检、Web 质量门禁、Reader 安全一致性及实际容器故障/更新验收。NAS 更新后为 healthy，运行目录中共同匹配、候选转换、上下文投影、队列与来源解析的 5 个关键文件逐字节与镜像一致。联调期间没有修改生产代码，本节文档提交不改变受验代码。

NAS 实库为 **94 本书、403 个资源、20 个有效 ISBN 资源、0 条历史识别任务/人工确认记录**。只使用已经启用的豆瓣和 Bangumi；Google Books/Open Library 未启用，AI 未配置且关闭。现有界面确认：本地优先开、路径修正关、定时/新增自动执行关、OPF 写回关，均未修改。

在当前容器使用当前安装的 Python、代码和真实数据库，以临时有界探针调用既有 `process_metadata_lookup_task`。明确建立 24 个 resource 目标的任务，复用真实来源 HTTP、parser、gate、共同规则和记录持久化；未替换响应，未另造识别实现。该证据覆盖应用队列入口，**不等于 24 个目标都从浏览器 HTTP 入队，也不验收调度器领取链**。浏览器另核对当前服务的新来源能力说明和路径修正/本地优先设置。只读元数据投影，不读/上传全文、不做整书哈希、不强制覆盖书库；24 条真实识别记录保留在 NAS。原始样本映射与候选只保存在 NAS 私有临时验收目录，本文使用 N01–N24，不提交凭据、路径或内部目标 ID。

### 首次识别结果（A 组）

选择 21 个书目组的 24 个真实资源：12 个有效 ISBN 目标，2 个较正常的书名/作者目标，4 个噪声标题目标（含一个“未知作者”），以及 3 个系列各 2 个分卷；包含同作品不同资源、修订版和套装标记。是目的抽样，样本很小，不代表全库准确率。目标已经导入，此次是首次远程识别，未重演首次文件导入流程。

| 指标 | 实测结果 |
| --- | --- |
| 正确自动应用 / 自动应用数 | **0 / 0，未定义** |
| 自动应用数 / 可评估目标数 | **0 / 24 = 0%** |
| 正确候选出现的目标数 / 可评估目标数 | 严格出版版本真值未独立核定，不能计算。可核验的较弱指标为 **12 / 24 = 50% 出现 ISBN 等价候选**，在 12 个有效 ISBN 子集内为 12 / 12；不把这当作严格版本正确率 |
| 待确认 | **6 / 24 = 25%**（N19–N24） |
| 无匹配 | **18 / 24 = 75%**（N01–N18） |
| 来源故障 | **0 次** |
| 错版本写入 | **0 次**；自动应用分母为 0，不证明正向版本识别成功 |
| 实际来源请求 | **66 次**，gate 计数也为 66，每目标 2–3 次，平均 2.75 次 |
| 应用模型请求 | **0 次** |

24 项队列入口顺序执行合计约 206.67 秒。兼容任务 status 均为 `NO_MATCH`，业务 recognition outcome 为 18 `NO_MATCH`、6 `AMBIGUOUS`，统计使用业务 outcome，不能把 6 个待确认算作无匹配。每个目标执行前后投影未变化；Codex 对照完成后按同一 JSON 日期/集合表示再次核对，24 个目标仍未变化。最初的统计探针对 ISBN 做字面比较漏计 N09 的连字符形式，已改用生产 `normalize_isbn` 统计等价值；这是统计口径纠正，没有改变匹配结果或重跑首次识别。

### 真实反例及补修判断

**本轮不能判定增强识别已达到可发布的识别效果，存在明确局部补修项。** 保留原结果，不修改目标元数据、范围或作者来制造通过。

1. **作者国籍前缀造成误冲突。** N01 本地“安迪·威尔”与来源“[美] 安迪·威尔”、N02 的“阿瑟·克拉克”与“[英] 阿瑟·克拉克”，均被判 `AUTHOR_CONFLICT`；N13 正常书名相同，作者“鲍·瓦西里耶夫”与“[苏联] 鲍·瓦西里耶夫”也被拒绝。直接位置为 `app/modules/metadata/domain/recognition.py::_authors`：通用标点归一化去掉括号，却保留国籍文本成为姓名的一部分。应补有边界的作者注记归一化反例，不能把真实不同作者、合著角色或未知别名一并放宽。
2. **套装候选的来源范围标注不正确。** N07 的豆瓣候选“全三册”带 ISBN/出版字段，却被 `parse_douban_subject_html` 标为 `isbnScope=EDITION`。直接位置为 `app/services/organize_service.py` 的 scope 判定，只识别“套装/全套/box set”等少量标记，漏了该真实表达。本次本地 scope 为 UNKNOWN 且标题证据不足，未发生自动写入；共同匹配的套装限制仍有效，但来源标注本身需要补修，不能依赖下游碰巧拦截。范围判断仍需保留结构证据，不能只扩关键词后宣称所有套装问题已解决。
3. **标题混入作者/下载附注导致证据不足。** N03/N05/N09/N10/N11 已出现 ISBN 等价且作者相符的候选，但本地完整标题含作者后缀，无法按当前规则建立作品身份；本地 ISBN scope UNKNOWN 又不能单独授予版本字段。N04 是拼音标题，N06 另有作者污染和出版字段冲突，N12 有修订版标记不一致。这些应在既有标题/导入证据链中定位，不能将查询清洗或 Codex 建议直接替换原始匹配身份，也不能把所有同 ISBN 目标放行。

N19/N20 有相符作品/分卷字样的候选，但来源卷册结构证据不足；N21/N22 是纯卷号且父级尚未确认；N23/N24 返回作品层候选。保留待确认符合安全边界，不以分卷自动通过率为由降低规则。本轮没有实施上述生产代码补修；补修后应定向验证这些真实反例，再绑定新代码执行相关 NAS 复验，不能继承本轮为修复后结果。

### B 组与 Codex 对照

历史确认记录为 0，用户未确认具体候选，**B 组仍为 0 个实测目标、待验**。没有伪造 `humanConfirmed`，没有把首次查询返回同 ISBN 当作已确认版本。

沿用用户“没有配置 AI，直接使用 Codex”的要求，对 N01/N02/N03/N04/N15/N16 生成 6 份有原始标题引用、标注 hypothesis 的结构化查询建议，经过现有 `assistance_input` / `parse_assistance` 校验，并调用当前容器的真实来源和共同匹配。原始目标、作者、ISBN、卷号、上下文指纹均未改变。

- 6 / 6 结构校验通过；基线与追加查询结果均为 NO_MATCH ×6，新增可自动应用目标 **0 / 6**，未证明收益。
- 追加实际来源请求 **17 次**，无来源故障；各目标连同基线累计 5–6 次，仍在 8 次预算内。
- A 组与对照共 **83 次**真实来源请求；本轮没有额外来源连接探测请求。应用模型请求始终为 0。
- Codex 会话建议不是应用内模型 HTTP 返回。真实模型结构化兼容性、SUGGEST_ONLY/ASSIST_ON_AMBIGUITY 的运行对照、错误/超时与 2 次模型预算仍未验证；AI 关闭时本批未调用模型。

### 有效证据与保留门禁

本轮实际执行：原服务镜像更新及健康核对、运行代码与镜像 5 文件一致性、24 个真实队列入口目标、6 个 Codex 查询对照、当前 NAS 浏览器设置核对、目标最终元数据投影核对。没有新增测试框架或重跑既有全量套件；此前同代码树的 M7 定向测试及上述镜像 Actions 证据可复用，不能替代本轮明确未验项。仓库只更新本文，独立提交并沿用 `[skip ci]` 推送；NAS 继续运行前述固定代码 SHA，无需因文档提交重建镜像。

仍待验：首次文件导入链、严格出版版本标注/自动正确应用、用户确认后的 B 组、应用真实模型、浏览器完整确认写入链。有声录音正向识别、旧插件内部 HTTP 完整预算、100k 以外的吞吐、原生真机均未扩大验收。已知调度 waiting/ready 失败和递归 mypy 6 项问题仍按前文保留，没有修复或重跑。正式发布仍需处理本轮反例、版本/双语发布说明、发布分支对齐及对应正式产物门禁；本次仅更新 NAS 已有 develop 服务，没有 main 合并、稳定 tag 或正式发布。

## 发布前真实联调与交付收口（2026-09-26）

### 冻结版本及证据有效性

本轮受验**代码 SHA 为 `7e7b00a0ccf390c894f8343eadef294043a7432e`**，分支 `codex/metadata-recognition-enhancement`；开始时工作树干净，与远端一致。M7 的 203 项后端、32 项 Web、4 项桌面/窄屏浏览器及相关静态检查绑定此代码。检查后无生产代码、测试、依赖或配置文件变更，本轮只补本文；不因文档提交重新跑这些套件。文档提交 SHA 与受验代码 SHA 分开，不要求本文引用自身提交。

### 可用配置、真实数据及隔离方式

只读取本机已有应用库及其已启用配置：豆瓣、Bangumi 可执行真实请求；AI disabled 且配置为空，Google/Open Library 未配置。用户随后明确“没有配置 ai，直接使用 Codex”，因此增加本会话 Codex 查询建议对照，未把它接成应用模型端点，也未启用新的来源或修改 AI 权限。未输出凭据或连接密钥。

主要本地库有 104 本书、4289 个资源、0 条 MetadataLookupTask、0 个非空资源 ISBN。排除名称为“公开格式测试”的 55 本测试记录，在余下书目中按稳定顺序选择 20 个书目组的资源，并增加 4 个相关分卷/版本标记资源，合计 21 个书目组、24 个目标。14 个缺作者；另 10 个有作者值，但多数混有格式、卷数或版本后缀。唯一明确书名/作者组合是有声资源，不能借纸书候选确认录音版本。本批偏向漫画、分卷和脏元数据，既非随机抽样，也不代表全库分布。

用 SQLite 在线 backup 从只读连接复制应用库到本机临时目录；副本由项目既有 `apply_schema` 从 `0010_book_metadata_completion` 升级至 `0038_import_scan_round_fact`，没有手工补列或修改迁移。生产库保持原 revision、0 条识别记录。副本 OPF 写入关闭，保留原来源配置和默认本地优先/路径修正语义；通过真实 `process_metadata_lookup_task`、来源 registry/parser/gate、共同匹配及持久化链执行。只在副本建立 24 个明确 resource 目标任务，没有启动生产 worker、重扫/读取整书、整书哈希或原件写回。HTTP 观察包装只计数并原样调用实际 opener，没有替换响应、伪造候选或强制清洗目标身份。

原始候选及样本映射仅保留在本机临时验收目录；此处以 A01–A24 脱敏，不提交书库路径、内部资源 ID、原始页面或配置。真实请求时间受当时来源状态影响，不能继承为未来可用性承诺。

### A：没有历史确认的首次识别

24 个目标均没有历史来源确认，ISBN scope 均 UNKNOWN。这是已有本地导入资源的首次远程识别，**不等于“首次导入、有效 ISBN、无人工确认历史”的组合已通过**：两个本地应用库均无 ISBN 样本，也没有独立可核对的出版版本真值；该组合与准确出版版本区分保持待验。

| 样本 | 保留的样本特征 | 首次结果 | 实际请求 |
| --- | --- | --- | ---: |
| A01、A02 | 卷/副标题完整，作者字段混入格式信息 | NO_MATCH ×2 | 3、3 |
| A03 | 分卷、缺作者、标题含连写英文 | NO_MATCH | 3 |
| A04、A05 | 章节/卷号与不可靠作者字段 | NO_MATCH ×2 | 2、2 |
| A06 | 期号、缺作者 | NO_MATCH | 3 |
| A07 | 原卷号与新版合订本编号不同 | AMBIGUOUS | 3 |
| A08 | 纯“全一卷”，父级未确认 | NO_MATCH | 2 |
| A09、A10 | 卷/副标题；缺作者或作者字段为附注 | NO_MATCH ×2 | 3、3 |
| A11、A12 | 数字前缀/章节序号噪声，缺作者 | NO_MATCH ×2 | 3、3 |
| A13 | 缺作者、同名来源候选；Bangumi TLS 中断 | SOURCE_ERROR，PENDING 待重试 | 3 |
| A14、A15 | 分卷；格式作者或标题错字 | NO_MATCH ×2 | 2、2 |
| A16 | 指定第 2 卷，返回第 1/3 卷或其他作品 | AMBIGUOUS | 3 |
| A17、A18 | 合集多个标题/系列与副标题，缺作者 | NO_MATCH ×2 | 2、3 |
| A19 | 正常英文书名/作者，但为指定录音版本 | NO_MATCH | 3 |
| A20 | 作者字段混入版本后缀 | NO_MATCH | 2 |
| A21、A22 | 与前面样本同系列的另一个分卷 | NO_MATCH ×2 | 2、2 |
| A23、A24 | 全彩/外传版本标记与分卷，缺作者 | AMBIGUOUS、NO_MATCH | 2、2 |

| 指标 | 实测结果与分母 |
| --- | --- |
| 正确自动应用 / 自动应用数 | **0 / 0，未定义**；不能称为 100% |
| 自动应用 / 可评估识别目标 | **0 / 24 = 0%** |
| 正确候选出现 / 可评估目标 | 严格出版/录音版本级真值不足，**不可计算**。人工按本地可见书名/卷号作较弱核对，A01/A02/A03/A09/A10/A11/A14/A18/A22 共 **9 / 24 = 37.5%** 出现相符书名/卷册候选；该数不证明作者、出版版本或录音身份正确，不作为严格“正确候选召回率” |
| 待确认 | **3 / 24 = 12.5%** |
| 无匹配 | **20 / 24 = 83.3%** |
| 来源故障 | **1 / 24 = 4.2%**，一次真实 Bangumi TLS EOF，记录 NETWORK_ERROR、SOURCE_ERROR 和后续重试时间；未人工重跑取成功覆盖这次失败 |
| 错版本写入 | **0 次**，但自动应用分母为 0，不能据此证明正向版本识别能力 |
| 实际请求 | **61 / 24 = 2.54 次/目标**，每目标 2–3 次；观察到的 opener 次数与 gate 计数均为 61，AI 请求 0 |

24 个目标的前后元数据投影完全相同，没有自动写入，也没有原件变化。这批数据说明相关候选可达，但本地身份不足/冲突导致低覆盖；不把安全拒绝改成通过，也不把“来源返回候选”包装成识别成功。

### B：用户确认后的后续识别

本地历史确认样本数 0，本轮用户没有确认任何具体候选/版本，**B 组实测目标数为 0，待验**。未代替用户认定候选版本或往副本伪造确认记录来补齐统计。M7 的确认 ISBN → 后续版本应用用例仍只是 fixture 证据，不能代替本轮 A 或 B 的真实成功。

### Codex 辅助查询对照与真实模型缺口

对同批 A01/A02/A03/A04/A06/A09 给出 6 份 Codex 结构化查询建议：只拆分原标题词/数字或抽取副标题，保留原作者、卷号、ISBN 和父级证据。每份建议经现有 `assistance_input` / `parse_assistance` 严格校验，带 `target:title` 引用并标 hypothesis；沿原来源入口查询，再由共同匹配比较原目标。

- 6 / 6 建议通过本地结构校验；这是本会话生成内容的校验，**不是应用模型 HTTP 接口成功**。
- 追加实际来源请求 12 次，6 个目标连同各自 A 组请求累计为 4–5 次/目标，未越过 8 次来源预算；上下文指纹 6 / 6 不变。
- 关闭应用 AI 的 A 组为 NO_MATCH ×6，Codex 辅助查询后共同规则仍为 NO_MATCH ×6，新增可自动应用目标 **0 / 6**。其中章节样本召回了更相关的作品系列，但仍不能确认当前章节；没有证据证明识别效果提升。
- 按前述较弱书名/卷册核对，原查询 4 / 6 有相符候选；新查询自身仅 2 / 6，合并原候选后仍为 4 / 6，没有新增可核对目标。不能只用“查询更简短”或“返回相关条目”宣称改进。
- 应用内 AI 始终未启用、实际模型请求 0。真实模型结构化兼容性、OFF/SUGGEST_ONLY/ASSIST_ON_AMBIGUITY 的运行对照、模型错误/超时回退、2 次模型请求预算以及模型收益均**待验**。旧 fixture 模式/预算/回退测试可复用为工程证据，不能冒充这里的真实模型证据。Codex 查询建议未扩展应用 AI 权限，也未成为候选事实来源。

本轮总计真实来源请求 **76 次**：初始连通/候选探测 3 次，A 组 61 次，Codex 对照 12 次；统计分母分开，不把探测或对照请求重复计入 A 组。

### 交付语义、局部补修与保留限制

未发现本轮必须修改生产实现才能解决的误写、预算绕过或身份被查询建议替换。低覆盖的直接观察是旧本地元数据缺失/污染、卷/章节与来源粒度不同、版本真值不足；没有重写匹配、调度或插件系统，也不为这批数据强行改作者或降低门槛。一次真实 TLS 错误按现有机制记录并待重试。当前不需要局部代码补修；这不等于真实正向识别或发布门禁全部通过。

核对路径修正 UI、`allow_path_metadata_repair`、共同应用与既有四组合测试，语义一致：

| 本地优先 | 路径修正 | 自动应用行为（均先通过身份匹配与字段保护） |
| --- | --- | --- |
| 开 | 关或开 | 仅补缺，不覆盖现有路径字段 |
| 关 | 关 | 仅补缺 |
| 关 | 开 | 仅可修正有持久化 PATH 来源证据的字段；未知来源的非空字段仍不覆盖 |

路径修正不解除作者/卷号冲突；人工保护始终有效。其已有测试未失效，本轮未重复扩大执行。其他边界保持：有声录音正向识别不包含；旧插件内部 HTTP 不在内置 gate 的完整预算保证范围；100k 仅证明单目标索引投影，不是吞吐量/全库识别验收；mobile-chrome 仅浏览器窄屏，无原生真机验收。

既有调度用例 `test_manual_wait_does_not_block_other_books_and_local_failure_stops_remote` 的 waiting/ready 失败仍未修复，未新跑或宣称恢复；默认递归 mypy 的 6 项既有依赖问题仍保留（sqlite、exception_diagnostics、library infrastructure books），本次文件局部检查通过的历史证据不代表递归检查通过。

### 冻结代码的发布预检

按仓库 ermao-release 技能与当前发布 ADR 执行只读预检，未选择新版本、改发布元数据或绕过规则：

```powershell
& 'C:/Program Files/nodejs/node.exe' scripts/validate-release-notes.mjs
# exit 0：Validated v1.4.3 with strict zh-CN and en-US release notes.
& 'C:/Program Files/nodejs/node.exe' scripts/release-mode.mjs --published-base
# exit 1：code-only cannot change unknown migration layouts or interface contracts
```

当前已有 v1.4.3 索引仍声明 code-only、基线 v1.4.2；实际差异命中 `apps/api-python/app/contracts/recognized_metadata_fields.py`，现有发布规则拒绝接口契约变更。该文件是 M3 已提交的共同字段契约；无 schema 变化不能免除这个门禁。检查在源码资格处停止，后续 published-base/产物资格未因此获得通过，不改白名单、不静默转普通发布。

仍未完成的发布门禁：真实有效 ISBN 首次识别、准确出版版本/正常纸书书名作者样本、真实 B 组、应用实际模型及模式/收益验证；后续新版本同步与本能力双语发布说明；按明确发布模式处理当前 code-only 不合格；普通发布要求的后端完整测试/容器边界验收及双架构不可变产物、完整性验证和发布分支对齐。现有 v1.4.3 说明校验通过不表示已为本功能准备新发布说明。本轮没有合并、tag、构建发布制品或发布；收口文档独立提交并沿用已授权的推送与 `[skip ci]`。

## M7 实施与最终验收记录

起点 `92faf33f`。工程实现与本地定向验收完成，外部来源/模型联调待验；这不是“所有发布门禁通过”。本阶段复用既有 pytest、tsx、Playwright 和临时 SQLite HTTP 夹具，未新增测试框架、表、迁移、依赖、CI 或发布配置。

收口两项直接缺陷：旧 MetadataLookupTask 可能保存非 JSON 原文、数组或 null 对象，`recognition_context.py` / `recognition_records.py` 原先会直接解析或取字段；现在跳过不能成为确认依据的历史记录，明确确认入口拒绝它们，不升级 ISBN 范围。新路径修正开关在配置尚未加载时可点击，随后会被加载结果覆盖；`recognition-settings-panel.tsx` 沿用加载禁用状态，保存按钮也等待加载完成。新增浏览器回归在修复前出现保存重载为 false，修复后桌面/窄屏均保持 true。没有混入已记录调度问题的修复。

三条纵切片均有现有生产入口证据：

- ISBN：真实登录/人工搜索记录 → 明确确认 ISBN → 自动资源队列 → Google parser 与 gate → ISBN-10/13 等价版本 → 共同 patch → SQLite → 两次实际旁车队列 → OPF。Google HTTP bytes 为 fixture；原文件 bytes 和 mtime 不变。`test_confirmed_isbn_google_to_automatic_edition_and_real_opf`。
- 多卷：无 ISBN 的第 2 卷任务经过共同匹配与实际持久化，仅第 2 卷简介变化，第 1 卷和父书不变；OPF 排队失败单独记录，已应用任务不重放。`test_explicit_volume_task_changes_only_selected_resource` 两分支。
- 噪声：实际 SourceNode/ResourceAsset 的 `001_黑暗坡食人树_扫描版_FINAL.txt` 进入 AI 有界输入；模型建议仅用于查询，候选仍用原目标验证，只有来源简介入库。OFF/SUGGEST_ONLY 无自动模型请求，双版本模型推荐仍待确认。`test_ai_assistance_queue.py` 三模式及歧义用例。模型 transport 为 fixture，不代表真实模型质量。

固定合成验收集 `test_fixed_acceptance_sample_denominators` 的 6 个目标为：唯一作品、作者冲突、卷号冲突、作者未知、双版本、空来源。真实 SQL 队列结果分别为 APPLIED、NO_MATCH、NO_MATCH、AMBIGUOUS、AMBIGUOUS、NO_MATCH。仅作为确定性规则回归统计：

| 指标 | 明确分母及结果 |
| --- | --- |
| 自动应用正确率 | 正确自动应用 1 / 自动应用 1 = 100% |
| 自动覆盖率 | 自动应用 1 / 可评估目标 6 = 16.7% |
| 候选召回 | fixture 含正确候选的目标 3 / 可评估目标 6 = 50% |
| 待人工确认占比 | AMBIGUOUS 2 / 可评估目标 6 = 33.3%（不是实际人工完成率） |
| 错版本写入 | 0 / 6 个可评估目标 |
| 每目标请求 | 6 次计入 gate 的 fixture 尝试 / 6 个目标 = 1；没有外部网络请求 |

真实人工标注样本数为 0，真实准确率/覆盖率/召回均未测，不能用上述数值推断生产表现。

100k 验证在同一 SQLite 库新增 100000 个无关 Resource 和对应 SourceNode：同一目标上下文、provider payload、SELECT 次数前后一致；每条 SELECT 的 EXPLAIN QUERY PLAN 无 Resource/SourceNode/MetadataLookupTask 全表扫描，投影仍为目标资源 1、文件最多 8。没有对外发大批请求或读取原件。既有跨两个 Python 进程的限速预约、网络前事务释放、缓存锁忙降级仍在最终组合中通过。

浏览器用真实 FastAPI/Next HTTP、权限、SQLite、来源解析和共同应用，仅替换 Google 响应 bytes。桌面 Chrome、mobile-chrome 窄屏各运行两个用例：配置保存/重载、逐字段确认、年精度日期不可提交、第二浏览器旧结果 409、Escape、重开显示实值；策略保存重载、来源禁用后零请求。随后停止并重新启动 8106 fixture 进程（同一临时 STORAGE_ROOT），重新登录检查 Google disabled、configuredSecrets.apiKey=true、allowRepairPathMetadata=true，禁用查询 candidates=[] 且请求计数 0。这里的 mobile-chrome 是浏览器视口，不是 Android/iOS 原生验收。

验收矩阵的证据归属（测试路径均相对 `apps/api-python/tests`）：

| 矩阵 | 已运行证据 |
| --- | --- |
| R01–R07、R10 | `unit/modules/metadata/test_recognition.py`：作者/标题/卷号/套装、10/13 ISBN、聚合/系列限制、语言/出版社/修订冲突、去重歧义；内部卷号冲突先于 ISBN |
| R08–R09、R11 | `integration/modules/metadata/test_bibliographic_providers.py`、共同 supplement 用例、日期精度用例与浏览器禁用部分日期字段 |
| R12 | 纸书版本即使有等价 ISBN 且 payload 带 narrator/abridged，也不授予音频字段；目前来源未提供已确认的录音身份，C26 的正向录音版本联调没有证据，不声称已支持 |
| R13–R15、R27 | `test_metadata_lookup_queue.py` 的 PATH/取消/删除/父级修改、多卷场景；`integration/modules/automation/test_metadata_patches.py` 和 `contract/api/test_recognized_metadata_api.py` 的权限、保护、跨会话修订、重复确认/副作用、伪造候选/字段拒绝 |
| R16–R17、R19–R20 | queries/cache、AI assistance 单元/实际队列模式与假候选拒绝；浏览器禁用来源零请求 |
| R18 | 实际队列分别保存 RATE_LIMITED、AUTHENTICATION、SOURCE_RESTRICTED、PARSE_ERROR、TIMEOUT，业务 outcome=SOURCE_ERROR 且保留有时间的重试；空来源另为 NO_MATCH；provider diagnostics 检查真实异常原因 |
| R21 | AI 输入/输出白名单与恶意文本拒绝；封面私网 DNS、MIME/大小、损坏图片；来源详情只提取来源 ID 后构造固定端点 |
| R22–R23 | 两进程限速、8 次来源/2 次 AI 预算、格式重试/取消、旧 worker 拒绝、lease 恢复与配置实际进程重启；没有模拟宿主断电或外部网络长期中断 |
| R24–R25 | 实际 OPF 与原件不变、关闭/故障分离；旧排序保留密钥、旧 AI 默认模式、旧客户端、人工保护和历史队列 payload 不扩权 |
| R26、R28 | 100k 索引投影；两个浏览器会话与刷新后实际保存值 |

最终定向命令与结果：

```powershell
# apps/api-python
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/unit/modules/metadata/test_recognition_queries.py tests/unit/modules/metadata/test_automatic_rate_limiter.py tests/unit/modules/metadata/test_ai_assistance.py tests/integration/modules/metadata/test_recognition_context.py tests/integration/modules/metadata/test_bibliographic_providers.py tests/integration/modules/metadata/test_provider_registry.py tests/integration/modules/metadata/test_provider_failure_diagnostics.py tests/integration/modules/metadata/test_search_transactions.py tests/integration/modules/metadata/test_ai_assistance_queue.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py tests/integration/modules/automation/test_metadata_patches.py tests/unit/modules/library/application/test_recognized_metadata.py tests/unit/modules/library/infrastructure/test_recognized_metadata_cover.py tests/contract/api/test_recognized_metadata_api.py tests/contract/api/test_queue_metadata_contract_regressions.py tests/test_metadata_lookup_queue.py tests/test_metadata_writeback_queue.py --tb=short
# 203 passed in 76.89s
.venv-windows/Scripts/python.exe -m ruff check app/modules/metadata/infrastructure/recognition_context.py app/modules/metadata/infrastructure/recognition_records.py tests/contract/api/test_recognized_metadata_api.py tests/integration/modules/metadata/test_ai_assistance_queue.py tests/integration/modules/metadata/test_recognition_context.py tests/test_metadata_lookup_queue.py tests/test_metadata_writeback_queue.py tests/unit/modules/metadata/test_recognition.py
.venv-windows/Scripts/python.exe -m mypy --follow-imports=silent app/modules/metadata/infrastructure/recognition_context.py app/modules/metadata/infrastructure/recognition_records.py
# apps/web；实际使用 C:/Program Files/nodejs/node.exe（Node 22）
node node_modules/tsx/dist/cli.mjs --conditions=import --test features/books/api/client.test.ts features/books/model/recognized-metadata.test.ts features/books/model/metadata-match.test.ts features/books/application/metadata-apply-completion.test.ts
# 32 passed
node node_modules/typescript/bin/tsc --noEmit
node node_modules/eslint/bin/eslint.js e2e/metadata-recognition.spec.ts features/organize/recognition-settings-panel.tsx
$env:RECOGNITION_HTTP_SMOKE='1'; $env:PLAYWRIGHT_BASE_URL='http://127.0.0.1:3100'
node node_modules/@playwright/test/cli.js test e2e/metadata-recognition.spec.ts --project=chrome --project=mobile-chrome --workers=1 --reporter=line
# 4 passed；fixture 启动方式见 M6 与 tests/fixtures/recognition_http_server.py
```

最终后端组合 203 passed in 76.89s，Web 32 passed，浏览器 4 passed in 24.8s；上述 ruff、2 文件局部 mypy、Web tsc/ESLint 和 git diff --check 通过。静态检查按变动文件限定；未运行全量回归。M6 的 2375 条双语目录校验通过，M7 未新增用户文案。

已知缺口：没有真实 Google Books/Open Library/豆瓣/Bangumi 或真实模型凭据联调，没有真实标注准确率；有声录音正向证据未提供。沿用 M0/M1/M2 已定位的 `test_manual_wait_does_not_block_other_books_and_local_failure_stops_remote` waiting/ready 调度失败，未改断言或屏蔽；M6 默认 mypy 递归依赖暴露的 6 项既有问题仍保留，局部检查通过。旧 entry-point 插件内部 HTTP 仍不能从旧接口逐次观测，内置来源受统一 gate。没有全量构建、移动真机或发布产物验收。

发布范围为 Web/Python 应用与既有记录/配置 JSON 的兼容扩展，无 schema/依赖/原件拓扑变动。按当前发布 ADR，普通发布仍是默认；只有后续明确要求 code-only 才在冻结发布提交执行 `node scripts/release-mode.mjs --published-base` 判断资格，并补版本同步、双语说明、双架构产物/依赖身份和远端完整性门禁。当前未给出已具备 code-only 资格的结论。本轮只分阶段提交、推送并带 `[skip ci]`，没有合并、tag 或发布。

## M6 实施记录

起点 `ee6467e2`。既有来源页增加参与方式、查询/层级说明、AI 辅助模式与认证选择；连接/模型请求/配置检查分别标注，Open Library 仍仅人工。识别策略页面接通默认关闭的路径修正和固定请求预算说明。弹窗空查询使用既有 ISBN/标题作者计划，AI 建议只填查询词，候选按共同规则展示；字段选择受服务端 confirmableFields、保护、范围和日期精度约束，不再显示误导性的来源置信百分数。

复用 MetadataLookupTask 保存 schema 3 有界人工结果；现有整理详情展示业务 outcome，并可重开/忽略待确认结果。重开与提交校验原目标、书/资源归属、完整上下文指纹；提交只接受记录中的来源 ID，字段值从服务端记录取回。明确人工选择只补来源身份，不解除已知标题/作者/卷号冲突。确认后的 ISBN 范围仅在来源明确 EDITION、当前 ISBN 等价、确认修订仍一致时投影；单纯保护/校验位仍不能升级范围。重复确认无新写入和 OPF 副作用，忽略结果由既有指纹抑制。资源 sourceNodeId 保存并重新验证，不把未绑定目录变成整书写入目标。

删除目录识别弹窗直接把候选写入目录的旧路径，改用同一个逐字段确认弹窗；没有明确资源绑定的目录只能查看候选，人工编辑入口保留。页面更新保留当前导航和选择。实际浏览器测试暴露并修正详情轮询清空候选、展示字段夹带到严格应用请求、Escape 失焦失效；SQLite 毫秒时间/浮点表示进入稳定修订摘要，避免无变化结果误过期。新字段和文案完成 zh-CN/en-US。没有新增表、迁移、依赖或独立审核页面。

有效验证：

```powershell
# apps/api-python
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/integration/modules/metadata/test_recognition_context.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py tests/unit/modules/library/application/test_recognized_metadata.py tests/contract/api/test_recognized_metadata_api.py tests/test_metadata_lookup_queue.py --tb=short
# 102 passed（运行时尚未加入 M7 的 100k 用例）
.venv-windows/Scripts/python.exe -m pytest -q tests/contract/api/test_queue_metadata_contract_regressions.py tests/integration/modules/library/test_storage_metadata_writeback_organize_review.py --tb=short
# 10 passed
# apps/web；Node 22，沿既有 tsx / Playwright runner
node node_modules/tsx/dist/cli.mjs --conditions=import --test features/books/api/client.test.ts features/books/model/recognized-metadata.test.ts features/books/model/metadata-match.test.ts features/books/application/metadata-apply-completion.test.ts
# 32 passed
node node_modules/@playwright/test/cli.js test e2e/metadata-recognition.spec.ts --project=chrome --workers=1 --reporter=line
# RECOGNITION_HTTP_SMOKE=1、PLAYWRIGHT_BASE_URL=http://127.0.0.1:3100；1 passed
```

HTTP 浏览器夹具用临时 STORAGE_ROOT 启动 `tests/fixtures/recognition_http_server.py`（端口 8106），Next 的 PYTHON_API_ORIGIN 指向它。真实登录、配置保存/重载、来源 parser/gate、搜索记录、预览、共同 patch、SQLite 和详情刷新均运行；仅 Google 响应 bytes 是固定夹具，无外部网络。两个独立 browser context 中第二个旧结果返回 409，不覆盖第一个窗口写入；年精度日期保留 1980 且不可提交。夹具必须显式启用，不能指向生产库。7 个关键 Python 文件局部 mypy、变动 Python ruff、变动 Web ESLint、Web tsc 和 2375 条双语目录校验通过。默认 mypy 递归依赖检查另外暴露原 sqlite/diagnostics/books 的 6 项既有问题，未改范围外代码；使用 follow-imports=silent 的本次文件检查通过。

移动窄屏、重启和最终矩阵继续 M7。真实来源/模型凭据及真实标注样本仍缺失；不将该固定 HTTP 夹具称为来源准确率或真实联网验收。

## M5 实施记录

起点 `65dc2d42`。AI Manifest 改为 assist 角色，从后台事实来源顺序中移除。既有启用配置缺少新字段时解释为 SUGGEST_ONLY，旧模型/地址/密钥保留；新增 OFF、ASSIST_ON_AMBIGUITY 和 bearer/none（none 不发送 Authorization）。运行配置、自动入口及客户端都检查模式，主开关关闭不请求。模型测试走同一客户端的真实 Chat Completions 结构化请求，使用所选模型，不再 `/models` 探测。

应用层 `ai_assistance.py` 仅生成有界证据输入和严格解析查询辅助/候选消歧：最多 5 个候选，输入 <=12000 字符，输出 800 tokens；字段/类型/长度/候选键/证据引用逐一校验。文件只取 basename，移除旧的 parentPaths/raw 元数据摘要、任意元数据生成建议和 AI 虚拟候选转换。模型无工具权限，输入作为不可信数据；新词即使模型自称确定也标 hypothesis。两种用途和格式重试共享每目标 2 次尝试，外部来源仍共用 8 次预算；取消/故障降级保留规则结果。

自动困难分支在常规来源结束后才询问模型，查询建议仅改变下一次查询，绝不修改用于匹配的原目标/作者/别名。新查询排除 Open Library，返回候选仍经 M1–M3。候选消歧保存推荐键供人工查看，模型偏好不会解除多版本歧义；强冲突/保护仍由共同规则约束。缓存 v3 包含提示词版本、模型、认证配置、目标授权范围和候选实际内容，只缓存通过本地校验的建议，不保存模型全文。手动搜索响应增加可选 assistance，现有弹窗的可见入口和记录重开继续在 M6 完成。

有效验证（`apps/api-python`）：

```powershell
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_ai_assistance.py tests/integration/modules/metadata/test_ai_assistance_queue.py tests/integration/modules/metadata/test_search_transactions.py tests/integration/modules/metadata/test_provider_registry.py tests/integration/modules/metadata/test_provider_failure_diagnostics.py tests/integration/modules/metadata/test_bibliographic_providers.py tests/unit/modules/metadata/test_recognition_queries.py tests/contract/api/test_recognized_metadata_api.py tests/test_metadata_lookup_queue.py --tb=short
# 78 passed；8 个关键生产文件 mypy、变动 Python ruff 通过。
```

17 个新增 AI 用例覆盖不存在 ISBN 字段/候选/证据、类型/乱码/超长输出、隐私边界、两个格式请求后停止、取消零请求、none/bearer、实际结构化模型测试。真实 SQLite 自动队列三种模式验证 OFF/SUGGEST_ONLY 零模型请求；ASSIST 模式提示查询后只有来源描述入库；两个同身份候选即使模型选中一个仍 AMBIGUOUS 且零写入。未调用真实外部模型；模型兼容性和真实样本质量保持外部联调待验，不把 fixture 成功视为模型能力证明。

## M4 实施记录

起点 `11a90bb2`。新增默认关闭的 Google Books、Open Library Manifest，沿既有 Source bootstrap 幂等创建、配置/密钥脱敏、连接测试、候选缓存、请求 gate 和手动搜索入口接通。来源配置支持 OFF/MANUAL_ONLY/AUTO_AND_MANUAL，Open Library 仅支持前两者；服务端同时验证单目标、MANUAL 和明确人工查询入口，不参与后台 provider order、补缺和 AI 自动扩展。旧排序 payload 可只包含旧来源，保留遗漏来源的启用状态和全部密钥，使用单条 CASE UPDATE 保持原有有界 SQL 测试门槛。

Google 支持 ISBN、标题作者查询和 `id:<volume-id>` / `google-books:<volume-id>` 详情；只使用官方固定地址和配置密钥。映射作者列表、出版信息、原日期精度、语言、封面、简介，分类与人工 tags 分开。404 是零结果，429 保留错误不缓存；缺密钥或禁用不请求。Open Library Work 查询只保存作品事实，丢弃搜索聚合 ISBN/出版社/语言；ISBN 返回的具体 Edition 与 `/books/OL…M` / `/works/OL…W` 分开，最多两次作者详情。默认 1 request/s，保守遵循官方非鉴别请求限额；实际连接测试仅校验配置，明确要求从单目标执行查询，不偷偷发送无目标请求。

豆瓣详情显式提取 ISBN、出版者、原出版日期和多作者，只有绑定 subject 的出版事实才给来源 EDITION 范围，套装仍 SET，不改变本地 UNKNOWN 约束。半精度日期不再补 1 月 1 日。抓到的详情 URL 只提取 subject ID 后请求配置站点，拒绝验证码/访问受限，异常 HTML 与真正空结果分开。Bangumi 以书名/别名而非拼接作者检索，补最多两个必要详情，保留原作/作画角色；条目名不再自动成为 seriesName，作品/卷册不升级为出版版本。

依据：[Google Books 查询/详情](https://developers.google.com/books/docs/v1/using)、[Volume 字段](https://developers.google.com/books/docs/v1/reference/volumes)、[Open Library 使用政策与限速](https://openlibrary.org/developers/api)、[Work/Edition 搜索语义](https://openlibrary.org/dev/docs/api/search)、[Books API](https://openlibrary.org/dev/docs/api/books)、[Bangumi 官方 API](https://bangumi.github.io/api/)。本阶段没有使用真实 Google 凭据/生产数据；UI 配置选择控件及真实 HTTP 浏览器流程继续 M6/M7，不能据 fixture 宣称真实来源联调完成。

有效验证（`apps/api-python`）：新来源 fixture/真实 SQL 配置投影/请求构造/缓存/禁用/旧排序及原直接消费者组合 pytest 129 passed（命令见下）；另有 37 项精确复核通过，4 个关键文件 mypy、所有修改 Python ruff 通过。新增 12 个来源用例。旧空 HTML fixture 现在明确按解析错误拒绝，原 ISBN 请求测试改为合法空搜索响应，仍验证实际 HTTP 的 ISBN 和网络前事务释放，没有放宽断言。

```powershell
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/unit/modules/metadata/test_recognition_queries.py tests/unit/modules/metadata/test_automatic_rate_limiter.py tests/integration/modules/metadata/test_bibliographic_providers.py tests/integration/modules/metadata/test_provider_registry.py tests/integration/modules/metadata/test_provider_failure_diagnostics.py tests/integration/modules/metadata/test_search_transactions.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py tests/integration/modules/metadata/test_recognition_context.py tests/contract/api/test_recognized_metadata_api.py tests/test_metadata_lookup_queue.py --tb=short
```

## M3 实施记录

起点 `bd531a3f`。Provider 字段映射收敛到 `contracts/recognized_metadata_fields.py`，FieldProposal 保留当前值、保护、候选键、层级及证据。自动和手动通过原 `ApplyMetadataPatches.stage` 复用白名单、字段校验、授权范围、修订与操作记录，删除对应直接 ORM 字段写入；原 execute 仍拥有提交，stage 由识别用例持有事务。系统身份绑定 RUNNING 的真实任务与明确目标，没有 MCP grant 或 override 权限。

资源目标由任务记录明确声明；代表资源不会自动成为写入目标。资源修订包含父级字段，搜索返回 targetRevision/bookRevision，确认支持旧修订拒绝；旧客户端不强制新增字段。自动写入不误标人工保护。历史 UNKNOWN 来源仅补缺；`allowRepairPathMetadata` 默认关闭并保存在原 rulesJson，且本地优先关闭后才允许已持久化单资产本地观察、当前值和解析优先级共同证明的 PATH 值修正。多资产或缺观察保持 UNKNOWN，不凭文件名相同猜来源。旧请求遗漏新字段不会重置它。无需 schema 迁移。

可靠主来源之后最多访问一个额外来源，仍经原预算；补缺候选同时通过目标匹配与对主来源的身份比较，不合并作者/卷号/出版社等强冲突。日期建议保留年/月精度，不伪造日期。结果保留有界候选摘要、提议与修订，不存 provider raw 响应。记录的重新打开/忽略、服务端候选绑定和逐字段 UI 在连续执行的 M6 收口，不把该 UI 写成已交付。

手动和自动共用安全封面下载：禁凭据 URL/非 HTTP(S)/私网解析及重定向；连接固定在已检查的 DNS 地址，TLS 仍验证原主机，不跟代理或重解析。检查 MIME、大小和完整图片。封面独立失败可保留其他字段；原补偿改为共同 patch 且精准目标。OPF 通知共用装配入口、遵守原开关，无变化不排队；DB 成功但 OPF 排队失败单独记录，任务不会重放元数据。实际定向测试暴露 Windows 时钟纳秒重复导致连续操作 ID 冲突，既有 operation factory 改 UUID，未修改调度行为。

有效验证（`apps/api-python`）：

```powershell
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/integration/modules/metadata/test_recognition_context.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py tests/integration/modules/automation/test_metadata_patches.py tests/unit/modules/library/application/test_recognized_metadata.py tests/unit/modules/library/infrastructure/test_recognized_metadata_cover.py tests/contract/api/test_recognized_metadata_api.py tests/test_metadata_lookup_queue.py tests/unit/modules/library/test_library_operations.py --tb=short
# 116 passed；9 个关键生产文件 mypy 通过；全部变动 Python ruff 通过。
```

新增实际队列反例证明仅第 2 卷变化、父书/第 1 卷不变，OPF 故障保持 COMPLETED；准备后父级变更/人工保护/取消/删除拒绝；两个真实 Session 的旧搜索修订在 HTTP 返回 409。PATH 四种设置/证据组合经过真实数据库与持久化策略验证。未做外部来源或浏览器联调，继续 M4–M7；历史 ISBN 仍缺显式范围，不能单凭校验位或保护标记升级，后续确认事实需保持这一边界。

## M2 实施记录

起点 `10a79a88`，工作树干净。应用层新增小型有界查询计划：明确人工 query 保留，适用来源优先校验后的资源 ISBN，再用标题/作者及已有别名；不改变用于匹配的原目标。手动资源数据库投影至实际 HTTP 请求已验证 ISBN 查询。自动 book 仍不借代表资源 ISBN；明确资源自动应用在 M3 接入。

候选缓存改为版本化摘要键，包含 provider、完整结构化目标上下文、查询、配置语义及凭据轮换摘要；不保存明文凭据于 key，不缓存匹配结论。成功空结果缓存 30 分钟；错误不缓存，命中后仍重新匹配。池上限 10。Provider 公共入口共用请求 gate；8 次来源尝试和 2 次 AI 尝试预算分开记录，技术重试保留计数。所有内置来源和连接测试受限速；HTTP 不自动跟随重定向，避免隐藏额外请求及凭据转发。旧 entry-point 插件 API 保持兼容，其内部自发 HTTP 仍无法由旧契约逐次观测；公共调用计数，完整新 gate 契约接入及真实来源纵切片继续在 M4/M7 验证。

跨进程预约复用 ExternalMetadataCache 的既有唯一索引，保留独立 namespace 的每源一行数值状态；SQLAlchemy 原子 upsert/returning 后释放短事务再等待，未新增表/迁移/Redis。跨两个实际 Python 进程的预约间隔测试通过。下一请求与等待过程检查取消、来源禁用及配置改变；网络前关闭读事务。任务结果增加版本 2 recognition 对象，分离 APPLIED/NO_CHANGES/AMBIGUOUS/NO_MATCH 和技术错误，保留 selected/attempted 读取形状；零结果冷却至少 24h、同指纹待确认抑制自动再次入队，目标/策略/来源修订改变后允许重查。查询只看当前 book 的最近记录和有界上下文，不回填历史。

有效测试（工作目录 `apps/api-python`）：

```powershell
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/unit/modules/metadata/test_recognition_queries.py tests/unit/modules/metadata/test_automatic_rate_limiter.py tests/integration/modules/metadata/test_recognition_context.py tests/integration/modules/metadata/test_search_transactions.py tests/integration/modules/metadata/test_provider_registry.py tests/integration/modules/metadata/test_provider_failure_diagnostics.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py tests/test_metadata_lookup_queue.py tests/contract/api/test_recognized_metadata_api.py
# 102 passed；11 个生产文件 mypy --follow-imports=silent 通过，改动 Python 的 ruff check 通过。
```

另执行 T2 调度消费者时，组合为 47 passed、1 failed：仍是原 M1 记录中 `test_manual_wait_does_not_block_other_books_and_local_failure_stops_remote` 的 waiting/ready 既有失败，未改断言或隐藏跳过。本次预算/上下文/缓存检查未依赖该失败；后续最终门禁仍明确保留此缺口。不宣称全部调度回归通过。来源/模型真实联调、UI 和统一字段应用不在此提交中冒充完成，继续 M3–M7。

## M1 补修记录（2026-09-26）

本次起点、审查提交和实际 HEAD 均为 `9c6ccbb8a78d47a7e3da9db38a3d746c9c273df9`，分支 `codex/metadata-recognition-enhancement`，开始时工作树干净。只补修以下三个证据问题；独立提交并沿用用户授权推送及 `[skip ci]`，不进入 M2，不改调度、查询计划、缓存、限速、资源自动写入或统一 patch。

- **卷号冲突**：`app/modules/metadata/domain/recognition.py` 原来用结构化卷号 `or` 标题卷号，掩盖同一对象的矛盾。现在分别保留标题、显式 volume、确认过语义的 resourceIndex 观察与证据引用，先检查两侧各自内部冲突，再比较双方；共用 NFKC、数字/中文数字归一化（包含数据库浮点 `1.0`），任何卷号冲突都拒绝且没有 allowed_fields，ISBN 相同也不能越过此检查。
- **ISBN 范围**：`application/recognition.py` 删除 douban 加 ISBN 自动升级 EDITION 的分支；显式 UNKNOWN、SET 及缺少 scope 均不升级。`infrastructure/recognition_context.py` 删除资源 ISBN 无条件 EDITION：现有资源表只有 ISBN 值，没有范围证据，字段保护也不能证明范围。数据库投影保持 UNKNOWN；已有显式双方 EDITION 的共同规则仍支持合法 ISBN-10/13 等价与版本字段授权。套装关键词仅保留为额外限制，不替代 scope。
- **父级和资源证据**：确认 `source_tree_repository.py` 将本地 `volume_index` 写到 `resource_index`，但 OPF 同时可能从 `calibre:series_index` 取得它，catalog/bookshelf 等又用于排序，故历史值不能一概作为出版卷号。现有手工资源编辑把字段标为 protected，Web 标签明确为“卷号”：仅这样的本地 resource_index 接入独立资源卷号证据。候选只有明确 `matchLevel=VOLUME` 时接入 resourceIndex；普通排序、无范围的 index 和 series_index 不接入。显式 volume 与 resourceIndex 同时存在时仍各自校验，不作优先级覆盖。
- **父级确认依据**：Book 也可能只是目录聚合；只在现有 title、author 均经过手工保护且作者存在时，将其标题作为独立 work_title 证据，并且仅用于当前标题是纯卷号、父级标题本身不是卷号的情况。未确认父级/普通目录仍待确认；不拼写或替换子资源标题，不借兄弟 ISBN，不扫描操作日志。未保护的历史父级即使看似书名，也不会因此获得强作品身份。

路径前缀为 `apps/api-python/`。生产修改仅以上三个 recognition 文件；仍由自动队列和手动搜索共同使用原 assess_candidates/decide_match。复用 VOLUME_CONFLICT、UNKNOWN_SCOPE、INSUFFICIENT_EVIDENCE 等现有双语原因，无 Web/翻译/API schema 变化。

### 反例和验证

先将场景补进原有三份测试文件，在未修改生产代码时运行下列反例命令：**12 failed、5 passed、47 deselected**。失败包括 book/resource 的“本地第 1 卷、候选第 2 卷但 volume=1”（含相同 ISBN）、本地内部矛盾、UNKNOWN/缺失 scope 被升级、数据库资源 scope 错误；真实自动队列在 `preferLocalMetadata=False` 时实际将标题从第 1 卷改成第 2 卷。修复后这些场景通过：矛盾拒绝且无授权字段，队列 NO_MATCH 且原题保留，范围不明不能授权版本字段；01/一仍匹配。

```powershell
# 工作目录 apps/api-python；修复前反例复现：12 failed / 5 passed
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/integration/modules/metadata/test_recognition_context.py tests/test_metadata_lookup_queue.py -k 'structured_volume or local_volume_evidence or provider_isbn_scope or confirmed_parent or unconfirmed_resource_order or conflicting_candidate_cannot'
# 最终五个直接消费者：76 passed（原 55 项 + 本次 21 项），14.35s
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/integration/modules/metadata/test_recognition_context.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py tests/test_metadata_lookup_queue.py tests/contract/api/test_recognized_metadata_api.py
# 3 个生产文件类型检查通过
.venv-windows/Scripts/python.exe -m mypy --follow-imports=silent app/modules/metadata/domain/recognition.py app/modules/metadata/application/recognition.py app/modules/metadata/infrastructure/recognition_context.py
# 6 个变动 Python 文件检查通过
.venv-windows/Scripts/python.exe -m ruff check app/modules/metadata/domain/recognition.py app/modules/metadata/application/recognition.py app/modules/metadata/infrastructure/recognition_context.py tests/unit/modules/metadata/test_recognition.py tests/integration/modules/metadata/test_recognition_context.py tests/test_metadata_lookup_queue.py
```

新增 SQLite 测试经过真实数据库投影 → 候选转换 → 共同规则，覆盖确认父级、未确认父级、双方资源卷号相同/不同、本地保护卷号与自身标题冲突、普通排序和 series_index 不充当卷号、持久化 ISBN 本身不足以确认版本；子资源标题保持原值。追加边界包含套装范围不授权分册版本字段、候选 resourceIndex 不掩盖显式 volume。所有场景使用既有夹具与测试入口，没有引入审查快照或第二套测试框架。

未验证真实来源网络、生产数据准确率、浏览器/移动交互及全量回归；没有 Web 改动，未重复运行 Web 测试。当前数据库不保存显式 ISBN scope，因此本地数据库路径不会仅凭 ISBN 产生 EDITION；这是缺失证据的保守边界，不以出版商、校验位或保护标记猜测范围。原 M1 记录中的范围外调度失败未改、未重跑。没有新表、依赖、工作流或发布操作；后续阶段门槛仍按下方原计划，不宣称 M2 或最终发布验收完成。

## M1 交付记录

用户本次授权执行 M1、完成后推送并跳过 CI。起点为 `codex/metadata-recognition-enhancement@a09a37ce649dcf0f4e8f28e29183bc40c0a59d89`，开始时工作树干净；远端 develop 仍为 `33a71986`，远端尚无本开发分支。M0 以下各节保留为当时核查记录，不视为 M1 后的当前实现。M1 提交使用 `[skip ci]`，只推送当前开发分支，不创建 PR、不合并、不发布；仓库 push 工作流本来也只监听 develop/prod/版本 tag，不改 workflow。

### 实际功能和调用链

- 新增 `modules/metadata/domain/recognition.py`：显式 RecognitionContext、IdentityEvidence、Contributor、CandidateEvidence、MatchDecision；归一化保留原值，ISBN 校验及 10→13 等价、作者角色/UNKNOWN、中文/Vol 卷号、上下册/续作/版本冲突、层级和允许字段均由一处规则决定。同名且作者不明待确认，已知作者/卷号冲突拒绝；AI 自报候选不能进入自动匹配。模糊比较仅排序；同源同 ID 去重，重复身份内容冲突或多个可靠候选转待确认。
- 新增 `modules/metadata/application/recognition.py`：已有 Provider 字典在此转换为候选证据；来源键绑定实际请求的 providerId，不采信返回 payload 的 source 冒充来源。alias/raw/infobox 的标题提取迁到此处，organize_service 旧标题工具仅委托；用户输入 query 不变成身份事实。
- 新增 `modules/metadata/infrastructure/recognition_context.py`：按 book 或明确 resource 投影已有值、保护、目标/关联修订、库、执行方式和规则/策略修订；父级 title 独立保留。未证明的 provenance 一律 UNKNOWN，不把 identifier 猜成来源 ID，不读操作历史全表。聚合判断最多读 2 个资源 ID，Provider 兼容输入最多 8 个资源/8 个文件名，读取前限制，不逐图识别。多资源 book 暂保守要求聚合层级证据，不能借某子卷 ISBN。
- 自动链：现有 task → 有界 book 上下文 → 原 Provider 查询 → assess_candidates/rank_matches → MATCHED 才进入原应用分支。删除 `_choose_exact_candidate`，用真实队列行为用例取代旧私有选择器测试；保留短事务/取消/book guard/OPF 机制。决定和证据引用写入现有 attempted 记录的 matches；任务状态仍用原 NO_MATCH/COMPLETED，完整业务 outcome/冷却属于 M2。
- 自动整理现有任务实际写 book；其 resourceId 是调度器选出的代表资源及导入/OPF 引用，M1 不把它偷偷升级为明确版本目标。M1 只把规则允许的 title/author/description 传给现有 book writer；description 还要求 Provider 明确给出匹配范围。现有来源无法证明简介/标签/系列/封面范围时保守不自动写，自动采用覆盖率会降低，完整字段建议和 resource 应用留到 M3。此阶段没有新增自动资源写入。
- 手动链：原 search HTTP 新增可选 resourceId → 原用例/adapter → 相同上下文与 assess_candidates → 候选返回可选 match（outcome/level/candidateKey/evidenceIds/reasons/allowedFields）。保留现有字段及 payload 兼容；其他 book 的资源返回 404，不请求来源。两个已有弹窗传明确资源 ID、保持后端排序并显示双语状态/层级/原因，未知原因有保守提示。UI 与 DTO 仍不拥有信任/写入授权；手动 patch 统一、修订提交和逐字段确认门槛留到 M3/M6。

后端本段路径前缀为 `apps/api-python/app/`。其余生产改动仅涉及 metadata public、library 的 source_node_metadata_recognition 用例/适配器/HTTP/schema，以及 `services/organize_service.py`、`services/metadata_lookup_queue.py`。Web 改动限于 books API/client/model、两个现有识别弹窗、共用匹配说明组件和双语目录；API 是既有手写 client，不涉及生成 wire 文件。

### 有效验证与已知缺口

在 `apps/api-python` 使用现有 Windows Python 环境运行，未安装依赖、未改 lockfile：

```powershell
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/unit/modules/metadata/test_local_metadata.py tests/unit/modules/library/application/test_source_node_metadata_recognition.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py tests/test_metadata_lookup_queue.py tests/integration/modules/metadata/test_search_transactions.py tests/contract/api/test_recognized_metadata_api.py tests/contract/api/test_queue_metadata_contract_regressions.py tests/integration/modules/metadata/test_provider_registry.py tests/integration/modules/metadata/test_provider_failure_diagnostics.py
# 76 passed；随后补强冲突证据引用及作者列表边界，以下重验直接消费者和新增 SQLite 用例：
.venv-windows/Scripts/python.exe -m pytest -q tests/unit/modules/metadata/test_recognition.py tests/test_metadata_lookup_queue.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py tests/integration/modules/metadata/test_recognition_context.py tests/contract/api/test_recognized_metadata_api.py
# 55 passed；与上一组复用未变覆盖，共 79 个不同用例。
.venv-windows/Scripts/python.exe -m mypy --follow-imports=silent app/modules/metadata/domain/recognition.py app/modules/metadata/application/recognition.py app/modules/metadata/infrastructure/recognition_context.py app/modules/library/application/source_node_metadata_recognition.py app/modules/library/infrastructure/source_node_metadata_recognition.py app/modules/library/presentation/schemas.py app/services/metadata_lookup_queue.py app/services/organize_service.py
# 8 个文件通过；全部本次变动 Python 文件 ruff check 通过。
```

新增测试包括 31 个小型领域用例、实际自动队列的冲突/未知/可靠候选/聚合保护、HTTP 查询覆盖词不改变原卷身份、重复候选去重排序、跨书资源拒绝；SQLite 两个用例证明资源 ISBN/修订隔离、8 项投影上限、增加无关书后 SELECT 次数不变。是小型合成样本，不是生产识别准确率，也不冒充 M7 的 100k 或真实来源验收。

Web 使用仓库可用 Node 22（`C:/Program Files/nodejs/node.exe`）直接运行现有工具：`node_modules/tsx/dist/cli.mjs --conditions=import --test features/books/model/metadata-match.test.ts features/books/model/recognized-metadata.test.ts features/books/application/metadata-apply-completion.test.ts features/books/api/client.test.ts`，29/29；`node_modules/typescript/bin/tsc --noEmit` 通过；对本次 8 个 TS/TSX 文件执行现有 ESLint `--max-warnings=0` 通过。`scripts/generate-i18n-catalog.mjs --write` 生成目录后再检查，2344 条双语文案通过。默认 pnpm 指向不符合项目要求的 Node24/pnpm11，故使用上述固定工具链；i18n Python 调用复用临时 python3 shim，未改项目运行配置或依赖。

相邻调度套件 `tests/test_organize_scheduler.py` 有一项既有失败：`test_manual_wait_does_not_block_other_books_and_local_failure_stops_remote` 在第 309 行期望领取 ready，实际 waiting。该断言发生在新识别逻辑之前；用 `git show a09a37ce:apps/api-python/app/services/metadata_lookup_queue.py` 在独立 Python 进程加载 M0 原队列模块后单独运行该测试，同处复现。未跳过/修改断言，未改本次未触及的任务领取/导入生命周期；不能声称相邻套件或全量回归全部通过。

没有真实来源/模型联调、浏览器交互/双浏览器并发和移动验收；本次手动链证据为真实 HTTP 测试客户端与 Web 解析/标签单测、类型检查，不等同于 M6 浏览器闭环。未新增配置默认值、schema、迁移、依赖、原件写回或文件拓扑变化。不执行 M2–M7，不声明最终发布门禁通过。

## M0 基线与检查清单

- [x] 初始分支 `develop`，HEAD `33a71986f5a2307f563e5d5b3b6440219eeee5f7`（`chore(release): prepare code-only v1.4.3`），初始工作树干净。
- [x] 本地 `origin/develop` 和 `git ls-remote origin refs/heads/develop` 的实时结果均为上述 SHA；与方案基线、远端 develop 无差异，无本能力漂移待合并。
- [x] 在 `codex/metadata-recognition-enhancement` 独立提交 M0；不 push、不合并、不发版、不打 tag。
- [x] 读取 [仓库规则](../../AGENTS.md)、[工程规范](../engineering-standards.md)、[能力入口](../business-code-layering-and-refactoring.md)、[测试策略](../testing/test-execution-policy.md) 与相关现行实现；检索现有 plans，未发现等价增强识别计划。
- [x] 核对六项现存问题、实际入口、patch 适配边界、字段与层级、配置与历史结果、后续文件/验证范围、40 个用例设计。
- [x] M0 只新增本文；生产逻辑、默认值、schema、接口、依赖、lockfile、测试基础设施均不改。
- [x] M1 结构化证据与共同匹配（见上方交付记录及验证边界）。
- [x] M2 有界查询、缓存隔离、限速和业务 outcome。
- [x] M3 统一字段应用与人工确认结果。
- [x] M4 来源增强与新来源。
- [x] M5 AI 辅助。
- [x] M6 后台与确认闭环。
- [x] M7 工程实现与本地定向验收；真实来源/模型与标注样本验收待补，见 M7 缺口。

## 当前调用链与直接证据

以下文件路径相对仓库根；函数名为本次从当前 HEAD 读取的定位锚点。后续目标不描述为已经实现。

| 入口 | 当前真实调用链 |
| --- | --- |
| 来源配置 | `apps/web/features/organize/metadata-providers-panel.tsx` → `/metadata/providers`、`/metadata/provider-order` → `apps/api-python/app/modules/metadata/presentation/http.py` → `services/metadata_provider_registry.py` 的 prepare/persist/test → `modules/metadata/infrastructure/sources.py` 与现有 Source 行。Manifest 在 `modules/metadata/domain/providers.py`，是能力和配置字段描述者。 |
| 策略与自动任务 | `apps/web/features/organize/recognition-settings-panel.tsx`、`features/settings/center/organize-settings-page.tsx` → organize policy HTTP → `modules/organize/application/commands.py::prepare_organize_policy_update` → policy 存储。`services/organize_scheduler.py::process_organize_schedule_tick` 分别以 NEW/SCHEDULE 调用 `create_organize_run` → OrganizeJob/MetadataLookupTask → `services/metadata_lookup_queue.py::process_metadata_lookup_task`。导入完成是查询任务前置条件，外部调用不进入导入关键路径。 |
| 自动上下文/查询 | `metadata_context_for_book` → `modules/organize/infrastructure/review.py::load_book_context` → book、该书全部资源、各资源文件与元数据 → `_search_provider` → `search_with_metadata_provider` → 内置 `metadata_search_candidates` 或 entry point 插件。 |
| 手动查询 | `apps/web/features/books/metadata-lookup-modal.tsx` → `features/books/api/client.ts` → `/books/{book_id}/source-nodes/{source_node_id}/metadata/search` → library HTTP/用例 → `modules/library/infrastructure/source_node_metadata_recognition.py::ProviderSourceNodeMetadataRecognition.search` → metadata 公开 `search_with_metadata_provider`。手动 query 确实传入；当前节点上下文包含父书作者、节点标题和资源格式，未携带完整资源 ISBN/修订证据。 |
| 手动应用 | 弹窗字段选择 → `/books/{book_id}/metadata/apply` → `bootstrap/library.py::apply_recognized_metadata` → `modules/library/application/recognized_metadata.py::ApplyRecognizedMetadata` → `SqlAlchemyRecognizedMetadata`；封面走 `ApplyRecognizedCover` 和 `SafeRemoteCoverDownloader`。此路径尚未委托 `ApplyMetadataPatches`。 |
| 自动应用与记录 | `_choose_exact_candidate` → `_prepare_candidate_application` → `_persist_candidate_application` → book 更新及 facet 同步；另写任务 `candidateRawJson/appliedFields` 与 ProviderExecution。成功分支再 load writeback projection → `prepare_metadata_writeback_intents` → `enqueue_prepared_writeback_intents` → 既有 OPF 队列/worker。 |
| 查询/审核记录 | `modules/organize/presentation/http.py::_organize_job_view`、list/get/pending jobs 读取 lookup 与 writeback 展示；现有列表可复用，但完整 evidence/字段差异/过期判定尚未接通。 |

后端上表简写路径均位于 `apps/api-python/app/`。

| 必查问题 | 当前文件/函数证据与结论 | 收口阶段 |
| --- | --- | --- |
| 查询压缩为书名 | `services/metadata_lookup_queue.py::process_metadata_lookup_task` 向每源传 `str(book.get("title") or "")`；`organize_service.py::metadata_search_candidates` 回退 book.title。ISBN/作者/卷号没有形成自动查询计划。 | M1/M2 |
| 单个同名直接选中 | `metadata_lookup_queue.py::_choose_exact_candidate` 在 `len(exact) == 1` 直接返回，只有多个同名才比较已知作者。唯一候选的作者冲突/未知作者不是门槛。 | M1 |
| 缓存隔离不足 | `organize_service.py::metadata_search_candidates` 用 `metadata_title_key(search_text)`；`infrastructure/external_cache.py::get_cached_raw_json` 仅 provider + query_key；内置 ai 也参与。缺配置语义、授权上下文、候选内容等隔离。`external_metadata_result_cacheable` 当前只缓存有有效字段候选，成功零结果尚不缓存。 | M2/M5 |
| AI 普通来源 | `metadata_search_candidates` 把 AI suggestions 转成 `id="ai-suggestion"` 的普通 candidate；`run_ai_metadata_provider` 使用一套 bearer chat/completions 请求，要求 Key，30 秒超时。registry 内 AI 测试走 models；没有新模式/结构化辅助调用验证。 | M5 |
| 首源早停 | `process_metadata_lookup_task` 在第一份被旧选择器接受的候选应用后 `return "COMPLETED"`，没有基于目标字段需求和身份冲突决定继续/补缺。并非任意非空搜索结果都早停。 | M2/M3 |
| 自动资源字段应用 | `_PreparedCandidateApplication` 带 resource_id，但 `_persist_candidate_application` 仅 `update_book`/facet/job；没有调用 `lookup_queue.update_resource`。不是已存在的自动 resource 误写，而是能力缺口；当前 book 封面判断 `_local_cover_exists` 还显式丢弃 resource_id。 | M3 |

另有同链具体缺口：`review.load_book_context` 先加载资源/文件，`local_metadata_summary` 才截取 8 文件/4 元数据，不能称作有界 SQL；手动节点 search 也遍历节点下资源。`automatic_rate_limiter.py::AutomaticMetadataRequestRateLimiter` 明确为进程内、仅自动请求，不能称作跨 worker/手动共享限速。已有 `db.close()`、短写事务和 book metadata guard 应保留，不能把现状说成完全没有事务释放或并发保护。

## 写入复用结论与唯一归属

权威字段为 [METADATA_FIELDS](../../apps/api-python/app/modules/library/domain/metadata_patch.py)。[ApplyMetadataPatches](../../apps/api-python/app/modules/library/application/metadata_patches.py) 及 [SqlAlchemyMetadataPatches](../../apps/api-python/app/modules/library/infrastructure/metadata_patches.py) 可作为共同应用核心，**不能原样接入识别就宣布完成**。

| 边界 | 当前能力/限制 | 冻结的后续实现责任 |
| --- | --- | --- |
| 权限 | actor 有 user_id/grant_id/library_ids/can_write/can_tags/can_override；snapshot 按库授权，应用检查权限、字段与 revision。现装配在 `bootstrap/automation.py`。 | M3 在 library 公开应用入口复用；扩展 actor 的真实用户/系统任务来源表达，不伪造 grant，不依赖 MCP 配置。系统任务按实际任务库范围授权，不获得 override；用户按现有管理/资源授权，跨库反枚举。 |
| 字段/保护 | `prepare_metadata_patch` 是白名单/类型/清空/保护校验所有者；低层 `books.update_book_fields`、`resource_commands.SqlAlchemyResourceMetadata.update_resource` 及 tags 写入会保护字段。 | M3 使共同适配器明确区分人工所有权与自动来源；自动不能新增人工保护、越权覆盖或清空。保留人工显式保护语义。不得另写第二套字段验证。 |
| 无变更 | patch 的相同值赋值仍代表显式所有权决策；`updated` 统计非空 patch，不等于实际值改变。 | FieldProposal 先比较真实差异；自动/识别 no_changes 不产生无意义 patch、操作或 OPF 副作用，不能全局改变人工相同值赋值语义。 |
| 事务/修订 | execute 统一 commit/rollback；adapter apply 再取 snapshot 验 revision，涵盖值、保护、updated_at、库和 book 归属。自动现有 guard 仅 book 相关状态。 | M3 共用应用事务，不套另一套提交；网络/封面准备在事务外，写前重新检查目标和关联修订、权限、取消状态。父书字段也要独立 book revision；原 resource 删除后不得因 SET NULL 退化为 book 应用。并发双连接必须实测。 |
| 封面 | patch.resolve_cover 仅接受该书有界资源资产中的受控引用（最多 50）；不接受远程 URL，不能直接登记当前远端下载结果。手动已有安全下载/文件发布与补偿。 | M3 复用 SafeRemoteCoverDownloader/文件发布，最小扩展内部登记/解析以绑定精确目标，复用安全和大小校验；外部 coverUrl 永不直接作为 cover_ref。失败清理临时内容；封面失败可保留其他已验证字段并报告部分结果。 |
| provenance | PreparedMetadataPatch.provenance 存入 `record` 的操作 payload `changes[].source`；snapshot 不提供逐字段来源。local_metadata 的 field_sources 是解析结果，当前识别上下文不足以证明每个现有值来自 PATH。 | metadata 上下文只从可验证的现有来源记录取证；缺证据一律 UNKNOWN。新识别来源在现有操作记录有界保存；禁止依据“值等于文件名”反推来源或全库回填。M3 验证取证查询有界，不能扫描全部操作日志。 |
| OPF/原件 | patch 是数据库应用，不承诺自动 OPF；自动队列已有 projection/intents/enqueue，开关由 OrganizePolicy/writeback policy 管理。数据库成功后 OPF 入队仍可能失败。 | M3 在识别应用编排中显式复用 metadata 公开通知/队列，数据库和 OPF 状态分别返回/记录；不把入队异常当 DB 未提交而重复写入。不得给现有 MCP database-only 调用暗加文件副作用；EPUB/PDF/CBZ 原件不改。 |
| 诊断 | `app.core.exception_diagnostics` 及现有 FailureDiagnostics 端口可用。 | M2–M6 捕获终止边界记录原 cause、阶段及目标，先诊断再恢复；记录和补偿失败分别可查，不存秘密/正文/私有路径。 |

M3 替换范围是自动 `_prepare/_persist_candidate_application` 的直接字段写入与手动 `ApplyRecognizedMetadata` 的对应映射/写入分支；旧 HTTP 可作委托兼容壳。保留任务、facet、授权、文件发布和 OPF 所有者，不搬迁整个 services 文件。跨能力通过 `modules/library/public.py`、`modules/metadata/public.py`，装配在 bootstrap；若形成新的跨能力长期决策，按现行规范补 ADR，不能以本文绕过 ADR。

## 冻结的字段与身份规则

`RecognitionContext`、候选证据、`MatchDecision`、`FieldProposal` 为小型内部类型，不是新实体表。metadata/domain 负责归一化、ISBN/作者角色/卷号匹配与层级决策；metadata/application 负责目标上下文、查询计划和建议编排；基础设施提供有界投影/请求；library 拥有授权与最终写入。M1 同时接自动选择和手动排序/展示，M3 接共同应用。

| 目标 | 唯一允许字段 | 证据门槛 |
| --- | --- | --- |
| book | title、author、description、series_name、series_index、tags、cover_ref | title/author 至少确认适配此 book 的 WORK，聚合父书须有 SERIES 或对应聚合作品证据；series_name/index 必须有系列关系/序号证据。description/tags/cover 必须与目标描述范围相符，不把卷册/版本内容提升为通用作品内容。 |
| resource | title、description、resource_index、cover_ref | 明确 resourceId 和归属；至少对应 VOLUME/具体内容，description/cover 还要核对版本范围，不能以 SERIES 代替具体卷册。单资源也需显式目标，不能取第一册猜测。 |
| resource | publisher、published_at、language、isbn、identifier | EDITION 证据；ISBN 校验位及 10/13 等价检查，套装 ISBN 仅套装范围。identifier 须证明业务语义相同，providerItemId 默认只做来源键。日期保留原文/精度；年、年月不得伪造成带时区精确日期。 |
| resource（有声书） | narrator、abridged | 对应录音/版本证据；纸书作者/出版社不推出朗读者/节略状态，音轨不成为逐资产识别目标。 |

SERIES/WORK/VOLUME/EDITION/UNKNOWN 是匹配结论而非新增数据库对象。标题唯一或标题相似不授予自动写入权；未知作者不构成冲突也不构成强证据。有效 ISBN/来源 ID 匹配仍不得掩盖已知作者/卷号冲突。作者、译者、编者按可比角色比较；原值保留，归一化不能删除续作/上下册/修订版身份。候选键为 providerId + providerItemId，同条目多次召回只算一份事实。

聚合父书未指定资源，只允许本身已证实的 book 字段；第 2 卷只写第 2 卷，父书作者等也须另有 book 建议与修订，不能由卷册候选顺手覆盖。series_index 与 resource_index 不互代。AI 新别名/标题/ISBN 是假设，不能反过来充当独立证据。匹配层级不足时只建议该层级允许的字段或待确认，不拼接冲突出版版本。

保留既有 preferLocalMetadata（模型当前默认 true）；新安装只补缺失。新增 allowRepairPathMetadata 默认 false，仅可证明 PATH、未人工修改、未保护且匹配可靠时生效；UNKNOWN 不进入修正。人工选择不绕过保护/权限，自动不构造 override_fields/clear_fields。

## 配置、结果与有界执行契约

| 项目 | 唯一所有者/兼容决策 | 阶段 |
| --- | --- | --- |
| 来源启用/参与 | 继续以 Source.enabled 表达 OFF；Source.config 只保存启用时 MANUAL_ONLY/AUTO_AND_MANUAL，API 投影三态，不再持久化另一份 OFF/enabled。Manifest.mode=search/infer 不复用。旧来源缺参与字段时保持已有权限；Open Library 后端永远只允许明确人工单目标。 | M4 |
| 连接/排序 | Source.config 是端点/模型/密钥所有者，Source.priority 是顺序所有者。现有 `sources.prepare_metadata_source_seed_write` 已 on_conflict_do_nothing，继续只补缺行。registry 现要求完整来源集合，需改为已提交来源按请求排序、遗漏来源按现存相对顺序追加；遗漏来源的 enabled/密钥不动，未知/重复 ID 拒绝。 | M4 |
| 识别策略 | OrganizePolicy 继续拥有定时/新增/preferLocalMetadata/OPF；allowRepairPathMetadata 放现有 rules_json 的命名识别设置内，保留其他规则键。prepare/update 需保留旧 payload 未提交的新字段，不能整个覆盖 JSON。 | M3/M6 |
| AI | 继续复用 ai Source 的 enabled/config。关闭保持关闭；已启用且模式缺失读作 SUGGEST_ONLY，保存时显式规范化并提示行为调整，不动凭据。ASSIST_ON_AMBIGUITY 必须显式开启。认证新增 bearer/none，缺值保留旧 bearer；none 不发送 Authorization。仅一套客户端/解析器/提示词管理。 | M5 |
| 业务 outcome | 写在 MetadataLookupTask.candidate_raw_json 的版本化 recognition 对象中，保留旧 selected/attempted 兼容读取；含 outcome/reason、目标类型与原目标 ID/修订、上下文及策略指纹、候选键、字段建议、有界证据摘要、createdAt/retryAfter、确认/忽略状态。applied_fields 继续表示实际应用，ProviderExecution 记录技术执行；不另设任务生命周期表。 | M2/M3 |
| 历史与过期 | 旧 candidateRawJson 无 schema/修订证据时只读展示，不能直接确认写入，必须重查。不批量删除/回填历史记录。新结果在目标/归属/关联修订、配置语义/规则版本改变或授权失效时过期；重新打开和提交均验证。忽略仅对相同上下文+策略指纹生效；AMBIGUOUS 同指纹不再自动入队；NO_MATCH 至少 24h 冷却。手动明确重试可重查，仍受限速。使用当前按 book/job 的任务查询，避免历史全表扫描。 | M2/M3/M6 |
| 请求预算 | 来源搜索+详情总 HTTP 尝试 ≤8（含重试/重定向），详情不同条目 ≤3，候选池 ≤10；可靠匹配后最多再查 1 源补缺；AI HTTP ≤2、候选 ≤5、输入 ≤12000 字符、输出 ≤800 tokens；最终封面 ≤1。AI 可 45s，但须与现 worker deadline 协调。取消/来源关闭每次下一请求前检查。 | M2/M5 |
| 缓存 | 仅缓存候选，不共享匹配结论；key 包括实例/端点/非秘密配置语义修订/结构化 query/语言/层级/解析版本。AI 另含授权范围、上下文、候选内容摘要、模型和提示词版本。零候选成功缓存 30min；网络/鉴权/解析错误不是零候选。每次缓存命中仍匹配当前目标。 | M2/M5 |
| 限速 | 增强现有执行 gate，搜索/详情/测试/手动/重试共同经过；M2 验证实际部署多 worker 范围，现有进程内锁不能充当跨进程承诺。需要共享预约状态时优先现有存储，短事务预约后释放再等待/HTTP；不得持 SQLite 写锁等待外部网络，不增加 Redis。 | M2/M4 |
| 数据读取 | 只投影明确目标及有界关联/文件样本；单目标 SQL 查询数和扫描形状不随全库增长，不逐图片创建任务，不计算全书哈希，不重扫原件。 | M1/M2/M7 |

迁移判断：配置 JSON、候选结果 JSON、操作记录和缓存现有 key 足以承载上述契约，M0 不批准预建表，M1 不需要 schema 变化。M2 的跨进程限速/指纹查询、M3 的可验证 provenance/受控封面登记如实测现有存储或索引不足，先在本计划记录具体缺口与最小迁移，再仅新增必要迁移；不得预先承诺“绝无迁移”，也不得改已发布迁移。外部来源政策与 API 在 M4 实施时再核对官方文档，本次未联网请求图书来源或模型。

## M1–M7 最小文件面和验收门槛

下表的 backend 路径以 `apps/api-python/app/` 为前缀。新增文件只在现有对应能力层放小型类型/规则；不为表格机械创建所有文件。每阶段独立提交后停止，须有新授权才能继续。

| 阶段 | 最小实际文件范围 | 必须通过的门槛 / 定向验证组 |
| --- | --- | --- |
| M1 | `modules/metadata/domain/` 的识别类型/规则、application 上下文、infrastructure 有界投影；`services/metadata_lookup_queue.py` 选择器、`services/organize_service.py` 排序、`modules/library/infrastructure/source_node_metadata_recognition.py`；必要 schema/client 展示字段 | 同名异作者/异卷不自动采用；ISBN 校验/等价、角色、UNKNOWN、去重和匹配层级明确；自动与手动实际调用同一规则，M3 前不扩大写字段。T1，补匹配用例。 |
| M2 | 上述查询入口；`modules/metadata/infrastructure/external_cache.py`、`automatic_rate_limiter.py`、`lookup_queue.py`；`services/metadata_provider_registry.py`、`services/organize_scheduler.py` 与 organize 队列持久化 | ISBN 查询真实发出、用户 query 保留原上下文；冲突不能首源早停；所有尝试计数，取消/禁用后停止；错误分类、缓存隔离、冷却/去重；网络无事务，单目标有界。T2。 |
| M3 | metadata 字段建议；library `application/metadata_patches.py`、`domain/metadata_patch.py`、`infrastructure/metadata_patches.py` 及现有写适配器必要来源参数；`application/recognized_metadata.py`、其基础设施/封面、bootstrap/public；自动直接写分支、现有 writeback intent 与记录 | book/resource 精确定位，保护/权限/双修订、相同值无变更、重复确认幂等；无伪造日期/identifier；封面受控，DB/OPF 分离，原件不改；替换两条旧直接写分支。T3。 |
| M4 | `modules/metadata/domain/providers.py`、infrastructure 来源适配/seed；registry 与 organize_service 既有两源；provider schema、Web providers panel/client | 豆瓣/Bangumi 保留真实作者/别名/卷册；Google 搜索+详情+配置重启链路；Open Library Work/Edition 分离且后台零调用；旧插件/排序/密钥兼容，测试请求也限速。T4，少量真实请求另记。 |
| M5 | 现有 AI 请求入口、metadata application 辅助编排/domain 严格输出验证、缓存配置；registry/manifest、必要 Web 模式和认证控件 | 单客户端；OFF 零请求、SUGGEST_ONLY 无自动调用；假 candidate/evidence、高分冲突、注入/乱码均不写库；两次预算/取消生效；噪声→查询提示→来源→规则→应用或待确认纵切片。T5。 |
| M6 | 已有 Web provider/settings/modal、books API/model/application、organize 记录 UI、i18n；backend 现有 HTTP/schema、organize 记录投影；必要 wire 生成器输出 | 保存→重启/重载→搜索→差异→确认→真实值刷新；过期/忽略结果、两浏览器并发；三入口共用规则，zh-CN/en-US/焦点/键盘/窄屏；没有独立审核平台或移动页。T6。 |
| M7 | 本能力既有测试及必要小 fixture、本文进度/实测记录；仅修复直接发现的本能力缺陷 | 三纵切片（ISBN 版本、多卷精确资源、AI 噪声）；严重误写/跨卷/越权/保护/过期零失败；预算/缓存/错误/恢复；升级旧配置与必要迁移恢复；真实准确率只以标注真实样本为分母，不把合成通过率包装为整体准确率。T7。 |

## 已有验证入口（本次不执行应用测试）

遵循测试策略：M0 文档变更只验路径/引用、语义与差异，不运行 pytest/Web/构建。下列命令供后续按受影响边界选择，不是每阶段全部运行清单；新增规则测试沿已有 pytest/tsx 入口补充。后端命令在 `apps/api-python` 执行，Windows 沿既有 `.venv-windows` 设置 `UV_PROJECT_ENVIRONMENT`，不新建测试基础设施。

```powershell
# T1：已有选择、本地证据与手动候选
uv run --extra dev --locked pytest -q tests/test_metadata_lookup_queue.py tests/unit/modules/metadata/test_local_metadata.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py
# T2：查询事务、节流、调度和取消
uv run --extra dev --locked pytest -q tests/integration/modules/metadata/test_search_transactions.py tests/unit/modules/metadata/test_automatic_rate_limiter.py tests/test_organize_scheduler.py tests/test_metadata_lookup_queue.py
# T3：共同写入、授权、手动与副作用
uv run --extra dev --locked pytest -q tests/integration/modules/automation/test_metadata_patches.py tests/integration/modules/automation/test_metadata_side_effects.py tests/unit/modules/library/application/test_recognized_metadata.py tests/unit/modules/library/infrastructure/test_recognized_metadata_cover.py tests/contract/api/test_recognized_metadata_api.py tests/test_metadata_writeback_queue.py
# T4：来源注册、真实原因诊断和搜索适配
uv run --extra dev --locked pytest -q tests/integration/modules/metadata/test_provider_registry.py tests/integration/modules/metadata/test_provider_failure_diagnostics.py tests/integration/modules/library/test_provider_source_node_metadata_recognition.py
# T5：复用 T2/T4，并在同一测试目录加入 AI schema/预算/模式用例（目前不存在，不能标已通过）。
# T6：Web 工作目录 apps/web；沿既有 run-tests.mjs 的 tsx 参数定向运行
pnpm exec tsx --conditions=import --test features/books/model/recognized-metadata.test.ts features/books/application/metadata-apply-completion.test.ts features/books/api/client.test.ts
pnpm i18n:check
pnpm typecheck
# T7：复用有效的 T1–T6 结果，新增三纵切片/升级/有界 SQL 证据；实际 HTTP/双浏览器验收不能被单测代替。
```

Web `pnpm test` 的现有 runner 不接受文件过滤且 pretest 含 Reader 前置，故定向命令直接使用现有 tsx 工具；新增 UI 交互需要补相应 HTTP/浏览器证据。当前没有足以证明本方案完整链路的专用 E2E，不能把现有 resource-details 或模拟测试算为新功能验收。schema 若变化再走现有生成机制，不手改 generated 文件。M7 只在具体风险要求时扩大测试，不默认构建移动安装包；发布类型届时依据实际 schema/依赖/产物判定，M0 无发布资格结论。

## 样本与 40 个小型用例设计

可复用：`tests/test_metadata_lookup_queue.py` 的《黑暗坡食人树》/岛田庄司与其他作者候选；`tests/integration/modules/library/test_provider_source_node_metadata_recognition.py` 的来源映射夹具；`tests/unit/modules/metadata/test_local_metadata.py` 和 `tests/unit/modules/imports/test_path_metadata.py` 的 PATH/内嵌/旁车合成输入；`tests/unit/modules/library/application/test_recognized_metadata.py` 的字段/封面结果；`tests/support/import_fixtures.py` 的导入构造器。上述均是仓库测试样本，不是已抽样确认的真实生产图书或真实来源回包。

本次没有取得经用户授权的生产问题样本、服务端配置、来源凭据或本地模型联通证据。下列 40 项是待实现的合成/变体设计，真实脱敏样本到位后优先替换相应输入并记录出处/人工判定，不上传正文；M0 没有新增或运行这些测试。

| ID | 小型输入/场景 | 预期 |
| --- | --- | --- |
| C01 | 唯一同名，已知作者不同 | 冲突，不自动应用 |
| C02 | 同名，作者均未知 | 待确认 |
| C03 | 标题+同角色作者一致，无版本线索 | WORK，仅作品允许字段 |
| C04 | 本地有证据别名+作者一致 | 可 WORK；保留别名来源 |
| C05 | 标题 Unicode/全半角/空白变体 | 等价比较，原值不丢 |
| C06 | 正篇与续作/修订版同核心标题 | 不因归一化吞掉身份差异 |
| C07 | 作者与译者名字互换 | 不当作者一致或无理由冲突 |
| C08 | 有效 ISBN 9780306406157，身份无冲突 | 对应 EDITION |
| C09 | ISBN 0306406152 与 C08 | 等价 |
| C10 | ISBN 校验位错/任意 13 位数 | 不作强证据 |
| C11 | 有效 979 ISBN | 不强行转换 ISBN-10 |
| C12 | 套装 ISBN 与某子卷 | 不传染父书/其他卷版本字段 |
| C13 | ISBN 一致但可信作者不同 | 阻止自动应用 |
| C14 | ISBN 一致但明确卷 1/卷 2 冲突 | 阻止自动应用 |
| C15 | 第2卷/Vol.2，作者一致 | 对应 VOLUME，资源索引单独解释 |
| C16 | 上册/下册同名 | 不跨卷选择 |
| C17 | 系列候选查具体卷册 | 不自动写卷册简介/封面 |
| C18 | 聚合父书，无 resourceId | 仅父级允许字段，不选首册 |
| C19 | 单资源明确 resourceId | 版本字段只写该资源 |
| C20 | 作者相同、语言/出版社/修订版不同 | 可同 WORK，不混 EDITION |
| C21 | 来源 A/B 分别有同版本简介/语言 | 验证后最多 1 额外源补缺 |
| C22 | 来源 A/B 版本强冲突 | 不投票拼接虚构版本 |
| C23 | 日期 2020 / 2020-03 | 保留精度，不伪造 datetime |
| C24 | series_index=2、resource_index=3 | 不互相映射 |
| C25 | 纸书候选用于有声资源 | 不推断 narrator/abridged |
| C26 | 明确同一录音及节略证据 | 可对应音频版本字段 |
| C27 | protected title；自动 payload 带 override | 拒绝覆盖 |
| C28 | UNKNOWN 来源值恰等于文件名 | 不判 PATH，不修复 |
| C29 | 已证 PATH，修复开关关/开 | 关不修；开仍需可靠匹配且无保护/人工改动 |
| C30 | 查询期间编辑/移库/删除原资源 | 旧 revision/归属拒绝，资源 ID 清空不降级 |
| C31 | 同字段值、重复确认、重复任务 | no_changes/幂等，无重复副作用 |
| C32 | 同名异作者/卷号/模型/端点的缓存 | 键隔离；命中后仍重新匹配 |
| C33 | 来源 OFF、AI OFF/仅建议，后台尝试 | 零越模式请求 |
| C34 | 旧完整来源列表遗漏新来源、旧 config payload | 合并保留顺序/密钥/新增字段；重复/未知拒绝 |
| C35 | 429/401/受限 HTML/网络/解析/成功空 | 分类明确，只有成功空结果进入短负缓存 |
| C36 | 最坏搜索+详情+重试+重定向，期间取消 | 来源尝试≤8、详情≤3；停止后续请求/应用 |
| C37 | AI 噪声查询建议→来源候选 | 保留原目标证据，不能用 AI 假设自证 |
| C38 | AI 假候选/假 evidence/高分冲突/注入；恶意封面 URL | 严格拒绝/安全抓取边界；无模型工具，AI尝试≤2 |
| C39 | DB 已成功，OPF 开/关/入队失败/重启 | 分开记录 DB/OPF；不重复 DB 应用、不改原件 |
| C40 | 同目标放入小库/100k 索引数据；普通用户跨库提交 | 查询有界，授权反枚举；不向外发送批量请求 |

40 项是基础案例，不能代替文末 R01–R28 全验收矩阵：Open Library Work 聚合 ISBN、人工限定调用、重复候选去重、历史结果过期/忽略、服务重启迟到响应、配置保存重启、双语/窄屏/焦点和真实 UI 刷新，在所属阶段继续按矩阵验证。

## M0 验证与交付边界

实际执行：Git status/branch/log/rev-parse/diff/ls-remote；定向 rg/Get-Content 核对以上文件与符号；文档差异、链接/文件引用和检查项核对。未运行应用测试、访问生产 DB、进行来源/模型联调，未以历史测试通过记录替代本次证据。

M0 的有效交付是本文中的当前证据、职责/契约决策、后续文件边界和验收门槛。未删除或委托任何旧业务入口（这属于 M1–M5）；无数据库迁移、依赖、构建产物和发布影响。提交 SHA 由本次独立提交与聊天交付给出，避免在文件内自引用尚未产生的 commit。提交后停止。

---

## 用户提供的原始实施方案（需求基准，后续阶段未执行）

# 二毛图书：增强元数据识别 Codex 实施方案

版本：方案 v1；核验日期：2026-09-26。
核验基线：GMD170629/ermao-library，develop，33a71986f5a2307f563e5d5b3b6440219eeee5f7。
性质：待执行的实施要求，不是已完成报告，也不代表读取了生产服务器实际配置。

## 1. 交付目标与范围

在现有元数据能力上形成一条完整流程：

本地证据与明确目标 → 有界查询计划 → 来源搜索/详情 → 证据匹配 → 必要时 AI 辅助 → 按目标与字段生成建议 → 自动应用或人工确认 → 现有元数据保存与旁车 OPF。

最终必须满足：

- 豆瓣、Bangumi 的查询与候选信息得到增强；Google Books 可配置后参与手动/自动识别；Open Library 作为默认关闭、人工单目标按需查询的可选来源。
- ISBN、作者、卷号、别名不再被一个书名字符串吞掉；同名不能自动等同于同一本书。
- AI 能辅助拆解噪声线索、建议查询、在有限候选中消歧；不能凭模型自报置信度直接写库。
- 作品、具体卷册、具体出版版本的识别层级分开；字段只能写到现有 schema 允许的目标。
- 自动与手动识别共用匹配和字段规则，保留人工保护、权限、并发检查与现有文件保存语义。
- 后台配置、手动识别、定时/新增识别、日志和审核入口全部真实接通。
- 单目标查询和写入有界，不随着全库图书数增长而扫描全库；外部失败不拖垮导入。

本轮不做：通用插件市场、通用 Agent/工作流引擎、向量数据库、知识图谱、模型训练、目录重组、文件移动/重命名、正文全文上传、OCR、全库重扫/追溯补识别、阅读器/TTS/标注改造、移动端新增管理页面、正式发版。

AniList、额外中文爬虫/付费书目服务不属于本轮交付，不创建无实现占位 Provider。后续根据真实未命中样本和来源授权再接入。

## 2. 基线入口与强制复用

以下为核验基线中的实际入口；执行时先检查分支漂移和调用关系，不按文件名猜测已完成能力。

| 职责 | 已核验入口 |
| --- | --- |
| 全仓规范 | AGENTS.md |
| Provider 描述与配置字段 | apps/api-python/app/modules/metadata/domain/providers.py |
| Provider 注册、连接测试、配置、排序 | apps/api-python/app/services/metadata_provider_registry.py |
| 查询与识别服务 | apps/api-python/app/services/organize_service.py |
| 自动候选选择与应用 | apps/api-python/app/services/metadata_lookup_queue.py |
| 查询队列持久化 | apps/api-python/app/modules/metadata/infrastructure/lookup_queue.py |
| 外部结果缓存、自动限速 | apps/api-python/app/modules/metadata/infrastructure/external_cache.py、automatic_rate_limiter.py |
| 本地元数据解析 | apps/api-python/app/modules/metadata/application/local_metadata.py |
| 跨模块公开能力 | apps/api-python/app/modules/metadata/public.py |
| 元数据 HTTP 入口 | apps/api-python/app/modules/metadata/presentation/http.py |
| 已有版本化元数据应用 | apps/api-python/app/modules/library/application/metadata_patches.py |
| 已有目标字段和保护规则 | apps/api-python/app/modules/library/domain/metadata_patch.py |
| 来源配置 | apps/web/features/organize/metadata-providers-panel.tsx |
| 识别策略 | apps/web/features/organize/recognition-settings-panel.tsx |
| 手动识别 | apps/web/features/books/metadata-lookup-modal.tsx |
| 设置中心 | apps/web/features/settings/center/organize-settings-page.tsx |
| 既有自动识别测试入口 | apps/api-python/tests/test_metadata_lookup_queue.py |

重要：ApplyMetadataPatches 已有 expected_revision、字段校验、权限、来源记录和事务处理。优先核对它的适配器、事务边界与旁车副作用，再通过命名公开 API 复用。不能简单复制一份；也不能为复用它而伪造 MCP grant、让后台任务依赖用户配置 MCP。

读取范围内工程规范及 docs/testing/test-execution-policy.md。新增能力遵守当前模块分层；不因接触遗留大文件而全文件搬家。

## 3. 全阶段共同约束

### 3.1 目标和证据

RecognitionContext 是小型、明确类型的数据结构，不是新实体表。至少表达：目标类型/ID、bookId、可选 resourceId、书库授权范围、目标与关联修订、现有字段及保护、字段来源、ISBN/来源 ID、标题/作者/别名、卷册及版本线索、允许补充字段、执行方式和配置版本。

仅从当前目标及有界关联投影取得证据。父级标题只能作为上下文；某一子卷的 ISBN 不能作为整套书或其他卷册的 ISBN。没有明确资源目标时不得随便选第一册。资产文件名只取有限、相关样本，不按漫画图片逐张建立识别任务。

字段来源能在现有记录中证实才使用。历史来源未知时按 UNKNOWN 保守处理，不能只因字段值与文件名相同就认定它是可覆盖的路径推断结果。不做全库来源回填。

### 3.2 归一化和匹配

保留原始值；归一化值只用于检索和比较。处理 Unicode、空白、大小写、常见标点与角色明确的作者列表；不能把卷号、续作、修订版、上下册等身份信息一律删除。

ISBN 去除展示分隔符后校验校验位；有效 ISBN-10 可与等价 ISBN-13 比较。不能把任意 10/13 位数字当 ISBN，也不能强行把所有 ISBN-13 转为 ISBN-10。套装 ISBN 与分册 ISBN 必须保留各自作用范围。

匹配层级建议为 SERIES / WORK / VOLUME / EDITION / UNKNOWN；它们是判定结果，不是新建五类数据库对象。不同出版版本可属于同一作品，不能因此混用 ISBN、出版社、语言或封面。

第一版采用可解释规则，而不是未经校准的概率或通用加权引擎：

1. 来源 ID/有效 ISBN 等强证据吻合，且可信关键证据无冲突，才可进入高可靠匹配；标识符吻合不掩盖明显作者/卷号冲突。
2. 标题或有证据的别名、作者和必要卷号吻合，可确认到相应作品/卷册层级；版本不明时禁止版本字段自动应用。
3. 只有一个同名候选、只有标题相似、只有 AI 自报高置信度，均不足以自动应用。
4. 未知作者不是冲突；已知且角色可比的作者明显冲突必须阻止自动采用。译者、编者和作者不能简单互相比较。
5. 模糊比较服务于候选召回和排序，不直接授予自动写入权限。
6. AI 生成的标题、别名和查询不能反过来充当独立证据，避免模型自己制造线索再自证。

MatchDecision 至少包含 outcome、候选键、匹配层级、证据引用、冲突/排除原因和允许的字段集合。候选键必须包含 providerId + providerItemId；同一个条目通过多个查询返回不能算多份独立证据。

### 3.3 字段、覆盖和写回

以现有 METADATA_FIELDS 为权威。识别第一版只应用 book/resource，不新增任意字段，也不把 source_node 和 linked book 同时提交成重叠目标。

- book：title、author、description、series_name、series_index、tags、cover_ref。
- resource：title、description、publisher、published_at、language、isbn、identifier、narrator、abridged、resource_index、cover_ref。
- 外部 Provider 的字段名在一个边界做显式转换。series_index 与 resource_index 不互相替代。来源条目 ID 不直接覆盖含义不明的 identifier。外部 coverUrl 先经现有安全下载/登记能力转为内部受控 cover_ref，不能把远程 URL 塞进 cover_ref 绕过引用校验。
- authors/aliases/日期精度等候选信息可以保留为判定证据；未有对应业务字段时不擅自新增表列或丢失原候选。
- 作者/作品信息、具体卷册信息、出版版本信息使用不同层级门槛。简介、标签、封面也必须确认其描述范围，不默认都是作品通用信息。
- 有声书朗读者和 abridged 等字段需要对应录音/版本证据，不能从普通纸书条目推断。
- 出版日期只有年份或年月时，保留原始文本与精度供展示/判定；不伪造 1 月 1 日后写入要求带时区日期的现有字段。仅在现有契约有明确无损表达时映射，否则不自动应用。

保持 preferLocalMetadata 的既有用户选择。为新安装采用只补缺失的安全默认值。新增 allowRepairPathMetadata 默认 false；只有明确来自 PATH、未人工修改、未保护且可靠匹配时可修正。未知来源不进入修正范围。

不再新增与 preferLocalMetadata 相互矛盾的全局覆盖模式。单次人工选择可以限定本次字段，但受保护字段仍遵循现有显式覆盖权限/确认流程；自动任务不能产生 override_fields，不能主动清空字段。

所有自动和人工应用都重新校验目标归属、授权和 expected_revision。用户在识别期间编辑、资源迁移或删除时，过期建议不得落库。无变更应返回 matched/no_changes，不伪报更新成功。

数据库元数据保存和文件保存是两个结果。继续复用既有旁车 OPF 开关和异步队列；本轮自动识别不改写 EPUB/PDF/CBZ 原件，不扩展原文件写回权限。OPF 队列失败不能被当成 DB 失败，也不能隐藏。

### 3.4 外部调用预算、缓存与调度

以下为第一版工程默认值，不是第三方服务承诺。优先作为受测试约束的内部常量或现有高级配置，不把每个值都做成后台输入框：

| 预算 | 默认值 |
| --- | --- |
| 每目标来源搜索+详情 HTTP 尝试数 | 最多 8，重试/重定向计入 |
| 每目标详情补充 | 最多 3 个不同条目 |
| 用于后续决策的候选池 | 最多 10 个 |
| 身份确认后的额外补全来源 | 最多 1 个，仍受总预算限制 |
| 每目标 AI HTTP 尝试数 | 最多 2，格式重试也计入 |
| AI 消歧候选 | 最多 5 个 |
| AI 输入 | 默认不超过 12,000 字符，仅结构化元数据和有限文件名 |
| AI 输出 | 最多 800 tokens 或当前兼容接口等效上限 |
| 每目标封面下载 | 最多 1 个最终采用封面，沿用既有大小/格式限制 |
| 确认无结果的候选缓存 | 30 分钟；网络/鉴权错误不能写成空结果 |
| 同输入、同策略的自动无匹配重试 | 默认至少间隔 24 小时 |

请求超时/限速沿用并收敛到现有实现。AI 单请求可采用 45 秒超时以容纳本地模型，超时后回退规则结果，不启动无界重试。具体超时与现有 worker deadline 协调，不能擅自改全局队列策略。

来源公共缓存的键包含来源实例、端点、配置修订/非秘密语义指纹、查询结构、语言/查询目标层级和解析版本。不要把明文 token/apiKey 放进键或日志。缓存候选，不缓存可以跨图书复用的身份结论；缓存命中后针对当前目标重新匹配。

AI 缓存额外包含目标上下文、候选实际内容摘要、模型、提示词/规则版本、输入范围与所用连接配置修订。只对小型输入求指纹，不对完整书文件做内容哈希。私有上下文不得跨用户/授权范围共享。

复用现有限速门和队列；手动搜索、后台任务、补详情、重试和测试请求都不能绕过来源限制。多 worker 配置下核验共享限速的实际范围，不能每个任务各自生成一份限速器。无必要不引入 Redis 或新的分布式组件。

来源错误分类至少能区分：确实无结果、鉴权失败、访问受限、限流、超时/网络失败、解析失败、配置不完整、目标不适用。真实失败通过现有诊断入口记录并脱敏。取消/关闭后的晚到响应不得应用，也不得继续发起后续请求。

只复用已有任务生命周期，在结果里追加 recognition outcome 和原因。待确认和无匹配不是网络故障，不进入技术错误无限重试。对同目标、同上下文、同策略的待确认结果去重，不能每个调度周期重新调用 AI。来源/规则改变只影响后续正常调度，不在启动时把历史全库瞬间重新入队。

### 3.5 来源和 AI 配置兼容

ProviderManifest 仍是唯一来源描述。新增功能默认字段可选，兼容已存在的 Python entry point 插件；旧插件可继续提供候选，但无法证明的能力/字段不能当作支持。Provider 原 mode=search/infer 不复用为参与方式。

数据来源的参与方式为 OFF / MANUAL_ONLY / AUTO_AND_MANUAL。OFF 使用已有 enabled 语义；参与方式有唯一的持久化所有者，不能维护互相矛盾的两个 enabled。Open Library 在服务端强制人工单目标按需，不提供自动/批量模式。

新增来源只补缺失配置行，不修改现有密钥、优先级、启用状态和定时策略。新增字段有明确默认值；旧客户端未提交新字段时不能清零。旧来源排序请求遗漏新增来源时，保留未提交来源并在既定位置合并，不能把它们删除或禁用；未知/重复 ID 仍按契约校验。

AI 使用原有一套连接配置。主开关关闭就绝不调用；启用后分 SUGGEST_ONLY 与 ASSIST_ON_AMBIGUITY。旧 AI 已关闭的保持关闭；旧 AI 已启用但没有新模式字段的迁移为 SUGGEST_ONLY，并展示行为调整提示，保留连接/密钥。不默默增加自动调用权限。

旧“AI 作为普通远程事实来源”的入口改为显式人工建议兼容入口，内部委托同一 AI 辅助实现；自动候选流程不再将 AI 生成字段伪装为来源事实。不得同时保留两套 AI 提示词/调用管线。

支持显式选择 bearer / none 认证；none 不发送伪造 Authorization，bearer 必须验证密钥。管理员明确配置的本地模型端点允许内网地址；这不等于允许远程候选或封面任意访问内网。

### 3.6 安全、兼容和发布

模型只接收受限数据，返回严格校验的结构化建议；文件名、简介、候选、模型输出都视为不可信文本。模型没有 SQL、shell、任意 HTTP、文件操作或业务写入工具。提示注入不得改变系统规则或授予权限。

来源详情 URL 应由可信来源 ID 和配置构造。封面 URL 复用安全抓取入口，校验协议、地址、重定向目标、内容类型与大小；禁止由外部条目绕入私网/云元数据地址。凭据不能随跨域重定向转发。管理员指定的模型服务与第三方返回的 URL 使用不同信任边界。

后端是权限、预算、模式与字段校验的权威，不能只在前端隐藏按钮。新增用户可见文本必须支持 zh-CN/en-US，日志/错误码不依赖本地化文案。

优先使用已有设置 JSON、任务结果和操作记录；确有需要才做小型新增迁移，不创建通用证据表、审核流平台或第二套库结构。迁移不能改写已发布迁移，不能要求全库重扫/解析/回填。新增 SQLAlchemy 类型化实现；不借机切换数据库。

不自动发版。最终根据实际 schema/依赖/运行时/前端产物变化使用现有发布规则判断 code-only 资格；“迁移在启动时执行”不自动代表 code-only 可用或不可用。先验证新包与旧 DB、备份恢复与回退前提。

## 4. 执行方式

采用 M0 → M1 → M2 → M3 → M4 → M5 → M6 → M7。
每阶段独立提交并停止供审查；需要连续执行时必须有用户明确授权。第一次只交付 M0，不凭完整方案自动执行全部阶段。
每阶段复用同一份计划文档更新进度，不为每个小补丁新建审计/报告体系。已经验证且没有具体新风险的部分不重复扩大测试。

每阶段交付报告只需：基线/提交 SHA；实际功能与调用链；变更文件；删除/委托的旧入口；测试命令及结果；未验证项；迁移/依赖/发布影响。不能以测试数量、文档数量代替功能交付。

## 5. 给 Codex 的总控提示词

```text
你正在为 GMD170629/ermao-library 实施“增强元数据识别”。
阅读本方案与 AGENTS.md，按用户指定阶段执行。本次未指定阶段时只执行 M0。

方案核验基线是 develop@33a71986f5a2307f563e5d5b3b6440219eeee5f7。
先读取当前分支、HEAD、工作树状态及 origin/develop 差异，保护全部既有未提交变更。
若分支已前进，仅核对本能力相关差异；以当前有效契约为准，不能退回旧基线。
未指定开发分支且工作树适合切换时，可使用 feat/metadata-recognition-enhancement；不得强制 checkout/reset/rebase。

目标是增强既有系统，不是另建识别平台：
增加可靠来源；让 AI 辅助查询与消歧；通过证据判断身份，再按目标和字段受控应用。

必须执行：
1. 先定位现有职责、公开 API、调用方与测试，再原位增强。
2. 复用 Provider 注册、识别队列、限速缓存、book/resource 元数据 patch、权限、revision、OPF 和诊断机制。
3. 遵循本方案全部共同约束；尤其禁止全库重扫、逐图片识别任务、全书哈希、外部调用占用数据库事务及自动覆盖保护字段。
4. 每个阶段新增行为必须真实接到规定入口；不得只写未调用的 helper、静态 UI、模拟 success。
5. 替换规则时迁移本范围内所有调用方，删除旧规则，或保留仅委托唯一实现的兼容壳。
6. 新增配置默认安全，旧配置/密钥/顺序/客户端 payload 不被覆盖；自动任务不获得新权限。
7. 后端、Web、DTO、必要生成代码与 zh-CN/en-US 同步；不手改生成文件。
8. 测试遵守 docs/testing/test-execution-policy.md；先定向，遇到具体关联风险再扩大。
9. 模拟测试不等于真实来源/本地模型联通；没有凭据或设备时明确报告验证缺口，继续完成不受阻的范围，不伪造通过。
10. 不混入目录重构、扫描性能改版、Reader、TTS、MCP 新功能或数据库切换。

每阶段完成后形成独立可审查 commit，给出简短交付报告并停止。
不要自动 push、触发发布 workflow、合并或打 tag，除非用户明确授权。
不要反复确认已明确的要求；按已定边界实施，具体阻塞准确记录。
```

## M0：核对基线并冻结实施契约

目的：为实际代码确定最小变更面，不重新盘点整个项目，不提前写业务代码。

```text
执行 M0：增强识别基线与契约冻结。

核对总控提示词所列基线与工作树。只审查增强识别直接相关路径：
后台来源/策略 → 手动或自动任务 → 本地上下文 → Provider → 候选判断 → book/resource 应用 → OPF/记录。

必须完成：
1. 标出查询被压缩为书名、单一同名直接选择、缓存隔离、AI 普通来源、首源早停和自动资源字段应用的当前实现；逐项确认仍存在，不复述旧审计作证据。
2. 核对现有 metadata_patches.py 及其适配器是否适合识别场景，明确权限、事务、封面、provenance、OPF 和并发修订的唯一归属。
3. 冻结 book/resource 字段矩阵与 SERIES/WORK/VOLUME/EDITION 层级规则，特别记录聚合父书、分卷、单资源和有声书边界。
4. 明确配置单一所有者、旧 AI 配置映射、新来源排序兼容、任务 outcome 的存储位置、历史待确认结果的保留/过期方式。
5. 明确 M1–M7 的文件范围和已有测试命令。是否需要迁移必须由实际缺口决定，不能为未来能力预先建表。
6. 定位可用的现有样本；设计约 40 个小型判定用例，优先真实脱敏问题，不能把合成样本描述成真实生产数据。
7. 在 docs/plans/metadata-recognition-enhancement.md 保存一份计划和检查清单；存在等价文档则更新它，不创建第二份。

禁止修改生产逻辑、配置默认值、schema、接口、依赖、lockfile 或测试基础设施。

验收：
- 每项已确认问题有当前文件/函数证据。
- 每条新规则有唯一职责位置、调用入口和后续验收阶段。
- 对未知字段来源和缺失真实验证条件做明确记录。
- 报告仅涉及本能力，不展开全仓重构建议。

提交建议：docs(metadata): freeze recognition enhancement plan
完成后停止。
```

## M1：结构化证据与可靠候选匹配

目的：修复“拿到了线索却没用对、候选唯一就认为身份唯一”。

```text
执行 M1：识别上下文和匹配规则。

在现有 metadata 模块添加或增强最少量、显式类型的 RecognitionContext、候选证据与 MatchDecision。
它们是内部契约，不是新表，不建立通用评分引擎。

必须完成：
1. 从明确的 book/resource 目标取得有界上下文，保留父级线索与当前资源线索的区别、字段来源/保护和修订。
2. 实现保留原值的归一化、ISBN 校验/等价比较、作者角色与 UNKNOWN 处理、卷号/版本线索解析。
3. 将 _choose_exact_candidate 的“单个同名直接通过”替换为共同匹配规则。
4. 标题/别名模糊比较只做排序；作者/卷号/可信版本冲突有明确原因码。
5. 输出匹配层级、证据引用、冲突、可采用字段；对同来源同 ID 去重。
6. 自动识别调用新的 MatchDecision；手动识别展示/排序复用同一结果。先限制在已安全支持的应用字段内，不借此扩大写入范围。
7. 旧函数若需兼容只能委托新规则，不能保留一份独立精确匹配逻辑。
8. 元数据查询与导入不得依赖这次匹配去变更文件拓扑。

验收：
- 唯一同名但作者不同：不能自动采用。
- 缺作者且仅同名：待确认；UNKNOWN 不等于作者冲突。
- 标题/有证据的别名＋作者匹配：可确认到作品；不凭此写 ISBN。
- 第 1 卷与第 2 卷、正传与续作：不混淆。
- 等价 ISBN-10/13 正确匹配；无效 ISBN 不作强证据；套装与分册不混用。
- 父级和兄弟资源不因本资源识别发生变更。
- 关闭 AI 后这些能力完整工作。

提交建议：feat(metadata): add evidence-based candidate matching
完成后停止。
```

## M2：查询计划、缓存、限速与队列闭环

目的：真正用上 ISBN/作者/卷号，同时限制网络、数据库与重试成本。

```text
执行 M2：有界查询计划与执行。

复用现有 Provider、lookup 队列、外部缓存和限速，按能力生成结构化查询计划：
可信来源 ID/有效 ISBN → 标题＋作者＋必要卷号 → 有证据的别名/标题变体。

必须完成：
1. 自动流程不再无条件向所有 Provider 传 book.title；显式人工 query 是用户覆盖查询，仍保留原始上下文用于匹配。
2. 保留用户全局来源顺序；按来源能力跳过不适用方式，记录原因。PDF/EPUB/CBZ 扩展名不能直接推断内容类别。
3. 所有来源尝试、详情、限速、超时、重试、取消统一经过现有执行入口；按照共同预算实际计数。
4. 匹配达到当前目标和字段需求时早停；未解决冲突时不能因第一个来源返回结果就宣布成功。
5. 修正缓存键和命名空间；成功零结果可短缓存，错误不能变成零结果；命中缓存仍针对当前对象重新匹配。
6. 重复任务/请求复用现有去重能力；若需补充同进程在途请求合并，只做本调用链最小实现。
7. 区分识别业务 outcome 与技术失败，在现有任务结果中记录，不创建第二个调度器。
8. 同输入 NO_MATCH 受重试冷却约束；AMBIGUOUS 不被每轮重复入队；手动明确重试可重查，但不能绕过限速。
9. 数据库读取在外部调用前结束；写入使用短事务。仅从目标及其有界关系取数。
10. 取消、目标删除、来源关闭后停止新请求，拒绝晚到应用；不在启动或配置变化时全库回填任务。

验收：
- 有 ISBN 的资源实际产生 ISBN 查询，而不是只查询书名。
- 手动输入的查询确实发送；候选仍与原目标检查冲突。
- 同名不同作者/卷号以及不同模型配置的缓存不串用。
- 高质量首次命中提前结束；最坏分支不超过预算，重试计入。
- 429、鉴权、受限网页、超时、解析失败和零候选能区分。
- 慢来源不会持有 SQLite 写事务；取消不再有后续应用。
- 使用代表性数据验证单目标 SQL 形状/查询次数与全库规模无关；禁止因此再造压力测试平台。

提交建议：feat(metadata): bound recognition queries and cache scope
完成后停止。
```

## M3：统一 book/resource 字段应用与多源补全

目的：先保证写入安全，再开放更多来源和 AI。

```text
执行 M3：字段建议、目标应用与确认结果。

优先复用现有 METADATA_FIELDS、prepare_metadata_patch、ApplyMetadataPatches 及实际适配器。
通过现有公开能力接入；必要调整只服务于识别场景。后台身份由真实系统任务授权提供，不伪造 MCP grant，不默认允许 override。

必须完成：
1. 建立唯一 Provider 字段→目标字段映射与 FieldProposal，记录值、来源 ID、匹配层级、证据、当前值和保护状态。
2. 自动/手动识别共用字段白名单、修订校验、来源记录、事务和 OPF 变更通知；移除对应旧直接 patch 分支。
3. 自动资源字段仅写明确 resource；聚合 book 没有明确子资源时只更新允许的 book 字段。
4. 按共同约束落实 preferLocalMetadata、allowRepairPathMetadata、人工保护、日期精度、卷号和有声书版本限制。
5. 身份可靠确认后最多访问一个额外来源补缺，仍受 M2 总预算；采用前证明它指向同一目标及所需层级。
6. 不把两个冲突来源的字段拼接成虚构版本；不因为多数来源一致就掩盖强冲突。
7. 候选确认与应用使用已有任务/操作记录。持久化有界摘要、目标修订、候选 ID、字段建议及原因，不存完整网页/模型全文。
8. AMBIGUOUS 可从已有记录打开手动识别弹窗；过期/已修改结果要求重新识别。自动重试不重复制造审核记录。
9. 最小必要迁移要说明用途，兼容旧设置/旧结果；禁止建通用审核平台、事件溯源系统或历史全库回填。
10. 封面先安全准备，再执行受修订保护的应用；失败清理临时文件。封面获取失败允许其他已验证字段受控保存，并准确报告部分结果。
11. 无有效变更返回 no_changes；数据库成功但 OPF 排队/保存异常必须分开呈现。

验收：
- 作品级匹配不能写 ISBN/出版社等版本字段。
- 明确匹配第 2 卷只修改第 2 卷；不能覆盖父书或第 1 卷封面。
- protectedFields、人工改动、未知 provenance、取消、目标删除全部受保护。
- 重复应用不会重复副作用；旧 revision 被拒绝。
- 自动和人工选择相同目标/字段时，得到相同字段校验结果。
- 半精度日期不伪造精确日期；series_index/resource_index 不混写。
- OPF 开关行为不变，原件内容与目录结构不变。

提交建议：feat(metadata): unify scoped metadata application
完成后停止。
```

## M4：增强现有来源，接入 Google Books / Open Library

目的：完整交付实际可用来源，不只写一个能返回 JSON 的函数。

```text
执行 M4：来源增强。

Provider 注册/Manifest/配置/测试/查询/详情/候选映射/缓存限速必须完整接通。
新增 Provider 默认关闭，不改变现有来源的启用、顺序、密钥和调度。

A. 豆瓣和 Bangumi：
- 修正 ISBN、作者和别名查询使用方式。
- 仅对必要的有限候选补详情；作者/别名/卷册层级按源真实字段保留。
- 不把所有条目名称直接当系列名，也不把漫画作品条目当成出版版本。
- 访问受限、验证码/异常 HTML、空结果和解析错误分别处理；不实现绕过访问限制。

B. Google Books：
- 接入官方 volumes 搜索和单 volume 详情，支持 ISBN、标题/作者与来源 ID。
- API Key 使用现有密钥保存/脱敏机制；未配置时给出明确状态，不内置共享密钥。
- 映射标题、authors、简介、标识符、出版社、日期/精度、语言、封面、分类等现有可用信息。
- 不引入评分、销售、购买/下载功能；分类不自动等价于人工标签。
- 自动模式遵循 M1–M3，同名或搜索排序第一并不代表版本相同。

C. Open Library：
- 默认关闭，只支持用户明确发起的单目标人工查询，不参加定时、新增、批量、自动补缺或 AI 自动扩展查询。
- 使用官方 API，不抓 HTML；缓存结果、明确 User-Agent，按当前官方政策限速。
- Work 与 Edition 分开；Work 搜索中的聚合 ISBN/出版社/语言不能直接当某个 Edition 的事实。
- 只有得到目标 Edition 的事实且通过匹配后，才能建议其版本字段。
- 不下载/索引完整书目 dump，不建立全库补全后端。

D. 配置和兼容：
- 新来源出现在真实后台列表、配置、连接/查询测试和手动识别来源列表中。
- 提供来源级 OFF/MANUAL_ONLY/AUTO_AND_MANUAL 能力，后端强制执行。
- 现有 entry point 插件保持可运行；新增契约字段可选、默认保守。
- 来源 bootstrap 幂等，旧排序 payload 不删除新增来源、不改变已有密钥。
- 来源详情/封面链接与凭据遵守共同安全边界。

验收：
- 已有两源回归通过；Google Books 从 UI 保存到重启后的实际请求、候选、应用完整跑通。
- 未配置 Key、404 条目、429、空 items、部分日期、多作者、缺封面有确定行为。
- Open Library 只在用户明确单目标人工查询时产生请求；后台任务不能调用。
- 来源禁用后无实际请求，测试请求也尊重配置与限速。
- Fixture 测试通过；有真实凭据时做少量端到端查询，无凭据时准确报告联调缺口。

提交建议：feat(metadata): extend bibliographic providers
完成后停止。
```

## M5：受控 AI 查询辅助与候选消歧

目的：AI 负责理解线索，不负责自创事实或自行写库。

```text
执行 M5：AI 辅助识别。

复用原 AI 连接、密钥、请求与诊断机制。把旧 AI 普通事实来源改成辅助角色，并按共同约束迁移旧配置。
主开关关闭绝不调用；SUGGEST_ONLY 只在用户显式操作时生成建议；ASSIST_ON_AMBIGUITY 才允许既有自动识别任务在困难分支调用。

必须完成两种真实能力：
A. 查询辅助：规则无法解析、正常查询无结果时，返回少量 title/author/volume/queryHints，并引用输入中实际存在的 evidenceId；AI 基于常识补出的名称标为假设，不直接写入。
B. 候选消歧：只接收最多 5 个已有候选，返回 selectedCandidateKey 或 null、支持/冲突 evidenceIds 和简短理由；允许无法判断。

安全和决策要求：
1. 使用严格 JSON schema/本地校验，拒绝未知候选 ID、字段、类型、超长输出和指向不存在证据的引用。
2. 模型只提供建议；服务端重新执行 M1 的冲突和层级校验。模型自报分数不作为自动门槛。
3. 模型在数据里发现的新事实须能绑定到原始证据；仅 AI 常识、推测作者/ISBN或自己提出的别名不能升级为已验证事实。
4. AI 建议生成的新查询仍经 M2 预算和来源适用性检查；不能自己选择任意 URL、访问 Open Library 自动接口、调用写库工具。
5. 默认只发元数据、有限文件名/父目录名与受限候选摘要，不发绝对路径、整本正文或完整目录树。
6. 提示注入只作为数据处理；不赋予模型工具，不执行模型输出的指令。
7. 两种 AI 调用和格式重试共用每目标最多两次 HTTP 尝试预算；取消/超时后回退规则结果或待确认，不进入无限修复循环。
8. 缓存纳入模型、提示词、输入、候选实际内容、配置和授权范围，不能只以书名为键。
9. 增加 bearer/none 认证，none 不发送 Authorization；新配置读写不泄露密钥。
10. 测试按钮运行一个小型结构化请求，验证所选模型与当前模式，不仅访问 /models。
11. 手动“AI 补全建议”若保留，只调用同一客户端/解析器；无来源事实的生成简介/标签明确标记 AI 建议，只能人工选择，不能覆盖受保护字段或冒充来源原文。

验收：
- 噪声文件名→AI 提示查询→真实来源候选→规则确认→M3 应用完整打通。
- 多候选能选择也能返回无法确定；理由中的假 evidenceId 被拒绝。
- 模型生成不存在 ISBN/候选、选择作者冲突项、输出提示注入/乱码均不写库。
- 关闭 AI 无请求；SUGGEST_ONLY 不触发自动调用；预算和取消生效。
- 旧凭据保留，本地无鉴权模型可配置；真实模型测试缺口如实报告。

提交建议：feat(metadata): add bounded AI recognition assistance
完成后停止。
```

## M6：后台配置、人工确认与识别记录完整闭环

目的：收口前面各阶段最小 UI，确保用户能理解和控制真实行为。

```text
执行 M6：后台管理与手动识别闭环。

复用现有 metadata-providers-panel、recognition-settings-panel、metadata-lookup-modal 和识别记录入口。
保持现有视觉、布局组件和导航，不设计第二个设置中心或独立审核平台。

必须完成：
1. 来源页显示支持的查询/层级、参与方式、配置状态、最近测试状态；连接测试与查询测试语义分开。
2. 来源排序仍是全局顺序；AI 显示为辅助角色而非事实来源。处理旧列表/旧排序 payload 的兼容，不假隐藏后仍参与。
3. AI 显示关闭/仅人工建议/困难时辅助、发送范围、认证方式和模型测试；原有配置与密钥可继续管理。
4. 识别策略保留定时、新增范围、本地优先、OPF 语义；新增低质量路径修正默认关闭。请求预算放高级说明，别让用户配置评分公式。
5. 手动弹窗显示当前 book/resource、查询方式、候选层级、匹配依据、冲突、字段来源和逐字段差异。
6. 只有满足权限/保护/目标范围的字段才能提交；客户端不能自行标记 trusted/matched 绕过后端。
7. 多源补缺只显示经过 M3 验证的建议；人工不认可时可放弃，不强迫合并所有源。
8. 识别记录区分已匹配未变更、已应用、待确认、未找到、来源故障、配置/目标不适用；任务取消沿用既有状态。
9. 待确认记录可重新打开已有弹窗、选择字段确认或忽略；过期结果提示重查，忽略的同一结果不被后台反复生成。
10. 应用完成后刷新受影响详情/列表和识别记录，保留现有导航与选择；不要全应用强制刷新。
11. 每个新增开关验证后端持久化、重启加载、实际请求/写入行为。旧客户端遗漏字段不能重置新设置。
12. 完成 zh-CN/en-US、错误文案、键盘/焦点和窄屏可用性；不新增移动原生页面。

验收：
- 使用真实 HTTP 链路验证保存→重载→搜索→预览→确认→数据库变化→页面刷新。
- 两个浏览器同时操作时旧结果被拒绝，不覆盖另一处新改动。
- UI 显示关闭与服务端零请求一致；不能只靠按钮 disabled。
- 手动、定时、新增后三条入口调用相同匹配/应用规则。
- 旧 API 客户端仍可读取/使用基本识别，无 breaking 字段替换。

提交建议：feat(web): complete metadata recognition controls
完成后停止。
```

## M7：回归、真实链路验收与交付门禁

目的：证明功能可用和写入安全，而不是继续膨胀测试设施。

```text
执行 M7：增强识别最终验收。

先阅读测试执行策略。复用既有 pytest、Web 测试和集成入口；只补本能力所需 fixtures，不引入测试框架/模拟数据平台或新的全仓 CI。

必须完成：
1. 固定样本集，给出自动匹配准确率、自动覆盖率、候选召回、人工确认占比、错版本次数与每目标请求数。
   精确写出分母：自动应用正确数/自动应用数，自动应用数/可评估目标数。
   仅在被抽样确认的真实样本上报告真实准确率；少量/合成测试不能宣称整体准确率。
2. 下列矩阵全部有自动测试或明确运行证据；严重误写/越权用例零失败。
3. 跑通三条纵切片：
   a. 有 ISBN 的单资源→来源候选→版本级字段→DB→启用时 OPF；
   b. 无 ISBN 的多卷书→书名作者卷号→只更新选定资源；
   c. 噪声文件名→AI 查询辅助→来源验证→自动安全应用或待确认。
4. 验证真实后台配置、重启、来源禁用、AI 关闭、请求预算、取消、故障降级及记录。
5. 对单目标 DB 投影、查询次数、外部预算和事务持有范围作有界验证；100k 类场景用合成索引数据/现有工具，不真的对外发送大批查询。
6. 验证升级前已有配置/密钥/保护字段/队列记录；有迁移时验证重复启动、失败恢复和备份恢复路径，不要求原件重扫。
7. 输出实际变更、已删旧入口、测试命令/结果、实测样本说明、未验证来源/模型、已知限制、schema/依赖/发布范围。
8. 不为了报告好看修改断言、跳过失败、降低门槛或用模拟结果冒充真实联调。
9. 缺凭据只阻塞对应真实来源联调，不阻塞已经可验证的规则/接口/配置；报告可以是工程实现完成、外部联调待验，不能写全部通过。
10. 按项目既有发布规则给出可选发布类型与必要条件，不自动发布/合并/tag，也不无理由重建移动端。

最终门禁：
- 三个用户目标都有实际入口和端到端证据。
- 无已知严重误识别写入、跨卷污染、越权、保护失效和过期覆盖。
- 原件与拓扑不变，导入不等待外部来源/模型。
- 预算、缓存隔离、错误分类、关闭开关和恢复语义可验证。
- 任何未完成真实验证在报告中清楚标注。

提交建议：test(metadata): verify recognition enhancement flows
完成后停止，等待用户审查和后续发布授权。
```

## 6. 最终验收矩阵

| 编号 | 场景 | 必须结果 |
| --- | --- | --- |
| R01 | 唯一同名但不同已知作者 | 拒绝自动应用，显示冲突 |
| R02 | 作者未知、仅标题吻合 | 待确认，不宣称强匹配 |
| R03 | 有效 ISBN 与标题/作者无冲突 | 可确认相应版本并仅应用允许字段 |
| R04 | 无效 ISBN / 套装 ISBN / 等价 10/13 位 | 分别拒绝强证据、限制范围、正确归一 |
| R05 | 两卷同名或卷号表达不同 | 可归一表达，不跨卷采用 |
| R06 | 不同语言/出版社/修订版 | 不混写版本字段；可按证据只确认作品 |
| R07 | 系列级条目识别具体卷册 | 不用系列封面/简介直接覆盖卷册 |
| R08 | Open Library Work 聚合 ISBN | 不当作某个 Edition 的直接事实 |
| R09 | 来源 A 缺简介、B 同一目标补缺 | 先确认身份/层级，再补；不增加无界来源 |
| R10 | 来源 A/B 互相冲突 | 待确认或舍弃字段，不拼装虚构版本 |
| R11 | 只有年份/年月的出版日期 | 保留精度，不伪造完整日期写入 |
| R12 | 有声书朗读者/节略版 | 只有录音/版本证据才能应用 |
| R13 | 人工保护和未知字段来源 | 自动不能覆盖；PATH 修正只作用于可证明字段 |
| R14 | 查找期间用户修改/移库/删资源 | revision/归属校验拒绝旧结果 |
| R15 | 重复任务/重复点击确认 | 不重复应用与派生副作用 |
| R16 | 来源禁用、AI OFF、人工建议模式 | 实际请求符合模式；没有隐藏自动调用 |
| R17 | 同名不同作者/卷号/连接配置缓存 | 不串结果；候选命中后重新匹配 |
| R18 | 429/鉴权/受限网页/解析失败/空结果 | 分类正确，不统一成 NO_MATCH |
| R19 | AI 提出新标题并引导查询 | 原目标证据不丢；结果再验证，不自证 |
| R20 | AI 返回假候选/假证据/高置信冲突项 | 拒绝，不写入 |
| R21 | 提示注入与恶意封面/详情 URL | 不执行指令，不越出端点与网络安全边界 |
| R22 | 取消、超时、服务重启、晚到响应 | 不再产生未授权后续请求/旧写入 |
| R23 | 最坏查询、详情、格式重试分支 | 所有尝试计入预算，上限有效 |
| R24 | OPF 开/关及队列故障 | DB/OPF 结果分离，原件不变 |
| R25 | 旧配置/旧排序/旧 AI/旧客户端 | 明确兼容，无密钥丢失或权限暗增 |
| R26 | 小库与大库的同一目标识别 | 无全库查找/重扫/哈希/逐资产任务 |
| R27 | 普通用户跨库或伪造 apply payload | 服务端拒绝，遵循既有反枚举契约 |
| R28 | UI 应用后重新打开详情/资源 | 展示实际保存值，不只 toast 成功 |

## 7. 官方来源核对入口

下列地址仅供实现时核对官方接口与使用边界；实现不能依赖文档中的示例 Key，也不能把政策当成永久不变。

```text
https://developers.google.com/books/docs/v1/using
https://openlibrary.org/developers/api
https://openlibrary.org/dev/docs/api/search
https://openlibrary.org/dev/docs/api/books
```

Google Books 使用官方 volumes 搜索/详情和用户自身凭据。本方案不接购买、下载或用户书架 OAuth。
Open Library 依据当前官方的人类按需、低量查询指导限定本轮使用范围；未来要做自动大规模补全，应另行确定授权/数据来源，而非把本方案的手动限制移除。

## 首次执行建议

将本文件交给 Codex，并明确发送：
“按总控提示词执行本方案；本次只执行 M0，完成后独立提交并停止，输出基线、调用链、最小改动范围和后续阶段验收门槛。”
