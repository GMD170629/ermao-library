import SwiftUI

struct SecuritySettingsView: View {
    private enum Tab: Hashable {
        case email
        case password
    }

    @ObservedObject var viewModel: SettingsViewModel

    @State private var tab: Tab = .email
    @State private var email: String
    @State private var emailCurrentPassword = ""
    @State private var currentPassword = ""
    @State private var newPassword = ""
    @State private var confirmation = ""
    @State private var confirmsLogout = false

    init(viewModel: SettingsViewModel) {
        self.viewModel = viewModel
        _email = State(initialValue: viewModel.snapshot.account.email)
    }

    var body: some View {
        SettingsScreen("settings.security.title") {
            Section {
                SettingsTabPicker("settings.security.title", selection: $tab) {
                    Text("settings.security.email.tab").tag(Tab.email)
                    Text("settings.security.password.tab").tag(Tab.password)
                }
                .disabled(viewModel.isBusy)
            }

            switch tab {
            case .email:
                emailForm
            case .password:
                passwordForm
            }

            Section {
                SettingsActionRow("me.logout.action", role: .destructive) {
                    confirmsLogout = true
                }
                .disabled(viewModel.isBusy)
                .confirmationDialog(
                    "me.logout.confirm.title",
                    isPresented: $confirmsLogout,
                    titleVisibility: .visible
                ) {
                    Button("me.logout.confirm.action", role: .destructive) {
                        Task { await viewModel.signOut() }
                    }
                    .disabled(viewModel.isBusy)
                    Button("common.cancel", role: .cancel) {}
                } message: {
                    Text("me.logout.confirm.message")
                }
            } footer: {
                Text("settings.security.logout.footer")
            }
        }
        .settingsAlert(viewModel: viewModel)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                SettingsToolbarAction(
                    currentSaveTitle,
                    working: currentSaveIsWorking,
                    disabled: currentSaveIsDisabled,
                    action: saveCurrentTab
                )
            }
        }
    }

    @ViewBuilder
    private var emailForm: some View {
        Section {
            SettingsTextInputRow("me.email") {
                TextField("me.email", text: $email)
                    .labelsHidden()
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .accessibilityHint(Text("settings.security.email.hint"))
            }
            SettingsTextInputRow("settings.security.currentPassword") {
                SecureField("settings.security.currentPassword", text: $emailCurrentPassword)
                    .labelsHidden()
                    .textContentType(.password)
                    .submitLabel(.done)
                    .onSubmit {
                        guard !emailSaveIsDisabled else { return }
                        saveEmail()
                    }
            }
        } header: {
            SettingsSectionHeader("settings.security.email.section")
        } footer: {
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text("settings.security.email.footer")
                if !email.isEmpty && !emailIsValid {
                    validationMessage("settings.security.email.invalid")
                }
                if emailCurrentPassword.count > SettingsInputValidation.maximumPasswordLength {
                    validationMessage("settings.security.currentPassword.maximum")
                }
            }
        }
    }

    @ViewBuilder
    private var passwordForm: some View {
        Section {
            SettingsTextInputRow("settings.security.currentPassword") {
                SecureField("settings.security.currentPassword", text: $currentPassword)
                    .labelsHidden()
                    .textContentType(.password)
            }
            SettingsTextInputRow("settings.security.newPassword") {
                SecureField("settings.security.newPassword", text: $newPassword)
                    .labelsHidden()
                    .textContentType(.newPassword)
            }
            SettingsTextInputRow("settings.security.confirmPassword") {
                SecureField("settings.security.confirmPassword", text: $confirmation)
                    .labelsHidden()
                    .textContentType(.newPassword)
                    .submitLabel(.done)
                    .onSubmit {
                        guard !passwordSaveIsDisabled else { return }
                        changePassword()
                    }
            }
        } header: {
            SettingsSectionHeader("settings.security.password.section")
        } footer: {
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text("settings.security.password.footer")
                if currentPassword.count > SettingsInputValidation.maximumPasswordLength {
                    validationMessage("settings.security.currentPassword.maximum")
                }
                if !newPassword.isEmpty && newPassword.count < SettingsInputValidation.minimumPasswordLength {
                    validationMessage("settings.security.newPassword.minimum")
                } else if newPassword.count > SettingsInputValidation.maximumPasswordLength {
                    validationMessage("settings.security.newPassword.maximum")
                }
                if !confirmation.isEmpty && newPassword != confirmation {
                    validationMessage("settings.security.password.mismatch")
                }
            }
        }
    }

    private var currentSaveTitle: LocalizedStringKey {
        switch tab {
        case .email:
            "settings.security.email.save"
        case .password:
            "settings.security.changePassword.action"
        }
    }

    private var currentSaveIsWorking: Bool {
        switch tab {
        case .email:
            viewModel.isWorking(.savingEmail)
        case .password:
            viewModel.isWorking(.changingPassword)
        }
    }

    private var currentSaveIsDisabled: Bool {
        if viewModel.isBusy { return true }
        return switch tab {
        case .email:
            emailSaveIsDisabled
        case .password:
            passwordSaveIsDisabled
        }
    }

    private var emailIsValid: Bool {
        SettingsInputValidation.isValidEmail(email)
    }

    private var emailSaveIsDisabled: Bool {
        let normalizedEmail = email.trimmingCharacters(in: .whitespacesAndNewlines)
        return !emailIsValid ||
            !SettingsInputValidation.isValidCurrentPassword(emailCurrentPassword) ||
            normalizedEmail == viewModel.snapshot.account.email
    }

    private var passwordSaveIsDisabled: Bool {
        !SettingsInputValidation.isValidCurrentPassword(currentPassword) ||
            !SettingsInputValidation.isValidNewPassword(newPassword) ||
            confirmation.isEmpty ||
            newPassword != confirmation
    }

    private func saveCurrentTab() {
        switch tab {
        case .email:
            saveEmail()
        case .password:
            changePassword()
        }
    }

    private func saveEmail() {
        Task {
            if await viewModel.saveEmail(email, currentPassword: emailCurrentPassword) {
                email = viewModel.snapshot.account.email
                emailCurrentPassword = ""
            }
        }
    }

    private func changePassword() {
        Task {
            if await viewModel.changePassword(
                currentPassword: currentPassword,
                newPassword: newPassword,
                confirmation: confirmation
            ) {
                currentPassword = ""
                newPassword = ""
                confirmation = ""
            }
        }
    }

    private func validationMessage(_ key: LocalizedStringKey) -> some View {
        Text(key)
            .foregroundStyle(.red)
    }
}
