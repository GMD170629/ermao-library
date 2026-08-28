# 封面 small 参数与同步长按菜单

日期：2026-08-27。仅修改 Mobile，没有修改后端、Web、Reader 或下载业务；保留工作区其他改动。本轮在当前主工作区验证，没有使用上一轮隔离副本。

## 调整

- 共享封面请求入口规范化 `size=small`：图书、目录、资源封面均覆盖，保留其他参数；页面预览、原文件和外部图片不改。Android/iOS 的缓存读取与管理操作失效使用同一 URL 规则，已有 medium/原图缓存不会再命中。
- Android 继续使用官方 Material 3 DropdownMenu，iOS 继续使用系统 contextMenu/Menu。打开菜单为同步纯本地操作；选择动作后才读取管理快照，在操作 Sheet 中显示进度、失败和重试。
- 显式传递 completed、Kindle 和目录代表资源能力。缺失已读标志不能按 progress 或 false 推断；在页面封面出现时使用现有单书接口读取一次，按会话去重、最多 4 个并发、最多 256 个缓存目标。等待或失败时仅阅读状态项不可用，不用菜单进度条；页面重新出现可以重试失败预取。
- Android 以实际长按坐标建立零尺寸布局锚点，由 Material 处理弹出边界；无坐标入口保留控件锚点。宽度为 280dp，窄窗口限制为可用宽度减 32dp；标题单行省略，完整语义保留，动作文字可换行。
- 保留目录下载扩展项、权限矩阵、准确对象身份、危险确认和原有管理业务。会话销毁和操作切换拒绝过期响应；菜单关闭不会发起或重复请求。

## 已验证

- 当前工作区 `:shared:testAndroidHostTest`：307 项，0 失败、0 跳过。
- `:androidApp:testDebugUnitTest`：144 项，0 失败、0 跳过。
- `:androidApp:lintDebug`、`verifyDesignTokens`、`verifyMobileOfflineContract` 通过。
- `assembleDebug`、`assembleDebugAndroidTest` 通过。日志见 gates.txt，APK 哈希见 results.json。
- 新增覆盖：封面参数与 base path / ETag、非封面 URL 不变、菜单首次和重复打开零快照请求、动作延迟准备与重试、并发去重、缺失已读状态、会话销毁后响应拒绝。
- Android 双语资源无重复，iOS nativeManagement 文案均包含 en / zh-Hans；`git diff --check -- apps/mobile` 通过。

## 设备与待验

- Android 设备：9e896bbc，物理 M2102K1AC。安装前重新确认 device 状态；主包和测试包均 install -r 成功，没有卸载或清数据。包 com.ermao.library，versionCode 1，versionName 1.0.0。
- 安装后 force-stop / start 返回 Status ok，但设备锁屏，LaunchState UNKNOWN，未取得 resumed 可见页面。不能将此次启动算作冷启动或交互验收。读取时 crash buffer 为空，系统 lastanr 无记录。
- 7 项 Compose 测试已编译：普通点击/滚动、重复长按零请求、按压点定位、长标题固定宽度、普通用户 Kindle、脏表单取消、中文深色菜单；待设备解锁后执行。尚无这一版本的真机交互、TalkBack、键盘、大字体、旋转/分屏或实际服务器页面证据。
- iOS 无可用 Mac、有效签名或物理 iPhone/iPad。Swift 改动及 XCTest 已添加，未运行 Xcode 编译或真机测试。没有使用模拟器。
- Web pnpm i18n:check 仍因现有缺失/陈旧文案失败，见 web-i18n.txt。未降低门禁，也未改动这些范围外文案。

解锁后运行：`adb -s 9e896bbc shell am instrument -w -e class com.ermao.library.features.workmanagement.BookManagementCoverTest com.ermao.library.test/androidx.test.runner.AndroidJUnitRunner`；必须先再次确认设备在线且解锁，检查明确测试结果，再冷启动主应用并验证 crash/ANR 与实际页面。
