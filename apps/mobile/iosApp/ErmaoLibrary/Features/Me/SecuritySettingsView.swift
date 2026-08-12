import SwiftUI

struct SecuritySettingsView: View {
    @ObservedObject var viewModel: SettingsViewModel

    @Environment(\.appTheme) private var theme
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
        List {
            Section {
                TextField("me.email", text: $email)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .accessibilityHint(Text("settings.security.email.hint"))
                SecureField("settings.security.currentPassword", text: $emailCurrentPassword)
                    .textContentType(.password)
                    .submitLabel(.done)
                    .onSubmit(saveEmail)

                Button(action: saveEmail) {
                    HStack {
                        Text("settings.security.email.save")
                        Spacer(minLength: .space1)
                        if viewModel.isWorking(.savingEmail) {
                            ProgressView().accessibilityLabel(Text("common.loading"))
                        }
                    }
                    .frame(minHeight: .iosMinimumTouchTarget)
                }
                .disabled(
                    viewModel.isBusy ||
                        emailCurrentPassword.isEmpty ||
                        email.trimmingCharacters(in: .whitespacesAndNewlines) ==
                        viewModel.snapshot.account.email
                )
            } header: {
                Text("settings.security.email.section")
            } footer: {
                Text("settings.security.email.footer")
            }
            .listRowBackground(theme.surface)

            Section {
                SecureField("settings.security.currentPassword", text: $currentPassword)
                    .textContentType(.password)
                SecureField("settings.security.newPassword", text: $newPassword)
                    .textContentType(.newPassword)
                SecureField("settings.security.confirmPassword", text: $confirmation)
                    .textContentType(.newPassword)
                    .submitLabel(.done)
                    .onSubmit(changePassword)

                PrimaryActionButton(
                    "settings.security.changePassword.action",
                    isWorking: viewModel.isWorking(.changingPassword),
                    isDisabled: !passwordFormIsComplete || viewModel.isBusy,
                    action: changePassword
                )
                .listRowInsets(
                    EdgeInsets(
                        top: .space2,
                        leading: 0,
                        bottom: .space1,
                        trailing: 0
                    )
                )
            } header: {
                Text("settings.security.password.section")
            } footer: {
                Text("settings.security.password.footer")
            }
            .listRowBackground(theme.surface)

            Section {
                Button("me.logout.action", role: .destructive) {
                    confirmsLogout = true
                }
                .frame(minHeight: .iosMinimumTouchTarget)
                .disabled(viewModel.isBusy)
            } footer: {
                Text("settings.security.logout.footer")
            }
            .listRowBackground(theme.surface)
        }
        .listStyle(.insetGrouped)
        .settingsListSurface()
        .settingsAlert(viewModel: viewModel)
        .navigationTitle("settings.security.title")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(
            "me.logout.confirm.title",
            isPresented: $confirmsLogout,
            titleVisibility: .visible
        ) {
            Button("me.logout.confirm.action", role: .destructive) {
                Task { await viewModel.signOut() }
            }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text("me.logout.confirm.message")
        }
    }

    private var passwordFormIsComplete: Bool {
        !currentPassword.isEmpty && !newPassword.isEmpty && !confirmation.isEmpty
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
}
