import SwiftUI
import UIKit

struct LoginView: View {
    @ObservedObject var store: SessionStore
    @Environment(\.appTheme) private var theme

    @FocusState private var focusedField: Field?

    private enum Field {
        case email
        case password
    }

    private var isAuthenticating: Bool {
        store.snapshot.phase == .authenticating
    }

    private var hasInvalidCredentials: Bool {
        store.snapshot.reasonCode == "UNAUTHORIZED" ||
            store.snapshot.reasonCode == "INVALID_CREDENTIALS"
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: .space3) {
                    Image("BrandMark")
                        .resizable()
                        .scaledToFit()
                        .frame(width: 112, height: 112)
                        .accessibilityHidden(true)
                    Text("auth.login.welcome")
                        .appTextStyle(.display)
                    if let profile = store.snapshot.profile {
                        ServerIdentityView(profile: profile)
                    }

                    VStack(alignment: .leading, spacing: .space3) {
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
                                Label("auth.invalidCredentials", systemImage: "exclamationmark.circle.fill")
                                    .appTextStyle(.caption)
                                    .foregroundStyle(.red)
                                    .onAppear {
                                        UIAccessibility.post(
                                            notification: .announcement,
                                            argument: String(localized: "auth.invalidCredentials")
                                        )
                                    }
                            } else if store.snapshot.phase == .loginFailed {
                                Label("common.requestFailed", systemImage: "exclamationmark.triangle.fill")
                                    .appTextStyle(.caption)
                                    .foregroundStyle(.red)
                            }
                        }
                    }

                    PrimaryActionButton(
                        "auth.login.action",
                        isWorking: isAuthenticating,
                        isDisabled: !isFormValid,
                        action: loginIfValid
                    )
                    Button("server.switch.action") {
                        store.chooseAnotherServer()
                    }
                    .frame(minHeight: .iosMinimumTouchTarget)
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
            .appCanvas()
        }
    }

    private var isFormValid: Bool {
        !store.email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !store.password.isEmpty
    }

    private func loginIfValid() {
        guard isFormValid, !isAuthenticating else { return }
        focusedField = nil
        store.login()
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
                        Text(store.snapshot.userDisplayName ?? store.snapshot.userEmail ?? "")
                            .appTextStyle(.headline)
                        if let email = store.snapshot.userEmail {
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
            store.email = store.snapshot.userEmail ?? store.email
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
