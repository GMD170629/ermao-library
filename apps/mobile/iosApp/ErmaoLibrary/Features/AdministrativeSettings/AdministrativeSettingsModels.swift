import Foundation

enum AdministrativeSettingsRoute: Hashable, Sendable {
    case management
    case emailAndKindle
    case kindleQueue
    case users
    case userEditor(userID: String?)
    case userAccess(userID: String)
    case librarySources
    case librarySourceEditor(sourceID: String?)
    case serverDirectoryPicker(purpose: ServerDirectoryPurpose)
    case importTasks
    case importTaskDetail(taskID: String)
    case importScans
    case importPreferences
    case organizeQueue
    case organizeCandidates
    case organizeRuns
    case recognitionPolicy
    case libraryOperations
    case categoryGovernance
    case metadataProviders
    case metadataProvider(providerID: String)
    case metadataPipeline
    case opds
    case backups
    case workDetailOrder
    case health
    case logs
    case about
}

enum AdministrativeSettingsLocale: String, CaseIterable, Hashable, Sendable {
    case zhCN = "zh-CN"
    case enUS = "en-US"
}

struct AdministrativePermission: Equatable, Sendable {
    let isAdmin: Bool
    let canManageSystem: Bool

    func permits(_ route: AdministrativeSettingsRoute) -> Bool {
        switch route {
        case .users, .userEditor, .userAccess:
            isAdmin
        case .emailAndKindle, .kindleQueue, .about:
            true
        default:
            canManageSystem
        }
    }
}

enum AdministrativeFailureKind: String, Equatable, Sendable {
    case validation
    case unauthorized
    case forbidden
    case notFound
    case conflict
    case unavailable
    case transport
    case protocolViolation
}

struct AdministrativeFieldViolation: Equatable, Sendable {
    let field: String
    let code: String
}

struct AdministrativeFailure: Error, Equatable, Sendable {
    let kind: AdministrativeFailureKind
    let code: String
    let fields: [AdministrativeFieldViolation]

    init(
        kind: AdministrativeFailureKind,
        code: String,
        fields: [AdministrativeFieldViolation] = []
    ) {
        self.kind = kind
        self.code = code
        self.fields = fields
    }
}

enum AdministrativeLoadState<Value: Equatable & Sendable>: Equatable, Sendable {
    case idle
    case loading
    case loaded(Value)
    case failed(AdministrativeFailure)
}

struct AdministrativeManagementSummary: Equatable, Sendable {
    let librarySourceCount: Int
    let monitoredSourceCount: Int
    let activeImportCount: Int
    let automaticImportEnabled: Bool
    let pendingOrganizeCount: Int
    let availableProviderCount: Int
    let providerCount: Int
    let userCount: Int
    let smtpEnabled: Bool
    let failedKindleCount: Int
    let opdsRunning: Bool
    let latestBackupAt: Date?
    let healthyComponentCount: Int
    let componentCount: Int
    let logBytes: Int64
    let logLimitBytes: Int64
}

enum KindleFileFormat: String, CaseIterable, Hashable, Sendable {
    case epub = "EPUB"
    case mobi = "MOBI"
    case pdf = "PDF"
}

struct KindleSettings: Equatable, Sendable {
    var recipient: String
    var smtpConfigured: Bool
    var senderEmail: String
}

enum SMTPEncryption: String, CaseIterable, Hashable, Sendable {
    case none = "NONE"
    case startTLS = "STARTTLS"
    case tls = "TLS"
}

struct SMTPSettings: Equatable, Sendable {
    var host: String
    var port: Int
    var encryption: SMTPEncryption
    var senderEmail: String
    var username: String
    var senderName: String
    var maximumAttachmentMegabytes: Double?
    var hasPassword: Bool
    var replacementPassword: String
}

struct EmailKindleSnapshot: Equatable, Sendable {
    var kindle: KindleSettings
    var smtp: SMTPSettings?
    let canManageSMTP: Bool
}

enum KindleTaskStatus: String, CaseIterable, Hashable, Sendable {
    case queued
    case sending
    case sent
    case failed
    case cancelled
}

struct KindleSendTask: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let recipientMasked: String
    let status: KindleTaskStatus
    let progress: Double?
    let createdAt: Date
    let errorCode: String?
}

enum UserRole: String, CaseIterable, Hashable, Sendable {
    case member
    case administrator
}

struct AdministrativeUser: Identifiable, Equatable, Sendable {
    let id: String
    var displayName: String
    var email: String
    var role: UserRole
    var enabled: Bool
    var canManageSystem: Bool
    var libraryIDs: Set<String>
    var canViewManualImports: Bool
    var locale: AdministrativeSettingsLocale
}

struct UserPage: Equatable, Sendable {
    let users: [AdministrativeUser]
    let page: Int
    let pageCount: Int
    let total: Int
}

struct UserDraft: Equatable, Sendable {
    var displayName: String
    var email: String
    var role: UserRole
    var enabled: Bool
    var canManageSystem: Bool
    var locale: AdministrativeSettingsLocale
    var initialPassword: String

    static let empty = UserDraft(
        displayName: "",
        email: "",
        role: .member,
        enabled: true,
        canManageSystem: false,
        locale: .zhCN,
        initialPassword: ""
    )
}

struct UserAccessSnapshot: Equatable, Sendable {
    let user: AdministrativeUser
    let scopes: [AdministrativeLibraryScope]
}

struct AdministrativeLibraryScope: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let serverPath: String
    let workCount: Int
}

enum MonitorInterval: String, CaseIterable, Hashable, Sendable {
    case realtime
    case fiveMinutes
    case hourly
    case manual
}

enum MediaKind: String, CaseIterable, Hashable, Sendable {
    case ebook
    case comic
    case audiobook
}

enum LibraryOrganizationMode: String, CaseIterable, Hashable, Sendable {
    case flat
    case volumes
    case audiobook
}

struct LibrarySource: Identifiable, Equatable, Sendable {
    let id: String
    var displayName: String
    var serverPath: String
    var enabled: Bool
    var organizationMode: LibraryOrganizationMode
    var ignorePatterns: String
    var ignoreHidden: Bool
    var minimumFileSizeBytes: Int64
    var description: String
}

struct StorageSummary: Equatable, Sendable {
    let label: String
    let path: String
    let freeBytes: Int64?
    let totalBytes: Int64?
}

struct LibrarySourcesSnapshot: Equatable, Sendable {
    let storage: StorageSummary?
    let sources: [LibrarySource]
    let activeScan: DirectoryScanProgress?
}

enum ServerDirectoryPurpose: Hashable, Sendable {
    case createSource
    case updateSource(sourceID: String)
    case scanDirectory
}

struct ServerDirectoryEntry: Identifiable, Equatable, Sendable {
    var id: String { absolutePath }
    let name: String
    let absolutePath: String
    let modifiedAt: Date?
    let isParent: Bool
}

struct ServerDirectoryPage: Equatable, Sendable {
    let currentPath: String
    let breadcrumbs: [ServerDirectoryEntry]
    let directories: [ServerDirectoryEntry]
}

struct DirectoryScanProgress: Equatable, Sendable {
    let path: String
    let processed: Int
    let discovered: Int?
    let bytesPerSecond: Int64?
    let canCancel: Bool
}

enum ImportTaskStatus: String, CaseIterable, Hashable, Sendable {
    case pending
    case parsing
    case completed
    case failed
    case cancelled
}

struct ImportTask: Identifiable, Equatable, Sendable {
    let id: String
    let filename: String
    let sourcePath: String
    let status: ImportTaskStatus
    let progress: Double?
    let createdAt: Date
    let errorCode: String?
}

struct ImportTaskLog: Identifiable, Equatable, Sendable {
    let id: String
    let level: String
    let message: String
    let createdAt: Date?
}

struct ImportTaskDetail: Equatable, Sendable {
    let task: ImportTask
    let logs: [ImportTaskLog]
}

enum ImportScanStatus: String, Equatable, Sendable {
    case pending, running, completed, failed, cancelled
}

struct ImportScanJob: Identifiable, Equatable, Sendable {
    let id: String
    let path: String
    let status: ImportScanStatus
    let directoriesScanned: Int
    let filesScanned: Int
    let candidatesFound: Int
    let queuedCount: Int
    let errorCount: Int
    var isActive: Bool { status == .pending || status == .running }
}

enum DuplicateFilePolicy: String, CaseIterable, Hashable, Sendable {
    case skip
    case replace
    case keepBoth
}

enum MetadataLanguage: String, CaseIterable, Hashable, Sendable {
    case automatic
    case zhCN
    case enUS
    case jaJP
}

struct ImportPreferences: Equatable, Sendable {
    var stabilityCheckEnabled: Bool
    var stabilitySeconds: Double
    var allowedExtensions: [String]
    var ignorePatterns: String
}

enum OrganizeJobStatus: String, CaseIterable, Hashable, Sendable {
    case pendingRecognition
    case needsConfirmation
    case organized
    case failed
    case cancelled
}

struct OrganizeJob: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let subtitle: String?
    let status: OrganizeJobStatus
    let errorCode: String?
}

struct OrganizeRun: Identifiable, Equatable, Sendable {
    let id: String
    let status: String
    let queuedCount: Int
    let completedCount: Int
    let reviewCount: Int
    let failedCount: Int
    let startedAt: Date?
    let finishedAt: Date?
}

struct RecognitionCandidate: Identifiable, Equatable, Sendable {
    let id: String
    let title: String
    let author: String?
    let confidence: Double
}

enum RecognitionSchedule: String, CaseIterable, Hashable, Sendable {
    case hourly
    case sixHours
    case daily
    case manual
}

enum MetadataPriority: String, CaseIterable, Hashable, Sendable {
    case opf
    case embedded
    case pathAndFilename
}

struct RecognitionPolicy: Equatable, Sendable {
    var scheduled: Bool
    var schedule: RecognitionSchedule
    var runAfterImport: Bool
    var persistToOPF: Bool
    var localMetadataFirst: Bool
    var priorities: [MetadataPriority]
    var recognizeUnmatched: Bool
    var recognizeMissingAuthorOrCover: Bool
    let eligibleCount: Int
    let nextRunAt: Date?
    let opfQueueCompleted: Int
    let opfQueueTotal: Int
}

struct LibraryOperation: Identifiable, Equatable, Sendable {
    let id: String
    let action: String
    let status: String
    let summary: String
    let createdAt: Date?
    let undoAvailable: Bool
}

enum CategoryKind: String, CaseIterable, Hashable, Sendable {
    case author
    case tag
    case series
}

struct GovernedCategory: Identifiable, Equatable, Sendable {
    let id: String
    let kind: CategoryKind
    let name: String
    let aliases: [String]
    let workCount: Int
}

struct MergeCategoryRequest: Equatable, Sendable {
    let kind: CategoryKind
    let sourceIDs: Set<String>
    let targetID: String
}

enum MetadataProviderStatus: String, Hashable, Sendable {
    case available
    case unavailable
    case untested
}

struct MetadataProvider: Identifiable, Equatable, Sendable {
    let id: String
    let displayName: String
    var enabled: Bool
    let status: MetadataProviderStatus
    let responseMilliseconds: Int?
    let supportedMediaKinds: Set<MediaKind>
    let hasSecret: Bool
    let priority: Int
}

struct MetadataProviderConfiguration: Equatable, Sendable {
    let provider: MetadataProvider
    var values: [String: ProviderEditableValue]
    var secretReplacements: [String: String]
    var clearedSecretKeys: Set<String>
}

enum ProviderEditableValue: Equatable, Sendable {
    case text(String)
    case toggle(Bool)
    case integer(Int64)
    case decimal(Double)
    case textList([String])
    case empty
}

enum MetadataPipelineStage: String, CaseIterable, Hashable, Sendable {
    case isbn
    case titleAndAuthor
    case fileMetadata
}

struct MetadataPipeline: Equatable, Sendable {
    var mediaKind: MediaKind
    var providerIDs: [String]
    var enabledProviderIDs: Set<String>
}

struct OPDSConfiguration: Equatable, Sendable {
    var enabled: Bool
    var publicBaseURL: String
    let catalogURL: String?
    let running: Bool
}

struct BackupRecord: Identifiable, Equatable, Sendable {
    let id: String
    let filename: String
    let kind: String
    let sizeBytes: Int64
    let createdAt: Date
    let workCount: Int
    let progressCount: Int
    let directoryCount: Int
}

enum AdministrativeWorkDetailSection: String, CaseIterable, Hashable, Sendable {
    case ebook
    case comic
    case audiobook
    case chaptersAndContent
}

enum HealthStatus: String, Hashable, Sendable {
    case healthy
    case warning
    case failed
    case checking
}

struct HealthComponent: Identifiable, Equatable, Sendable {
    let id: String
    let name: String
    let group: String
    let status: HealthStatus
    let detail: String?
}

struct SystemHealthSnapshot: Equatable, Sendable {
    let checkedAt: Date?
    let components: [HealthComponent]
    let queueRestartInProgress: Bool
    let queueRestartStatus: String?
}

enum LogLevel: String, CaseIterable, Hashable, Sendable {
    case information
    case warning
    case error
}

struct ManagementLogEvent: Identifiable, Equatable, Sendable {
    let id: String
    let timestamp: Date
    let level: LogLevel
    let source: String
    let summary: String
    let correlationID: String?
    let target: String?
}

struct LogFilter: Equatable, Sendable {
    var query: String
    var levels: Set<LogLevel>
    var source: String?
    var since: Date?
}

struct LogPage: Equatable, Sendable {
    let events: [ManagementLogEvent]
    let usedBytes: Int64
    let limitBytes: Int64
}

struct LogSettings: Equatable, Sendable {
    var limitMegabytes: Int
}

struct AdministrativeExportFile: Equatable, Sendable {
    let data: Data
    let filename: String
}

struct AdministrativeDirectorySelection: Equatable, Sendable {
    let purpose: ServerDirectoryPurpose
    let path: String
}

struct AdministrativeAbout: Equatable, Sendable {
    let appVersion: String
    let appBuild: String
    let serverVersion: String
    let supportedFormats: [String]
    let license: String
    let repositoryURL: URL?
    let releases: [AdministrativeRelease]
}

struct AdministrativeAppIdentity: Equatable, Sendable {
    let version: String
    let build: String
    let supportedFormats: [String]
    let license: String
    let repositoryURL: URL?
    let releases: [AdministrativeRelease]

    static func current(
        bundle: Bundle = .main,
        supportedFormats: [String] = ["EPUB", "Comic", "PDF", "Text", "Audiobook"],
        license: String = "MIT License",
        repositoryURL: URL? = URL(string: "https://github.com/GMD170629/ermao-library"),
        releases: [AdministrativeRelease] = []
    ) -> AdministrativeAppIdentity {
        AdministrativeAppIdentity(
            version: bundle.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "—",
            build: bundle.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "—",
            supportedFormats: supportedFormats,
            license: license,
            repositoryURL: repositoryURL,
            releases: releases
        )
    }
}

struct AdministrativeRelease: Identifiable, Equatable, Sendable {
    var id: String { version }
    let version: String
    let date: Date?
    let notes: String
}
