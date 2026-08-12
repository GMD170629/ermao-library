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
        List {
            Section {
                VStack(spacing: .space2) {
                    SettingsAvatarView(
                        data: viewModel.avatarData,
                        displayName: viewModel.snapshot.account.displayName,
                        size: 88
                    )
                    avatarActions
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, .space1)
            } footer: {
                Text("settings.avatar.footer")
            }
            .listRowBackground(theme.surface)

            Section("settings.profile.name.section") {
                TextField("me.name", text: $displayName)
                    .textContentType(.name)
                    .submitLabel(.done)
                    .onSubmit(saveName)
                    .accessibilityHint(Text("settings.profile.name.hint"))

                Button(action: saveName) {
                    workingLabel(
                        titleKey: "settings.profile.name.save",
                        operation: .savingName
                    )
                }
                .disabled(
                    viewModel.isBusy ||
                        displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ||
                        displayName.trimmingCharacters(in: .whitespacesAndNewlines) ==
                        viewModel.snapshot.account.displayName
                )
            }
            .listRowBackground(theme.surface)

        }
        .listStyle(.insetGrouped)
        .settingsListSurface()
        .settingsAlert(viewModel: viewModel)
        .navigationTitle("settings.profile.title")
        .navigationBarTitleDisplayMode(.inline)
        .confirmationDialog(
            "settings.avatar.remove.confirm.title",
            isPresented: $confirmsAvatarRemoval,
            titleVisibility: .visible
        ) {
            Button("settings.avatar.remove.action", role: .destructive) {
                Task { await viewModel.deleteAvatar() }
            }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text("settings.avatar.remove.confirm.message")
        }
        .onChange(of: selectedPhoto) { item in
            guard let item else { return }
            loadPhoto(item)
        }
    }

    @ViewBuilder
    private var avatarActions: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: .space2) {
                photoPicker
                removeAvatarButton
            }
            VStack(spacing: .space1) {
                photoPicker
                removeAvatarButton
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
        .disabled(viewModel.avatarData == nil || viewModel.isBusy)
    }

    private func workingLabel(titleKey: String, operation: SettingsOperation) -> some View {
        HStack {
            Text(LocalizedStringKey(titleKey))
            Spacer(minLength: .space1)
            if viewModel.isWorking(operation) {
                ProgressView()
                    .accessibilityLabel(Text("common.loading"))
            }
        }
        .frame(minHeight: .iosMinimumTouchTarget)
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
