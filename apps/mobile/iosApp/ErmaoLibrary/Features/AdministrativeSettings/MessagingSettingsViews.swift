import SwiftUI

struct EmailKindleSettingsView: View {
    enum Tab: Hashable { case kindle, smtp }
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<EmailKindleSnapshot> = .idle
    @State private var tab: Tab = .kindle
    @State private var kindle: KindleSettings?
    @State private var smtp: SMTPSettings?
    @State private var initialKindle: KindleSettings?
    @State private var initialSMTP: SMTPSettings?
    @State private var testSucceeded = false

    @Environment(\.administrativeCopy) private var copy

    var body: some View {
        VStack(spacing: 0) {
            SettingsTabPicker(verbatim: copy[.emailKindle], selection: $tab) {
                Text(copy[.kindleTab]).tag(Tab.kindle)
                if snapshot?.canManageSMTP == true { Text(copy[.smtpTab]).tag(Tab.smtp) }
            }
            .padding(.horizontal, .space2)
            .padding(.vertical, .space1)
            .disabled(store.operationInFlight != nil)

            AdministrativeStateView(state: state, retry: load) { _ in
                if tab == .kindle { kindleForm } else { smtpForm }
            }
            .disabled(store.operationInFlight != nil)
        }
        .settingsPageSurface()
        .navigationTitle(copy[.emailKindle])
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            if currentSettingsAreLoaded {
                ToolbarItem(placement: .confirmationAction) {
                    AdministrativeToolbarAction(
                        title: currentSaveTitle,
                        working: currentSaveIsWorking,
                        disabled: currentSaveIsDisabled,
                        action: saveCurrentTab
                    )
                }
            }
        }
        .task { await loadAsync() }
        .onDisappear { store.cancelPendingRequests() }
        .onChange(of: tab) { _, _ in testSucceeded = false }
        .onChange(of: smtp) { _, _ in testSucceeded = false }
    }

    private var snapshot: EmailKindleSnapshot? {
        guard case let .loaded(value) = state else { return nil }; return value
    }

    private var kindleForm: some View {
        Group {
            if let binding = Binding($kindle) {
                SettingsForm {
                Section(copy[.kindleRecipient]) {
                    SettingsTextInputRow(LocalizedStringKey(copy[.kindleRecipient])) {
                        TextField(LocalizedStringKey(copy[.kindleRecipient]), text: binding.recipient)
                            .keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                }
                Section {
                    SettingsValueRow(
                        verbatim: "SMTP",
                        value: binding.wrappedValue.smtpConfigured ? copy[.enabled] : copy[.disabled]
                    )
                    SettingsValueRow(
                        LocalizedStringKey(copy[.senderEmail]),
                        value: binding.wrappedValue.senderEmail.isEmpty ? "—" : binding.wrappedValue.senderEmail
                    )
                }
                }
                .administrativeNotice(store: store)
            } else {
                SettingsLoadingState(title: LocalizedStringKey(copy[.loading]))
            }
        }
    }

    private var smtpForm: some View {
        Group {
            if let binding = Binding($smtp) {
                SettingsForm {
                Section {
                    SettingsTextInputRow(LocalizedStringKey(copy[.smtpHost])) {
                        TextField(LocalizedStringKey(copy[.smtpHost]), text: binding.host)
                            .textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                    SettingsTextInputRow(LocalizedStringKey(copy[.smtpPort])) {
                        TextField(LocalizedStringKey(copy[.smtpPort]), value: binding.port, format: .number)
                            .keyboardType(.numberPad)
                    }
                    SettingsFieldRow(LocalizedStringKey(copy[.smtpEncryption])) {
                        Picker(LocalizedStringKey(copy[.smtpEncryption]), selection: binding.encryption) {
                            ForEach(SMTPEncryption.allCases, id: \.self) { value in
                                Text(encryptionTitle(value)).tag(value)
                            }
                        }
                    }
                    SettingsTextInputRow(LocalizedStringKey(copy[.senderEmail])) {
                        TextField(LocalizedStringKey(copy[.senderEmail]), text: binding.senderEmail)
                            .keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                    }
                    SettingsTextInputRow(LocalizedStringKey(copy[.username])) {
                        TextField(LocalizedStringKey(copy[.username]), text: binding.username).textInputAutocapitalization(.never)
                    }
                    SettingsTextInputRow(LocalizedStringKey(copy[.senderName])) {
                        TextField(LocalizedStringKey(copy[.senderName]), text: binding.senderName)
                    }
                    SettingsTextInputRow(LocalizedStringKey(copy[.maximumAttachment])) {
                        TextField(LocalizedStringKey(copy[.maximumAttachment]), value: binding.maximumAttachmentMegabytes, format: .number)
                            .keyboardType(.decimalPad)
                    }
                    SettingsTextInputRow(LocalizedStringKey(copy[.password])) {
                        SecureField(
                            LocalizedStringKey(binding.wrappedValue.hasPassword ? copy[.passwordConfigured] : copy[.password]),
                            text: binding.replacementPassword
                        )
                    }
                }
                Section {
                    SettingsActionRow(
                        LocalizedStringKey(testSucceeded ? copy[.smtpTestSucceeded] : copy[.sendTestEmail])
                    ) { testSMTP() }
                    .disabled(smtpTestIsDisabled)
                }
                }
                .administrativeNotice(store: store)
            } else {
                SettingsLoadingState(title: LocalizedStringKey(copy[.loading]))
            }
        }
    }

    private var currentSettingsAreLoaded: Bool {
        switch tab {
        case .kindle: kindle != nil
        case .smtp: smtp != nil
        }
    }
    private var currentSaveTitle: String {
        tab == .kindle ? copy[.saveKindle] : copy[.saveSMTP]
    }
    private var currentSaveIsWorking: Bool {
        store.operationInFlight == (tab == .kindle ? "save-kindle" : "save-smtp")
    }
    private var currentSaveIsDisabled: Bool {
        if store.operationInFlight != nil { return true }
        switch tab {
        case .kindle:
            guard let kindle, let initialKindle else { return true }
            return !isValidKindleEmail(kindle.recipient) || kindle == initialKindle
        case .smtp:
            guard let smtp, let initialSMTP else { return true }
            return !isValidSMTP(smtp) || smtp == initialSMTP
        }
    }
    private var smtpTestIsDisabled: Bool {
        guard let smtp else { return true }
        return store.operationInFlight != nil || !isValidSMTP(smtp)
    }
    private func saveCurrentTab() {
        switch tab {
        case .kindle:
            if let kindle { saveKindle(kindle) }
        case .smtp:
            if let smtp { saveSMTP(smtp) }
        }
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async {
        state = .loading
        let loaded = await store.load(scope: "email-kindle") { try await store.client.loadEmailAndKindle() }
        state = loaded
        if case let .loaded(value) = loaded {
            kindle = value.kindle
            smtp = value.smtp
            initialKindle = value.kindle
            initialSMTP = value.smtp
        }
    }
    private func saveKindle(_ value: KindleSettings) {
        guard store.operationInFlight == nil, isValidKindleEmail(value.recipient) else { return }
        Task {
            let result = await store.performValue(id: "save-kindle") { try await store.client.saveKindle(value) }
            if case let .success(updated) = result {
                kindle = updated
                initialKindle = updated
            }
        }
    }
    private func saveSMTP(_ value: SMTPSettings) {
        guard store.operationInFlight == nil, isValidSMTP(value) else { return }
        Task {
            let result = await store.performValue(id: "save-smtp") { try await store.client.saveSMTP(value) }
            if case let .success(updated) = result {
                smtp = updated
                initialSMTP = updated
            }
        }
    }
    private func testSMTP() {
        guard let smtp, isValidSMTP(smtp), store.operationInFlight == nil else { return }
        Task {
            let ok = await store.perform(id: "test-smtp", success: .smtpTestSucceeded) { try await store.client.sendSMTPTest(smtp) }
            if ok { testSucceeded = true }
        }
    }
    private func isValidSMTP(_ value: SMTPSettings) -> Bool {
        guard AdministrativeInputValidation.isValidSMTPHost(value.host),
              AdministrativeInputValidation.isValidSMTPPort(value.port),
              AdministrativeInputValidation.isValidEmail(value.senderEmail) else { return false }
        guard let maximumAttachment = value.maximumAttachmentMegabytes else { return true }
        return AdministrativeInputValidation.isValidAttachmentMegabytes(maximumAttachment)
    }
    private func isValidKindleEmail(_ rawValue: String) -> Bool {
        AdministrativeInputValidation.isValidOptionalEmail(rawValue)
    }
    private func encryptionTitle(_ value: SMTPEncryption) -> String {
        switch value {
        case .none: copy[.noEncryption]
        case .startTLS: "STARTTLS"
        case .tls: "TLS"
        }
    }
}

struct KindleQueueView: View {
    enum Filter: Hashable { case all, sending, failed }
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[KindleSendTask]> = .idle
    @State private var filter: Filter = .all
    @State private var taskToDelete: KindleSendTask?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(spacing: 0) {
            Picker(copy[.kindleQueueTitle], selection: $filter) {
                Text(copy[.all]).tag(Filter.all); Text(copy[.sending]).tag(Filter.sending); Text(copy[.failed]).tag(Filter.failed)
            }
            .pickerStyle(.segmented).padding(.horizontal, .space2).padding(.vertical, .space1)
            AdministrativeStateView(state: state, retry: load) { tasks in
                SettingsList { ForEach(filtered(tasks)) { task in taskRow(task) } }
                    .overlay { if filtered(tasks).isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "paperplane") } }
            }
            .disabled(store.operationInFlight != nil)
        }
        .settingsPageSurface()
        .navigationTitle(copy[.kindleQueueTitle])
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.refresh], action: load).disabled(store.operationInFlight != nil) } }
        .confirmationDialog(copy[.deleteKindleTitle], isPresented: Binding(get: { taskToDelete != nil }, set: { if !$0 { taskToDelete = nil } }), titleVisibility: .visible) {
            if let taskToDelete { Button(copy[.delete], role: .destructive) { delete(taskToDelete) }.disabled(store.operationInFlight != nil) }
            Button(copy[.cancel], role: .cancel) { taskToDelete = nil }
        } message: { Text(copy[.deleteKindleMessage]) }
        .task { await loadAsync() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }

    private func taskRow(_ task: KindleSendTask) -> some View {
        VStack(alignment: .leading, spacing: .space1) {
            HStack { Text(task.title).appTextStyle(.headline); Spacer(); status(task) }
            Text(task.recipientMasked).foregroundStyle(theme.textSecondary).textSelection(.enabled)
            if let progress = task.progress, task.status == .sending { ProgressView(value: progress).tint(theme.brandAccent) }
            HStack {
                Text(task.createdAt.administrativeFormatted(locale: copy.locale)).appTextStyle(.caption).foregroundStyle(theme.textTertiary)
                Spacer()
                if task.canCancel { Button(copy[.cancel]) { cancel(task) } }
                if task.canRetry { Button(copy[.retry]) { retry(task) } }
                if task.canDelete { Button(copy[.delete], role: .destructive) { taskToDelete = task } }
            }
            .buttonStyle(.borderless)
            .disabled(store.operationInFlight != nil)
        }
        .padding(.vertical, .spaceHalf)
    }

    private func status(_ task: KindleSendTask) -> some View {
        let title: String; let color: Color
        switch task.status { case .queued: title = copy[.queued]; color = .secondary; case .sending: title = copy[.sending]; color = theme.actionAccent; case .sent: title = copy[.sent]; color = .green; case .failed: title = copy[.failed]; color = .red; case .cancelled: title = copy[.cancelled]; color = .secondary; case .unknown: title = copy[.unknown]; color = .secondary }
        return Text(title).appTextStyle(.label).foregroundStyle(color)
    }
    private func filtered(_ tasks: [KindleSendTask]) -> [KindleSendTask] {
        switch filter { case .all: tasks; case .sending: tasks.filter { $0.status == .sending || $0.status == .queued }; case .failed: tasks.filter { $0.status == .failed } }
    }
    private func load() { Task { await loadAsync() } }
    private func loadAsync() async {
        state = .loading
        state = await store.load(scope: "kindle-queue") { try await store.client.loadKindleTasks(status: nil) }
    }
    private func cancel(_ task: KindleSendTask) { mutate("cancel-kindle-\(task.id)") { try await store.client.cancelKindleTask(id: task.id) } }
    private func retry(_ task: KindleSendTask) { mutate("retry-kindle-\(task.id)") { try await store.client.retryKindleTask(id: task.id) } }
    private func delete(_ task: KindleSendTask) { taskToDelete = nil; mutate("delete-kindle-\(task.id)") { try await store.client.deleteKindleTask(id: task.id) } }
    private func mutate(_ id: String, operation: @escaping @Sendable () async throws -> Void) {
        guard store.operationInFlight == nil else { return }
        Task { if await store.perform(id: id, operation: operation) { await loadAsync() } }
    }
}
