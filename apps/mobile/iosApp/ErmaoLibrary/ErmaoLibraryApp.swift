import SwiftUI
import UIKit
@preconcurrency import ErmaoShared

@main
@MainActor
struct ErmaoLibraryApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var sessionStore: SessionStore
    @StateObject private var downloadCenter: DownloadCenterStore
    private let contentClient: any ContentClient
    private let shelfClient: any ShelfClient
    private let coverCache: AuthenticatedCoverCache
    private let settingsRepository: (any ErmaoShared.PersonalSettingsRepository)?
    private let administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)?
    private let workManagementRepository: (any ErmaoShared.WorkManagementRepository)?
    private let settingsClientOverride: (any SettingsClient)?
    private let readerComposition: IosReaderComposition?

    init() {
        let usesContentFixture = ProcessInfo.processInfo.environment[
            ContentUITestFixture.launchEnvironmentKey
        ] == "1"
        let cookieStore = KeychainCookiePayloadStore()
        let managedDownloads = ManagedDownloadStore()
        let readerPrivateContentCache = IosReaderPrivateContentCache()
        let runtime: any MobileRuntimeClient = usesContentFixture
            ? ContentUITestFixture.makeRuntime()
            : AppCompositionRoot.makeRuntimeClient(cookieStore: cookieStore)
        let coverCache = AuthenticatedCoverCache()
        let downloadTransfer: any ManagedDownloadTransferring = usesContentFixture
            ? UnavailableManagedDownloadTransfer()
            : SharedManagedDownloadTransfer(cookieStore: cookieStore)
        let downloadCenter = DownloadCenterStore(repository: managedDownloads, transfer: downloadTransfer)
        let readerContentClient: any ContentClient = usesContentFixture
            ? ContentUITestFixture.makeContentClient()
            : ContentCompositionRoot.makeClient(cookieStore: cookieStore)
        contentClient = readerContentClient
        let readerComposition = usesContentFixture ? nil : try? IosReaderComposition(
            cookieStore: cookieStore, completedDownloads: managedDownloads, downloads: downloadCenter,
            contentClient: readerContentClient, coverCache: coverCache
        )
        self.readerComposition = readerComposition
        shelfClient = usesContentFixture
            ? ContentUITestFixture.makeShelfClient()
            : ShelfCompositionRoot.makeClient(cookieStore: cookieStore)
        settingsRepository = usesContentFixture
            ? nil
            : IosCompositionKt.createIosPersonalSettingsRepository(cookieStore: cookieStore)
        administrativeSettingsRepository = usesContentFixture
            ? nil
            : IosCompositionKt.createIosAdministrativeSettingsRepository(cookieStore: cookieStore)
        workManagementRepository = usesContentFixture
            ? nil
            : IosCompositionKt.createIosWorkManagementRepository(cookieStore: cookieStore)
        settingsClientOverride = usesContentFixture
            ? ContentUITestFixture.makeSettingsClient()
            : nil
        self.coverCache = coverCache
        _downloadCenter = StateObject(
            wrappedValue: downloadCenter
        )
        _sessionStore = StateObject(
            wrappedValue: SessionStore(
                runtime: runtime,
                privateContentCache: CompositePrivateContentCache(
                    coverCache: coverCache,
                    downloads: managedDownloads,
                    reader: usesContentFixture ? nil : readerPrivateContentCache
                ),
                preparePrivateNamespaceTransition: {
                    await readerComposition?.closeActiveReader()
                    await downloadCenter.cancelAllTransfers()
                }
            )
        )
    }

    var body: some Scene {
        WindowGroup {
            AppRootView(
                store: sessionStore,
                contentClient: contentClient,
                shelfClient: shelfClient,
                coverCache: coverCache,
                downloads: downloadCenter,
                settingsRepository: settingsRepository,
                administrativeSettingsRepository: administrativeSettingsRepository,
                workManagementRepository: workManagementRepository,
                settingsClientOverride: settingsClientOverride,
                readerComposition: readerComposition
            )
                .task {
                    sessionStore.start()
                }
                .onChange(of: scenePhase) { phase in
                    if phase == .active {
                        sessionStore.refreshForForeground()
                    }
                }
                .onReceive(
                    NotificationCenter.default.publisher(for: UIApplication.willTerminateNotification)
                ) { _ in
                    sessionStore.close()
                }
        }
    }
}
