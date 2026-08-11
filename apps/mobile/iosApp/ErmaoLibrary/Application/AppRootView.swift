import SwiftUI

struct AppRootView: View {
    @ObservedObject var store: SessionStore
    @Environment(\.colorScheme) private var colorScheme

    var body: some View {
        rootContent
            .environment(\.appTheme, AppTheme.app(for: colorScheme))
            .tint(AppTheme.app(for: colorScheme).actionAccent)
            .appCanvas()
            .alert(
                "common.operationFailed.title",
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
                Text("common.operationFailed")
            }
    }

    @ViewBuilder
    private var rootContent: some View {
        if store.isSelectingServer {
            ServerFlowView(store: store, mode: .selection)
        } else {
            switch store.snapshot.phase {
            case .noServer, .checkingServer, .serverConnectionFailed, .tlsRisk, .incompatibleServer:
                ServerFlowView(store: store, mode: .gate)
            case .setupRequired, .settingUp, .setupFailed:
                SetupRequiredView(store: store)
            case .signedOut, .authenticating, .loginFailed:
                LoginView(store: store)
            case .sessionExpired:
                ReauthenticateView(store: store, serverUnavailable: false)
            case .accountDisabled:
                AccountDisabledView(store: store)
            case .sessionUnavailable:
                ReauthenticateView(store: store, serverUnavailable: true)
            case .authenticated:
                MainTabView(store: store)
                    .id(store.navigationGeneration)
            case .offlineGrace:
                OfflineShellView(store: store)
                    .id(store.navigationGeneration)
            }
        }
    }
}
