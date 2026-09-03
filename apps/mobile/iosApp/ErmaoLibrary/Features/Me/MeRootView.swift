import SwiftUI
@preconcurrency import ErmaoShared

struct MeRootView: View {
    @ObservedObject var viewModel: SettingsViewModel
    @ObservedObject var administrativeStore: AdministrativeSettingsStore
    let onOpenRoute: @MainActor @Sendable (SettingsRoute) -> Void
    let onOpenDownloads: @MainActor @Sendable () -> Void
    let downloadStatus: String?
    let onOpenEmailAndKindle: @MainActor @Sendable () -> Void
    let onOpenKindleQueue: @MainActor @Sendable () -> Void
    let onOpenAdministrativeRoute: @MainActor @Sendable (AdministrativeSettingsRoute) -> Void

    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        viewModel: SettingsViewModel,
        administrativeStore: AdministrativeSettingsStore,
        onOpenRoute: @escaping @MainActor @Sendable (SettingsRoute) -> Void,
        onOpenDownloads: @escaping @MainActor @Sendable () -> Void,
        downloadStatus: String? = nil,
        onOpenEmailAndKindle: @escaping @MainActor @Sendable () -> Void,
        onOpenKindleQueue: @escaping @MainActor @Sendable () -> Void,
        onOpenAdministrativeRoute: @escaping @MainActor @Sendable (AdministrativeSettingsRoute) -> Void
    ) {
        self.viewModel = viewModel
        self.administrativeStore = administrativeStore
        self.onOpenRoute = onOpenRoute
        self.onOpenDownloads = onOpenDownloads
        self.downloadStatus = downloadStatus
        self.onOpenEmailAndKindle = onOpenEmailAndKindle
        self.onOpenKindleQueue = onOpenKindleQueue
        self.onOpenAdministrativeRoute = onOpenAdministrativeRoute
    }

    var body: some View {
        SettingsScreen("tab.me", titleDisplayMode: .large) {
            ForEach(visibleCatalogGroups, id: \.id.wireValue) { group in
                if group.id.wireValue == SettingsGroupId.preferences.wireValue {
                    SettingsSection("me.server.section") {
                        serverIdentityRow
                    }
                }

                let items = visibleItems(in: group)
                if !items.isEmpty {
                    SettingsSection(LocalizedStringKey(groupTitleKey(group.id.wireValue))) {
                        ForEach(items, id: \.wireValue) { item in
                            settingsRow(item.wireValue)
                        }
                    }
                }
            }
        }
        .settingsAlert(viewModel: viewModel)
        .task {
            administrativeStore.updateLocale(administrativeLocale)
            await viewModel.loadIfNeeded()
            guard administrativeStore.permissions.isAdmin || administrativeStore.permissions.canManageSystem else {
                return
            }
            await administrativeStore.loadSummary()
        }
        .onChange(of: viewModel.snapshot.locale) { _, _ in
            administrativeStore.updateLocale(administrativeLocale)
        }
        .environment(\.locale, activeLocale)
    }

    private var serverIdentityRow: some View {
        HStack(alignment: .center, spacing: SettingsMetrics.iconTitleSpacing) {
            SettingsIcon(systemImage: "server.rack")
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    serverIdentityText
                    Text("settings.server.current")
                        .font(.subheadline)
                        .foregroundStyle(theme.textSecondary)
                }
                Spacer(minLength: 0)
            } else {
                serverIdentityText
                Spacer(minLength: 0)
                Text("settings.server.current")
                    .font(.subheadline)
                    .foregroundStyle(theme.textSecondary)
            }
        }
        .frame(minHeight: SettingsMetrics.rowContentMinimumHeight)
        .listRowInsets(SettingsMetrics.rowInsets)
        .alignmentGuide(.listRowSeparatorLeading) { _ in
            SettingsMetrics.separatorLeading
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            Text(
                String(
                    format: String(
                        localized: "settings.server.accessibility.format",
                        locale: activeLocale
                    ),
                    locale: activeLocale,
                    viewModel.snapshot.server.displayName,
                    viewModel.snapshot.server.displayAddress
                )
            )
        )
    }

    private var serverIdentityText: some View {
        VStack(alignment: .leading, spacing: .spaceHalf) {
            Text(viewModel.snapshot.server.displayName)
                .font(.body)
                .foregroundStyle(theme.textPrimary)
            Text(viewModel.snapshot.server.displayAddress)
                .appTextStyle(.caption)
                .foregroundStyle(theme.textSecondary)
                .textSelection(.enabled)
        }
    }

    private var activeLocale: Locale {
        Locale(identifier: viewModel.snapshot.locale.rawValue)
    }

    private var administrativeCopy: AdministrativeCopyCatalog {
        AdministrativeCopyCatalog(locale: administrativeLocale)
    }

    private var administrativeLocale: AdministrativeSettingsLocale {
        viewModel.snapshot.locale == .zhCN ? .zhCN : .enUS
    }

    private var visibleCatalogGroups: [SettingsCatalogGroup] {
        SettingsCenterCatalog.shared.groups
    }

    private var visibleItemIDs: Set<String> {
        Set(
            SettingsCenterPublicKt.visibleSettingsItems(
                isAdmin: administrativeStore.permissions.isAdmin,
                canManageSystem: administrativeStore.permissions.canManageSystem
            ).map(\.wireValue)
        )
    }

    private func visibleItems(in group: SettingsCatalogGroup) -> [SettingsItemId] {
        group.itemIds.filter { visibleItemIDs.contains($0.wireValue) }
    }

    private func groupTitleKey(_ groupID: String) -> String {
        switch groupID {
        case SettingsGroupId.account.wireValue: "me.account.section"
        case SettingsGroupId.readingAndStorage.wireValue: "me.offline.section"
        case SettingsGroupId.connectedServices.wireValue: "settings.connectedServices.section"
        case SettingsGroupId.systemManagement.wireValue: "settings.administration.section"
        case SettingsGroupId.preferences.wireValue: "settings.preferences.section"
        case SettingsGroupId.product.wireValue: "settings.product.section"
        default: ""
        }
    }

    @ViewBuilder
    private func settingsRow(_ itemID: String) -> some View {
        switch itemID {
        case SettingsItemId.profile.wireValue:
            SettingsNavigationRow(
                "settings.profile.title",
                status: viewModel.snapshot.account.displayName,
                systemImage: "person.crop.circle"
            ) { onOpenRoute(.profile) }
        case SettingsItemId.security.wireValue:
            SettingsNavigationRow("settings.security.title", systemImage: "lock.shield") { onOpenRoute(.security) }
        case SettingsItemId.downloads.wireValue:
            SettingsNavigationRow(
                "downloads.title",
                status: downloadStatus,
                systemImage: "arrow.down.circle",
                action: onOpenDownloads
            )
        case SettingsItemId.emailKindle.wireValue:
            SettingsNavigationRow(
                "settings.emailKindle.title",
                statusKey: emailAndKindleStatusKey,
                systemImage: "envelope",
                action: onOpenEmailAndKindle
            )
        case SettingsItemId.kindleQueue.wireValue:
            SettingsNavigationRow(
                "settings.kindleQueue.title",
                status: kindleQueueStatus,
                systemImage: "paperplane",
                action: onOpenKindleQueue
            )
        case SettingsItemId.users.wireValue:
            administrativeRow(.usersPermissions, icon: "person.2", route: .users)
        case SettingsItemId.opds.wireValue:
            administrativeRow(.opds, icon: "network", route: .opds)
        case SettingsItemId.logs.wireValue:
            administrativeRow(.systemLogs, icon: "doc.text", route: .logs)
        case SettingsItemId.language.wireValue:
            SettingsNavigationRow(
                "settings.language.title",
                statusKey: LocalizedStringKey(viewModel.snapshot.locale.titleKey),
                systemImage: "globe"
            ) { onOpenRoute(.language) }
        case SettingsItemId.about.wireValue:
            SettingsNavigationRow(
                "settings.about.title",
                status: "v\(viewModel.snapshot.app.version)",
                systemImage: "info.circle"
            ) { onOpenAdministrativeRoute(.about) }
        default:
            EmptyView()
        }
    }

    private var emailAndKindleStatusKey: LocalizedStringKey? {
        guard case let .loaded(summary) = administrativeStore.summary, summary.smtpEnabled else {
            return nil
        }
        return "settings.status.configured"
    }

    private var kindleQueueStatus: String? {
        guard case let .loaded(summary) = administrativeStore.summary, summary.failedKindleCount > 0 else {
            return nil
        }
        return String(summary.failedKindleCount)
    }

    private func administrativeRow(
        _ title: AdministrativeCopyKey,
        icon: String,
        route: AdministrativeSettingsRoute
    ) -> some View {
        SettingsNavigationRow(
            verbatim: administrativeCopy[title],
            systemImage: icon
        ) {
            onOpenAdministrativeRoute(route)
        }
    }
}

struct SettingsDestinationView: View {
    let route: SettingsRoute
    @ObservedObject var viewModel: SettingsViewModel

    init(route: SettingsRoute, viewModel: SettingsViewModel) {
        self.route = route
        self.viewModel = viewModel
    }

    var body: some View {
        Group {
            switch route {
            case .profile:
                ProfileSettingsView(viewModel: viewModel)
            case .security:
                SecuritySettingsView(viewModel: viewModel)
            case .language:
                LanguageSettingsView(viewModel: viewModel)
            case .about:
                AboutSettingsView(viewModel: viewModel)
            }
        }
        .environment(\.locale, Locale(identifier: viewModel.snapshot.locale.rawValue))
    }
}
