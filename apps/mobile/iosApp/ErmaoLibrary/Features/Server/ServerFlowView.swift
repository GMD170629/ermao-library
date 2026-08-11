import Combine
import SwiftUI

enum ServerFlowMode {
    case gate
    case selection
}

private enum ServerRoute: Hashable {
    case addOrEdit
    case detail(String)
    case tlsRisk
    case incompatible
}

struct ServerFlowView: View {
    @ObservedObject var store: SessionStore
    let mode: ServerFlowMode

    @State private var path: [ServerRoute] = []

    var body: some View {
        NavigationStack(path: $path) {
            Group {
                if store.serverProfiles.isEmpty {
                    ServerEmptyGateView(addServer: showAddServer)
                } else {
                    ServerProfilesView(
                        store: store,
                        canCancel: mode == .selection,
                        addServer: showAddServer,
                        showProfile: { path.append(.detail($0.id)) }
                    )
                }
            }
            .navigationDestination(for: ServerRoute.self) { route in
                switch route {
                case .addOrEdit:
                    AddServerView(store: store)
                case let .detail(profileID):
                    if let profile = store.serverProfiles.first(where: { $0.id == profileID }) {
                        ServerDetailView(
                            store: store,
                            profile: profile,
                            edit: {
                                store.beginEditingServer(profile)
                                path.append(.addOrEdit)
                            }
                        )
                    } else {
                        VStack(spacing: .space1) {
                            Label("server.removed.title", systemImage: "server.rack")
                                .font(.headline)
                            Text("server.removed.message")
                                .foregroundStyle(.secondary)
                        }
                        .multilineTextAlignment(.center)
                        .padding()
                    }
                case .tlsRisk:
                    TLSRiskView(store: store)
                case .incompatible:
                    IncompatibleServerView(store: store) {
                        path = []
                    }
                }
            }
        }
        .onReceive(store.$snapshot.map(\.phase).removeDuplicates()) { phase in
            synchronizePath(with: phase)
        }
    }

    private func showAddServer() {
        store.beginAddingServer()
        path.append(.addOrEdit)
    }

    private func synchronizePath(with phase: SessionPhase) {
        switch phase {
        case .checkingServer, .serverConnectionFailed:
            if path.last != .addOrEdit { path.append(.addOrEdit) }
        case .tlsRisk:
            if path.last != .tlsRisk { path.append(.tlsRisk) }
        case .incompatibleServer:
            path = [.incompatible]
        default:
            break
        }
    }
}

private struct ServerEmptyGateView: View {
    let addServer: () -> Void

    @Environment(\.appTheme) private var theme

    var body: some View {
        ScrollView {
            VStack(spacing: .space3) {
                Spacer(minLength: .space5)
                Image("BrandMark")
                    .resizable()
                    .scaledToFit()
                    .frame(width: 124, height: 124)
                    .accessibilityHidden(true)
                VStack(spacing: .space1Half) {
                    Text("server.empty.title")
                        .appTextStyle(.display)
                        .multilineTextAlignment(.center)
                    Text("server.empty.message")
                        .appTextStyle(.body)
                        .foregroundStyle(theme.textSecondary)
                        .multilineTextAlignment(.center)
                }
                VStack(alignment: .leading, spacing: .space1Half) {
                    Label("server.empty.multiple", systemImage: "server.rack")
                    Label("server.empty.singleActive", systemImage: "checkmark.circle")
                }
                .appTextStyle(.callout)
                .foregroundStyle(theme.textSecondary)
                .accessibilityElement(children: .combine)
                Spacer(minLength: .space3)
                PrimaryActionButton("server.add.action", action: addServer)
                Text("server.empty.privacy")
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textTertiary)
                    .multilineTextAlignment(.center)
            }
            .frame(maxWidth: 520)
            .padding(.horizontal, .space2)
            .padding(.bottom, .space4)
            .frame(maxWidth: .infinity)
        }
        .navigationBarBackButtonHidden(true)
        .navigationTitle("")
        .appCanvas()
    }
}

private struct ServerProfilesView: View {
    @ObservedObject var store: SessionStore
    let canCancel: Bool
    let addServer: () -> Void
    let showProfile: (RuntimeServerProfile) -> Void

    @Environment(\.appTheme) private var theme

    var body: some View {
        List {
            if let active = store.serverProfiles.first(where: \.isActive) {
                Section("server.current.section") {
                    profileButton(active)
                }
            }
            let inactive = store.serverProfiles.filter { !$0.isActive }
            if !inactive.isEmpty {
                Section("server.saved.section") {
                    ForEach(inactive) { profileButton($0) }
                }
            }
            Section {
                Button(action: addServer) {
                    Label("server.add.action", systemImage: "plus")
                }
                .foregroundStyle(theme.actionAccent)
            } footer: {
                Text("server.inactive.policy")
            }
        }
        .scrollContentBackground(.hidden)
        .background(theme.canvas)
        .navigationTitle("server.profiles.title")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if canCancel {
                ToolbarItem(placement: .cancellationAction) {
                    Button("common.cancel") { store.cancelServerSelection() }
                }
            }
        }
    }

    private func profileButton(_ profile: RuntimeServerProfile) -> some View {
        Button { showProfile(profile) } label: {
            HStack {
                VStack(alignment: .leading, spacing: .spaceHalf) {
                    Text(profile.displayName)
                        .foregroundStyle(theme.textPrimary)
                    Text(profile.baseURL)
                        .font(.caption)
                        .foregroundStyle(theme.textSecondary)
                        .lineLimit(1)
                }
                Spacer()
                if profile.isActive {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                        .accessibilityLabel(Text("server.connection.active"))
                }
                Image(systemName: "chevron.right")
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(theme.textTertiary)
                    .accessibilityHidden(true)
            }
        }
    }
}

private struct ServerDetailView: View {
    @ObservedObject var store: SessionStore
    let profile: RuntimeServerProfile
    let edit: () -> Void

    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme
    @State private var confirmation: Confirmation?

    private enum Confirmation: Identifiable, Equatable {
        case switchServer
        case removeServer

        var id: Int { self == .switchServer ? 0 : 1 }
    }

    var body: some View {
        List {
            Section {
                ServerIdentityView(profile: profile)
                LabeledContent("server.connection.status") {
                    Text(profile.isActive ? "server.connection.active" : "server.connection.inactive")
                }
                LabeledContent("server.tls.mode") {
                    Text(LocalizedStringKey(
                        profile.tlsMode == .systemTrust
                            ? "server.tls.system"
                            : "server.tls.insecure"
                    ))
                    .foregroundStyle(
                        profile.tlsMode == .systemTrust ? theme.textSecondary : Color.orange
                    )
                }
            }

            Section {
                if !profile.isActive {
                    Button("server.activate.action") { confirmation = .switchServer }
                }
                Button("server.edit.action", action: edit)
                if profile.tlsMode == .insecureSkipAllValidation {
                    Button("server.tls.restore.action") {
                        store.restoreSystemTrust(profileID: profile.id)
                    }
                }
            }

            Section {
                Button("server.delete.action", role: .destructive) {
                    confirmation = .removeServer
                }
            } footer: {
                Text("server.delete.footer")
            }
        }
        .scrollContentBackground(.hidden)
        .background(theme.canvas)
        .navigationTitle(profile.displayName)
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(
            confirmationTitle,
            isPresented: Binding(
                get: { confirmation != nil },
                set: { if !$0 { confirmation = nil } }
            ),
            titleVisibility: .visible
        ) {
            if confirmation == .switchServer {
                Button("server.activate.confirm.action") {
                    store.switchServer(profileID: profile.id)
                    dismiss()
                }
            } else if confirmation == .removeServer {
                Button("server.delete.confirm.action", role: .destructive) {
                    store.removeServer(profileID: profile.id)
                    dismiss()
                }
            }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text(confirmationMessage)
        }
    }

    private var confirmationTitle: LocalizedStringKey {
        confirmation == .removeServer ? "server.delete.confirm.title" : "server.activate.confirm.title"
    }

    private var confirmationMessage: String {
        let key = confirmation == .removeServer
            ? "server.delete.confirm.message.format"
            : "server.activate.confirm.message.format"
        return String(
            format: NSLocalizedString(key, comment: ""),
            locale: .current,
            profile.displayName
        )
    }
}
