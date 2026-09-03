import PhotosUI
import SwiftUI

struct ProfileSettingsView: View {
    @ObservedObject var viewModel: SettingsViewModel

    @Environment(\.appTheme) private var theme
    @State private var displayName: String
    @State private var selectedPhoto: PhotosPickerItem?
    @State private var confirmsAvatarRemoval = false

    init(viewModel: SettingsViewModel) {
        self.viewModel = viewModel
        _displayName = State(initialValue: viewModel.snapshot.account.displayName)
    }

    var body: some View {
        SettingsScreen("settings.profile.title") {
            Section {
                VStack(spacing: .space2) {
                    SettingsAvatarView(
                        data: viewModel.avatarData,
                        size: 88
                    )
                    avatarActions
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, .space1)
            } footer: {
                Text("settings.avatar.footer")
            }

            SettingsSection("settings.profile.name.section") {
                SettingsTextInputRow("me.name") {
                    TextField("me.name", text: $displayName)
                        .labelsHidden()
                        .textContentType(.name)
                        .submitLabel(.done)
                        .onSubmit {
                            guard !nameSaveIsDisabled else { return }
                            saveName()
                        }
                        .accessibilityHint(Text("settings.profile.name.hint"))
                }
                SettingsValueRow("me.email", value: viewModel.snapshot.account.email)
            }

        }
        .settingsAlert(viewModel: viewModel)
        .onChange(of: selectedPhoto) { _, item in
            guard let item else { return }
            loadPhoto(item)
        }
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                SettingsToolbarAction(
                    "settings.profile.name.save",
                    working: viewModel.isWorking(.savingName),
                    disabled: nameSaveIsDisabled,
                    action: saveName
                )
            }
        }
    }

    @ViewBuilder
    private var avatarActions: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: .space2) {
                photoPicker
                if viewModel.snapshot.account.avatarURL != nil { removeAvatarButton }
            }
            VStack(spacing: .space1) {
                photoPicker
                if viewModel.snapshot.account.avatarURL != nil { removeAvatarButton }
            }
        }
    }

    private var photoPicker: some View {
        PhotosPicker(selection: $selectedPhoto, matching: .images) {
            Label("settings.avatar.choose.action", systemImage: "photo.on.rectangle")
                .frame(minHeight: .iosMinimumTouchTarget)
        }
        .disabled(viewModel.isBusy)
        .accessibilityHint(Text("settings.avatar.choose.hint"))
    }

    private var removeAvatarButton: some View {
        Button(role: .destructive) {
            confirmsAvatarRemoval = true
        } label: {
            Label("settings.avatar.remove.action", systemImage: "trash")
                .frame(minHeight: .iosMinimumTouchTarget)
        }
        .disabled(viewModel.isBusy)
        .confirmationDialog(
            "settings.avatar.remove.confirm.title",
            isPresented: $confirmsAvatarRemoval,
            titleVisibility: .visible
        ) {
            Button("settings.avatar.remove.action", role: .destructive) {
                Task { await viewModel.deleteAvatar() }
            }
            .disabled(viewModel.isBusy)
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text("settings.avatar.remove.confirm.message")
        }
    }

    private var nameSaveIsDisabled: Bool {
        let normalized = displayName.trimmingCharacters(in: .whitespacesAndNewlines)
        return viewModel.isBusy ||
            !SettingsInputValidation.isValidDisplayName(normalized) ||
            normalized == viewModel.snapshot.account.displayName
    }

    private func saveName() {
        Task {
            if await viewModel.saveName(displayName) {
                displayName = viewModel.snapshot.account.displayName
            }
        }
    }

    private func loadPhoto(_ item: PhotosPickerItem) {
        Task { @MainActor in
            defer { selectedPhoto = nil }
            do {
                guard let data = try await item.loadTransferable(type: Data.self) else {
                    viewModel.presentPhotoLoadingFailure()
                    return
                }
                let declaredType = item.supportedContentTypes.first?.identifier
                _ = await viewModel.uploadAvatar(
                    data: data,
                    declaredContentTypeIdentifier: declaredType
                )
            } catch {
                viewModel.presentPhotoLoadingFailure()
            }
        }
    }
}
