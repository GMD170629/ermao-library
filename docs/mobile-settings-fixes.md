# 手机端设置修复（2026-09-09）

## 原因与范围

- 用户与权限：后端 `AdminUser` 继承 `AuthUser`，正常响应包含 `avatarImageUrl`。KMP 管理设置解析器未接受此字段，导致 `UNEXPECTED_avatarImageUrl`。这不是旧数据问题。
- 系统日志：iOS 请求 `pageSize=200`，共享客户端上限为 100，发出 HTTP 请求前即返回 `INVALID_PAGE_SIZE`。同类整理任务、分类调用同步改为 100；Kindle 原本允许 200，保持不变。
- OPDS：原界面已有复制逻辑，但未配置公开地址时缺少初始值；现在使用当前连接服务器地址，并保留部署路径。后端仍是目录地址的唯一生成者。
- iOS 邮箱／密码分段控件只移除列表行的外层背景，保留系统选中态。Android 对应页面没有该额外背景。

不删除数据，不新增迁移，不改变后端契约。保留修改前工作区中已有的其他变更。

## 实现归属与行为

- 用户列表、详情、新增、编辑继续复用 KMP `toManagedUser`；仅增加头像展示元数据的显式字段接纳及字符串校验，不放宽全局响应检查，也不改变 `avatarUrl` 语义。
- `OpdsSettings.initialPublicBaseUrl` 统一管理默认地址规则，通过 `initialOpdsPublicBaseUrl` 公共接口供两端调用；已有公开地址优先，不在 Swift 或 Android 另写默认值规则。
- 两端开关只修改草稿，显示中英文未保存提示。右上角保存成功后更新地址；失败保留草稿和最近已保存的目录地址。iOS 关闭确认也改为修改草稿，文案说明保存后生效。
- Android 保留点击地址复制，并增加明确的复制按钮；iOS 继续使用系统剪贴板和已有成功反馈。
- 系统日志导出继续调用 `loadAllManagementEventsForExport`，逐页读取，未新增第二套分页实现。

## 验证

- KMP `:shared:testAndroidHostTest`：457 项通过，零失败、零跳过。新增覆盖实际头像响应、详情及权限更新、错误字段类型、OPDS 默认值与保存／重开／关闭、101 条日志跨页导出及筛选参数。
- iOS `xcodebuild ... -destination 'generic/platform=iOS' build`：通过。
- iOS 设置 XCTest 已尝试在已配对 iPhone 执行，但整个测试包先被已有 Reader 测试编译错误阻塞：`ReaderSecurityTests.swift:800` 访问 fileprivate `single`，`ReaderSafetyConformanceTests.swift:17` 的 `Int`／`Int32` 泛型冲突。没有为通过测试而排除或修改这些测试。
- Android 应用 Kotlin 源码编译已通过；完整单元测试被 `chapterCore:buildHostJni` 的宿主限制阻塞（要求 x86_64，本机 arm64）。针对设置的测试尝试又遇到未缓存的 Android 测试依赖，未取得通过结果。新增的 OPDS 复制及保存失败／重试测试尚未执行。
- 用户随后明确禁止本机 Android 构建；已停止后续 Android 构建及设备测试编译，仅继续共享层 JVM 单元测试。没有修改仓库依赖版本、构建配置或测试排除规则。
- 尚未获得两端设置界面的设备交互与真实服务器端到端证据。本机没有 Android 设备或模拟器；iOS 项目只配置 iphoneos，不支持当前方案中的模拟器执行。
