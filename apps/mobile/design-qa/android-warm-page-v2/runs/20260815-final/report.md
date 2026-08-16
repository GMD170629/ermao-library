# Android Warm Page v2 验收报告

- 验收日期：2026-08-15
- Git HEAD：`de3d303e4a7eb692e622c33bb29e748b4637e9ac`（工作树包含本次未提交实现）
- APK：`apps/mobile/androidApp/build/outputs/apk/debug/androidApp-debug.apk`
- SHA-256：`c07b79fea5b77f9463e71e18f9304f60ef7c58ec65c6551baad0840d0cdbfb49`
- Package：`com.ermao.library`
- Version：`0.1.0`（versionCode 1）
- AVD：`Shuku_API_36` / `emulator-5554`
- Android：API 36
- 设备：`sdk_gphone64_x86_64`
- 分辨率/密度：1080×2400 / 420 dpi（约 412×915dp）
- fontScale：1.0

## 实现范围

- 完整映射 Material ColorScheme 与 Typography，避免默认 seed 色泄漏；不全局覆盖 Material shapes。
- 新增统一 Scaffold、Navigation、Search、Segmented、Menu、Action、Feedback 与组件度量层。
- MainShell、Home、Library、Facet、Work Detail 已迁移到统一组件；业务状态、回调、导航和 test tag 保持不变。
- Library 的排序/视图拆分为独立菜单；Work Detail 保持唯一实心 CTA；C 类业务进度与内容区由 Warm Page 组件拥有视觉参数。
- Fixture 改为 capture-only，不再从当前 APK asset 读取并比较同批生成的 expected。

## 自动门禁

- `verifyDesignTokens`：通过。
- `:shared:testAndroidHostTest`：通过。
- `:androidApp:lintDebug`：通过，0 error。
- 主题/组件度量单测：7 tests，通过。
- QA 比较器单测：5 tests，通过。
- 视觉仪器化：3 tests，通过，0 skipped / 0 failed；输出 28 张 zh-CN/en-US × Light/Dark 与 6 张 fontScale=2.0 截图。
- APK replace-install、force-stop、冷启动、前台 Activity 与 crash log：通过。
- 三页静态政策扫描：无直接 `LargeTopAppBar`、`OutlinedTextField`、`SingleChoiceSegmentedButtonRow`、`NavigationSuiteScaffold`、页面裸 `dp` 或页面色值。

## 运行证据

- `fixture-captures-final/`：最终 APK 对应的 34 张确定型截图。
- `platform-api36-final/`：真实 MainActivity 的 Home、Library、Work Detail 整机截图与 UI hierarchy。

## 未伪造通过的门禁

- 全量 Android unit test 共 79 tests，其中 2 个既有 Reader CSP 测试失败：
  - `EpubContentSecurityPolicyTest.decoratesOnlyHeadAndPreservesAuthorBody`
  - `EpubContentSecurityPolicyTest.fakeHeadInsideCommentAndCdataCannotCaptureSecurityDecoration`
  本轮未修改 Reader 引擎或 CSP 行为。
- 390×844 权威 reference 门禁当前不能完整执行：三张 Work Detail PNG 在工作树中缺失，现存 actions PNG 为 853×1844。比较器会明确失败，未更新 golden、未扩大阈值、未遮罩 C 类区域。
