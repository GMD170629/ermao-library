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
                List {
                    ForEach(page.users) { user in
                        Button { navigate(.userEditor(userID: user.id)) } label: { userRow(user) }
                            .buttonStyle(.plain)
                            .swipeActions(edge: .trailing, allowsFullSwipe: false) {
                                Button(copy[.delete], role: .destructive) { userToDelete = user }
                                Button(user.enabled ? copy[.disableAccount] : copy[.enableAccount]) { toggle(user) }.tint(.orange)
                            }
                    }
                    if page.pageCount > 1 {
                        HStack { Spacer(); Text("\(page.page) / \(page.pageCount) · \(page.total)").foregroundStyle(theme.textSecondary); Spacer() }
                    }
                }
                .listStyle(.plain).administrativeListSurface()
                .overlay { if page.users.isEmpty { AdministrativeEmptyView(title: copy[.noResults], systemImage: "person.2") } }
            }
        }
        .background(theme.canvas)
        .navigationTitle(copy[.usersTitle])
        .navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: copy[.search])
        .onSubmit(of: .search, load)
        .onChange(of: filter) { _ in load() }
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.newUser]) { navigate(.userEditor(userID: nil)) } } }
        .confirmationDialog(copy[.deleteUserTitle], isPresented: Binding(get: { userToDelete != nil }, set: { if !$0 { userToDelete = nil } }), titleVisibility: .visible) {
            if let userToDelete { Button(copy[.deleteUser], role: .destructive) { delete(userToDelete) } }
            Button(copy[.cancel], role: .cancel) { userToDelete = nil }
        } message: { Text(copy[.deleteUserMessage]) }
        .task { await loadAsync() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }

    private func userRow(_ user: AdministrativeUser) -> some View {
        HStack(spacing: .space1Half) {
            Text(user.displayName.first.map(String.init) ?? "?")
                .appTextStyle(.headline).foregroundStyle(theme.actionAccent)
                .frame(width: 44, height: 44).background(theme.accentSoft).clipShape(Circle())
            VStack(alignment: .leading, spacing: .spaceHalf) {
                Text(user.displayName).appTextStyle(.headline)
                Text(user.email).appTextStyle(.label).foregroundStyle(theme.textSecondary)
                Text(user.role == .administrator ? copy[.administrator] : copy[.member]).appTextStyle(.caption).foregroundStyle(theme.textSecondary)
            }
            Spacer()
            Text(user.enabled ? copy[.enabled] : copy[.disabled]).foregroundStyle(user.enabled ? .green : theme.textSecondary)
        }
        .padding(.vertical, .spaceHalf)
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
        Task {
            let result = await store.performValue(id: "toggle-user-\(user.id)") { try await store.client.setUserEnabled(id: user.id, enabled: !user.enabled) }
            if case .success = result { await loadAsync() }
        }
    }
    private func delete(_ user: AdministrativeUser) {
        userToDelete = nil
        Task { if await store.perform(id: "delete-user-\(user.id)", operation: { try await store.client.deleteUser(id: user.id) }) { await loadAsync() } }
    }
}

struct UserEditorView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let userID: String?
    @State private var state: AdministrativeLoadState<AdministrativeUser?> = .idle
    @State private var draft = UserDraft.empty
    @State private var resetPasswordShown = false
    @State private var newPassword = ""
    @State private var confirmPassword = ""
    @State private var deleteShown = false
    @Environment(\.dismiss) private var dismiss
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        Form {
            Section {
                TextField(copy[.displayName], text: $draft.displayName)
                TextField(copy[.email], text: $draft.email).keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                Picker(copy[.role], selection: $draft.role) {
                    Text(copy[.member]).tag(UserRole.member); Text(copy[.administrator]).tag(UserRole.administrator)
                }
                Toggle(copy[.manageSystemPermission], isOn: $draft.canManageSystem)
                Picker(copy[.accountLanguage], selection: $draft.locale) {
                    Text("简体中文").tag(AdministrativeSettingsLocale.zhCN)
                    Text("English").tag(AdministrativeSettingsLocale.enUS)
                }
                if userID == nil { SecureField(copy[.password], text: $draft.initialPassword) }
            } header: { Text(copy[.editUser]) }
            if let userID {
                Section(copy[.accountStatus]) { Toggle(copy[.enableAccount], isOn: $draft.enabled) }
                Section(copy[.accessScope]) { Button(copy[.accessScope]) { navigate(.userAccess(userID: userID)) } }
                Section {
                    Button(copy[.resetPassword]) { resetPasswordShown = true }
                    Button(copy[.deleteUser], role: .destructive) { deleteShown = true }
                }
            }
        }
        .administrativeListSurface()
        .navigationTitle(userID == nil ? copy[.newUser] : copy[.editUser])
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.save], action: save).disabled(!valid || store.operationInFlight != nil) } }
        .sheet(isPresented: $resetPasswordShown) { resetPasswordSheet }
        .confirmationDialog(copy[.deleteUserTitle], isPresented: $deleteShown, titleVisibility: .visible) {
            Button(copy[.deleteUser], role: .destructive, action: delete); Button(copy[.cancel], role: .cancel) {}
        } message: { Text(copy[.deleteUserMessage]) }
        .task { await load() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }

    private var valid: Bool {
        !draft.displayName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draft.email.contains("@") && (userID != nil || draft.initialPassword.count >= 8)
    }
    private var resetPasswordSheet: some View {
        NavigationStack {
            Form {
                Section { SecureField(copy[.newPassword], text: $newPassword); SecureField(copy[.confirmPassword], text: $confirmPassword) }
            }
            .administrativeListSurface().navigationTitle(copy[.resetPassword]).navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button(copy[.cancel]) { resetPasswordShown = false } }
                ToolbarItem(placement: .confirmationAction) { Button(copy[.resetAndRequireLogin], action: resetPassword).disabled(newPassword.count < 8 || newPassword != confirmPassword) }
            }
        }
        .environment(\.administrativeCopy, copy).tint(theme.actionAccent)
    }
    private func load() async {
        guard let userID else { state = .loaded(nil); return }
        state = .loading
        state = await store.load(scope: "user-\(userID)") { Optional(try await store.client.loadUser(id: userID)) }
        if case let .loaded(user?) = state { draft = UserDraft(displayName: user.displayName, email: user.email, role: user.role, enabled: user.enabled, canManageSystem: user.canManageSystem, locale: user.locale, initialPassword: "") }
    }
    private func save() {
        Task {
            let result: AdministrativeOperationResult<AdministrativeUser>
            if let userID { result = await store.performValue(id: "save-user") { try await store.client.updateUser(id: userID, draft: draft) } }
            else { result = await store.performValue(id: "create-user") { try await store.client.createUser(draft) } }
            if case .success = result { dismiss() }
        }
    }
    private func resetPassword() {
        guard let userID else { return }
        Task {
            if await store.perform(id: "reset-password", operation: { try await store.client.resetUserPassword(id: userID, newPassword: newPassword) }) {
                newPassword = ""; confirmPassword = ""; resetPasswordShown = false
            }
        }
    }
    private func delete() {
        guard let userID else { return }
        Task { if await store.perform(id: "delete-user", operation: { try await store.client.deleteUser(id: userID) }) { dismiss() } }
    }
}

struct UserAccessView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let userID: String
    @State private var state: AdministrativeLoadState<UserAccessSnapshot> = .idle
    @State private var manualImports = false
    @State private var selected = Set<String>()
    @State private var query = ""
    @Environment(\.dismiss) private var dismiss
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: { Task { await load() } }) { snapshot in
            List {
                Section { Toggle(copy[.manualImports], isOn: $manualImports) }
                Section(copy[.selectedDirectories]) {
                    ForEach(snapshot.scopes.filter { query.isEmpty || $0.name.localizedCaseInsensitiveContains(query) }) { scope in
                        Button { if selected.contains(scope.id) { selected.remove(scope.id) } else { selected.insert(scope.id) } } label: {
                            HStack { Image(systemName: selected.contains(scope.id) ? "checkmark.square.fill" : "square"); VStack(alignment: .leading) { Text(scope.name); Text(scope.serverPath).font(.caption).foregroundStyle(theme.textSecondary) }; Spacer(); Text("\(scope.bookCount)").foregroundStyle(theme.textSecondary) }
                        }
                    }
                }
                Section { Text(copy[.accessHint]).appTextStyle(.callout).foregroundStyle(theme.textSecondary) }
            }
            .administrativeListSurface()
            .safeAreaInset(edge: .bottom) { AdministrativeBottomAction(title: copy[.saveAccess], working: store.operationInFlight == "save-access", action: save) }
        }
        .navigationTitle(copy[.accessScope]).navigationBarTitleDisplayMode(.inline)
        .searchable(text: $query, prompt: copy[.search])
        .task { await load() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func load() async {
        state = .loading
        state = await store.load(scope: "user-access-\(userID)") { try await store.client.loadUserAccess(id: userID) }
        if case let .loaded(snapshot) = state { manualImports = snapshot.user.canViewManualImports; selected = snapshot.user.libraryIDs }
    }
    private func save() {
        Task {
            let result = await store.performValue(id: "save-access") { try await store.client.saveUserAccess(id: userID, libraryIDs: selected, canViewManualImports: manualImports) }
            if case .success = result { dismiss() }
        }
    }
}
