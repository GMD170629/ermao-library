import SwiftUI

struct MetadataProvidersView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<[MetadataProvider]> = .idle
    @State private var pipeline: MetadataPipeline?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme
    @Environment(\.administrativeNavigate) private var navigate

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { providers in
            List {
                Section(copy[.provider]) {
                    ForEach(Array(providers.enumerated()), id: \.element.id) { index, provider in
                        HStack {
                            Text("\(index + 1)").foregroundStyle(theme.textSecondary)
                            Button { navigate(.metadataProvider(providerID: provider.id)) } label: {
                                VStack(alignment: .leading) { Text(provider.displayName).appTextStyle(.headline); HStack { AdministrativeStatusLabel(title: providerStatus(provider), status: provider.status == .available ? .good : provider.status == .unavailable ? .failed : .neutral); if let milliseconds = provider.responseMilliseconds { Text("\(milliseconds) ms").font(.caption).foregroundStyle(theme.textSecondary) } } }
                            }
                            Toggle("", isOn: Binding(get: { provider.enabled }, set: { enabled in toggle(provider, enabled) })).labelsHidden()
                        }.frame(minHeight: .iosMinimumTouchTarget)
                    }
                }
                Section(copy[.queryPipeline]) { Button(copy[.editPriority]) { navigate(.metadataPipeline) }; if let pipeline { LabeledContent(copy[.mediaTypes], value: mediaTitle(pipeline.mediaKind)); LabeledContent(copy[.enabled], value: "\(pipeline.enabledProviderIDs.count)") } }
                Section { Button(copy[.testProviders]) { testAll(providers) }.frame(maxWidth: .infinity) }
            }.administrativeListSurface()
        }.navigationTitle(copy[.providersTitle]).navigationBarTitleDisplayMode(.inline).refreshable { await loadAsync() }.task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func providerStatus(_ provider: MetadataProvider) -> String { switch provider.status { case .available: copy[.available]; case .unavailable: copy[.unavailable]; case .untested: copy[.unknown] } }
    private func mediaTitle(_ value: MediaKind) -> String { switch value { case .ebook: copy[.ebook]; case .comic: copy[.comic]; case .audiobook: copy[.audiobook] } }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; async let providersState = store.load(scope: "providers") { try await store.client.loadMetadataProviders() }; async let loadedPipeline = store.loadValue(scope: "pipeline-summary") { try await store.client.loadMetadataPipeline() }; state = await providersState; pipeline = await loadedPipeline }
    private func toggle(_ provider: MetadataProvider, _ enabled: Bool) { Task { let result = await store.performValue(id: "provider-toggle-\(provider.id)") { try await store.client.setMetadataProviderEnabled(id: provider.id, enabled: enabled) }; if case .success = result { await loadAsync() } } }
    private func testAll(_ providers: [MetadataProvider]) { Task { for provider in providers where provider.enabled { let result = await store.performValue(id: "provider-test-\(provider.id)", success: .connected) { try await store.client.testMetadataProvider(id: provider.id) }; if case .success = result { continue } else { break } }; await loadAsync() } }
}

struct MetadataProviderDetailView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    let providerID: String
    @State private var state: AdministrativeLoadState<MetadataProviderConfiguration> = .idle
    @State private var configuration: MetadataProviderConfiguration?
    @State private var tested: MetadataProvider?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            if let binding = Binding($configuration) {
                Form {
                    Section(copy[.provider]) {
                        Text(binding.wrappedValue.provider.displayName).appTextStyle(.headline)
                        Text(binding.wrappedValue.provider.supportedMediaKinds.map(mediaTitle).sorted().joined(separator: ", ")).foregroundStyle(theme.textSecondary)
                    }
                    Section(copy[.connectionTest]) {
                        ForEach(binding.wrappedValue.values.keys.sorted(), id: \.self) { key in
                            editableField(key, binding: binding)
                        }
                    }
                    if let tested { Section(copy[.connectionTest]) { AdministrativeStatusLabel(title: tested.status == .available ? copy[.connected] : copy[.unavailable], status: tested.status == .available ? .good : .failed); if let milliseconds = tested.responseMilliseconds { LabeledContent(copy[.responseTime], value: "\(milliseconds) ms") } } }
                    Section { Button(copy[.saveAndTest]) { saveAndTest(binding.wrappedValue) }.frame(maxWidth: .infinity); AdministrativeBottomAction(title: copy[.saveConfiguration], working: store.operationInFlight == "save-provider") { save(binding.wrappedValue) }.listRowInsets(EdgeInsets()) }
                }.administrativeListSurface()
            }
        }.navigationTitle(copy[.providerConfigurationTitle]).navigationBarTitleDisplayMode(.inline).task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func mediaTitle(_ value: MediaKind) -> String { switch value { case .ebook: copy[.ebook]; case .comic: copy[.comic]; case .audiobook: copy[.audiobook] } }
    @ViewBuilder private func editableField(_ key: String, binding: Binding<MetadataProviderConfiguration>) -> some View {
        let value = binding.wrappedValue.values[key] ?? .empty
        switch value {
        case let .toggle(current):
            Toggle(key, isOn: Binding(get: { if case let .toggle(value) = binding.wrappedValue.values[key] { value } else { current } }, set: { binding.wrappedValue.values[key] = .toggle($0) }))
        case let .integer(current):
            LabeledContent(key) { TextField(key, value: Binding(get: { if case let .integer(value) = binding.wrappedValue.values[key] { value } else { current } }, set: { binding.wrappedValue.values[key] = .integer($0) }), format: .number).keyboardType(.numberPad).multilineTextAlignment(.trailing) }
        case let .decimal(current):
            LabeledContent(key) { TextField(key, value: Binding(get: { if case let .decimal(value) = binding.wrappedValue.values[key] { value } else { current } }, set: { binding.wrappedValue.values[key] = .decimal($0) }), format: .number).keyboardType(.decimalPad).multilineTextAlignment(.trailing) }
        case let .textList(current):
            TextField(key, text: Binding(get: { if case let .textList(value) = binding.wrappedValue.values[key] { value.joined(separator: ", ") } else { current.joined(separator: ", ") } }, set: { binding.wrappedValue.values[key] = .textList($0.split(separator: ",").map { $0.trimmingCharacters(in: .whitespaces) }) }))
        case let .text(current):
            TextField(key, text: Binding(get: { if case let .text(value) = binding.wrappedValue.values[key] { value } else { current } }, set: { binding.wrappedValue.values[key] = .text($0) })).textInputAutocapitalization(.never)
        case .empty:
            SecureField(copy[.keepSecretHint], text: Binding(get: { binding.wrappedValue.secretReplacements[key] ?? "" }, set: { binding.wrappedValue.secretReplacements[key] = $0 }))
        }
    }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "provider-\(providerID)") { try await store.client.loadMetadataProviderConfiguration(id: providerID) }; state = loaded; if case let .loaded(value) = loaded { configuration = value } }
    private func save(_ value: MetadataProviderConfiguration) { Task { let result = await store.performValue(id: "save-provider") { try await store.client.saveMetadataProviderConfiguration(value) }; if case let .success(updated) = result { configuration = updated; state = .loaded(updated) } } }
    private func saveAndTest(_ value: MetadataProviderConfiguration) { Task { let saveResult = await store.performValue(id: "save-provider") { try await store.client.saveMetadataProviderConfiguration(value) }; guard case let .success(updated) = saveResult else { return }; configuration = updated; let testResult = await store.performValue(id: "test-provider", success: .connected) { try await store.client.testMetadataProvider(id: providerID) }; if case let .success(result) = testResult { tested = result } } }
}

struct MetadataPipelineView: View {
    @ObservedObject var store: AdministrativeSettingsStore
    @State private var state: AdministrativeLoadState<MetadataPipeline> = .idle
    @State private var pipeline: MetadataPipeline?
    @Environment(\.administrativeCopy) private var copy
    @Environment(\.appTheme) private var theme

    var body: some View {
        AdministrativeStateView(state: state, retry: load) { _ in
            if let binding = Binding($pipeline) {
                Form {
                    Section(copy[.queryPipeline]) {
                        Picker(copy[.mediaTypes], selection: binding.mediaKind) { ForEach(MediaKind.allCases, id: \.self) { Text(mediaTitle($0)).tag($0) } }
                        ForEach(Array(binding.wrappedValue.providerIDs.enumerated()), id: \.element) { index, providerID in
                            HStack { Text("\(index + 1)"); Toggle(providerID, isOn: Binding(get: { binding.wrappedValue.enabledProviderIDs.contains(providerID) }, set: { enabled in if enabled { binding.wrappedValue.enabledProviderIDs.insert(providerID) } else { binding.wrappedValue.enabledProviderIDs.remove(providerID) } })); Spacer(); Button { move(index, -1) } label: { Image(systemName: "chevron.up") }.disabled(index == 0); Button { move(index, 1) } label: { Image(systemName: "chevron.down") }.disabled(index == binding.wrappedValue.providerIDs.count - 1) }
                        }
                    }
                }.administrativeListSurface().safeAreaInset(edge: .bottom) { AdministrativeBottomAction(title: copy[.saveConfiguration], working: store.operationInFlight == "save-pipeline") { save(binding.wrappedValue) } }
            }
        }.navigationTitle(copy[.queryPipeline]).navigationBarTitleDisplayMode(.inline).task { await loadAsync() }.onDisappear { store.cancelPendingRequests() }.administrativeNotice(store: store)
    }
    private func mediaTitle(_ value: MediaKind) -> String { switch value { case .ebook: copy[.ebook]; case .comic: copy[.comic]; case .audiobook: copy[.audiobook] } }
    private func move(_ index: Int, _ delta: Int) { guard var value = pipeline else { return }; value.providerIDs.swapAt(index, index + delta); pipeline = value }
    private func load() { Task { await loadAsync() } }; private func loadAsync() async { state = .loading; let loaded = await store.load(scope: "metadata-pipeline") { try await store.client.loadMetadataPipeline() }; state = loaded; if case let .loaded(value) = loaded { pipeline = value } }
    private func save(_ value: MetadataPipeline) { Task { let result = await store.performValue(id: "save-pipeline") { try await store.client.saveMetadataPipeline(value) }; if case let .success(updated) = result { pipeline = updated; state = .loaded(updated) } } }
}
