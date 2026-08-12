import SwiftUI
import UIKit

struct LoginView: View {
    @ObservedObject var store: SessionStore
    var canCancel = false

    @Environment(\.appTheme) private var theme

    @FocusState private var focusedField: Field?
    @State private var isShowingServerSwitcher = false
    @State private var presentedAlert: PresentedAlert?

    private enum Field {
        case server
        case email
        case password
    }

    private enum PresentedAlert: String, Identifiable {
        case deleteServer
        case unavailable
        case incompatible
        case insecureTLS

        var id: String { rawValue }
    }

    private var isAuthenticating: Bool {
        store.isPerformingOperation ||
            store.snapshot.phase == .checkingServer ||
            store.snapshot.phase == .authenticating
    }

    private var hasInvalidCredentials: Bool {
        store.snapshot.reasonCode == "UNAUTHORIZED" ||
            store.snapshot.reasonCode == "INVALID_CREDENTIALS" ||
            store.operationErrorCode == "UNAUTHORIZED"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: .space3) {
                    Image("BrandMark")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 88, height: 88)
                        .accessibilityHidden(true)
                    VStack(spacing: .space1) {
                        Text("auth.login.welcome")
                            .appTextStyle(.display)
                            .multilineTextAlignment(.center)
                        Text("auth.login.entry.subtitle")
                            .appTextStyle(.body)
                            .foregroundStyle(theme.textSecondary)
                            .multilineTextAlignment(.center)
                    }

                    VStack(alignment: .leading, spacing: .space3) {
                        VStack(alignment: .leading, spacing: .space1) {
                            Text("server.url.label")
                                .appTextStyle(.label)
                                .foregroundStyle(theme.textSecondary)
                            TextField("server.url.placeholder", text: $store.serverBaseURL)
                                .textContentType(.URL)
                                .keyboardType(.URL)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .focused($focusedField, equals: .server)
                                .submitLabel(.next)
                                .onSubmit { focusedField = .email }
                                .padding(.vertical, .space1)
                                .accessibilityHint(Text("auth.server.hint"))
                                .onChange(of: store.serverBaseURL) { _ in
                                    store.reconcileSelectedLoginProfileWithAddress()
                                }
                            Divider()
                            if (!store.serverBaseURL.isEmpty && !isServerAddressValid) || hasInvalidServerAddress {
                                fieldError("server.url.invalid")
                            }
                        }
                        VStack(alignment: .leading, spacing: .space1) {
                            Text("auth.email.label")
                                .appTextStyle(.label)
                                .foregroundStyle(theme.textSecondary)
                            TextField("auth.email.placeholder", text: $store.email)
                                .textContentType(.username)
                                .keyboardType(.emailAddress)
                                .textInputAutocapitalization(.never)
                                .autocorrectionDisabled()
                                .focused($focusedField, equals: .email)
                                .submitLabel(.next)
                                .onSubmit { focusedField = .password }
                                .padding(.vertical, .space1)
                            Divider()
                        }
                        VStack(alignment: .leading, spacing: .space1) {
                            Text("auth.password.label")
                                .appTextStyle(.label)
                                .foregroundStyle(theme.textSecondary)
                            SecureField("auth.password.placeholder", text: $store.password)
                                .textContentType(.password)
                                .focused($focusedField, equals: .password)
                                .submitLabel(.go)
                                .onSubmit(loginIfValid)
                                .padding(.vertical, .space1)
                            Divider()
                            if hasInvalidCredentials {
                                fieldError("auth.invalidCredentials")
                            } else if store.snapshot.phase == .loginFailed {
                                fieldError("common.requestFailed")
                            }
                        }
                    }
                    .padding(.space3)
                    .background(
                        theme.surface,
                        in: RoundedRectangle(
                            cornerRadius: CGFloat(GeneratedDesignTokens.Radii.task),
                            style: .continuous
                        )
                    )

                    PrimaryActionButton(
                        "auth.login.action",
                        isWorking: isAuthenticating,
                        isDisabled: !isFormValid,
                        action: loginIfValid
                    )

                    HStack(spacing: .space1) {
                        Button {
                            isShowingServerSwitcher = true
                        } label: {
                            Label("server.switch.action", systemImage: "arrow.triangle.2.circlepath")
                                .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(theme.actionAccent)
                        .disabled(store.otherServerLoginSummaries.isEmpty)
                        .accessibilityHint(Text("server.switch.hint"))

                        Button(role: .destructive) {
                            presentedAlert = .deleteServer
                        } label: {
                            Label("server.delete.current.action", systemImage: "trash")
                                .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                        }
                        .buttonStyle(.plain)
                        .disabled(store.selectedLoginProfile == nil)
                        .accessibilityHint(Text("server.delete.current.hint"))
                    }
                    .appTextStyle(.label)

                    if let remainingOfflineDays {
                        Button {
                            store.enterOfflineMode()
                        } label: {
                            Text(
                                String(
                                    format: NSLocalizedString("auth.offline.action.format", comment: ""),
                                    locale: .current,
                                    remainingOfflineDays
                                )
                            )
                            .frame(minHeight: .iosMinimumTouchTarget)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(theme.textSecondary)
                        .accessibilityHint(Text("auth.offline.hint"))
                    }

                    Spacer(minLength: .space3)
                    Label("auth.privateDeployment", systemImage: "lock")
                        .appTextStyle(.caption)
                        .foregroundStyle(theme.textTertiary)
                        .multilineTextAlignment(.center)
                }
                .frame(maxWidth: 520)
                .padding(.horizontal, .space3)
                .padding(.vertical, .space3)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle("auth.login.navigationTitle")
            .navigationBarTitleDisplayMode(.inline)
            .disabled(isAuthenticating)
            .toolbar {
                if canCancel {
                    ToolbarItem(placement: .cancellationAction) {
                        Button("common.cancel") { store.cancelServerSelection() }
                    }
                }
            }
            .appCanvas()
        }
        .sheet(isPresented: $isShowingServerSwitcher) {
            ServerSwitcherSheet(store: store, isPresented: $isShowingServerSwitcher)
        }
        .alert(item: $presentedAlert, content: makeAlert)
        .onAppear { presentAlert(for: store.snapshot.phase) }
        .onChange(of: store.snapshot.phase) { presentAlert(for: $0) }
    }

    private var isFormValid: Bool {
        isServerAddressValid &&
            !store.email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !store.password.isEmpty
    }

    private var isServerAddressValid: Bool {
        guard
            let components = URLComponents(
                string: store.serverBaseURL.trimmingCharacters(in: .whitespacesAndNewlines)
            ),
            let scheme = components.scheme?.lowercased(),
            scheme == "https" || scheme == "http",
            components.host?.isEmpty == false
        else { return false }
        return true
    }

    private var hasInvalidServerAddress: Bool {
        store.snapshot.reasonCode == "INVALID_ADDRESS" ||
            store.operationErrorCode == "INVALID_SERVER_ADDRESS"
    }

    private var remainingOfflineDays: Int? {
        guard
            [.sessionExpired, .sessionUnavailable].contains(store.snapshot.phase),
            let expiry = store.snapshot.entitlementExpiresAt
        else { return nil }
        let interval = expiry.timeIntervalSinceNow
        guard interval > 0 else { return nil }
        return max(1, Int(ceil(interval / 86_400)))
    }

    private func loginIfValid() {
        guard isFormValid, !isAuthenticating else { return }
        focusedField = nil
        store.loginToCurrentServer()
    }

    private func fieldError(_ key: LocalizedStringKey) -> some View {
        Label(key, systemImage: "exclamationmark.circle.fill")
            .appTextStyle(.caption)
            .foregroundStyle(.red)
            .accessibilityElement(children: .combine)
    }

    private func presentAlert(for phase: SessionPhase) {
        switch phase {
        case .serverConnectionFailed:
            presentedAlert = hasInvalidServerAddress ? nil : .unavailable
        case .incompatibleServer: presentedAlert = .incompatible
        case .tlsRisk: presentedAlert = .insecureTLS
        case .loginFailed:
            presentedAlert = nil
            if hasInvalidCredentials {
                UIAccessibility.post(
                    notification: .announcement,
                    argument: String(localized: "auth.invalidCredentials")
                )
            }
        default:
            if presentedAlert != .deleteServer { presentedAlert = nil }
        }
    }

    private func makeAlert(_ alert: PresentedAlert) -> Alert {
        switch alert {
        case .deleteServer:
            return Alert(
                title: Text("server.delete.current.confirm.title"),
                message: Text(deleteConfirmationMessage),
                primaryButton: .destructive(Text("server.delete.confirm.action")) {
                    store.deleteSelectedLoginServer()
                },
                secondaryButton: .cancel()
            )
        case .unavailable:
            return Alert(
                title: Text("server.unavailable.title"),
                message: Text("server.unavailable.message"),
                primaryButton: .default(Text("server.retry.action"), action: loginIfValid),
                secondaryButton: .cancel()
            )
        case .incompatible:
            return Alert(
                title: Text("server.incompatible.title"),
                message: Text("server.incompatible.message"),
                dismissButton: .cancel()
            )
        case .insecureTLS:
            return Alert(
                title: Text("server.tls.risk.title"),
                message: Text("server.tls.risk.message"),
                primaryButton: .destructive(Text("server.tls.accept.action")) {
                    store.loginToCurrentServer(acceptingInsecureTLS: true)
                },
                secondaryButton: .cancel()
            )
        }
    }

    private var deleteConfirmationMessage: String {
        String(
            format: String(localized: "server.delete.current.confirm.message.format"),
            locale: .current,
            store.selectedLoginProfile?.displayName ?? store.serverBaseURL
        )
    }
}

private struct ServerSwitcherSheet: View {
    @ObservedObject var store: SessionStore
    @Binding var isPresented: Bool

    @Environment(\.appTheme) private var theme

    var body: some View {
        NavigationStack {
            List(store.otherServerLoginSummaries) { summary in
                Button {
                    store.selectServerForLogin(profileID: summary.id)
                    isPresented = false
                    UIAccessibility.post(
                        notification: .announcement,
                        argument: String(
                            format: String(localized: "server.switch.selected.format"),
                            locale: .current,
                            summary.displayName
                        )
                    )
                } label: {
                    VStack(alignment: .leading, spacing: .spaceHalf) {
                        Text(summary.displayName)
                            .appTextStyle(.headline)
                            .foregroundStyle(theme.textPrimary)
                        Text(summary.accountOrAddress)
                            .appTextStyle(.caption)
                            .foregroundStyle(theme.textSecondary)
                            .lineLimit(2)
                    }
                    .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget, alignment: .leading)
                }
                .accessibilityHint(Text("server.switch.item.hint"))
            }
            .scrollContentBackground(.hidden)
            .background(theme.canvas)
            .navigationTitle("server.switch.sheet.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("common.done") { isPresented = false }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }
}

struct AccountDisabledView: View {
    @ObservedObject var store: SessionStore
    @Environment(\.appTheme) private var theme

    var body: some View {
        NavigationStack {
            VStack(spacing: .space3) {
                Image(systemName: "person.crop.circle.badge.exclamationmark")
                    .font(.largeTitle)
                    .foregroundStyle(.red)
                    .accessibilityHidden(true)
                Text("auth.accountDisabled.title")
                    .appTextStyle(.title)
                    .multilineTextAlignment(.center)
                if let profile = store.snapshot.profile {
                    ServerIdentityView(profile: profile)
                }
                if let email = store.snapshot.userEmail {
                    Text(email)
                        .appTextStyle(.body)
                        .foregroundStyle(theme.textSecondary)
                        .textSelection(.enabled)
                }
                Text("auth.accountDisabled.message")
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                Spacer(minLength: .space4)
                PrimaryActionButton("server.other.action") {
                    store.chooseAnotherServer()
                }
            }
            .frame(maxWidth: 520)
            .padding(.horizontal, .space2)
            .padding(.vertical, .space4)
            .navigationTitle("auth.accountDisabled.navigationTitle")
            .navigationBarTitleDisplayMode(.inline)
            .appCanvas()
        }
    }
}

struct ReauthenticateView: View {
    @ObservedObject var store: SessionStore
    let serverUnavailable: Bool

    @Environment(\.appTheme) private var theme
    @FocusState private var passwordFocused: Bool

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: .space3) {
                    Image(systemName: serverUnavailable ? "wifi.exclamationmark" : "lock.rotation")
                        .font(.largeTitle)
                        .foregroundStyle(serverUnavailable ? .orange : theme.brandAccent)
                        .accessibilityHidden(true)
                    Text("auth.reauthenticate.title")
                        .appTextStyle(.title)
                        .multilineTextAlignment(.center)
                    if let profile = store.snapshot.profile {
                        ServerIdentityView(profile: profile)
                    }
                    VStack(spacing: .spaceHalf) {
                        Text(
                            store.snapshot.userDisplayName ??
                                store.reauthenticationUserDisplayName ??
                                store.snapshot.userEmail ??
                                store.reauthenticationUserEmail ??
                                ""
                        )
                            .appTextStyle(.headline)
                        if let email = store.snapshot.userEmail ?? store.reauthenticationUserEmail {
                            Text(email)
                                .appTextStyle(.label)
                                .foregroundStyle(theme.textSecondary)
                                .textSelection(.enabled)
                        }
                    }
                    Text(
                        LocalizedStringKey(
                            serverUnavailable
                                ? "auth.reauthenticate.unavailable"
                                : "auth.reauthenticate.message"
                        )
                    )
                        .foregroundStyle(theme.textSecondary)
                        .multilineTextAlignment(.center)

                    VStack(alignment: .leading, spacing: .space1) {
                        Text("auth.password.label")
                            .appTextStyle(.label)
                            .foregroundStyle(theme.textSecondary)
                        SecureField("auth.password.placeholder", text: $store.password)
                            .textContentType(.password)
                            .focused($passwordFocused)
                            .submitLabel(.go)
                            .onSubmit(loginIfValid)
                            .padding(.vertical, .space1)
                        Divider()
                        if store.snapshot.reasonCode == "INVALID_CREDENTIALS" ||
                            store.operationErrorCode == "UNAUTHORIZED" {
                            Label("auth.invalidCredentials", systemImage: "exclamationmark.circle.fill")
                                .appTextStyle(.caption)
                                .foregroundStyle(.red)
                        }
                    }

                    PrimaryActionButton(
                        "auth.reauthenticate.action",
                        isWorking: store.snapshot.phase == .authenticating,
                        isDisabled: store.password.isEmpty,
                        action: loginIfValid
                    )

                    if let remainingDays {
                        Button {
                            store.enterOfflineMode()
                        } label: {
                            Text(
                                String(
                                    format: NSLocalizedString("auth.offline.action.format", comment: ""),
                                    locale: .current,
                                    remainingDays
                                )
                            )
                        }
                        .frame(minHeight: .iosMinimumTouchTarget)
                        .accessibilityHint(Text("auth.offline.hint"))
                    } else {
                        Text("auth.offline.expired")
                            .appTextStyle(.caption)
                            .foregroundStyle(theme.textTertiary)
                            .multilineTextAlignment(.center)
                    }

                    Button("server.switch.action") {
                        store.chooseAnotherServer()
                    }
                    .frame(minHeight: .iosMinimumTouchTarget)
                }
                .frame(maxWidth: 520)
                .padding(.horizontal, .space3)
                .padding(.vertical, .space3)
                .frame(maxWidth: .infinity)
            }
            .navigationTitle("auth.reauthenticate.navigationTitle")
            .navigationBarTitleDisplayMode(.inline)
            .appCanvas()
        }
        .onAppear {
            store.email = store.snapshot.userEmail ?? store.reauthenticationUserEmail ?? store.email
        }
    }

    private var remainingDays: Int? {
        guard let expiry = store.snapshot.entitlementExpiresAt else { return nil }
        let interval = expiry.timeIntervalSinceNow
        guard interval > 0 else { return nil }
        return max(1, Int(ceil(interval / 86_400)))
    }

    private func loginIfValid() {
        guard !store.email.isEmpty, !store.password.isEmpty else { return }
        passwordFocused = false
        store.login()
    }
}
