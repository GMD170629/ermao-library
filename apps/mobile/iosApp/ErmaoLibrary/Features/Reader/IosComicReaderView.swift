import ReadiumNavigator
import SwiftUI
@preconcurrency import ErmaoShared

struct IosComicReaderView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: IosComicReaderSession
    var onRetry: () -> Void = {}
    @State private var sliderPage = 0.0
    @State private var sliderIsEditing = false
    @State private var showsPages = false
    @State private var showsSettings = false
    @State private var pendingPageIndex: Int?
    @State private var navigationFailed = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()
            content
            if session.controlsVisible, session.phase == .reading || session.phase == .background {
                controls
            }
            if session.restoreWarning != nil {
                VStack {
                    Spacer()
                    HStack {
                        Text("reader.restore.warning.message")
                        Spacer()
                        Button { session.dismissRestoreWarning() } label: { Image(systemName: "xmark") }
                            .accessibilityLabel(Text("common.close"))
                    }
                    .padding()
                    .background(.regularMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                    .padding()
                }
            }
            if let snapshot = session.remoteProgressSnapshot,
               let location = snapshot.locator as? ErmaoShared.ComicPublicationLocation {
                IosPageRemoteProgressNotice(
                    snapshot: snapshot,
                    position: String(
                        format: String(localized: "reader.page.number.format"),
                        Int(location.pageIndex) + 1
                    ),
                    onOpen: { Task { await session.goToRemoteProgress() } },
                    onClose: session.dismissRemoteProgressNotice
                )
            }
        }
        .statusBarHidden(!session.controlsVisible)
        .accessibilityAction(named: Text("reader.controls.show")) { session.showControls() }
        .task {
            await session.open()
            await session.verifyRestoredLocationAfterPresentation()
            sliderPage = Double(session.pageIndex)
        }
        .onChange(of: session.pageIndex) { value in
            if !sliderIsEditing { sliderPage = Double(value) }
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
        .sheet(isPresented: $showsPages) {
            NavigationStack {
                List {
                    if navigationFailed { Text("reader.navigation.failed").foregroundStyle(.red) }
                    ForEach(session.pages, id: \.pageIndex) { page in
                    Button {
                        Task {
                            pendingPageIndex = page.pageIndex
                            navigationFailed = false
                            if await session.goToPage(page.pageIndex) { showsPages = false }
                            else { navigationFailed = true }
                            pendingPageIndex = nil
                        }
                    } label: {
                        HStack {
                            Text(page.title ?? String(
                                format: String(localized: "reader.comic.page.format"),
                                page.pageIndex + 1
                            ))
                            Spacer()
                            if page.pageIndex == session.pageIndex { Image(systemName: "location.fill") }
                            if pendingPageIndex == page.pageIndex { ProgressView() }
                        }
                    }
                    .disabled(pendingPageIndex != nil)
                    }
                }
                .navigationTitle("reader.toc")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { showsPages = false } } }
            }
            .presentationDetents([.medium, .large])
        }
        .sheet(isPresented: $showsSettings) { IosComicReaderSettingsSheet(session: session) }
        .alert(
            String(localized: "reader.error.title"),
            isPresented: Binding(
                get: { session.presentationError != nil },
                set: { _ in session.dismissPresentationError() }
            )
        ) {
            Button(String(localized: "common.ok"), role: .cancel) {}
        } message: { Text(session.presentationError?.localizedDescription ?? "") }
    }

    @ViewBuilder private var content: some View {
        switch session.phase {
        case .opening:
            ProgressView("reader.opening").tint(.white)
        case let .failed(code):
            VStack(spacing: 16) {
                Image(systemName: "exclamationmark.triangle").font(.largeTitle)
                Text("reader.error.title").font(.headline)
                Text(code.localizedDescription).multilineTextAlignment(.center)
                Button("reader.retry.open", action: onRetry)
                Button("common.close") { dismiss() }
            }
            .padding(24).foregroundStyle(.white)
        default:
            if let navigator = session.navigator {
                ComicNavigatorHost(navigator: navigator).ignoresSafeArea()
            }
        }
    }

    private var controls: some View {
        VStack {
            HStack {
                Button(action: close) { Image(systemName: "chevron.backward").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.close"))
                Text(session.displayTitle).font(.headline).lineLimit(1).frame(maxWidth: .infinity)
                Button { showsPages = true } label: { Image(systemName: "square.grid.2x2").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.toc"))
                Button { showsSettings = true } label: { Image(systemName: "gearshape").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.settings"))
            }
            .padding(.horizontal, 8).background(.regularMaterial)
            Spacer()
            VStack(spacing: 8) {
                HStack {
                    Button { Task { await session.goPrevious() } } label: {
                        Image(systemName: "chevron.backward").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text("reader.previous"))
                    Slider(
                        value: $sliderPage,
                        in: 0 ... Double(max(0, session.pageCount - 1)),
                        step: 1
                    ) { editing in
                        sliderIsEditing = editing
                        if !editing { Task { _ = await session.goToPage(Int(sliderPage.rounded())) } }
                    }
                    .accessibilityLabel(Text("reader.progress"))
                    .accessibilityValue(Text(session.pageLabel))
                    Button { Task { await session.goNext() } } label: {
                        Image(systemName: "chevron.forward").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text("reader.next"))
                }
                Text(session.pageLabel).font(.caption.monospacedDigit())
            }
            .padding(.horizontal, 16).padding(.vertical, 8).background(.regularMaterial)
        }
        .foregroundStyle(.primary)
    }

    private func close() {
        Task {
            try? await session.close()
            dismiss()
        }
    }
}

private struct IosComicReaderSettingsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: IosComicReaderSession
    @State private var draft: IosReaderPreferences
    @State private var applyFailed = false

    init(session: IosComicReaderSession) {
        self.session = session
        _draft = State(initialValue: session.preferences)
    }

    var body: some View {
        NavigationStack {
            Form {
                if applyFailed { Text("reader.preferences.apply.failed").foregroundStyle(.red) }
                Section("reader.settings.layout") {
                    Picker("reader.settings.readingMode", selection: $draft.comicFlow) {
                        Text("reader.mode.paged").tag(IosComicFlow.paginated)
                        Text("reader.mode.scroll").tag(IosComicFlow.scrolled)
                    }
                    Picker("reader.settings.spread", selection: $draft.comicSpread) {
                        Text("reader.spread.single").tag(IosComicSpread.single)
                        Text("reader.spread.double").tag(IosComicSpread.double)
                    }.disabled(draft.comicFlow == .scrolled)
                    Picker("reader.settings.comicDirection", selection: $draft.comicDirection) {
                        Text(verbatim: "LTR").tag(IosComicDirection.ltr)
                        Text(verbatim: "RTL").tag(IosComicDirection.rtl)
                    }.disabled(draft.comicFlow == .scrolled)
                    Toggle("reader.settings.coverSingle", isOn: $draft.comicCoverSingle)
                        .disabled(draft.comicFlow == .scrolled || draft.comicSpread != .double)
                    Picker("reader.settings.pageGap", selection: $draft.comicPageGap) {
                        ForEach([0, 8, 16, 24], id: \.self) { Text("\($0) px").tag($0) }
                    }.disabled(draft.comicFlow == .scrolled)
                }
            }
            .navigationTitle("reader.settings")
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("common.cancel") { dismiss() } }
                ToolbarItem(placement: .confirmationAction) {
                    Button("common.done") {
                        Task {
                            if await session.applyPreferences(draft) { dismiss() }
                            else { applyFailed = true }
                        }
                    }
                }
            }
        }.presentationDetents([.medium, .large])
    }
}

private struct ComicNavigatorHost: UIViewControllerRepresentable {
    let navigator: CBZNavigatorViewController
    func makeUIViewController(context: Context) -> CBZNavigatorViewController { navigator }
    func updateUIViewController(_ uiViewController: CBZNavigatorViewController, context: Context) {}
}
