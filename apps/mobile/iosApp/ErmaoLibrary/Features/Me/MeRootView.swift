import SwiftUI

struct MeRootView: View {
    @ObservedObject var viewModel: SettingsViewModel
    let onOpenRoute: @MainActor @Sendable (SettingsRoute) -> Void
    let canOpenAdministration: Bool
    let onOpenEmailAndKindle: @MainActor @Sendable () -> Void
    let onOpenKindleQueue: @MainActor @Sendable () -> Void
    let onOpenAdministration: @MainActor @Sendable () -> Void

    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        viewModel: SettingsViewModel,
        onOpenRoute: @escaping @MainActor @Sendable (SettingsRoute) -> Void,
        canOpenAdministration: Bool = false,
        onOpenEmailAndKindle: @escaping @MainActor @Sendable () -> Void = {},
        onOpenKindleQueue: @escaping @MainActor @Sendable () -> Void = {},
        onOpenAdministration: @escaping @MainActor @Sendable () -> Void = {}
    ) {
        self.viewModel = viewModel
        self.onOpenRoute = onOpenRoute
        self.canOpenAdministration = canOpenAdministration
        self.onOpenEmailAndKindle = onOpenEmailAndKindle
        self.onOpenKindleQueue = onOpenKindleQueue
        self.onOpenAdministration = onOpenAdministration
    }

    var body: some View {
        List {
            Section {
                identityHeader
                    .listRowBackground(theme.surface)
            }

            Section("me.account.section") {
                Button { onOpenRoute(.profile) } label: {
                    settingsNavigationLabel(
                        titleKey: "settings.profile.title",
                        subtitleKey: "settings.profile.subtitle",
                        systemImage: "person.crop.circle"
                    )
                }
                .buttonStyle(.plain)
                Button { onOpenRoute(.security) } label: {
                    settingsNavigationLabel(
                        titleKey: "settings.security.title",
                        subtitleKey: "settings.security.subtitle",
                        systemImage: "lock.shield"
                    )
                }
                .buttonStyle(.plain)
            }
            .listRowBackground(theme.surface)

            Section("settings.connectedServices.section") {
                Button(action: onOpenEmailAndKindle) {
                    settingsNavigationLabel(
                        titleKey: "settings.emailKindle.title",
                        subtitleKey: "settings.emailKindle.subtitle",
                        systemImage: "envelope"
                    )
                }
                .buttonStyle(.plain)
                Button(action: onOpenKindleQueue) {
                    settingsNavigationLabel(
                        titleKey: "settings.kindleQueue.title",
                        subtitleKey: "settings.kindleQueue.subtitle",
                        systemImage: "paperplane"
                    )
                }
                .buttonStyle(.plain)
            }
            .listRowBackground(theme.surface)

            if canOpenAdministration {
                Section("settings.administration.section") {
                    Button(action: onOpenAdministration) {
                        settingsNavigationLabel(
                            titleKey: "settings.administration.title",
                            subtitleKey: "settings.administration.subtitle",
                            systemImage: "gearshape.2"
                        )
                    }
                    .buttonStyle(.plain)
                }
                .listRowBackground(theme.surface)
            }

            Section("me.server.section") {
                serverIdentityRow
                    .listRowBackground(theme.surface)
            }

            Section("settings.preferences.section") {
                Button { onOpenRoute(.language) } label: {
                    HStack(spacing: .space1Half) {
                        SettingsRowLabel(
                            titleKey: "settings.language.title",
                            systemImage: "globe"
                        )
                        Spacer(minLength: .space1)
                        Text(LocalizedStringKey(viewModel.snapshot.locale.titleKey))
                            .foregroundStyle(theme.textSecondary)
                            .multilineTextAlignment(.trailing)
                        navigationChevron
                    }
                }
                .buttonStyle(.plain)
            }
            .listRowBackground(theme.surface)

            Section("settings.product.section") {
                Button { onOpenRoute(.about) } label: {
                    HStack(spacing: .space1Half) {
                        SettingsRowLabel(
                            titleKey: "settings.about.title",
                            systemImage: "info.circle"
                        )
                        Spacer(minLength: .space1)
                        navigationChevron
                    }
                }
                .buttonStyle(.plain)
            }
            .listRowBackground(theme.surface)
        }
        .listStyle(.plain)
        .settingsListSurface()
        .settingsAlert(viewModel: viewModel)
        .navigationTitle("tab.me")
        .task { await viewModel.loadIfNeeded() }
        .environment(\.locale, activeLocale)
    }

    @ViewBuilder
    private var identityHeader: some View {
        if dynamicTypeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: .space2) {
                avatar
                identityText
            }
            .padding(.vertical, .space1)
        } else {
            HStack(spacing: .space2) {
                avatar
                identityText
                Spacer(minLength: 0)
            }
            .padding(.vertical, .space1)
        }
    }

    private var avatar: some View {
        SettingsAvatarView(
            data: viewModel.avatarData,
            displayName: viewModel.snapshot.account.displayName
        )
    }

    private var identityText: some View {
        VStack(alignment: .leading, spacing: .spaceHalf) {
            Text(viewModel.snapshot.account.displayName)
                .appTextStyle(.headline)
                .foregroundStyle(theme.textPrimary)
            Text(viewModel.snapshot.account.email)
                .appTextStyle(.callout)
                .foregroundStyle(theme.textSecondary)
                .textSelection(.enabled)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(
            Text(
                String(
                    format: String(
                        localized: "settings.identity.accessibility.format",
                        locale: activeLocale
                    ),
                    locale: activeLocale,
                    viewModel.snapshot.account.displayName,
                    viewModel.snapshot.account.email
                )
            )
        )
    }

    private var serverIdentityRow: some View {
        HStack(alignment: .top, spacing: .space1Half) {
            Image(systemName: "server.rack")
                .foregroundStyle(theme.textSecondary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(viewModel.snapshot.server.displayName)
                    .foregroundStyle(theme.textPrimary)
                Text(viewModel.snapshot.server.displayAddress)
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
                    .textSelection(.enabled)
            }
            Spacer(minLength: 0)
            Text("settings.server.current")
                .appTextStyle(.caption)
                .foregroundStyle(theme.textSecondary)
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

    private var activeLocale: Locale {
        Locale(identifier: viewModel.snapshot.locale.rawValue)
    }

    private func settingsNavigationLabel(
        titleKey: String,
        subtitleKey: String,
        systemImage: String
    ) -> some View {
        HStack(alignment: .top, spacing: .space1Half) {
            Image(systemName: systemImage)
                .foregroundStyle(theme.textSecondary)
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(LocalizedStringKey(titleKey))
                    .foregroundStyle(theme.textPrimary)
                Text(LocalizedStringKey(subtitleKey))
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
            }
            Spacer(minLength: .space1)
            navigationChevron
        }
        .accessibilityElement(children: .combine)
    }

    private var navigationChevron: some View {
        Image(systemName: "chevron.forward")
            .font(.caption.weight(.semibold))
            .foregroundStyle(theme.textTertiary)
            .accessibilityHidden(true)
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
