import SwiftUI
import UniformTypeIdentifiers

private struct AdministrativeCopyKeyEnvironment: EnvironmentKey {
    static let defaultValue = AdministrativeCopyCatalog(locale: .enUS)
}

private struct AdministrativeNavigationEnvironment: EnvironmentKey {
    static let defaultValue: @MainActor (AdministrativeSettingsRoute) -> Void = { _ in }
}

extension EnvironmentValues {
    var administrativeCopy: AdministrativeCopyCatalog {
        get { self[AdministrativeCopyKeyEnvironment.self] }
        set { self[AdministrativeCopyKeyEnvironment.self] = newValue }
    }

    var administrativeNavigate: @MainActor (AdministrativeSettingsRoute) -> Void {
        get { self[AdministrativeNavigationEnvironment.self] }
        set { self[AdministrativeNavigationEnvironment.self] = newValue }
    }
}

extension View {
    func administrativeNavigation(
        onNavigate: @escaping @MainActor (AdministrativeSettingsRoute) -> Void
    ) -> some View {
        environment(\.administrativeNavigate, onNavigate)
    }

}

struct AdministrativeSettingsDestination: View {
    let route: AdministrativeSettingsRoute
    @ObservedObject var store: AdministrativeSettingsStore

    var body: some View {
        Group {
            switch route {
            case .emailAndKindle: EmailKindleSettingsView(store: store)
            case .kindleQueue: KindleQueueView(store: store)
            case .users: UsersSettingsView(store: store)
            case let .userEditor(userID): UserEditorView(store: store, userID: userID)
            case let .userAccess(userID): UserAccessView(store: store, userID: userID)
            case .opds: OPDSSettingsView(store: store)
            case .logs: SystemLogsView(store: store)
            case .about: AdministrativeAboutView(store: store)
            case .librarySources,
                 .librarySourceEditor,
                 .serverDirectoryPicker,
                 .importTasks,
                 .importTaskDetail,
                 .importScans,
                 .importPreferences,
                 .organizeQueue,
                 .organizeCandidates,
                 .organizeRuns,
                 .recognitionPolicy,
                 .libraryOperations,
                 .categoryGovernance,
                 .metadataProviders,
                 .metadataProvider,
                 .backups,
                 .workDetailOrder,
                 .health:
                Color.clear
                    .navigationTitle("tab.me")
            }
        }
        .settingsPageSurface()
        .environment(\.administrativeCopy, store.copy)
    }
}

struct AdministrativeStateView<Value: Equatable & Sendable, Content: View>: View {
    let state: AdministrativeLoadState<Value>
    let retry: () -> Void
    @ViewBuilder let content: (Value) -> Content

    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        switch state {
        case .idle, .loading:
            ProgressView(copy[.loading])
                .frame(maxWidth: .infinity, minHeight: 160)
        case let .loaded(value):
            content(value)
        case let .failed(failure):
            AdministrativeEmptyView(title: copy[.requestFailed], systemImage: "exclamationmark.triangle", detail: failure.code, actionTitle: copy[.retry], action: retry)
        }
    }
}

struct AdministrativeEmptyView: View {
    let title: String
    let systemImage: String
    var detail: String? = nil
    var actionTitle: String? = nil
    var action: (() -> Void)? = nil
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(spacing: .space1Half) {
            Image(systemName: systemImage).font(.largeTitle).foregroundStyle(theme.textSecondary).accessibilityHidden(true)
            Text(title).appTextStyle(.headline)
            if let detail { Text(detail).appTextStyle(.callout).foregroundStyle(theme.textSecondary).multilineTextAlignment(.center) }
            if let actionTitle, let action { Button(actionTitle, action: action).buttonStyle(.bordered) }
        }.padding(.space3).frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

struct AdministrativeNoticeView: View {
    let notice: AdministrativeNotice
    let dismiss: () -> Void

    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: .space1) {
            Image(systemName: icon)
                .foregroundStyle(color)
                .accessibilityHidden(true)
            Text(notice.message)
                .appTextStyle(.callout)
            Spacer(minLength: 0)
            Button(action: dismiss) {
                Image(systemName: "xmark")
                    .frame(minWidth: .iosMinimumTouchTarget, minHeight: .iosMinimumTouchTarget)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text("common.close"))
        }
        .padding(.horizontal, .space2)
        .background(theme.surface)
        .overlay(alignment: .top) { Divider() }
    }

    private var icon: String {
        switch notice.style { case .success: "checkmark.circle.fill"; case .error: "exclamationmark.triangle.fill"; case .information: "info.circle.fill" }
    }

    private var color: Color {
        switch notice.style { case .success: .green; case .error: .red; case .information: theme.actionAccent }
    }
}

struct AdministrativeBottomAction: View {
    let title: String
    var destructive = false
    var working = false
    var disabled = false
    let action: @MainActor () -> Void

    var body: some View {
        SettingsBottomActionBar(
            verbatim: title,
            destructive: destructive,
            working: working,
            disabled: disabled,
            action: action
        )
    }
}

struct AdministrativeToolbarAction: View {
    let title: String
    var working = false
    var disabled = false
    let action: @MainActor () -> Void

    var body: some View {
        SettingsToolbarAction(
            verbatim: title,
            working: working,
            disabled: disabled,
            action: action
        )
    }
}

struct AdministrativeStatusLabel: View {
    let title: String
    let status: AdministrativeStatus

    enum AdministrativeStatus { case good, warning, failed, neutral }

    var body: some View {
        Label(title, systemImage: icon)
            .font(.caption)
            .foregroundStyle(color)
            .accessibilityElement(children: .combine)
    }

    private var icon: String {
        switch status { case .good: "checkmark.circle.fill"; case .warning: "exclamationmark.triangle.fill"; case .failed: "xmark.circle.fill"; case .neutral: "circle.fill" }
    }

    private var color: Color {
        switch status { case .good: .green; case .warning: .orange; case .failed: .red; case .neutral: .secondary }
    }
}

struct ActivityOverlayModifier: ViewModifier {
    @ObservedObject var store: AdministrativeSettingsStore

    func body(content: Content) -> some View {
        content.safeAreaInset(edge: .bottom, spacing: 0) {
            if let notice = store.notice {
                AdministrativeNoticeView(notice: notice) { store.replaceNotice(nil) }
            }
        }
    }
}

extension View {
    func administrativeNotice(store: AdministrativeSettingsStore) -> some View {
        modifier(ActivityOverlayModifier(store: store))
    }
}

struct ActivityFileDocument: FileDocument {
    static var readableContentTypes: [UTType] { [.data] }
    let data: Data

    init(data: Data = Data()) { self.data = data }
    init(configuration: ReadConfiguration) throws { data = configuration.file.regularFileContents ?? Data() }
    func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: data) }
}

extension Date {
    func administrativeFormatted(locale: AdministrativeSettingsLocale) -> String {
        formatted(.dateTime.locale(Locale(identifier: locale.rawValue)).year().month().day().hour().minute())
    }
}

extension Int64 {
    var administrativeByteCount: String { ByteCountFormatter.string(fromByteCount: self, countStyle: .file) }
}
