import ReadiumNavigator
import SwiftUI

struct IosEpubReaderView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: IosEpubReaderSession
    @State private var showingTOC = false
    @State private var showingSettings = false
    @State private var closingFailure = false
    @State private var sliderValue = 0.0
    @State private var sliderIsEditing = false

    var body: some View {
        ZStack {
            readerBackground.ignoresSafeArea()
            content
            if session.controlsVisible, session.phase == .reading || session.phase == .background {
                controls
                    .transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.18), value: session.controlsVisible)
        .accessibilityAction(named: Text("reader.controls.show")) {
            session.showControls()
        }
        .statusBarHidden(!session.controlsVisible)
        .task { await session.open() }
        .onChange(of: session.progress) { value in
            if !sliderIsEditing { sliderValue = value }
        }
        .onChange(of: scenePhase) { phase in
            Task {
                switch phase {
                case .background: await session.enterBackground()
                case .active: session.becomeActive()
                default: break
                }
            }
        }
        .sheet(isPresented: $showingTOC) { ReaderTOCSheet(session: session) }
        .sheet(isPresented: $showingSettings) { ReaderSettingsSheet(session: session) }
        .alert(String(localized: "reader.save.failure.title"), isPresented: $closingFailure) {
            Button(String(localized: "common.ok"), role: .cancel) {}
        } message: {
            Text("reader.save.failure.message")
        }
        .alert(
            String(localized: "reader.restore.warning.title"),
            isPresented: Binding(
                get: { session.restoreWarning != nil },
                set: { _ in session.dismissRestoreWarning() }
            )
        ) {
            Button(String(localized: "common.ok"), role: .cancel) {}
        } message: {
            Text("reader.restore.warning.message")
        }
        .alert(
            String(localized: "reader.error.title"),
            isPresented: Binding(
                get: { session.presentationError != nil && !closingFailure },
                set: { _ in session.dismissPresentationError() }
            )
        ) {
            Button(String(localized: "common.ok"), role: .cancel) {}
        } message: {
            Text(session.presentationError?.localizedDescription ?? "")
        }
    }

    @ViewBuilder
    private var content: some View {
        switch session.phase {
        case .opening:
            ProgressView("reader.opening")
        case let .failed(code):
            VStack(spacing: 16) {
                Image(systemName: "exclamationmark.triangle")
                    .font(.largeTitle)
                Text("reader.error.title").font(.headline)
                Text(code.localizedDescription)
                    .multilineTextAlignment(.center)
                Button("common.close") { dismiss() }
            }
            .padding(24)
        default:
            if let navigator = session.navigator {
                ReadiumNavigatorHost(navigator: navigator)
                    .ignoresSafeArea()
            }
        }
    }

    private var controls: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                Button(action: close) {
                    Image(systemName: "chevron.backward")
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel(Text("reader.close"))

                VStack(spacing: 2) {
                    Text(session.displayTitle)
                        .font(.headline)
                        .lineLimit(1)
                    if let chapter = session.chapterTitle {
                        Text(chapter).font(.caption).lineLimit(1).foregroundStyle(.secondary)
                    }
                }
                .frame(maxWidth: .infinity)

                Button { showingSettings = true } label: {
                    Image(systemName: "textformat.size")
                        .frame(width: 44, height: 44)
                }
                .accessibilityLabel(Text("reader.settings"))
            }
            .padding(.horizontal, 8)
            .background(.ultraThinMaterial)

            Spacer()

            VStack(spacing: 8) {
                HStack {
                    Text(session.progress, format: .percent.precision(.fractionLength(0)))
                        .font(.caption.monospacedDigit())
                    Slider(value: $sliderValue, in: 0 ... 1) { editing in
                        sliderIsEditing = editing
                        if !editing { Task { await session.goToProgression(sliderValue) } }
                    }
                    .accessibilityLabel(Text("reader.progress"))
                }
                HStack {
                    ReaderControlButton(title: "reader.previous", systemImage: "chevron.backward") {
                        Task { await session.goPrevious() }
                    }
                    ReaderControlButton(title: "reader.toc", systemImage: "list.bullet") {
                        showingTOC = true
                    }
                    ReaderControlButton(title: "reader.settings", systemImage: "textformat.size") {
                        showingSettings = true
                    }
                    ReaderControlButton(title: "reader.next", systemImage: "chevron.forward") {
                        Task { await session.goNext() }
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(.ultraThinMaterial)
        }
        .foregroundStyle(foregroundColor)
    }

    private var readerBackground: Color {
        switch session.preferences.theme {
        case .paper: Color(red: 0.98, green: 0.96, blue: 0.91)
        case .night: Color(red: 0.06, green: 0.06, blue: 0.07)
        case .system: Color(uiColor: .systemBackground)
        }
    }

    private var foregroundColor: Color {
        session.preferences.theme == .night ? .white : .primary
    }

    private func close() {
        Task {
            do {
                try await session.close()
                dismiss()
            } catch {
                closingFailure = true
            }
        }
    }
}

private struct ReadiumNavigatorHost: UIViewControllerRepresentable {
    let navigator: EPUBNavigatorViewController

    func makeUIViewController(context: Context) -> EPUBNavigatorViewController { navigator }
    func updateUIViewController(_ uiViewController: EPUBNavigatorViewController, context: Context) {}
}

private struct ReaderControlButton: View {
    let title: LocalizedStringKey
    let systemImage: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 3) {
                Image(systemName: systemImage).font(.title3)
                Text(title).font(.caption2)
            }
            .frame(maxWidth: .infinity, minHeight: 44)
        }
        .accessibilityLabel(Text(title))
    }
}

private struct ReaderTOCSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: IosEpubReaderSession

    var body: some View {
        NavigationStack {
            Group {
                if session.tableOfContents.isEmpty {
                    VStack(spacing: 12) {
                        Image(systemName: "list.bullet").font(.largeTitle)
                        Text("reader.toc.empty")
                    }
                    .foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
                } else {
                    List(session.tableOfContents) { entry in
                        Button {
                            Task {
                                await session.goToTOCEntry(entry)
                                dismiss()
                            }
                        } label: {
                            Text(entry.title)
                                .foregroundStyle(.primary)
                                .padding(.leading, CGFloat(entry.depth) * 16)
                        }
                    }
                }
            }
            .navigationTitle("reader.toc")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("common.done") { dismiss() }
                }
            }
        }
    }
}

private struct ReaderSettingsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: IosEpubReaderSession

    var body: some View {
        NavigationStack {
            Form {
                Section("reader.settings.typography") {
                    LabeledContent("reader.settings.fontSize") {
                        Slider(value: $session.preferences.fontSize, in: 0.75 ... 2, step: 0.05)
                    }
                    LabeledContent("reader.settings.lineHeight") {
                        Slider(value: $session.preferences.lineHeight, in: 1 ... 2, step: 0.1)
                    }
                    Toggle("reader.settings.publisherStyles", isOn: $session.preferences.publisherStyles)
                    Toggle("reader.settings.justify", isOn: $session.preferences.justifyText)
                }
                Section("reader.settings.appearance") {
                    Picker("reader.settings.theme", selection: $session.preferences.theme) {
                        Text("reader.theme.paper").tag(IosReaderTheme.paper)
                        Text("reader.theme.night").tag(IosReaderTheme.night)
                        Text("reader.theme.system").tag(IosReaderTheme.system)
                    }
                    Picker("reader.settings.readingMode", selection: $session.preferences.readingMode) {
                        Text("reader.mode.paged").tag(IosReaderReadingMode.paged)
                        Text("reader.mode.scroll").tag(IosReaderReadingMode.continuousScroll)
                    }
                }
            }
            .navigationTitle("reader.settings")
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("common.done") {
                        session.applyPreferences()
                        dismiss()
                    }
                }
            }
        }
    }
}
