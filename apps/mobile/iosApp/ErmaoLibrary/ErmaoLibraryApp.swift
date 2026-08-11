import SwiftUI
import UIKit

@main
@MainActor
struct ErmaoLibraryApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var sessionStore: SessionStore

    init() {
        let runtime = AppCompositionRoot.makeRuntimeClient()
        _sessionStore = StateObject(wrappedValue: SessionStore(runtime: runtime))
    }

    var body: some Scene {
        WindowGroup {
            AppRootView(store: sessionStore)
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
