import SwiftUI
@preconcurrency import ErmaoShared

struct AppRootView: View {
    @ObservedObject var store: SessionStore
    let contentClient: any ContentClient
    let contentCache: LibraryCacheStore
    let settingsRepository: (any ErmaoShared.PersonalSettingsRepository)?
    let administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)?
    let settingsClientOverride: (any SettingsClient)?
    let readerComposition: IosReaderComposition?
    @Environment(\.colorScheme) private var colorScheme

    init(
        store: SessionStore,
        contentClient: any ContentClient = ContentCompositionRoot.makeClient(),
        contentCache: LibraryCacheStore = LibraryCacheStore(),
        settingsRepository: (any ErmaoShared.PersonalSettingsRepository)? = nil,
        administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)? = nil,
        settingsClientOverride: (any SettingsClient)? = nil,
        readerComposition: IosReaderComposition? = nil
    ) {
        self.store = store
        self.contentClient = contentClient
        self.contentCache = contentCache
        self.settingsRepository = settingsRepository
        self.administrativeSettingsRepository = administrativeSettingsRepository
        self.settingsClientOverride = settingsClientOverride
        self.readerComposition = readerComposition
    }

    var body: some View {
        rootContent
            .environment(\.appTheme, AppTheme.app(for: colorScheme))
            .environment(\.locale, activeLocale)
            .tint(AppTheme.app(for: colorScheme).actionAccent)
            .appCanvas()
            .alert(
                infrastructureErrorTitle,
                isPresented: Binding(
                    get: { store.isPresentingInfrastructureError },
                    set: { isPresented in
                        if !isPresented {
                            store.dismissInfrastructureError()
                        }
                    }
                )
            ) {
                Button("common.ok", role: .cancel) {
                    store.dismissInfrastructureError()
                }
            } message: {
                Text(infrastructureErrorMessage)
            }
    }

    private var activeLocale: Locale {
        guard [.authenticated, .offlineGrace].contains(store.snapshot.phase) else {
            return .autoupdatingCurrent
        }
        switch store.snapshot.userLocale {
        case "zh-CN": return Locale(identifier: "zh-Hans-CN")
        case "en-US": return Locale(identifier: "en-US")
        default: return .autoupdatingCurrent
        }
    }

    private var infrastructureErrorTitle: LocalizedStringKey {
        store.operationErrorCode == "CREDENTIAL_STORAGE_FAILED"
            ? "auth.credentials.storageFailed.title"
            : "common.operationFailed.title"
    }

    private var infrastructureErrorMessage: LocalizedStringKey {
        store.operationErrorCode == "CREDENTIAL_STORAGE_FAILED"
            ? "auth.credentials.storageFailed.message"
            : "common.operationFailed"
    }

    @ViewBuilder
    private var rootContent: some View {
        if store.isSelectingServer {
            LoginView(store: store, canCancel: true)
        } else {
            switch store.snapshot.phase {
            case .noServer, .checkingServer, .serverConnectionFailed, .tlsRisk, .incompatibleServer:
                LoginView(store: store)
            case .setupRequired, .settingUp, .setupFailed:
                SetupRequiredView(store: store)
            case .signedOut:
                LoginView(store: store)
            case .authenticating, .loginFailed:
                if store.isReauthenticating {
                    ReauthenticateView(
                        store: store,
                        serverUnavailable: store.reauthenticationServerUnavailable
                    )
                } else {
                    LoginView(store: store)
                }
            case .sessionExpired:
                ReauthenticateView(store: store, serverUnavailable: false)
            case .accountDisabled:
                AccountDisabledView(store: store)
            case .sessionUnavailable:
                ReauthenticateView(store: store, serverUnavailable: true)
            case .authenticated:
                if settingsRepository != nil || settingsClientOverride != nil {
                    AuthenticatedShellHost(
                        store: store,
                        contentClient: contentClient,
                        cache: contentCache,
                        settingsRepository: settingsRepository,
                        administrativeSettingsRepository: administrativeSettingsRepository,
                        settingsClientOverride: settingsClientOverride,
                        readerComposition: readerComposition
                    )
                    .id(authenticatedShellIdentity)
                } else {
                    MainTabView(
                        store: store,
                        contentClient: contentClient,
                        cache: contentCache,
                        readerComposition: readerComposition
                    )
                    .id(authenticatedShellIdentity)
                }
            case .offlineGrace:
                OfflineShellView(store: store)
                    .id(store.navigationGeneration)
            }
        }
    }

    private var authenticatedShellIdentity: String {
        let authorizationVersion = store.snapshot.authorization?.authorizationVersion ?? 0
        return [
            String(store.navigationGeneration),
            store.snapshot.profile?.serverIdentity ?? "",
            store.snapshot.userID ?? "",
            String(authorizationVersion),
            store.snapshot.userLocale ?? "",
        ].joined(separator: "|")
    }
}

private struct AuthenticatedShellHost: View {
    @ObservedObject var store: SessionStore
    let contentClient: any ContentClient
    let cache: LibraryCacheStore
    let administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)?
    let readerComposition: IosReaderComposition?
    @StateObject private var settingsViewModel: SettingsViewModel
    @State private var administrativeSettingsStore: AdministrativeSettingsStore?

    @MainActor
    init(
        store: SessionStore,
        contentClient: any ContentClient,
        cache: LibraryCacheStore,
        settingsRepository: (any ErmaoShared.PersonalSettingsRepository)?,
        administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)?,
        settingsClientOverride: (any SettingsClient)?,
        readerComposition: IosReaderComposition?
    ) {
        self.store = store
        self.contentClient = contentClient
        self.cache = cache
        self.administrativeSettingsRepository = administrativeSettingsRepository
        self.readerComposition = readerComposition
        guard
            let profile = store.snapshot.profile,
            let userID = store.snapshot.userID,
            let displayName = store.snapshot.userDisplayName,
            let email = store.snapshot.userEmail
        else { preconditionFailure("Authenticated shell requires a complete session projection") }
        let client: any SettingsClient
        if let settingsClientOverride {
            client = settingsClientOverride
        } else {
            guard let settingsRepository else {
                preconditionFailure("Settings composition requires a client or repository")
            }
            let context = PersonalSettingsPublicKt.createPersonalSettingsContext(
                profileId: profile.id,
                displayName: profile.displayName,
                baseUrl: profile.baseURL,
                serverIdentity: profile.serverIdentity,
                acceptsInsecureTls: profile.tlsMode == .insecureSkipAllValidation
            )
            client = SharedSettingsClient(repository: settingsRepository, context: context)
        }
        _settingsViewModel = StateObject(
            wrappedValue: SettingsViewModel(
                initialSnapshot: SettingsSnapshot(
                account: SettingsAccount(
                    id: userID,
                    displayName: displayName,
                    email: email,
                    avatarURL: store.snapshot.userAvatarURL
                ),
                locale: store.snapshot.userLocale == "en-US" ? .enUS : .zhCN,
                server: SettingsServer(
                    displayName: profile.displayName,
                    baseURL: profile.baseURL,
                    serverIdentity: profile.serverIdentity,
                    version: nil
                ),
                app: .current()
                ),
                client: client,
                lifecycle: SettingsLifecycleHooks(
                    refreshSession: { await store.refreshCurrentSession() },
                    showReauthentication: { store.requireReauthentication() },
                    purgeCurrentNamespace: { try await store.purgeCurrentNamespace() },
                    logout: { try await store.logoutAwaitingCompletion(purgeNamespace: false) }
                )
            )
        )
        if let administrativeSettingsRepository,
           let authorization = store.snapshot.authorization {
            let administrativePermissions = AdministrativePermission(
                isAdmin: authorization.isAdmin,
                canManageSystem: authorization.canManageSystem
            )
            let administrativeContext = AdministrativeSettingsContractKt.createAdministrativeSettingsContext(
                profileId: profile.id,
                displayName: profile.displayName,
                baseUrl: profile.baseURL,
                serverIdentity: profile.serverIdentity,
                acceptsInsecureTls: profile.tlsMode == .insecureSkipAllValidation
            )
            let administrativeClient = SharedAdministrativeSettingsClient(
                repository: administrativeSettingsRepository,
                context: administrativeContext,
                appIdentity: .current(),
                permissions: administrativePermissions,
                serverVersionLoader: { try await client.loadServerVersion() }
            )
            _administrativeSettingsStore = State(
                initialValue: AdministrativeSettingsStore(
                    client: administrativeClient,
                    permissions: administrativePermissions,
                    locale: store.snapshot.userLocale == "en-US" ? .enUS : .zhCN,
                    onUnauthorized: { store.requireReauthentication() }
                )
            )
        } else {
            _administrativeSettingsStore = State(initialValue: nil)
        }
    }

    var body: some View {
        MainTabView(
            store: store,
            contentClient: contentClient,
            cache: cache,
            settingsViewModel: settingsViewModel,
            administrativeSettingsStore: administrativeSettingsStore,
            readerComposition: readerComposition
        )
    }
}
