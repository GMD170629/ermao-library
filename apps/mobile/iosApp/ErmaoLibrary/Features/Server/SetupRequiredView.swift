import SwiftUI
import UIKit

struct SetupRequiredView: View {
    @ObservedObject var store: SessionStore
    @Environment(\.appTheme) private var theme

    @State private var name = ""
    @State private var email = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @FocusState private var focusedField: Field?

    private enum Field {
        case name
        case email
        case password
        case confirmation
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    if let profile = store.snapshot.profile {
                        ServerIdentityView(profile: profile)
                    }
                    Text("setup.form.message")
                        .foregroundStyle(theme.textSecondary)
                }

                Section("setup.account.section") {
                    TextField("setup.name.placeholder", text: $name)
                        .textContentType(.name)
                        .focused($focusedField, equals: .name)
                        .submitLabel(.next)
                        .onSubmit { focusedField = .email }
                    fieldError("name")

                    TextField("auth.email.placeholder", text: $email)
                        .textContentType(.username)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .focused($focusedField, equals: .email)
                        .submitLabel(.next)
                        .onSubmit { focusedField = .password }
                    fieldError("email")

                    SecureField("setup.password.placeholder", text: $password)
                        .textContentType(.newPassword)
                        .focused($focusedField, equals: .password)
                        .submitLabel(.next)
                        .onSubmit { focusedField = .confirmation }
                    if !password.isEmpty && password.count < 10 {
                        validationLabel("setup.password.minimum")
                    } else {
                        fieldError("password")
                    }

                    SecureField("setup.confirmPassword.placeholder", text: $confirmPassword)
                        .textContentType(.newPassword)
                        .focused($focusedField, equals: .confirmation)
                        .submitLabel(.go)
                        .onSubmit(submitIfValid)
                    if !confirmPassword.isEmpty && password != confirmPassword {
                        validationLabel("setup.confirmPassword.mismatch")
                    }
                }

                Section {
                    PrimaryActionButton(
                        "setup.submit.action",
                        isWorking: store.snapshot.phase == .settingUp,
                        isDisabled: !isFormValid,
                        action: submitIfValid
                    )
                    .listRowInsets(EdgeInsets())
                    .listRowBackground(Color.clear)

                    Button("server.switch.action") {
                        clearPasswords()
                        store.chooseAnotherServer()
                    }
                    .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                } footer: {
                    Text("setup.scope.footer")
                }
            }
            .scrollContentBackground(.hidden)
            .background(theme.canvas)
            .navigationTitle("setup.required.navigationTitle")
            .navigationBarTitleDisplayMode(.inline)
            .disabled(store.snapshot.phase == .settingUp)
        }
    }

    @ViewBuilder
    private func fieldError(_ field: String) -> some View {
        if store.fieldViolation(for: field) != nil {
            validationLabel("setup.field.invalid")
        }
    }

    private func validationLabel(_ key: String) -> some View {
        Label(LocalizedStringKey(key), systemImage: "exclamationmark.circle.fill")
            .font(.caption)
            .foregroundStyle(.red)
            .onAppear {
                UIAccessibility.post(
                    notification: .announcement,
                    argument: NSLocalizedString(key, comment: "")
                )
            }
    }

    private var isFormValid: Bool {
        !name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            !email.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty &&
            password.count >= 10 &&
            password == confirmPassword &&
            store.snapshot.phase != .settingUp
    }

    private func submitIfValid() {
        guard isFormValid else { return }
        focusedField = nil
        store.setup(
            name: name,
            email: email,
            password: password,
            locale: Locale.preferredLanguages.first?.hasPrefix("zh") == true ? "zh-CN" : "en-US"
        )
    }

    private func clearPasswords() {
        password = ""
        confirmPassword = ""
    }
}
