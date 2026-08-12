import SwiftUI
import UIKit
@preconcurrency import ErmaoShared

@main
@MainActor
struct ErmaoLibraryApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var sessionStore: SessionStore
    private let contentClient: any ContentClient
    private let contentCache: LibraryCacheStore
    private let settingsRepository: (any ErmaoShared.PersonalSettingsRepository)?
    private let administrativeSettingsRepository: (any ErmaoShared.AdministrativeSettingsRepository)?
    private let settingsClientOverride: (any SettingsClient)?
    private let readerComposition: IosReaderComposition?

    init() {
        let usesContentFixture = ProcessInfo.processInfo.environment[
            ContentUITestFixture.launchEnvironmentKey
        ] == "1"
        let cookieStore = KeychainCookiePayloadStore()
        readerComposition = usesContentFixture ? nil : try? IosReaderComposition(cookieStore: cookieStore)
        let runtime: any MobileRuntimeClient = usesContentFixture
            ? ContentUITestFixture.makeRuntime()
            : AppCompositionRoot.makeRuntimeClient(cookieStore: cookieStore)
        let contentCache = LibraryCacheStore()
        contentClient = usesContentFixture
            ? ContentUITestFixture.makeContentClient()
            : ContentCompositionRoot.makeClient(cookieStore: cookieStore)
        settingsRepository = usesContentFixture
            ? nil
            : IosCompositionKt.createIosPersonalSettingsRepository(cookieStore: cookieStore)
        administrativeSettingsRepository = usesContentFixture
            ? nil
            : IosCompositionKt.createIosAdministrativeSettingsRepository(cookieStore: cookieStore)
        settingsClientOverride = usesContentFixture
            ? ContentUITestFixture.makeSettingsClient()
            : nil
        self.contentCache = contentCache
        _sessionStore = StateObject(
            wrappedValue: SessionStore(runtime: runtime, privateContentCache: contentCache)
        )
    }

    var body: some Scene {
        WindowGroup {
            AppRootView(
                store: sessionStore,
                contentClient: contentClient,
                contentCache: contentCache,
                settingsRepository: settingsRepository,
                administrativeSettingsRepository: administrativeSettingsRepository,
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
