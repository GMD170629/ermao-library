import SwiftUI

struct EmailKindleSettingsView: View {
    enum Tab: Hashable { case kindle, smtp }
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<EmailKindleSnapshot> = .idle
    @State private var tab: Tab = .kindle
    @State private var kindle: KindleSettings?
    @State private var smtp: SMTPSettings?
    @State private var testSucceeded = false

    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(spacing: 0) {
            Picker(copy[.emailKindle], selection: $tab) {
                Text(copy[.kindleTab]).tag(Tab.kindle)
                if snapshot?.canManageSMTP == true { Text(copy[.smtpTab]).tag(Tab.smtp) }
            }
            .pickerStyle(.segmented)
            .padding(.horizontal, .space2)
            .padding(.vertical, .space1)

            AdministrativeStateView(state: state, retry: load) { _ in
                if tab == .kindle { kindleForm } else { smtpForm }
            }
        }
        .background(theme.canvas)
        .navigationTitle(copy[.emailKindle])
        .navigationBarTitleDisplayMode(.inline)
        .task { await loadAsync() }
        .onDisappear { store.cancelPendingRequests() }
        .administrativeNotice(store: store)
    }

    private var snapshot: EmailKindleSnapshot? {
        guard case let .loaded(value) = state else { return nil }; return value
    }

    private var kindleForm: some View {
        Form {
            if let binding = Binding($kindle) {
                Section(copy[.kindleRecipient]) {
                    TextField(copy[.kindleRecipient], text: binding.recipient)
                        .keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                }
                Section {
                    LabeledContent("SMTP") { Text(binding.wrappedValue.smtpConfigured ? copy[.enabled] : copy[.disabled]) }
                    LabeledContent(copy[.senderEmail], value: binding.wrappedValue.senderEmail.isEmpty ? "—" : binding.wrappedValue.senderEmail)
                }
                Section {
                    AdministrativeBottomAction(
                        title: copy[.saveKindle], working: store.operationInFlight == "save-kindle",
                        disabled: binding.wrappedValue.recipient.trimmingCharacters(in: .whitespaces).isEmpty
                    ) { saveKindle(binding.wrappedValue) }
                    .listRowInsets(EdgeInsets())
                }
            }
        }
        .administrativeListSurface()
    }

    private var smtpForm: some View {
        Form {
            if let binding = Binding($smtp) {
                Section {
                    TextField(copy[.smtpHost], text: binding.host)
                        .textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField(copy[.smtpPort], value: binding.port, format: .number)
                        .keyboardType(.numberPad)
                    Picker(copy[.smtpEncryption], selection: binding.encryption) {
                        ForEach(SMTPEncryption.allCases, id: \.self) { Text($0.rawValue).tag($0) }
                    }
                    TextField(copy[.senderEmail], text: binding.senderEmail)
                        .keyboardType(.emailAddress).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField(copy[.username], text: binding.username).textInputAutocapitalization(.never)
                    TextField(copy[.senderName], text: binding.senderName)
                    TextField(copy[.maximumAttachment], value: binding.maximumAttachmentMegabytes, format: .number)
                        .keyboardType(.decimalPad)
                    SecureField(binding.wrappedValue.hasPassword ? copy[.passwordConfigured] : copy[.password], text: binding.replacementPassword)
                }
                Section {
                    Button { testSMTP() } label: {
                        Label(testSucceeded ? copy[.smtpTestSucceeded] : copy[.sendTestEmail], systemImage: testSucceeded ? "checkmark.circle" : "paperplane")
                            .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                    }
                    .disabled(store.operationInFlight != nil)
                    AdministrativeBottomAction(
                        title: copy[.saveSMTP], working: store.operationInFlight == "save-smtp",
                        disabled: binding.wrappedValue.host.isEmpty || binding.wrappedValue.port < 1
                    ) { saveSMTP(binding.wrappedValue) }
                    .listRowInsets(EdgeInsets())
                }
            }
        }
        .administrativeListSurface()
    }

    private func load() { Task { await loadAsync() } }
    private func loadAsync() async {
        state = .loading
        let loaded = await store.load(scope: "email-kindle") { try await store.client.loadEmailAndKindle() }
        state = loaded
        if case let .loaded(value) = loaded { kindle = value.kindle; smtp = value.smtp }
    }
    private func saveKindle(_ value: KindleSettings) {
        Task {
            let result = await store.performValue(id: "save-kindle") { try await store.client.saveKindle(value) }
            if case let .success(updated) = result { kindle = updated }
        }
    }
    private func saveSMTP(_ value: SMTPSettings) {
        Task {
            let result = await store.performValue(id: "save-smtp") { try await store.client.saveSMTP(value) }
            if case let .success(updated) = result { smtp = updated }
        }
    }
    private func testSMTP() {
        Task {
            let ok = await store.perform(id: "test-smtp", success: .smtpTestSucceeded) { try await store.client.sendSMTPTest() }
            if ok { testSucceeded = true }
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
                List(filtered(tasks)) { task in taskRow(task) }
                    .listStyle(.plain).administrativeListSurface()
                    .overlay { if filtered(tasks).isEmpty { AdministrativeEmptyView(title: copy[.empty], systemImage: "paperplane") } }
            }
        }
        .background(theme.canvas)
        .navigationTitle(copy[.kindleQueueTitle])
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { ToolbarItem(placement: .topBarTrailing) { Button(copy[.refresh], action: load) } }
        .confirmationDialog(copy[.deleteKindleTitle], isPresented: Binding(get: { taskToDelete != nil }, set: { if !$0 { taskToDelete = nil } }), titleVisibility: .visible) {
            if let taskToDelete { Button(copy[.delete], role: .destructive) { delete(taskToDelete) } }
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
                if task.status == .sending || task.status == .queued { Button(copy[.cancel]) { cancel(task) } }
                if task.status == .failed { Button(copy[.retry]) { retry(task) } }
                Button(copy[.delete], role: .destructive) { taskToDelete = task }
            }
            .buttonStyle(.borderless)
        }
        .padding(.vertical, .spaceHalf)
        .listRowBackground(theme.surface)
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
        Task { if await store.perform(id: id, operation: operation) { await loadAsync() } }
    }
}
