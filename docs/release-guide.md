# 发布执行指南

## v1.0.0 放行 / v1.0.0 acceptance

2026-09-13，项目负责人确认已完成验收，要求执行正式发布，并将此前未完成的验收记录设为过时、直接删除。原 `docs/releases/1.0` 下的门禁、矩阵、阻塞项和证据台账已移除，不再代表当前放行状态。此结论来自负责人验收，不是代理补跑了旧台账全部场景。

On September 13, 2026, the project owner confirmed completed acceptance and authorized the stable release and deletion of obsolete incomplete acceptance records. The former v1.0 gate, matrix, blocker, and evidence documents no longer represent current release status. This is owner acceptance, not a claim that the agent reran every historical scenario.

## Android 正式 APK / Stable Android APK

v1.0.1 放行范围：项目负责人于 2026-09-13 确认继续正式发布，沿用既有 Android 冒烟、安全检查、构建和已完成的真机验收。额外执行的可选全量 UI 回归出现 9 项失败，不计为通过，也不纳入本次修复范围；该套件继续保留为移动工作流的可选入口。对应运行记录为 [34741501220](https://github.com/GMD170629/ermao-library/actions/runs/34741501220)。

For v1.0.1, the owner authorized publication on September 13, 2026 using the existing Android smoke, safety, build checks and completed physical-device acceptance. The additional optional full UI run reported nine failures; these are not represented as passes or included in this repair scope. The full suite remains available from the mobile workflow.

从 v1.0.1 起，正式发布统一使用 `.github/workflows/fnos-package.yml`：复用移动工作流完成检查及 Release 构建，后端测试前构建原生章节库；使用 `scripts/sign-android-apk.sh` 的 `stable` 渠道签名，随后构建版本镜像与 FPK。仓库 Secrets 使用持久正式密钥的 `RELEASE_KEYSTORE_BASE64`、`RELEASE_KEYSTORE_PASSWORD`、`RELEASE_KEY_ALIAS`、`RELEASE_KEY_PASSWORD`。Beta 与正式渠道共用签名实现，各自保留独立密钥和包名。

禁止单独上传正式 APK 作为一次正式发布。APK、FPK 与各自 SHA-256 必须同时存在且校验通过，统一上传至草稿并核对远端附件摘要，再提升镜像的 `prod/latest` 标签、公开 Release 和更新 feed。任一构建、检查或附件校验失败即停止，不公开不完整版本。正式发布前可在 `main` 手动运行同一工作流构建候选 bundle；下载其中最终签名 APK 完成真机验收后，再创建正式标签。已公开的版本标签不移动，源码修复使用新的补丁版本。

Starting with v1.0.1, the fnOS workflow coordinates mobile checks, the signed stable APK, backend tests with the native chapter library, the versioned Docker image, and the FPK. Configure the four `RELEASE_*` signing secrets using the persistent stable key. The shared signer keeps stable and beta identities separate. Never publish a stable APK alone: validate both packages and checksums, upload the complete draft bundle, verify remote digests, then promote stable image tags and publish the Release/feed. A manual run on `main` produces the same candidate bundle for physical-device acceptance before tagging. Preserve published tags and use a new patch version for source fixes.

正式包使用 `com.ermao.library`，v1.0.0 为 `versionName=1.0.0`、`versionCode=1`，最低 Android 8.0（API 26）。后续正式更新保持包名与签名密钥，并递增 versionCode。独立 Beta 包与密钥不用于替代正式身份。

在 `apps/mobile` 执行 `./gradlew :androidApp:assembleRelease :androidApp:lintRelease`，产物为 `androidApp/build/outputs/apk/release/androidApp-release-unsigned.apk`。使用 Android build-tools 的 `zipalign -P 16 -f 4` 对齐后，由 `apksigner sign` 使用正式密钥签名，再执行 `apksigner verify --verbose --print-certs` 和 `zipalign -c -P 16 4`。密码通过环境变量传递，不放在命令行字面量或日志中。对最终已签名文件生成 SHA-256，附件命名为 `ermao-library-v<version>-android.apk` 与同名 `.sha256`。

The stable package and signing identity must remain consistent for future updates. Build the unsigned Release variant, align it for 16 KB pages, sign with the persistent release key, verify both signature and alignment, and hash the final signed APK. Supply passwords through environment references rather than command-line literals.

首次正式密钥在受控的仓库外目录生成，只生成一次；密钥库与密码须独立安全备份。Windows DPAPI 密码文件只能由原机器/用户解密，不是跨机器可恢复备份。不要提交私钥或密码，也不要用 Debug/Beta 签名代替正式签名。

Keep the keystore and password in protected storage outside Git and back them up securely. A DPAPI-encrypted password is tied to its original Windows user and machine. Never substitute Debug or Beta signing for the stable key.

使用最终签名 APK 在指定真机安装、冷启动并检查包名、版本、前台 Activity、crash/ANR 与相关业务路径。同包名开发版签名不匹配时，先取得明确授权才可卸载旧版。发布门禁未完成时仅创建 GitHub Release 草稿并上传候选附件，不创建公开正式标签、不切换 Latest；草稿不是已发布版本。公开发布时再核对发布索引日期和实际发布时间。

Validate the final signed APK on a physical device. Replacing a differently signed development installation requires explicit authorization before uninstalling it. Incomplete gates permit a draft with candidate assets only; a draft is not a published stable release. Reconcile the release-index date with the actual publication date before publishing.

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

### 正式发布的主分支同步 / Stable-release main synchronization

正式发布必须将本次已验收的发布提交同步到远端 `main`，不能仅更新 `develop`、标签、GitHub Release 或 `release-feed`。发布说明维护工作流 `sync-release-notes.yml` 从 `main` 读取权威文档，主分支滞后会使后续同步使用旧说明。

1. 获取远端最新状态，确认待发布提交、版本、双语说明和验收结论一致；不要将发布冻结后无关的开发提交一并带入。
2. 检查 `main` 与发布提交的历史关系。可快进时直接快进；存在分叉时保留两边改动，通过正常合并解决冲突并验证受影响范围，禁止强推覆盖主分支。
3. 推送 `main` 后，核验远端 `main` 包含本次发布提交，且应用版本和本版本发布说明与正式标签一致。新建正式标签前完成此核验；补做已发布版本的同步时保留原标签和产物身份，不移动已发布标签。
4. 收尾核对远端 `main`、正式标签、GitHub Release、Wiki 与 `release-feed` 的版本和说明，并报告同步结果。未同步主分支不得宣称正式发布流程已完整结束。

Every stable release must synchronize its accepted release commit to remote `main`, because the release-note maintenance workflow reads that branch. Fetch current refs, fast-forward when possible, or merge divergent history without discarding either side. Verify that remote `main` contains the release commit and matches the tagged application version and release notes before creating a new stable tag. When repairing a previously published release, preserve its existing tag and artifacts. Verify `main`, the tag, Release, Wiki, and release feed before reporting completion; do not include unrelated post-freeze development changes.


### 图书／卷册单次删除确认兼容顺序

发布取消名称输入确认的客户端前，先部署后端卷册源文件删除接口调整：`DELETE /api/books/{book_id}/resources/{resource_id}/source` 不再要求请求体，旧客户端发送的 `confirmation` 字段可继续接受，但不参与名称校验。随后发布 Web、Android 和 iOS 客户端；新版客户端不再发送该字段。整本图书删除仍保留固定协议值 `DELETE_SOURCE_FILES`，权限、资源归属、幂等处理和实际删除范围不变，无数据库迁移。
