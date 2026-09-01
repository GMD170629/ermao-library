import SwiftUI
@preconcurrency import ErmaoShared

struct AppRootView: View {
    @ObservedObject var store: SessionStore
    @ObservedObject var audioRuntime: AudioPlaybackRuntime
    let contentClient: any ContentClient
    let shelfClient: any ShelfClient
    let coverCache: AuthenticatedCoverCache
    @ObservedObject var downloads: DownloadCenterStore
    let settingsRepository: (any ErmaoShared.PersonalSettingsRepository)?
    let administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)?
    let workManagementRepository: (any ErmaoShared.WorkManagementRepository)?
    let settingsClientOverride: (any SettingsClient)?
    let readerComposition: IosReaderComposition?
    @Environment(\.colorScheme) private var colorScheme

    init(
        store: SessionStore,
        audioRuntime: AudioPlaybackRuntime = AudioCompositionRoot.makeRuntime(),
        contentClient: any ContentClient = ContentCompositionRoot.makeClient(),
        shelfClient: any ShelfClient = ShelfCompositionRoot.makeClient(),
        coverCache: AuthenticatedCoverCache = AuthenticatedCoverCache(),
        downloads: DownloadCenterStore = DownloadCenterStore(),
        settingsRepository: (any ErmaoShared.PersonalSettingsRepository)? = nil,
        administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)? = nil,
        workManagementRepository: (any ErmaoShared.WorkManagementRepository)? = nil,
        settingsClientOverride: (any SettingsClient)? = nil,
        readerComposition: IosReaderComposition? = nil
    ) {
        self.store = store
        self.audioRuntime = audioRuntime
        self.contentClient = contentClient
        self.shelfClient = shelfClient
        self.coverCache = coverCache
        self.downloads = downloads
        self.settingsRepository = settingsRepository
        self.administrativeSettingsRepository = administrativeSettingsRepository
        self.workManagementRepository = workManagementRepository
        self.settingsClientOverride = settingsClientOverride
        self.readerComposition = readerComposition
    }

    var body: some View {
        AudioApplicationHost(runtime: audioRuntime) {
            rootContent
        }
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
            .onChange(of: store.snapshot.phase) { _, phase in
                audioRuntime.sessionDidChange(
                    isAuthenticated: phase == .authenticated,
                    session: audioSessionContext
                )
                if phase != .authenticated {
                    Task { await downloads.cancelAllTransfers() }
                }
            }
            .onChange(of: audioSessionContext) { _, session in
                audioRuntime.sessionDidChange(
                    isAuthenticated: store.snapshot.phase == .authenticated,
                    session: session
                )
            }
            .task {
                audioRuntime.sessionDidChange(
                    isAuthenticated: store.snapshot.phase == .authenticated,
                    session: audioSessionContext
                )
            }
            .onChange(of: audioRuntime.snapshot.recoverableError?.code) { _, code in
                if code == .unauthorized {
                    audioRuntime.pause()
                    store.requireReauthentication()
                } else if code == .networkRetryable {
                    fallbackToVerifiedLocalAudio()
                }
            }
    }

    private var activeLocale: Locale {
        guard store.snapshot.phase == .authenticated else {
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
                    ReauthenticateView(store: store)
                } else {
                    LoginView(store: store)
                }
            case .sessionExpired:
                ReauthenticateView(store: store)
            case .accountDisabled:
                AccountDisabledView(store: store)
            case .authenticated:
                if settingsRepository != nil || settingsClientOverride != nil {
                    AuthenticatedShellHost(
                        store: store,
                contentClient: contentClient,
                shelfClient: shelfClient,
                        cache: coverCache,
                        downloads: downloads,
                        settingsRepository: settingsRepository,
                        administrativeSettingsRepository: administrativeSettingsRepository,
                        workManagementRepository: workManagementRepository,
                        settingsClientOverride: settingsClientOverride,
                        readerComposition: readerComposition
                    )
                    .id(authenticatedShellIdentity)
                } else {
                    MainTabView(
                        store: store,
                        downloads: downloads,
                        contentClient: contentClient,
                        shelfClient: shelfClient,
                        cache: coverCache,
                        workManagementRepository: workManagementRepository,
                        readerComposition: readerComposition
                    )
                    .id(authenticatedShellIdentity)
                }
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

    private var audioSessionContext: IosAudioSessionContext? {
        guard
            store.snapshot.phase == .authenticated,
            let profile = store.snapshot.profile,
            let userID = store.snapshot.userID,
            let authorizationVersion = store.snapshot.authorization?.authorizationVersion
        else { return nil }
        return IosAudioSessionContext(
            profile: profile,
            userID: userID,
            authorizationVersion: authorizationVersion
        )
    }

    private func fallbackToVerifiedLocalAudio() {
        guard let session = audioSessionContext,
              let resourceID = audioRuntime.snapshot.resourceID,
              let assetID = audioRuntime.snapshot.track?.assetID,
              let record = downloads.record(for: resourceID, assetID: assetID),
              record.namespace == session.namespaceKey,
              record.verifiedSharedArtifact != nil,
              let expectedBytes = record.expectedBytes,
              expectedBytes == record.receivedBytes,
              let mimeType = record.mimeType else { return }
        let positionMillis = audioRuntime.snapshot.positionMillis
        let durationMillis = audioRuntime.snapshot.durationMillis
        Task { @MainActor in
            guard let fileURL = await downloads.localFileURL(for: record) else { return }
            audioRuntime.launchVerifiedLocalArtifact(
                namespace: session.namespaceKey,
                userID: session.userID,
                bookID: record.bookID,
                bookTitle: record.bookTitle,
                author: record.bookAuthor,
                resourceID: record.resourceID,
                resourceTitle: record.resourceTitle,
                assetID: record.assetID,
                fileURL: fileURL,
                mimeType: mimeType,
                sizeBytes: expectedBytes,
                positionMillis: positionMillis,
                durationMillis: durationMillis
            )
        }
    }
}

private struct AuthenticatedShellHost: View {
    @ObservedObject var store: SessionStore
    let contentClient: any ContentClient
    let shelfClient: any ShelfClient
    let cache: AuthenticatedCoverCache
    @ObservedObject var downloads: DownloadCenterStore
    let administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)?
    let workManagementRepository: (any ErmaoShared.WorkManagementRepository)?
    let readerComposition: IosReaderComposition?
    @StateObject private var settingsViewModel: SettingsViewModel
    @State private var administrativeSettingsStore: AdministrativeSettingsStore?

    @MainActor
    init(
        store: SessionStore,
        contentClient: any ContentClient,
        shelfClient: any ShelfClient,
        cache: AuthenticatedCoverCache,
        downloads: DownloadCenterStore,
        settingsRepository: (any ErmaoShared.PersonalSettingsRepository)?,
        administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)?,
        workManagementRepository: (any ErmaoShared.WorkManagementRepository)?,
        settingsClientOverride: (any SettingsClient)?,
        readerComposition: IosReaderComposition?
    ) {
        self.store = store
        self.contentClient = contentClient
        self.shelfClient = shelfClient
        self.cache = cache
        self.downloads = downloads
        self.administrativeSettingsRepository = administrativeSettingsRepository
        self.workManagementRepository = workManagementRepository
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
                    purgeCurrentNamespace: {
                        try await store.purgeCurrentNamespace()
                    },
                    logout: {
                        try await store.logoutAwaitingCompletion(purgeNamespace: true)
                    }
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
            downloads: downloads,
            contentClient: contentClient,
            shelfClient: shelfClient,
            cache: cache,
            settingsViewModel: settingsViewModel,
            administrativeSettingsStore: administrativeSettingsStore,
            workManagementRepository: workManagementRepository,
            readerComposition: readerComposition
        )
    }
}
