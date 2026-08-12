import SwiftUI

struct ReaderPOCRootView: View {
    @StateObject private var store = ReaderPOCStore()

    var body: some View {
        NavigationStack {
            List(FixtureCatalog.all) { fixture in
                NavigationLink {
                    FixtureDetailView(descriptor: fixture, store: store)
                } label: {
                    FixtureRow(descriptor: fixture)
                }
                .accessibilityIdentifier("fixture.\(fixture.id)")
            }
            .navigationTitle(String(localized: "app.title"))
            .safeAreaInset(edge: .bottom) {
                Text(String(localized: "app.runtimeBoundary"))
                    .font(.caption)
                    .foregroundStyle(POCTheme.textSecondary)
                    .frame(maxWidth: .infinity)
                    .padding(12)
                    .background(.bar)
            }
        }
        .tint(POCTheme.actionAccent)
    }
}

private struct FixtureRow: View {
    let descriptor: FixtureDescriptor

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: descriptor.bundledURL() == nil ? "questionmark.square.dashed" : "book.closed")
                .foregroundStyle(descriptor.bundledURL() == nil ? .orange : POCTheme.actionAccent)
                .frame(width: 32)
            VStack(alignment: .leading, spacing: 4) {
                Text(descriptor.filename).font(.headline)
                Text(String(localized: String.LocalizationValue(descriptor.featureKey)))
                    .font(.subheadline)
                    .foregroundStyle(POCTheme.textSecondary)
            }
            Spacer()
            Text(descriptor.fileExtension.uppercased())
                .font(.caption.monospaced())
                .foregroundStyle(POCTheme.textSecondary)
        }
        .padding(.vertical, 4)
    }
}

private struct FixtureDetailView: View {
    let descriptor: FixtureDescriptor
    @ObservedObject var store: ReaderPOCStore

    @State private var readerPresented = false
    @State private var detailSelection = DetailSection.summary

    var body: some View {
        Group {
            switch store.state {
            case .idle:
                POCUnavailableView(
                    title: String(localized: "fixture.readyToLoad"),
                    systemImage: "waveform.path.ecg",
                    description: String(localized: String.LocalizationValue(descriptor.featureKey))
                ) {
                    loadButton
                }
            case .loading:
                ProgressView(String(localized: "fixture.extracting"))
            case let .failed(message):
                POCUnavailableView(
                    title: String(localized: "fixture.failed"),
                    systemImage: "exclamationmark.triangle",
                    description: message
                ) {
                    loadButton
                }
            case let .loaded(loaded):
                loadedContent(loaded)
            }
        }
        .navigationTitle(descriptor.filename)
        .navigationBarTitleDisplayMode(.inline)
        .task {
            if store.selectedFixtureID != descriptor.id {
                store.select(descriptor)
            }
        }
    }

    private var loadButton: some View {
        Button(String(localized: "action.extractAndBuild")) {
            Task { await store.load(descriptor) }
        }
        .buttonStyle(.borderedProminent)
        .accessibilityIdentifier("fixture.\(descriptor.id).load")
    }

    @ViewBuilder
    private func loadedContent(_ loaded: ReaderPOCStore.LoadedFixture) -> some View {
        VStack(spacing: 0) {
            Picker(String(localized: "detail.section"), selection: $detailSelection) {
                ForEach(DetailSection.allCases) { section in
                    Text(section.localizedTitle).tag(section)
                }
            }
            .pickerStyle(.segmented)
            .padding(16)

            switch detailSelection {
            case .summary:
                summary(loaded)
            case .resources:
                resourceList(loaded)
            case .toc:
                tocList(loaded)
            case .manifest:
                manifest(loaded)
            case .log:
                logView
            }
        }
        .safeAreaInset(edge: .bottom) {
            Button(String(localized: "action.openNavigator")) {
                readerPresented = true
            }
            .buttonStyle(.borderedProminent)
            .frame(maxWidth: .infinity)
            .padding(16)
            .background(.bar)
            .accessibilityIdentifier("fixture.\(descriptor.id).openNavigator")
        }
        .fullScreenCover(isPresented: $readerPresented) {
            ReaderScreen(loaded: loaded)
        }
    }

    private func summary(_ loaded: ReaderPOCStore.LoadedFixture) -> some View {
        List {
            Section(String(localized: "summary.publication")) {
                LabeledContent(String(localized: "summary.title"), value: loaded.result.book.metadata.title)
                LabeledContent(String(localized: "summary.format"), value: loaded.result.book.format.rawValue)
                LabeledContent(String(localized: "summary.language"), value: loaded.result.book.metadata.language ?? "—")
                LabeledContent(String(localized: "summary.progression"), value: loaded.result.book.metadata.readingProgression.rawValue)
            }
            Section(String(localized: "summary.preflight")) {
                LabeledContent(String(localized: "summary.buildTime"), value: milliseconds(loaded.publicationBuildMilliseconds))
                LabeledContent(String(localized: "summary.grade"), value: loaded.performanceGrade.rawValue)
                LabeledContent(String(localized: "summary.resources"), value: "\(loaded.result.preflight.resourceCount)")
                LabeledContent(String(localized: "summary.bytes"), value: ByteCountFormatter.string(fromByteCount: Int64(loaded.result.preflight.totalBytes), countStyle: .file))
                LabeledContent(String(localized: "summary.references"), value: "\(loaded.result.preflight.verifiedReferenceCount)")
            }
            if !loaded.result.book.warnings.isEmpty {
                Section(String(localized: "summary.warnings")) {
                    ForEach(loaded.result.book.warnings) { warning in
                        VStack(alignment: .leading, spacing: 4) {
                            Text(warning.code.rawValue).font(.caption.monospaced()).foregroundStyle(.orange)
                            Text(warning.message).font(.footnote)
                        }
                    }
                }
            }
        }
    }

    private func resourceList(_ loaded: ReaderPOCStore.LoadedFixture) -> some View {
        List(loaded.result.book.allResources) { resource in
            VStack(alignment: .leading, spacing: 4) {
                Text(resource.href).font(.subheadline.monospaced())
                Text("\(resource.mediaType) · \(ByteCountFormatter.string(fromByteCount: Int64(resource.data.count), countStyle: .file))")
                    .font(.caption)
                    .foregroundStyle(POCTheme.textSecondary)
            }
        }
    }

    @ViewBuilder
    private func tocList(_ loaded: ReaderPOCStore.LoadedFixture) -> some View {
        if loaded.result.book.tableOfContents.isEmpty {
            POCUnavailableView(
                title: String(localized: "toc.empty"),
                systemImage: "list.bullet.indent"
            )
        } else {
            List {
                ForEach(loaded.result.book.tableOfContents) { item in
                    TOCNodeView(item: item)
                }
            }
        }
    }

    private func manifest(_ loaded: ReaderPOCStore.LoadedFixture) -> some View {
        ScrollView([.horizontal, .vertical]) {
            Text(loaded.result.publication.jsonManifest ?? String(localized: "manifest.unavailable"))
                .font(.caption.monospaced())
                .textSelection(.enabled)
                .padding(16)
        }
    }

    private var logView: some View {
        List(store.eventLog, id: \.self) { line in
            Text(line).font(.caption.monospaced())
        }
    }

    private func milliseconds(_ value: Double) -> String {
        String(format: "%.1f ms", value)
    }
}

private struct POCUnavailableView<Action: View>: View {
    let title: String
    let systemImage: String
    let description: String?
    @ViewBuilder let action: Action

    init(
        title: String,
        systemImage: String,
        description: String? = nil,
        @ViewBuilder action: () -> Action
    ) {
        self.title = title
        self.systemImage = systemImage
        self.description = description
        self.action = action()
    }

    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: systemImage)
                .font(.system(size: 38))
                .foregroundStyle(POCTheme.textSecondary)
            Text(title)
                .font(.title3.weight(.semibold))
                .multilineTextAlignment(.center)
            if let description {
                Text(description)
                    .font(.body)
                    .foregroundStyle(POCTheme.textSecondary)
                    .multilineTextAlignment(.center)
            }
            action
        }
        .frame(maxWidth: 520)
        .padding(32)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

private extension POCUnavailableView where Action == EmptyView {
    init(title: String, systemImage: String, description: String? = nil) {
        self.init(title: title, systemImage: systemImage, description: description) {
            EmptyView()
        }
    }
}

private struct TOCNodeView: View {
    let item: MobiNavigationItem

    var body: some View {
        if item.children.isEmpty {
            label
        } else {
            DisclosureGroup {
                ForEach(item.children) { child in
                    TOCNodeView(item: child)
                }
            } label: {
                label
            }
        }
    }

    private var label: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(item.title)
            Text(item.href).font(.caption.monospaced()).foregroundStyle(POCTheme.textSecondary)
        }
    }
}

private enum DetailSection: String, CaseIterable, Identifiable {
    case summary
    case resources
    case toc
    case manifest
    case log

    var id: String { rawValue }
    var localizedTitle: String { String(localized: String.LocalizationValue("detail.\(rawValue)")) }
}
