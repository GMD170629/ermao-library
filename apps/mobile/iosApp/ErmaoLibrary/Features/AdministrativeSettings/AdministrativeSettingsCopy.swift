import Foundation

enum AdministrativeCopyKey: String, CaseIterable, Sendable {
    case managementTitle, librarySection, organizeSection, serviceSection, systemSection
    case librarySources, importTasks, importPreferences, organizeQueue
    case metadataProviders, usersPermissions, emailKindle, kindleQueue, opds, backups
    case workDetailOrder, systemHealth, systemLogs, enhancedAbout
    case loading, retry, save, saved, cancel, delete, remove, add, edit, done, close
    case all, active, failed, completed, enabled, disabled, available, unavailable
    case search, empty, unknown, test, testing, refresh, rescan, clearCompleted
    case kindleTab, smtpTab, kindleRecipient, kindleSendEnabled, kindleFormat, subjectTemplate
    case smtpEnabled, smtpHost, smtpPort, smtpEncryption, senderEmail, senderName, maximumAttachment, username, password
    case passwordConfigured, sendTestEmail, smtpTestSucceeded, saveKindle, saveSMTP
    case kindleQueueTitle, sending, sent, queued, taskCancel, taskRetry, taskDelete
    case deleteKindleTitle, deleteKindleMessage
    case usersTitle, newUser, displayName, email, role, member, administrator, accountStatus
    case enableAccount, disableAccount, deleteUser, editUser, accessScope, resetPassword
    case newPassword, confirmPassword, resetAndRequireLogin, deleteUserTitle, deleteUserMessage
    case manageSystemPermission, accountLanguage
    case allLibraries, manualImports, selectedDirectories, saveAccess, accessHint
    case sourcesTitle, storageLocation, availableSpace, libraries, browseDirectory
    case scanDirectory, sourceName, serverPath, scanningEnabled, scanInterval, mediaTypes
    case organizationMode, flatLayout, volumesLayout, audiobookLayout
    case includeSubdirectories, autoImportNewFiles, deleteSource, deleteSourceTitle
    case deleteSourceMessage, selectServerDirectory, parentDirectory, chooseDirectory
    case scanning, cancelScan, lastScan, scanFileCount
    case importTasksTitle, queueNormal, taskSource, taskCreated, parsing, pending, cancelled
    case importTaskDetail, importTaskLogs, scanJobs, directoriesScanned, filesScanned
    case candidatesFound, queuedCount, errorCount
    case deleteImportTitle, deleteImportMessage, rescanAll
    case importPreferencesTitle, fileProcessing, keepSourceFiles, duplicatePolicy
    case ignoreHiddenFiles, ignorePatterns, minimumFileSize, sourceDescription
    case allowedExtensions
    case duplicateSkip, duplicateReplace, duplicateKeepBoth, preferOPF, titleFromFilename
    case metadataSection, metadataLanguage, automatic, targetPathTemplate, autoOrganize
    case resourceLimits, concurrentTasks, retryLimit, futureTasksHint
    case organizeTitle, queueTab, policyTab, recognizeNow, viewCandidates, pauseQueue
    case organizeRuns, organizePending, reviewCount
    case clearOrganized, candidateTitle, confidence, useResult, skip
    case recognitionPolicyTitle, scheduledRecognition, schedule, runAfterImport
    case persistOPF, localMetadataFirst, metadataPriority, recognitionScope
    case recognizeUnmatched, recognizeIncomplete, eligibleCount, nextRun, opfQueue
    case merge, categoryGovernanceTitle, author, tag, series
    case selectedCount, aliases, workCount, deleteCategory, mergeCategoriesTitle
    case targetCategory, confirmMerge, renameCategory, newCategoryName, confirmRename
    case operationHistory, undoOperation, undoOperationMessage
    case providersTitle, provider, queryPipeline, editPriority, autoMatching
    case confidenceThreshold, autoApply, testProviders, saveConfiguration
    case providerConfigurationTitle, apiBaseURL, apiKey, keepSecretHint, countryRegion
    case languageCode, rateLimit, connectionTest, saveAndTest, connected, responseTime
    case opdsTitle, opdsEnabled, serviceStatus, running, stopped, publicBaseURL, catalogURL
    case opdsInstructions, copy, copied, disableOPDSTitle, disableOPDSMessage, disableService
    case backupsTitle, createBackup, backupDirectory, downloadFile, restoreBackup, deleteBackup
    case restoreWarning, restoreConfirmation, enterRestore, restore, deleteBackupTitle
    case deleteBackupMessage, backupWorkCount, backupProgressCount, backupDirectoryCount
    case workOrderTitle, workOrderHint, restoreDefault, saveOrder
    case overview, ebook, comic, audiobook, chaptersContent
    case healthTitle, lastChecked, runHealthCheck, restartImportQueue, restartQueueTitle
    case restartQueueMessage, safeRestart, waitForCurrentImports, directoryDatabase, backgroundQueues
    case featureConfiguration, healthy, warning, checking
    case logsTitle, searchLogs, allLevels, allSources, recentSevenDays, logCapacity
    case manageLogs, exportFiltered, clearInformationWarning, saveCapacity, capacityMegabytes
    case clearLogsTitle, clearLogsMessage, clearAllLogs, information
    case aboutTitle, appVersion, serverVersion, compatibility, compatible, supportedFormats
    case openSourceLicense, operationMode, selfHosted, releaseHistory, projectAddress, share
    case authorizationRequired, permissionDenied, conflict, temporarilyUnavailable
    case invalidInput, requestFailed, noResults, destructiveCannotUndo
}

struct AdministrativeCopyCatalog: Equatable, Sendable {
    let locale: AdministrativeSettingsLocale
    private let values: [AdministrativeCopyKey: String]

    init(locale: AdministrativeSettingsLocale) {
        self.locale = locale
        values = locale == .zhCN ? Self.chinese : Self.english
    }

    subscript(_ key: AdministrativeCopyKey) -> String {
        values[key] ?? key.rawValue
    }

    static func hasCompleteParity() -> Bool {
        Set(chinese.keys) == Set(AdministrativeCopyKey.allCases)
            && Set(english.keys) == Set(AdministrativeCopyKey.allCases)
    }

    private static let english: [AdministrativeCopyKey: String] = [
        .managementTitle: "Management", .librarySection: "Library", .organizeSection: "Organization",
        .serviceSection: "Services", .systemSection: "System", .librarySources: "Library Sources",
        .importTasks: "Import Tasks", .importPreferences: "Import Preferences", .organizeQueue: "Smart Organization",
        .metadataProviders: "Metadata Providers",
        .usersPermissions: "Users & Permissions", .emailKindle: "Email & Kindle",
        .kindleQueue: "Kindle Send Queue", .opds: "OPDS", .backups: "Data & Backups",
        .workDetailOrder: "Work Detail Order", .systemHealth: "System Health", .systemLogs: "System Logs",
        .enhancedAbout: "About Ermao Library", .loading: "Loading…", .retry: "Retry", .save: "Save",
        .saved: "Saved", .cancel: "Cancel", .delete: "Delete", .remove: "Remove", .add: "Add",
        .edit: "Edit", .done: "Done", .close: "Close", .all: "All", .active: "Active",
        .failed: "Failed", .completed: "Completed", .enabled: "Enabled", .disabled: "Disabled",
        .available: "Available", .unavailable: "Unavailable", .search: "Search", .empty: "No items",
        .unknown: "Unknown", .test: "Test", .testing: "Testing…", .refresh: "Refresh",
        .rescan: "Rescan", .clearCompleted: "Clear Completed", .kindleTab: "Kindle", .smtpTab: "SMTP",
        .kindleRecipient: "Kindle Recipient", .kindleSendEnabled: "Send to Kindle Enabled",
        .kindleFormat: "File Format", .subjectTemplate: "Subject Template", .smtpEnabled: "Enable SMTP",
        .smtpHost: "SMTP Host", .smtpPort: "Port", .smtpEncryption: "Encryption", .senderEmail: "Sender Email",
        .senderName: "Sender Name", .maximumAttachment: "Maximum Attachment (MB)",
        .username: "Username", .password: "Password", .passwordConfigured: "Configured; leave blank to keep it",
        .sendTestEmail: "Send Test Email", .smtpTestSucceeded: "Test email sent", .saveKindle: "Save Kindle Settings",
        .saveSMTP: "Save SMTP Settings", .kindleQueueTitle: "Kindle Send Queue", .sending: "Sending",
        .sent: "Sent", .queued: "Queued", .taskCancel: "Cancel Task", .taskRetry: "Retry Task",
        .taskDelete: "Delete Task", .deleteKindleTitle: "Delete this send task?",
        .deleteKindleMessage: "A deleted task cannot be recovered.", .usersTitle: "Users & Permissions",
        .newUser: "New User", .displayName: "Display Name", .email: "Email", .role: "Role",
        .member: "Member", .administrator: "Administrator", .accountStatus: "Account Status",
        .enableAccount: "Enable Account", .disableAccount: "Disable Account", .deleteUser: "Delete User",
        .editUser: "Edit User", .accessScope: "Access Scope", .resetPassword: "Reset Password",
        .newPassword: "New Password", .confirmPassword: "Confirm Password",
        .resetAndRequireLogin: "Reset and Require Sign In", .deleteUserTitle: "Delete this user?",
        .deleteUserMessage: "The account will lose access immediately. Private data handling follows the server policy.",
        .manageSystemPermission: "Manage System Settings", .accountLanguage: "Account Language",
        .allLibraries: "All Libraries", .manualImports: "Manual Imports", .selectedDirectories: "Selected Directories",
        .saveAccess: "Save Access Scope", .accessHint: "Users can only browse and read content inside their assigned scope.",
        .sourcesTitle: "Library Sources", .storageLocation: "Storage Location", .availableSpace: "Available Space",
        .libraries: "Library Roots", .browseDirectory: "Browse Server Directory",
        .scanDirectory: "Scan Directory", .sourceName: "Display Name", .serverPath: "Server Path",
        .scanningEnabled: "Enable Scanning", .scanInterval: "Scan Interval", .mediaTypes: "Media Types",
        .organizationMode: "Organization Mode", .flatLayout: "Flat", .volumesLayout: "Volumes", .audiobookLayout: "Audiobook",
        .includeSubdirectories: "Include Subdirectories", .autoImportNewFiles: "Automatically Import New Files",
        .deleteSource: "Delete Source", .deleteSourceTitle: "Delete this library source?",
        .deleteSourceMessage: "Its library-root configuration will be removed and future scans will stop. Original book files are not deleted.",
        .selectServerDirectory: "Select Server Directory", .parentDirectory: "Parent Directory",
        .chooseDirectory: "Choose This Directory", .scanning: "Scanning", .cancelScan: "Cancel Scan",
        .lastScan: "Last Scan", .scanFileCount: "Files Found", .importTasksTitle: "Import Tasks",
        .importTaskDetail: "Import Task Detail", .importTaskLogs: "Task Logs", .scanJobs: "Directory Scans",
        .directoriesScanned: "Directories Scanned", .filesScanned: "Files Scanned",
        .candidatesFound: "Candidates Found", .queuedCount: "Queued", .errorCount: "Errors",
        .queueNormal: "Queue operating normally", .taskSource: "Source", .taskCreated: "Created",
        .parsing: "Parsing", .pending: "Pending", .cancelled: "Cancelled",
        .deleteImportTitle: "Delete this import task?", .deleteImportMessage: "The task record will be removed.",
        .rescanAll: "Rescan All Sources", .importPreferencesTitle: "Import Preferences",
        .ignoreHiddenFiles: "Ignore Hidden Files", .ignorePatterns: "Ignore Patterns",
        .minimumFileSize: "Minimum File Size", .sourceDescription: "Description",
        .allowedExtensions: "Allowed Extensions",
        .fileProcessing: "File Processing", .keepSourceFiles: "Keep Source Files",
        .duplicatePolicy: "Duplicate File Policy", .duplicateSkip: "Skip Duplicates",
        .duplicateReplace: "Replace Existing", .duplicateKeepBoth: "Keep Both", .preferOPF: "Prefer OPF Metadata",
        .titleFromFilename: "Complete Title from Filename", .metadataSection: "Metadata",
        .metadataLanguage: "Language", .automatic: "Automatic", .targetPathTemplate: "Target Path Template",
        .autoOrganize: "Organize After Import", .resourceLimits: "Resource Limits",
        .concurrentTasks: "Concurrent Import Tasks", .retryLimit: "Failed Task Retry Limit",
        .futureTasksHint: "These settings apply only to future import tasks.", .organizeTitle: "Smart Organization",
        .organizeRuns: "Organization Runs", .organizePending: "Pending Overview", .reviewCount: "Needs Review",
        .queueTab: "Queue", .policyTab: "Policy", .recognizeNow: "Recognize Now",
        .viewCandidates: "View Candidates", .pauseQueue: "Pause Queue", .clearOrganized: "Clear Organized",
        .candidateTitle: "Select Recognition Result", .confidence: "Confidence", .useResult: "Use This Result",
        .skip: "Skip", .recognitionPolicyTitle: "Recognition Policy", .scheduledRecognition: "Scheduled Recognition",
        .schedule: "Schedule", .runAfterImport: "Run After New Import", .persistOPF: "Persist Changes to OPF",
        .localMetadataFirst: "Prefer Local Metadata", .metadataPriority: "Metadata Priority",
        .recognitionScope: "Recognition Scope", .recognizeUnmatched: "Unrecognized Books",
        .recognizeIncomplete: "Missing Author or Cover", .eligibleCount: "Eligible Books", .nextRun: "Next Run",
        .opfQueue: "OPF Save Queue", .merge: "Merge", .categoryGovernanceTitle: "Category Governance", .author: "Authors",
        .tag: "Tags", .series: "Series", .selectedCount: "Selected", .aliases: "Aliases",
        .workCount: "Works", .deleteCategory: "Delete Category", .mergeCategoriesTitle: "Merge Categories",
        .targetCategory: "Target Category", .confirmMerge: "Confirm Merge", .renameCategory: "Rename Category",
        .newCategoryName: "New Name", .confirmRename: "Rename", .operationHistory: "Operation History",
        .undoOperation: "Undo Operation", .undoOperationMessage: "Undo this library operation?",
        .providersTitle: "Metadata Providers",
        .provider: "Providers", .queryPipeline: "Query Pipeline", .editPriority: "Edit Priority",
        .autoMatching: "Automatic Matching", .confidenceThreshold: "Confidence Threshold",
        .autoApply: "Automatically Apply High Confidence Results", .testProviders: "Test Providers",
        .saveConfiguration: "Save Configuration", .providerConfigurationTitle: "Provider Configuration",
        .apiBaseURL: "API Base URL", .apiKey: "API Key", .keepSecretHint: "Configured; leave blank to keep unchanged",
        .countryRegion: "Country/Region", .languageCode: "Language", .rateLimit: "Automatic Recognition Rate",
        .connectionTest: "Connection Test", .saveAndTest: "Save and Test", .connected: "Connected",
        .responseTime: "Response Time", .opdsTitle: "OPDS", .opdsEnabled: "Enable OPDS Service",
        .serviceStatus: "Service Status", .running: "Running", .stopped: "Stopped",
        .publicBaseURL: "Public Base URL", .catalogURL: "Generated Catalog URL (Read Only)",
        .opdsInstructions: "Add the catalog URL to an OPDS 1.2 compatible reader. The client will discover and sync library content.",
        .copy: "Copy", .copied: "Copied", .disableOPDSTitle: "Disable OPDS service?",
        .disableOPDSMessage: "All OPDS catalog addresses will stop serving immediately.", .disableService: "Disable Service",
        .backupsTitle: "Data & Backups", .createBackup: "Create Backup", .backupDirectory: "Server Backup Directory",
        .downloadFile: "Download to Files", .restoreBackup: "Restore This Backup", .deleteBackup: "Delete Backup",
        .restoreWarning: "Restoring overwrites metadata, tags, progress, and library-root settings. Original book files are not affected.",
        .restoreConfirmation: "Enter RESTORE to continue", .enterRestore: "Enter RESTORE", .restore: "Restore Backup",
        .deleteBackupTitle: "Delete this backup?", .deleteBackupMessage: "The backup archive will be permanently removed.",
        .backupWorkCount: "Works", .backupProgressCount: "Progress Records", .backupDirectoryCount: "Directories",
        .workOrderTitle: "Work Detail Order", .workOrderHint: "Media sections without content are hidden automatically.",
        .restoreDefault: "Restore Default", .saveOrder: "Save Order", .overview: "Overview", .ebook: "Ebook",
        .comic: "Comic", .audiobook: "Audiobook", .chaptersContent: "Chapters & Content",
        .healthTitle: "System Health", .lastChecked: "Last Checked", .runHealthCheck: "Run Health Check",
        .restartImportQueue: "Safely Restart Import Queue", .restartQueueTitle: "Safely restart the import queue?",
        .restartQueueMessage: "Running import tasks will finish before the queue restarts. Keep this page open until completion.",
        .safeRestart: "Safe Restart", .waitForCurrentImports: "Waiting for current imports",
        .directoryDatabase: "Directories & Database", .backgroundQueues: "Background Queues",
        .featureConfiguration: "Feature Configuration", .healthy: "Healthy", .warning: "Warning", .checking: "Checking",
        .logsTitle: "System Logs", .searchLogs: "Search summary, action, or related object", .allLevels: "All Levels",
        .allSources: "All Sources", .recentSevenDays: "Last 7 Days", .logCapacity: "Log Capacity",
        .manageLogs: "Manage Logs", .exportFiltered: "Export Filtered Results",
        .clearInformationWarning: "Clear Information & Warnings", .saveCapacity: "Save Capacity",
        .capacityMegabytes: "Capacity Limit (MB)", .clearLogsTitle: "Clear all management logs?",
        .clearLogsMessage: "All management event records will be permanently removed.", .clearAllLogs: "Clear All Logs", .information: "Information",
        .aboutTitle: "About Ermao Library", .appVersion: "App Version", .serverVersion: "Server Version",
        .compatibility: "Compatibility", .compatible: "Compatible", .supportedFormats: "Supported Formats",
        .openSourceLicense: "Open-source License", .operationMode: "Operation Mode", .selfHosted: "Self-hosted Reading & Library Management",
        .releaseHistory: "Release History", .projectAddress: "Project Address", .share: "Share",
        .authorizationRequired: "Your session has expired. Sign in again to continue.",
        .permissionDenied: "You do not have permission to perform this action.",
        .conflict: "The server state changed. Refresh and try again.",
        .temporarilyUnavailable: "The service is temporarily unavailable.", .invalidInput: "Check the highlighted fields.",
        .requestFailed: "The request could not be completed.", .noResults: "No matching results",
        .destructiveCannotUndo: "This action cannot be undone."
    ]

    private static let chinese: [AdministrativeCopyKey: String] = Dictionary(
        uniqueKeysWithValues: english.map { key, value in
            (key, chineseOverrides[key] ?? value)
        }
    )

    private static let chineseOverrides: [AdministrativeCopyKey: String] = [
        .managementTitle: "管理", .librarySection: "书库", .organizeSection: "整理", .serviceSection: "服务",
        .systemSection: "系统", .librarySources: "书库来源", .importTasks: "导入任务", .importPreferences: "导入偏好",
        .organizeQueue: "智能整理", .metadataProviders: "元数据提供者",
        .usersPermissions: "用户与权限", .emailKindle: "邮件与 Kindle", .kindleQueue: "Kindle 发送队列",
        .opds: "OPDS", .backups: "数据与备份", .workDetailOrder: "作品详情顺序", .systemHealth: "系统健康",
        .systemLogs: "系统日志", .enhancedAbout: "关于二毛图书", .loading: "正在加载…", .retry: "重试",
        .save: "保存", .saved: "已保存", .cancel: "取消", .delete: "删除", .remove: "移除", .add: "新增",
        .edit: "编辑", .done: "完成", .close: "关闭", .all: "全部", .active: "进行中", .failed: "失败",
        .completed: "已完成", .enabled: "已启用", .disabled: "已停用", .available: "可用", .unavailable: "不可用",
        .search: "搜索", .empty: "暂无内容", .unknown: "未知", .test: "测试", .testing: "测试中…",
        .refresh: "刷新", .rescan: "重新扫描", .clearCompleted: "清理已完成", .kindleTab: "Kindle", .smtpTab: "SMTP",
        .kindleRecipient: "Kindle 接收地址", .kindleSendEnabled: "启用发送到 Kindle", .kindleFormat: "文件格式",
        .subjectTemplate: "主题模板", .smtpEnabled: "启用 SMTP", .smtpHost: "SMTP 主机", .smtpPort: "端口",
        .smtpEncryption: "加密方式", .senderEmail: "发件邮箱", .username: "用户名", .password: "密码",
        .senderName: "发件人名称", .maximumAttachment: "最大附件（MB）",
        .passwordConfigured: "已配置，留空不修改", .sendTestEmail: "发送测试邮件", .smtpTestSucceeded: "测试邮件已发送",
        .saveKindle: "保存 Kindle 设置", .saveSMTP: "保存 SMTP 设置", .kindleQueueTitle: "Kindle 发送队列",
        .sending: "发送中", .sent: "已发送", .queued: "排队中", .taskCancel: "取消任务", .taskRetry: "重试任务",
        .taskDelete: "删除任务", .deleteKindleTitle: "删除此发送任务？", .deleteKindleMessage: "删除后将无法恢复。",
        .usersTitle: "用户与权限", .newUser: "新增", .displayName: "显示名称", .email: "邮箱", .role: "角色",
        .member: "成员", .administrator: "管理员", .accountStatus: "账户状态", .enableAccount: "启用账户",
        .disableAccount: "停用账户", .deleteUser: "删除用户", .editUser: "编辑用户", .accessScope: "访问范围",
        .resetPassword: "重置密码", .newPassword: "新密码", .confirmPassword: "确认新密码",
        .resetAndRequireLogin: "重置并要求重新登录", .deleteUserTitle: "删除此用户？",
        .deleteUserMessage: "账户将立即失去访问权限；私有数据按服务器策略处理。", .allLibraries: "全部书库",
        .manageSystemPermission: "管理系统设置", .accountLanguage: "账户语言",
        .manualImports: "手工导入内容", .selectedDirectories: "已选目录", .saveAccess: "保存访问范围",
        .accessHint: "用户只能浏览和阅读所选范围内的内容。", .sourcesTitle: "书库来源", .storageLocation: "存储位置",
        .availableSpace: "可用空间", .libraries: "书库", .browseDirectory: "浏览服务器目录",
        .scanDirectory: "扫描指定目录", .sourceName: "显示名称", .serverPath: "服务器路径", .scanningEnabled: "启用扫描",
        .scanInterval: "扫描间隔", .mediaTypes: "媒体类型", .organizationMode: "组织方式",
        .flatLayout: "平铺", .volumesLayout: "卷册", .audiobookLayout: "有声书", .includeSubdirectories: "包含子目录",
        .autoImportNewFiles: "自动导入新文件", .deleteSource: "删除此来源", .deleteSourceTitle: "删除此书库来源？",
        .deleteSourceMessage: "将移除此书库根目录配置，并停止后续扫描，但不会删除原始书籍文件。",
        .selectServerDirectory: "选择服务器目录", .parentDirectory: "上级目录", .chooseDirectory: "选择此目录",
        .scanning: "正在扫描", .cancelScan: "取消扫描", .lastScan: "上次扫描", .scanFileCount: "本次找到文件",
        .importTaskDetail: "导入任务详情", .importTaskLogs: "任务日志", .scanJobs: "目录扫描任务",
        .directoriesScanned: "已扫描目录", .filesScanned: "已扫描文件", .candidatesFound: "发现候选",
        .queuedCount: "已入队", .errorCount: "错误数",
        .importTasksTitle: "导入任务", .queueNormal: "队列正常", .taskSource: "来源", .taskCreated: "创建于",
        .parsing: "解析中", .pending: "待处理", .cancelled: "已取消", .deleteImportTitle: "删除此导入任务？",
        .deleteImportMessage: "任务记录将被移除。", .rescanAll: "重新扫描全部来源", .importPreferencesTitle: "导入偏好",
        .ignoreHiddenFiles: "忽略隐藏文件", .ignorePatterns: "忽略规则", .minimumFileSize: "最小文件大小",
        .sourceDescription: "说明", .allowedExtensions: "允许的扩展名",
        .fileProcessing: "文件处理", .keepSourceFiles: "保留源文件", .duplicatePolicy: "重复文件处理策略",
        .duplicateSkip: "跳过重复文件", .duplicateReplace: "替换现有文件", .duplicateKeepBoth: "保留两者",
        .preferOPF: "优先读取 OPF", .titleFromFilename: "使用文件名补全标题", .metadataSection: "元数据",
        .metadataLanguage: "语言", .automatic: "自动检测", .targetPathTemplate: "目标路径模板",
        .autoOrganize: "导入后自动整理", .resourceLimits: "资源限制", .concurrentTasks: "并发导入任务数",
        .retryLimit: "失败重试策略", .futureTasksHint: "以上设置仅对未来的导入任务生效。", .organizeTitle: "智能整理",
        .organizeRuns: "整理运行记录", .organizePending: "待处理概览", .reviewCount: "需要复核",
        .queueTab: "队列", .policyTab: "策略", .recognizeNow: "立即识别", .viewCandidates: "查看候选",
        .pauseQueue: "暂停队列", .clearOrganized: "清除已整理", .candidateTitle: "选择识别结果", .confidence: "置信度",
        .useResult: "使用此结果", .skip: "跳过", .recognitionPolicyTitle: "识别策略", .scheduledRecognition: "定时执行识别",
        .schedule: "执行周期", .runAfterImport: "新增后自动执行", .persistOPF: "元数据变化自动保存到旁车 OPF",
        .localMetadataFirst: "本地元数据优先", .metadataPriority: "元数据优先级", .recognitionScope: "识别范围",
        .recognizeUnmatched: "尚未识别的读物", .recognizeIncomplete: "缺少作者或封面", .eligibleCount: "符合规则的读物",
        .nextRun: "下次执行", .opfQueue: "OPF 保存队列", .merge: "合并",
        .categoryGovernanceTitle: "分类治理", .author: "作者", .tag: "标签", .series: "丛书",
        .selectedCount: "已选择", .aliases: "别名", .workCount: "作品", .deleteCategory: "删除分类",
        .mergeCategoriesTitle: "合并分类", .targetCategory: "目标分类", .confirmMerge: "确认合并",
        .renameCategory: "重命名分类", .newCategoryName: "新名称", .confirmRename: "重命名",
        .operationHistory: "操作历史", .undoOperation: "撤销操作", .undoOperationMessage: "撤销此书库操作？",
        .providersTitle: "元数据提供者", .provider: "提供者", .queryPipeline: "查询流水线", .editPriority: "编辑优先级",
        .autoMatching: "自动匹配", .confidenceThreshold: "置信度阈值", .autoApply: "自动应用高置信度结果",
        .testProviders: "测试提供者", .saveConfiguration: "保存配置", .providerConfigurationTitle: "提供者配置",
        .apiBaseURL: "API 地址", .apiKey: "API 密钥", .keepSecretHint: "已配置，留空不修改", .countryRegion: "国家/地区",
        .languageCode: "语言", .rateLimit: "自动识别限流", .connectionTest: "连接测试", .saveAndTest: "保存并测试",
        .connected: "连接正常", .responseTime: "响应时间", .opdsTitle: "OPDS", .opdsEnabled: "启用 OPDS 服务",
        .serviceStatus: "服务状态", .running: "运行中", .stopped: "已停止", .publicBaseURL: "服务基础地址",
        .catalogURL: "生成的目录地址（只读）", .opdsInstructions: "使用支持 OPDS 1.2 的第三方客户端或阅读器，添加上方目录地址后即可同步书库内容。",
        .copy: "复制", .copied: "已复制", .disableOPDSTitle: "关闭 OPDS 服务？",
        .disableOPDSMessage: "关闭后，所有 OPDS 目录地址将立即停止服务，第三方客户端将无法访问。", .disableService: "关闭服务",
        .backupsTitle: "数据与备份", .createBackup: "创建备份", .backupDirectory: "服务器备份目录", .downloadFile: "下载到文件",
        .restoreBackup: "恢复此备份", .deleteBackup: "删除备份",
        .restoreWarning: "恢复此备份将覆盖当前的所有元数据、标签、进度以及书库根目录设置，但不会影响原始书籍文件。",
        .restoreConfirmation: "输入 RESTORE 继续", .enterRestore: "在此输入 RESTORE", .restore: "恢复备份",
        .deleteBackupTitle: "删除此备份？", .deleteBackupMessage: "备份压缩包将被永久移除。", .backupWorkCount: "部作品",
        .backupProgressCount: "条进度", .backupDirectoryCount: "个目录", .workOrderTitle: "作品详情顺序",
        .workOrderHint: "不包含内容的媒体将自动隐藏。", .restoreDefault: "恢复默认", .saveOrder: "保存顺序",
        .overview: "简介", .ebook: "电子书", .comic: "漫画", .audiobook: "有声书", .chaptersContent: "章节与内容",
        .healthTitle: "系统健康", .lastChecked: "上次检查", .runHealthCheck: "运行健康检查",
        .restartImportQueue: "安全重启导入队列", .restartQueueTitle: "安全重启导入队列？",
        .restartQueueMessage: "当前正在进行的导入任务将完成后再重启。请勿离开此页面或锁屏，以确保队列安全重启。",
        .safeRestart: "安全重启", .waitForCurrentImports: "正在等待当前导入任务结束", .directoryDatabase: "目录与数据库",
        .backgroundQueues: "后台队列", .featureConfiguration: "功能配置", .healthy: "正常", .warning: "警告",
        .checking: "检查中", .logsTitle: "系统日志", .searchLogs: "搜索摘要、动作或关联对象", .allLevels: "全部级别",
        .allSources: "全部来源", .recentSevenDays: "近 7 天", .logCapacity: "日志容量", .manageLogs: "管理日志",
        .exportFiltered: "导出筛选结果", .clearInformationWarning: "清理信息与警告", .saveCapacity: "保存容量",
        .capacityMegabytes: "日志容量上限（MB）", .clearLogsTitle: "清空全部管理日志？",
        .clearLogsMessage: "全部管理事件记录将被永久移除。", .clearAllLogs: "清空全部日志", .information: "信息", .aboutTitle: "关于二毛图书",
        .appVersion: "App 版本", .serverVersion: "服务器版本", .compatibility: "兼容性", .compatible: "兼容",
        .supportedFormats: "支持格式", .openSourceLicense: "开源许可", .operationMode: "运行方式",
        .selfHosted: "自托管阅读与书库管理", .releaseHistory: "版本历史", .projectAddress: "项目地址", .share: "分享",
        .authorizationRequired: "登录状态已失效，请重新登录后继续。", .permissionDenied: "你没有执行此操作的权限。",
        .conflict: "服务器状态已变化，请刷新后重试。", .temporarilyUnavailable: "服务暂时不可用。",
        .invalidInput: "请检查标记的输入项。", .requestFailed: "请求未能完成。", .noResults: "没有符合条件的结果",
        .destructiveCannotUndo: "此操作无法撤销。"
    ]
}

extension AdministrativeCopyCatalog {
    func formatted(_ key: AdministrativeCopyKey, _ arguments: CVarArg...) -> String {
        String(format: self[key], locale: Locale(identifier: locale.rawValue), arguments: arguments)
    }
}
