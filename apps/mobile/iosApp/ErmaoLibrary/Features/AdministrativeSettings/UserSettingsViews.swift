import SwiftUI

struct UsersSettingsView: View {
    enum Filter: Hashable { case all, enabled, disabled }
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<UserPage> = .idle
    @State private var query = ""
    @State private var filter: Filter = .all
    @State private var userToDelete: AdministrativeUser?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        VStack(spacing: 0) {
            Picker(copy[.accountStatus], selection: $filter) {
                Text(copy[.all]).tag(Filter.all); Text(copy[.enabled]).tag(Filter.enabled); Text(copy[.disabled]).tag(Filter.disabled)
            }
            .pickerStyle(.segmented).padding(.horizontal, .space2).padding(.top, .space1)
            AdministrativeStateView(state: state, retry: load) { page in
                SettingsList {
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
                .overlay { if page.users.isEmpty { AdministrativeEmptyView(title: copy[.noResults], systemImage: "person.2") } }
            }
        }
        .settingsPageSurface()
        .navigationTitle(copy[.usersTitle])
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: copy[.search])
        .onSubmit(of: .search, load)
        .onChange(of: filter) { _, _ in load() }
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.newUser]) { navigate(.userEditor(userID: nil)) } } }
        .confirmationDialog(copy[.deleteUserTitle], isPresented: Binding(get: { userToDelete != nil }, set: { if !$0 { userToDelete = nil } }), titleVisibility: .visible) {
            if let userToDelete {
                Button(copy[.deleteUser], role: .destructive) { delete(userToDelete) }
                    .disabled(store.operationInFlight != nil)
            }
            Button(copy[.cancel], role: .cancel) { userToDelete = nil }
        } message: { Text(copy[.deleteUserMessage]) }
        .task { await loadAsync() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }

    private func enabledFilter() -> Bool? { switch filter { case .all: nil; case .enabled: true; case .disabled: false } }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async {
        state = .loading
        let search = query
        let enabled = enabledFilter()
        state = await store.load(scope: "users") { try await store.client.loadUsers(query: search, enabled: enabled, page: 1) }
    }
    private func toggle(_ user: AdministrativeUser) {
        guard store.operationInFlight == nil else { return }
        Task {
            let result = await store.performValue(id: "toggle-user-\(user.id)") { try await store.client.setUserEnabled(id: user.id, enabled: !user.enabled) }
            if case .success = result { await loadAsync() }
        }
    }
    private func delete(_ user: AdministrativeUser) {
        guard store.operationInFlight == nil else { return }
        userToDelete = nil
        Task { if await store.perform(id: "delete-user-\(user.id)", operation: { try await store.client.deleteUser(id: user.id) }) { await loadAsync() } }
    }
}

struct UserEditorView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let userID: String?
    @State private var state: AdministrativeLoadState<AdministrativeUser?> = .idle
    @State private var draft = UserDraft.empty
    @State private var initialDraft = UserDraft.empty
    @State private var resetPasswordShown = false
    @State private var newPassword = ""
    @State private var confirmPassword = ""
    @State private var deleteShown = false
    @Environment(\.dismiss) private var dismiss
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        SettingsForm {
            Section {
                SettingsTextInputRow(LocalizedStringKey(copy[.displayName])) {
                    TextField(LocalizedStringKey(copy[.displayName]), text: $draft.displayName)
                }
                SettingsTextInputRow(LocalizedStringKey(copy[.email])) {
                    TextField(LocalizedStringKey(copy[.email]), text: $draft.email)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
                SettingsFieldRow(LocalizedStringKey(copy[.role])) {
                    Picker(LocalizedStringKey(copy[.role]), selection: $draft.role) {
                        Text(copy[.member]).tag(UserRole.member)
                        Text(copy[.administrator]).tag(UserRole.administrator)
                    }
                }
                SettingsToggleRow(LocalizedStringKey(copy[.manageSystemPermission]), isOn: $draft.canManageSystem)
                SettingsFieldRow(LocalizedStringKey(copy[.accountLanguage])) {
                    Picker(LocalizedStringKey(copy[.accountLanguage]), selection: $draft.locale) {
                        Text("简体中文").tag(AdministrativeSettingsLocale.zhCN)
                        Text("English").tag(AdministrativeSettingsLocale.enUS)
                    }
                }
                if userID == nil {
                    SettingsTextInputRow(LocalizedStringKey(copy[.password])) {
                        SecureField(LocalizedStringKey(copy[.password]), text: $draft.initialPassword)
                    }
                }
            } header: { Text(copy[.editUser]) }
            if let userID {
                Section(copy[.accountStatus]) {
                    SettingsToggleRow(LocalizedStringKey(copy[.enableAccount]), isOn: $draft.enabled)
                }
                Section(copy[.accessScope]) {
                    SettingsNavigationRow(
                        LocalizedStringKey(copy[.accessScope]),
                        systemImage: "lock.shield"
                    ) { navigate(.userAccess(userID: userID)) }
                }
                Section {
                    SettingsActionRow(LocalizedStringKey(copy[.resetPassword])) { resetPasswordShown = true }
                        .disabled(store.operationInFlight != nil)
                    SettingsActionRow(LocalizedStringKey(copy[.deleteUser]), role: .destructive) { deleteShown = true }
                        .disabled(store.operationInFlight != nil)
                }
            }
        }
        .navigationTitle(userID == nil ? copy[.newUser] : copy[.editUser])
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                AdministrativeToolbarAction(
                    title: copy[.save],
                    working: store.operationInFlight != nil,
                    disabled: store.operationInFlight != nil || !valid || draft == initialDraft,
                    action: save
                )
            }
        }
        .sheet(isPresented: $resetPasswordShown) { resetPasswordSheet }
        .confirmationDialog(copy[.deleteUserTitle], isPresented: $deleteShown, titleVisibility: .visible) {
            Button(copy[.deleteUser], role: .destructive, action: delete)
                .disabled(store.operationInFlight != nil)
            Button(copy[.cancel], role: .cancel) {}
        } message: { Text(copy[.deleteUserMessage]) }
        .task { await load() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }

    private var valid: Bool {
        let hasValidName = AdministrativeInputValidation.isValidDisplayName(draft.displayName)
        let hasValidEmail = AdministrativeInputValidation.isValidEmail(draft.email)
        let hasValidInitialPassword = userID != nil || AdministrativeInputValidation.isValidPassword(draft.initialPassword)
        return hasValidName && hasValidEmail && hasValidInitialPassword
    }
    private var resetPasswordSheet: some View {
        NavigationStack {
            SettingsForm {
                Section {
                    SettingsTextInputRow(LocalizedStringKey(copy[.newPassword])) {
                        SecureField(LocalizedStringKey(copy[.newPassword]), text: $newPassword)
                    }
                    SettingsTextInputRow(LocalizedStringKey(copy[.confirmPassword])) {
                        SecureField(LocalizedStringKey(copy[.confirmPassword]), text: $confirmPassword)
                    }
                }
            }
            .navigationTitle(copy[.resetPassword]).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(copy[.cancel]) { resetPasswordShown = false } }
                ToolbarItem(placement: .confirmationAction) {
                    Button(copy[.resetAndRequireLogin], action: resetPassword)
                        .disabled(store.operationInFlight != nil || !resetPasswordIsValid)
                }
            }
            .administrativeNotice(store: store)
        }
        .environment(\.administrativeCopy, copy).tint(theme.actionAccent)
    }
    private var resetPasswordIsValid: Bool {
        AdministrativeInputValidation.isValidPassword(newPassword) && newPassword == confirmPassword
    }
    private func load() async {
        guard let userID else { state = .loaded(nil); return }
        state = .loading
        state = await store.load(scope: "user-\(userID)") { Optional(try await store.client.loadUser(id: userID)) }
        if case let .loaded(user?) = state {
            let loadedDraft = UserDraft(displayName: user.displayName, email: user.email, role: user.role, enabled: user.enabled, canManageSystem: user.canManageSystem, locale: user.locale, initialPassword: "")
            draft = loadedDraft
            initialDraft = loadedDraft
        }
    }
    private func save() {
        guard store.operationInFlight == nil, valid, draft != initialDraft else { return }
        Task {
            let result: AdministrativeOperationResult<AdministrativeUser>
            let normalizedDraft: UserDraft = {
                var normalized = draft
                normalized.displayName = normalized.displayName.trimmingCharacters(in: .whitespacesAndNewlines)
                normalized.email = normalized.email.trimmingCharacters(in: .whitespacesAndNewlines)
                return normalized
            }()
            if let userID { result = await store.performValue(id: "save-user") { try await store.client.updateUser(id: userID, draft: normalizedDraft) } }
            else { result = await store.performValue(id: "create-user") { try await store.client.createUser(normalizedDraft) } }
            if case .success = result { dismiss() }
        }
    }
    private func resetPassword() {
        guard let userID, store.operationInFlight == nil, resetPasswordIsValid else { return }
        Task {
            if await store.perform(id: "reset-password", operation: { try await store.client.resetUserPassword(id: userID, newPassword: newPassword) }) {
                newPassword = ""; confirmPassword = ""; resetPasswordShown = false
            }
        }
    }
    private func delete() {
        guard let userID, store.operationInFlight == nil else { return }
        Task { if await store.perform(id: "delete-user", operation: { try await store.client.deleteUser(id: userID) }) { dismiss() } }
    }
}

struct UserAccessView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let userID: String
    @State private var state: AdministrativeLoadState<UserAccessSnapshot> = .idle
    @State private var manualImports = false
    @State private var selected = Set<String>()
    @State private var initialManualImports = false
    @State private var initialSelected = Set<String>()
    @State private var query = ""
    @Environment(\.dismiss) private var dismiss
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: { Task { await load() } }) { snapshot in
            SettingsList {
                Section { SettingsToggleRow(LocalizedStringKey(copy[.manualImports]), isOn: $manualImports) }
                Section(copy[.selectedDirectories]) {
                    ForEach(snapshot.scopes.filter { query.isEmpty || $0.name.localizedCaseInsensitiveContains(query) }) { scope in
                        SettingsToggleRow(
                            verbatim: "\(scope.name) · \(scope.serverPath) · \(scope.bookCount)",
                            isOn: Binding(
                                get: { selected.contains(scope.id) },
                                set: { isSelected in
                                    if isSelected { selected.insert(scope.id) } else { selected.remove(scope.id) }
                                }
                            )
                        )
                    }
                }
                Section { Text(copy[.accessHint]).appTextStyle(.callout).foregroundStyle(theme.textSecondary) }
            }
            .administrativeNotice(store: store)
        }
        .navigationTitle(copy[.accessScope]).navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .confirmationAction) {
                AdministrativeToolbarAction(
                    title: copy[.saveAccess],
                    working: store.operationInFlight == "save-access",
                    disabled: store.operationInFlight != nil || (manualImports == initialManualImports && selected == initialSelected),
                    action: save
                )
            }
        }
        .searchable(text: $query, prompt: copy[.search])
        .task { await load() }.onDisappear { store.cancelPendingRequests() }
    }
    private func load() async {
        state = .loading
        state = await store.load(scope: "user-access-\(userID)") { try await store.client.loadUserAccess(id: userID) }
        if case let .loaded(snapshot) = state {
            manualImports = snapshot.user.canViewManualImports
            selected = snapshot.user.libraryIDs
            initialManualImports = manualImports
            initialSelected = selected
        }
    }
    private func save() {
        guard store.operationInFlight == nil,
              manualImports != initialManualImports || selected != initialSelected else { return }
        Task {
            let result = await store.performValue(id: "save-access") { try await store.client.saveUserAccess(id: userID, libraryIDs: selected, canViewManualImports: manualImports) }
            if case .success = result { dismiss() }
        }
    }
}
