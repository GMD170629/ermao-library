# 核心页面视觉精修 — 关闭清单

视觉验收：**PASS**（批准的 Android 主语言、默认字号、竖屏范围）。主审与独立评审已复核同一最终 APK 的完整真机页面。全部工程门禁并非全绿，既有失败详见下方。

权威目标：[target-contract.md](target-contract.md) 与 [带尺寸蓝图](target-blueprint.svg)。旧审查建议只有在用户本次确认的范围内适用。

| 编号 | 问题 | 状态 | 修复 / 决定 | 最终证据 |
| --- | --- | --- | --- | --- |
| VIS-001 | 顶栏与安全区 | closed | 统一紧凑顶栏和 Android 返回箭头；父子消费已应用 insets。 | 12-directory / 22-password-empty；真机 Scaffold 测试。 |
| VIS-002 | 首页单项最近阅读 | closed | 复用已有 BookListItem，封面 64dp；多项横向列表保留。 | 候选单项原图 + 最终 APK 单项组件测试；最终真实数据为 2 项。 |
| VIS-003 | 目录身份区与首屏 | closed | 96dp 封面、8dp 身份间距，无空作者行；子项首屏可辨认。 | 12-directory / 15-directory-sort / 16-directory-list。 |
| VIS-004 | 重复封面下的条目识别 | closed | 按批准范围改进标题：书库 2 行、目录 3 行，资源格式独立；保留真实封面。 | 04-library-stable / 35-directory-contents；不推断图片加载故障。 |
| VIS-005 | 旧对比度目标 | superseded | 用户明确撤销该基准，改为契约与 Web 手机端一致；未按对比度重新配色。 | 新颜色验收见 VIS-009；旧对比度要求不声明通过。 |
| VIS-006 | 空资源元数据 | closed | 只渲染有值字段；全部缺失时不创建整个列表区块。 | 18-resource / 37-nested-resource；空与部分值单元测试。 |
| VIS-007 | 书库控制区节奏 | closed | 统计上下各 8dp，保持三列，省去空作者行。 | 04-library-stable；首排封面 y=912px。 |
| VIS-008 | SMTP 分组与空值 | closed | 连接→发件身份→发送限制→测试；Kindle 空发件邮箱显示未设置，中英文齐全。 | 26-kindle / 29-smtp / 33-smtp-bottom。 |
| VIS-009 | 契约颜色漂移 | closed | 契约 1.2.0 与生成链同步；App 主按钮 FF4F2A，Web 对应 owner 迁移变量。 | 真机六角色像素实测；Web 411px 登录主按钮运行时取色。 |
| VIS-010 | 输入框圆角与状态 | closed | 搜索及设置复用同一 12dp 形状/颜色默认值；数值左对齐，密码槽固定。 | 22–25 / 29 / 39–40；最终真机空值、有值、显隐、禁用、启用测试。 |
| VIS-011 | Popup 行与选中几何 | closed | 共用 Material Popup/菜单项；左右 12dp，最小 48dp，24dp 图标，勾选预留槽。 | 05 / 06 / 09 / 15 / 36；最终真机首、中、末选项测试。 |
| VIS-012 | Tab 与分段控件对齐 | closed | 保留各自交互形态，首中末选中填充对称，文字不偏移。 | 四 Tab 色块左右各 14px；30–32 文本边界一致。 |

## 构建与验证

- 契约：v1.2.0，schema 保持不变；generateDesignTokens / syncWebDesignTokens / verifyDesignTokens 通过。Kotlin、Swift、Android XML 均由现有生成链产出，Web CSS/TS 通过生成同步。保留其余校验（含 Reader）；只撤销冲突的 App 主按钮对比度断言。
- Android：204 项单元测试通过（0 失败 / 0 跳过）；最终主 APK 与 test APK 构建通过。真机直接 instrumentation **19/19 通过**（主测试组 14 + 下载页面回归 5），覆盖菜单、导航、搜索、设置输入、共享 Scaffold、首页单项与多项等。未使用会在结束后卸载主应用的 connectedAndroidTest。
- Android lint：**46 个既有错误**；本轮视觉修改未新增。分布为音频 UnstableApi 34、旧资源 11、Manifest ExportedService 1。未建立 baseline 或压低规则；见 [分类记录](checks/android-lint-classification.md)。
- Web 最终全量 lint、typecheck 通过；i18n 2102 项一致性通过；test **421/422 通过**，唯一失败是未修改的 Readium adapter 测试因 `@readium/shared` 导出而报 `ERR_PACKAGE_PATH_NOT_EXPORTED`，在固定 Node 22.23.1 / pnpm 9.12.2 单独复现。
- Windows 缺少 python3 命令别名；使用现有 Python 运行时临时 PATH 适配运行完全相同的 i18n/pretest 脚本，没有改测试或项目脚本。默认环境失败与固定运行时结果均保留在 checks。
- 交互：搜索及清空、排序、网格/列表切换、返回、密码显隐、保存启用/禁用已烟测。仅编辑合成测试值，随后清空；没有发送测试邮件、提交账户/SMTP/Kindle 修改、清除应用数据或卸载主应用。

## 证据与比较边界

- 设备 `9e896bbc`；1440×3200，density 3.5，fontScale 1.0，中文，竖屏，App Light。APK SHA-256：`008fd098f9d9fadde8ddb16ac017d53d5735e2f99f62bc46b97414cb1b6a60d4`。已对比安装包 SHA；最后冷启动成功。
- 最终原图目录 `core-tabs-polish-v1/final`；原始 PNG/XML 保留私有目录，未写入仓库。仓库仅保留不含账户值的度量、目标、源码身份与结论。
- 首页真实数据从 1 项变成 2 项；不能把这两张截图当作完全同数据比较。单项分支有候选真机原图及最终构建 synthetic component 测试，多项分支由最终完整 Shell 真机复拍验收。其余指定对照使用同内容和选择态。
- 03-library-menu 是复拍期间页面被外部操作切换的无效快照，排除；安全键盘可见时产生的零字节截图同样排除。未绕过系统安全截图限制；聚焦与显隐图在正常收起键盘后获取。
- 下载完成后的独立下载 Popup 已迁移共享 owner；当前审查资源未下载，未为视觉验收新增真实下载，其专属完整页面状态未单独复拍。共享菜单几何与单选语义有最终真机组件测试；目录操作 Popup 有完整页面原图。
- Web 验证到实际 411×914 登录页主按钮色、最终共享颜色 owner 与工程检查；当前内置浏览器没有登录，未声明四个 Web 登录后页面的整页视觉验收。iOS 仅同步生成的 App 颜色，未声明 iOS 页面验收。
- 不扩展 Reader、大字体、TalkBack、对比度或横屏专项。无后端、业务 API、数据结构、持久化变更。

## 复用与删除

- 唯一颜色 owner：`packages/design-contracts/visual-tokens.json`；未另建平台调色板。
- 输入 owner：现有 WarmPage 输入组件内的 `WarmPageTextFieldDefaults`，供搜索与 SettingsTextField 共同使用；移除原设置输入的独立颜色/形状声明。
- 顶栏 owner：`WarmPageScaffold` 的紧凑顶栏与可选 topBarBottom 插槽；设置改为委托，删除重复 Scaffold/顶栏实现。
- 菜单 owner：`WarmPagePopup` / `WarmPageMenuItem`；详情下载、排序、目录管理入口接入，删除各入口重复 DropdownMenuItem 布局，保留条件和回调。
- 页面复用：单项最近阅读用现有 BookListItem；元数据投影只负责展示已有值，删除缺值破折号及空区块。Web 在现有 button/select/combobox/progress/app-shell/book-detail owner 内迁移颜色，无布局重写。
- 工作区在实施前已有 Reader、脚本、文档与部分文案修改，均保留。两份 Android strings 的本轮修改仅删除 `work_metadata_missing`；Reader 等既有改动不归入本轮成果。

主审认可独立评审的 PASS；[独立评审](checks/independent-visual-review.md)、[实测](checks/physical-measurements.json)、[最终真机测试](checks/android-device-final.log)、[源码与证据清单](run-manifest.json)。
