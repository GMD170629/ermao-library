import SwiftUI
import UIKit

struct UsersSettingsView: View {
    enum Filter: Hashable { case all, enabled, disabled }
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<UserPage> = .idle
    @State private var query = ""
    @State private var filter: Filter = .all
    @State private var userToDelete: AdministrativeUser?
    @State private var loadTask: Task<Void, Never>?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        VStack(spacing: 0) {
            Picker(copy[.accountStatus], selection: $filter) {
                Text(copy[.all]).tag(Filter.all); Text(copy[.enabled]).tag(Filter.enabled); Text(copy[.disabled]).tag(Filter.disabled)
            }
            .pickerStyle(.segmented).padding(.horizontal, .space2).padding(.top, .space1)
            SettingsList {
                if case let .loaded(page) = state {
                    ForEach(page.users) { user in
                        SettingsNavigationRow(
                            verbatim: user.displayName,
                            status: "\(user.email) · \(user.role == .administrator ? copy[.administrator] : copy[.member]) · \(user.enabled ? copy[.enabled] : copy[.disabled])",
                            systemImage: "person.crop.circle"
                        ) { navigate(.userEditor(userID: user.id)) }
                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                Button(copy[.delete], role: .destructive) { userToDelete = user }
                                    .disabled(store.operationInFlight != nil)
                                Button(user.enabled ? copy[.disableAccount] : copy[.enableAccount]) { toggle(user) }
                                    .tint(.orange)
                                    .disabled(store.operationInFlight != nil)
                            }
                    }
                    if page.pageCount > 1 {
                        HStack { Spacer(); Text("\(page.page) / \(page.pageCount) · \(page.total)").foregroundStyle(theme.textSecondary); Spacer() }
                    }
                }
            }
            .disabled(loadTask != nil || store.operationInFlight != nil)
            .overlay { listStatus }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .settingsPageSurface()
        .navigationTitle(copy[.usersTitle])
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: copy[.search])
        .onSubmit(of: .search, load)
        .onChange(of: filter) { _, _ in load() }
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button { navigate(.userEditor(userID: nil)) } label: {
                    Label(copy[.newUser], systemImage: "plus")
                        .labelStyle(.iconOnly)
                        .frame(minWidth: .iosMinimumTouchTarget, minHeight: .iosMinimumTouchTarget)
                }
                .tint(nil)
            }
        }
        .sheet(item: $userToDelete) { user in
            UserDeletionSheet(store: store, user: user, onDeleted: load)
        }
        .onAppear(perform: load)
        .onDisappear {
            loadTask?.cancel()
            loadTask = nil
            store.cancelPendingRequests()
        }
        .administrativeNotice(store: store)
    }

    @ViewBuilder
    private var listStatus: some View {
        if loadTask != nil {
            ProgressView(copy[.loading])
                .padding(.space2)
                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: .space1))
        } else {
            switch state {
            case let .loaded(page) where page.users.isEmpty:
                AdministrativeEmptyView(title: copy[.noResults], systemImage: "person.2")
            case let .failed(failure):
                AdministrativeEmptyView(title: copy[.requestFailed], systemImage: "exclamationmark.triangle", detail: failure.code, actionTitle: copy[.retry], action: load)
            default:
                EmptyView()
            }
        }
    }

    private func enabledFilter() -> Bool? { switch filter { case .all: nil; case .enabled: true; case .disabled: false } }
    private func load() {
        loadTask?.cancel()
        // Keep the mounted list and its last rows while the next filter loads.
        if case .loaded = state {} else { state = .loading }
        let search = query
        let enabled = enabledFilter()
        loadTask = Task { @MainActor in
            let result = await store.load(scope: "users") { try await store.client.loadUsers(query: search, enabled: enabled, page: 1) }
            // A cancelled request must not clear a newer request's result or loading indicator.
            guard !Task.isCancelled else { return }
            loadTask = nil
            switch result {
            case .idle: break
            default: state = result
            }
        }
    }
    private func toggle(_ user: AdministrativeUser) {
        guard loadTask == nil, store.operationInFlight == nil else { return }
        Task {
            let result = await store.performValue(id: "toggle-user-\(user.id)") { try await store.client.setUserEnabled(id: user.id, enabled: !user.enabled) }
            if case .success = result { load() }
        }
    }

}

struct UserEditorView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let userID: String?
    @State private var state: AdministrativeLoadState<UserEditorSnapshot> = .idle
    @State private var draft = UserDraft.empty
    @State private var initialDraft = UserDraft.empty
    @State private var resetPasswordShown = false
    @State private var newPassword = ""
    @State private var userToDelete: AdministrativeUser?
    @State private var discardShown = false
    @State private var operationTask: Task<Void, Never>?
    @State private var reload = 0
    @Environment(\.dismiss) private var dismiss
    @Environment(\.administrativeCopy) private var copy

    private var hasChanges: Bool { draft != initialDraft }
    private var working: Bool { store.operationInFlight != nil || operationTask != nil }

    var body: some View {
        AdministrativeStateView(state: state, retry: { reload += 1 }) { snapshot in
            SettingsForm {
                Section {
                    SettingsTextInputRow(LocalizedStringKey(copy[.userName])) {
                        TextField(LocalizedStringKey(copy[.userName]), text: $draft.displayName)
                            .textContentType(.name)
                    }
                    SettingsTextInputRow(LocalizedStringKey(copy[.email])) {
                        TextField(LocalizedStringKey(copy[.email]), text: $draft.email)
                            .keyboardType(.emailAddress).textContentType(.emailAddress)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                    if userID == nil {
                        SettingsTextInputRow(LocalizedStringKey(copy[.initialPassword])) {
                            SecureField(LocalizedStringKey(copy[.initialPassword]), text: $draft.initialPassword)
                                .textContentType(.newPassword)
                        }
                        Text(copy[.initialPasswordHint]).font(.footnote)
                    }
                    SettingsFieldRow(LocalizedStringKey(copy[.interfaceLanguage])) {
                        Picker(copy[.interfaceLanguage], selection: $draft.locale) {
                            Text("简体中文").tag(AdministrativeSettingsLocale.zhCN)
                            Text("English").tag(AdministrativeSettingsLocale.enUS)
                        }.labelsHidden()
                    }
                    SettingsFieldRow(LocalizedStringKey(copy[.role])) {
                        Picker(copy[.role], selection: $draft.role) {
                            Text(copy[.member]).tag(UserRole.member)
                            Text(copy[.administrator]).tag(UserRole.administrator)
                        }.labelsHidden()
                    }
                    if userID != nil {
                        SettingsFieldRow(LocalizedStringKey(copy[.accountStatus])) {
                            Picker(copy[.accountStatus], selection: $draft.enabled) {
                                Text(copy[.userStatusActive]).tag(true)
                                Text(copy[.userStatusDisabled]).tag(false)
                            }.labelsHidden()
                        }
                    }
                    if let created = snapshot.user?.createdAt {
                        LabeledContent(copy[.createdAt], value: created.administrativeFormatted(locale: copy.locale))
                    }
                }
                if draft.role == .administrator {
                    Section { Text(copy[.adminPermissionsHint]).font(.callout) }
                } else {
                    Section {
                        SettingsToggleRow(LocalizedStringKey(copy[.manageSystemPermission]), isOn: $draft.canManageSystem)
                        Text(copy[.managementPermissionsHint]).font(.footnote)
                    } header: { Text(copy[.managementPermissions]) }
                    Section {
                        Text(copy[.emptyPermissionsHint]).font(.footnote)
                        SettingsToggleRow(LocalizedStringKey(copy[.manualImports]), isOn: $draft.canViewManualImports)
                        Text(copy[.manualImportsHint]).font(.footnote)
                        ForEach(snapshot.scopes) { scope in
                            SettingsToggleRow(verbatim: "\(scope.displayName)\n\(scope.serverPath)", isOn: Binding(
                                get: { draft.libraryIDs.contains(scope.id) },
                                set: { if $0 { draft.libraryIDs.insert(scope.id) } else { draft.libraryIDs.remove(scope.id) } }
                            ))
                        }
                    } header: { Text(copy[.libraryPermissions]) }
                }
                if let user = snapshot.user {
                    Section {
                        SettingsActionRow(LocalizedStringKey(copy[.resetPassword])) {
                            newPassword = ""
                            resetPasswordShown = true
                        }
                        SettingsActionRow(LocalizedStringKey(copy[.deleteUser]), role: .destructive) { userToDelete = user }
                    }
                }
            }
            .disabled(working)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
        .settingsPageSurface()
        .navigationTitle(userID == nil ? copy[.newUser] : copy[.editUser])
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(hasChanges || working)
        .interactiveDismissDisabled(hasChanges || working)
        .background(UserEditorBackGestureGuard(blocked: hasChanges || working) {
            if !working { discardShown = true }
        })
        .toolbar {
            if hasChanges || working {
                ToolbarItem(placement: .topBarLeading) {
                    Button { discardShown = true } label: { Label(copy[.back], systemImage: "chevron.backward") }
                        .disabled(working).tint(nil)
                }
            }
            ToolbarItem(placement: .confirmationAction) {
                AdministrativeToolbarAction(title: copy[.save], working: working,
                    disabled: working || !hasChanges || !draft.shared.isValid(creating: userID == nil) || !loaded,
                    action: save)
            }
        }
        .confirmationDialog(copy[.discardUserChanges], isPresented: $discardShown, titleVisibility: .visible) {
            Button(copy[.discardChanges], role: .destructive) { dismiss() }
            Button(copy[.cancel], role: .cancel) {}
        }
        .sheet(isPresented: $resetPasswordShown) { resetPasswordSheet }
        .sheet(item: $userToDelete) { user in
            UserDeletionSheet(store: store, user: user) { dismiss() }
        }
        .task(id: reload) { await load() }
        .onDisappear { operationTask?.cancel(); store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }

    private var loaded: Bool { if case .loaded = state { true } else { false } }
    private var resetPasswordSheet: some View {
        NavigationStack {
            SettingsForm {
                Section {
                    Text(copy[.resetSessionsHint])
                    SettingsTextInputRow(LocalizedStringKey(copy[.newPassword])) {
                        SecureField(LocalizedStringKey(copy[.newPassword]), text: $newPassword).textContentType(.newPassword)
                    }
                }
            }
            .disabled(working)
            .navigationTitle(copy[.resetPassword]).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(copy[.cancel]) { newPassword = ""; resetPasswordShown = false }.disabled(working)
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(copy[.resetAndRequireLogin], action: resetPassword)
                        .disabled(working || !AdministrativeInputValidation.isValidPassword(newPassword))
                }
            }
            .administrativeNotice(store: store)
        }
        .environment(\.administrativeCopy, copy)
        .interactiveDismissDisabled(working)
        .onDisappear { newPassword = "" }
    }

    private func load() async {
        state = .loading
        let result = await store.load(scope: "user-editor") { try await store.client.loadUserEditor(id: userID) }
        guard !Task.isCancelled else { return }
        state = result
        if case let .loaded(snapshot) = result {
            if let user = snapshot.user {
                draft = UserDraft(displayName: user.displayName, email: user.email, role: user.role, enabled: user.enabled,
                    canManageSystem: user.canManageSystem, locale: user.locale, initialPassword: "",
                    canViewManualImports: user.canViewManualImports, libraryIDs: user.libraryIDs)
            } else { draft = .empty }
            initialDraft = draft
        }
    }
    private func save() {
        guard loaded, !working, hasChanges, draft.shared.isValid(creating: userID == nil) else { return }
        let input = draft
        operationTask = Task { @MainActor in
            defer { operationTask = nil }
            let result = await store.performValue(id: "save-user") {
                if let userID { return try await store.client.updateUser(id: userID, draft: input) }
                return try await store.client.createUser(input)
            }
            if case .success = result, !Task.isCancelled { draft.initialPassword = ""; initialDraft = draft; dismiss() }
        }
    }
    private func resetPassword() {
        guard let userID, !working, AdministrativeInputValidation.isValidPassword(newPassword) else { return }
        let password = newPassword
        operationTask = Task { @MainActor in
            defer { operationTask = nil }
            if await store.perform(id: "reset-password", operation: { try await store.client.resetUserPassword(id: userID, newPassword: password) }), !Task.isCancelled {
                newPassword = ""; resetPasswordShown = false
            }
        }
    }
}

private struct UserDeletionSheet: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let user: AdministrativeUser
    let onDeleted: () -> Void
    @State private var confirmation = ""
    @State private var operationTask: Task<Void, Never>?
    @Environment(\.dismiss) private var dismiss
    @Environment(\.administrativeCopy) private var copy

    var body: some View {
        NavigationStack {
            SettingsForm {
                Section {
                    Text(copy[.permanentDeleteHint])
                    Text(verbatim: user.email)
                    TextField(copy[.deleteEmailConfirmation], text: $confirmation)
                        .keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                }
            }
            .disabled(working)
            .navigationTitle(copy[.deleteUserTitle]).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(copy[.cancel]) { dismiss() }.disabled(working) }
                ToolbarItem(placement: .confirmationAction) {
                    Button(copy[.deleteUser], role: .destructive, action: delete)
                        .disabled(working || !AdministrativeInputValidation.validDeletion(email: user.email, confirmation: confirmation))
                }
            }
            .administrativeNotice(store: store)
        }
        .environment(\.administrativeCopy, copy)
        .interactiveDismissDisabled(working)
        .onDisappear { operationTask?.cancel() }
    }
    private var working: Bool { store.operationInFlight != nil || operationTask != nil }
    private func delete() {
        guard !working, AdministrativeInputValidation.validDeletion(email: user.email, confirmation: confirmation) else { return }
        let input = confirmation
        operationTask = Task { @MainActor in
            defer { operationTask = nil }
            if await store.perform(id: "delete-user-\(user.id)", operation: { try await store.client.deleteUser(id: user.id, confirmation: input) }), !Task.isCancelled {
                dismiss(); onDeleted()
            }
        }
    }
}

/// Intercepts the native back swipe only while this editor has protected changes.
private struct UserEditorBackGestureGuard: UIViewControllerRepresentable {
    let blocked: Bool
    let onAttempt: () -> Void

    func makeUIViewController(context: Context) -> Controller { Controller() }
    func updateUIViewController(_ controller: Controller, context: Context) {
        controller.blocked = blocked
        controller.onAttempt = onAttempt
        controller.updateGesture()
    }
    static func dismantleUIViewController(_ controller: Controller, coordinator: ()) { controller.restoreGesture() }

    final class Controller: UIViewController, UIGestureRecognizerDelegate {
        var blocked = false
        var onAttempt: () -> Void = {}
        private weak var gesture: UIGestureRecognizer?
        private weak var previousDelegate: UIGestureRecognizerDelegate?

        override func viewDidAppear(_ animated: Bool) {
            super.viewDidAppear(animated)
            updateGesture()
        }
        override func viewWillDisappear(_ animated: Bool) {
            restoreGesture()
            super.viewWillDisappear(animated)
        }
        func updateGesture() {
            guard blocked else { restoreGesture(); return }
            guard let current = navigationController?.interactivePopGestureRecognizer else { return }
            if gesture !== current {
                restoreGesture()
                gesture = current
                previousDelegate = current.delegate
                current.delegate = self
            }
        }
        func restoreGesture() {
            if let gesture, gesture.delegate === self { gesture.delegate = previousDelegate }
            gesture = nil
            previousDelegate = nil
        }
        func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
            if blocked { onAttempt(); return false }
            return previousDelegate?.gestureRecognizerShouldBegin?(gestureRecognizer) ?? true
        }
    }
}
