# 发布执行指南

## Android 持续测试版 / Continuous Android beta

`Mobile Stage 1` 在 `develop` 的相关变更推送后执行现有移动检查并构建独立 Beta APK。也可在 Actions 选择该工作流、选择 `develop` 后手动运行；其他分支与 PR 不发布。所有既有移动检查成功后才签名并更新 [Android Beta](https://github.com/GMD170629/ermao-library/releases/tag/android-beta) 的 APK 与 SHA-256 附件。旧构建不覆盖新构建，检查或签名失败不替换上一版。

The mobile workflow builds an independent beta on relevant `develop` pushes or a manual run targeting `develop`. Only successful mobile checks permit signing and updating the fixed Android Beta prerelease. Other branches and pull requests never publish. Download the APK and its matching `.sha256` asset from the link above.

测试版包名 `com.ermao.library.beta`，显示“二毛图书测试版 / Ermao Library Beta”，与现有客户端共存且首次需要重新登录。采用非调试配置，基础版本追加 `-beta.<run_number>`，`versionCode = 100000 + run_number`；重跑保持安装版本号，附件使用提交 SHA 与 attempt 区分。不要重建工作流并重置计数器；迁移工作流时必须保持测试版版本号递增。本地构建入口为 `./gradlew :androidApp:assembleBeta :androidApp:lintBeta -PbetaBuildNumber=1`（目录 `apps/mobile`），产物默认未签名。

Beta uses its own package and data, requires initial sign-in, and preserves that data on subsequent correctly signed updates. Its non-debuggable build uses the application base version plus the CI build number. Workflow reruns retain the version code. Keep the build counter monotonic when migrating workflows; local beta APKs are unsigned by default.

首次发布前配置以下仓库 Actions Secrets，签名阶段缺少任何一项即失败：

| Secret | 内容 / Value |
| --- | --- |
| `BETA_KEYSTORE_BASE64` | 专用 PKCS12 密钥库的 Base64 / Base64-encoded dedicated PKCS12 keystore |
| `BETA_KEYSTORE_PASSWORD` | 密钥库密码 / Keystore password |
| `BETA_KEY_ALIAS` | 密钥别名 / Key alias |
| `BETA_KEY_PASSWORD` | 私钥密码 / Private-key password |

只生成一次专用测试密钥，持续复用。私钥和密码不入库、不输出日志；仓库 Secrets 不作为唯一备份，需在受控位置安全备份密钥及密码，Windows DPAPI 密码备份仅能由原用户/机器解密。丢失或更换签名会使既有测试安装无法保留数据覆盖升级。PR 构建不获取这些 Secrets，只有发布任务具有 `contents: write`。

Generate the dedicated beta key once and retain a secure backup of both the keystore and password. Secrets are not a recoverable backup. Windows DPAPI password backups are tied to the original user/machine. Losing or rotating the signing key prevents data-preserving upgrades of existing beta installations. Only the publication job receives signing secrets and release write access.

`android-beta` 是可变的预发布标签，不标记为 Latest，不进入正式 `v*` 标签、正式发布说明索引或更新源。说明明确区分 CI 检查与真机验收；CI 冒烟不替代真机证据。APK 签名及校验后先上传新附件，再更新标签和说明，最后清理该渠道旧附件；中断遗留的新附件可由后续成功运行清理。

The mutable `android-beta` prerelease is never Latest and does not update stable version tags or release feeds. CI smoke checks do not replace physical-device acceptance. New verified assets are uploaded before updating published metadata and removing old beta assets. A later successful run cleans up assets left by an interrupted publication.

测试范围遵循 [测试执行策略](testing/test-execution-policy.md)。局部修复完成、集成检查点和最终冻结 RC 是不同阶段，不以未执行发布全量门禁阻塞已充分验证的局部修复。

## 验证阶段

- 开发修复：定向验证原失败与实际受影响边界，复用有效结果，达到停止条件即继续下一项。
- 既定集成检查点：同模块相关修复可以统一验证，先覆盖变化的模块/消费者；不因新增文档或提交重复有效测试。
- 最终冻结 RC：执行该次发布既定门禁，需要的完整回归、设备证据与发布阻塞项必须满足；局部修复结果不能替代最终放行。冻结后相关代码、依赖或环境变化按实际影响重验，不能把失效证据当作当前 RC 通过。

历史发布记录不作为每个开发补丁的执行清单；其状态与结论仍保留，不因本指南改写。

## 版本与发布说明

一次协调发布使用一致的应用语义版本。根 `package.json` 是权威版本，tag 为 `v<version>`；发布前核对 Web About 与后端运行时版本，产物版本不得冲突。

复用根脚本 `pnpm release:validate`，实际校验实现见 [validate-release-notes.mjs](../scripts/validate-release-notes.mjs)。需要 tag 对照时传 `--tag v<version>`（替换为本次真实版本）。不新增第二套校验工具。

该脚本当前覆盖根/Web/reader-core/reader-contracts/readium-web-poc 包版本、Python 包与运行时、service-worker 资源版本、uv lock 元数据，以及 Android `versionName`、iOS `MARKETING_VERSION`。保持这份实际覆盖范围，不因宿主构建分工排除另一端版本。涉及的其他锁文件或产物元数据变化也需一致；以现有脚本与本次发布流程为执行入口，不在普通修复中顺手升级版本。

发布说明遵循现有脚本的双语文档与索引契约；GitHub Release 填写简短且有实际用户价值的修复/改进摘要，禁止空说明或只留自动生成列表。创建 tag 前完成版本来源同步与校验，发布前完成最终门禁；不得发布仍有版本冲突或实际验收阻塞的 RC。


### 图书／卷册单次删除确认兼容顺序

发布取消名称输入确认的客户端前，先部署后端卷册源文件删除接口调整：`DELETE /api/books/{book_id}/resources/{resource_id}/source` 不再要求请求体，旧客户端发送的 `confirmation` 字段可继续接受，但不参与名称校验。随后发布 Web、Android 和 iOS 客户端；新版客户端不再发送该字段。整本图书删除仍保留固定协议值 `DELETE_SOURCE_FILES`，权限、资源归属、幂等处理和实际删除范围不变，无数据库迁移。
