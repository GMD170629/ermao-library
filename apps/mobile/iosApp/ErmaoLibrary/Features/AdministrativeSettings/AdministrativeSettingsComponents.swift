import SwiftUI
import UniformTypeIdentifiers

struct AdministrativeSettingsHostView: View {
    @StateObject private var store: AdministrativeSettingsStore
    @State private var path: [AdministrativeSettingsRoute] = []

    init(store: @autoclosure @escaping () -> AdministrativeSettingsStore) {
        _store = StateObject(wrappedValue: store())
    }

    var body: some View {
        NavigationStack(path: $path) {
            AdministrativeManagementView(store: store)
                .administrativeDestinations(store: store)
        }
        .administrativeNavigation { path.append($0) }
        .tint(theme.actionAccent)
        .environment(\.administrativeCopy, store.copy)
    }

    @Environment(\.appTheme) private var theme
}

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

    func administrativeDestinations(store: AdministrativeSettingsStore) -> some View {
        navigationDestination(for: AdministrativeSettingsRoute.self) { route in
            AdministrativeSettingsDestination(route: route, store: store)
        }
    }

    func administrativeListSurface() -> some View {
        modifier(AdministrativeListSurfaceModifier())
    }
}

private struct AdministrativeListSurfaceModifier: ViewModifier {
    @Environment(\.appTheme) private var theme

    func body(content: Content) -> some View {
        content
            .scrollContentBackground(.hidden)
            .background(theme.canvas)
            .tint(theme.actionAccent)
    }
}

struct AdministrativeSettingsDestination: View {
    let route: AdministrativeSettingsRoute
    @ObservedObject var store: AdministrativeSettingsStore

    @ViewBuilder var body: some View {
        switch route {
        case .management: AdministrativeManagementView(store: store)
        case .emailAndKindle: EmailKindleSettingsView(store: store)
        case .kindleQueue: KindleQueueView(store: store)
        case .users: UsersSettingsView(store: store)
        case let .userEditor(userID): UserEditorView(store: store, userID: userID)
        case let .userAccess(userID): UserAccessView(store: store, userID: userID)
        case .librarySources: LibrarySourcesView(store: store)
        case let .librarySourceEditor(sourceID): LibrarySourceEditorView(store: store, sourceID: sourceID)
        case let .serverDirectoryPicker(purpose): ServerDirectoryPickerView(store: store, purpose: purpose)
        case .importTasks: ImportTasksView(store: store)
        case let .importTaskDetail(taskID): ImportTaskDetailView(store: store, taskID: taskID)
        case .importScans: ImportScansView(store: store)
        case .importPreferences: ImportPreferencesView(store: store)
        case .organizeQueue: OrganizeQueueView(store: store)
        case .organizeCandidates: RecognitionCandidatesView(store: store)
        case .organizeRuns: OrganizeRunsView(store: store)
        case .recognitionPolicy: RecognitionPolicyView(store: store)
        case .libraryOperations: LibraryOperationsView(store: store)
        case .categoryGovernance: CategoryGovernanceView(store: store)
        case .metadataProviders: MetadataProvidersView(store: store)
        case let .metadataProvider(providerID): MetadataProviderDetailView(store: store, providerID: providerID)
        case .opds: OPDSSettingsView(store: store)
        case .backups: BackupsView(store: store)
        case .workDetailOrder: WorkDetailOrderView(store: store)
        case .health: SystemHealthView(store: store)
        case .logs: SystemLogsView(store: store)
        case .about: AdministrativeAboutView(store: store)
        }
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
    let action: () -> Void

    @Environment(\.appTheme) private var theme

    var body: some View {
        Button(action: action) {
            ZStack {
                Text(title).appTextStyle(.button).opacity(working ? 0 : 1)
                if working { ProgressView().tint(theme.onAction) }
            }
            .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
        }
        .buttonStyle(.borderedProminent)
        .tint(destructive ? .red : theme.actionAccent)
        .disabled(disabled || working)
        .padding(.horizontal, .space2)
        .padding(.vertical, .space1)
        .background(theme.canvas)
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
