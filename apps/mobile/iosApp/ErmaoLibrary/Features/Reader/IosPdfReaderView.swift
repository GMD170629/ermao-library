import ReadiumNavigator
import SwiftUI
@preconcurrency import ErmaoShared

struct IosPdfReaderView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: IosPdfReaderSession
    var onRetry: () -> Void = {}
    @State private var sliderPage = 0.0
    @State private var sliderIsEditing = false
    @State private var showsTableOfContents = false
    @State private var showsSettings = false
    @State private var pendingPageID: String?
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
                    .padding().background(.regularMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 14)).padding()
                }
            }
            if let snapshot = session.remoteProgressSnapshot,
               let location = snapshot.locator as? ErmaoShared.PdfPublicationLocation {
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
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reader.pdf.screen")
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
        .sheet(isPresented: $showsTableOfContents) {
            NavigationStack {
                Group {
                    if session.tableOfContents.isEmpty {
                        VStack(spacing: 12) {
                            Image(systemName: "list.bullet").font(.largeTitle)
                            Text("reader.toc.empty").multilineTextAlignment(.center)
                        }
                        .padding(24)
                    } else {
                        List {
                            if navigationFailed { Text("reader.navigation.failed").foregroundStyle(.red) }
                            ForEach(session.tableOfContents) { entry in
                            Button {
                                Task {
                                    pendingPageID = entry.id
                                    navigationFailed = false
                                    if await session.goToTOCEntry(entry) { showsTableOfContents = false }
                                    else { navigationFailed = true }
                                    pendingPageID = nil
                                }
                            } label: {
                                HStack {
                                    Text(entry.title).padding(.leading, CGFloat(entry.depth) * 16)
                                    Spacer()
                                    if pendingPageID == entry.id { ProgressView() }
                                }
                            }
                            .disabled(pendingPageID != nil)
                            }
                        }
                    }
                }
                .navigationTitle("reader.toc")
                .toolbar {
                    ToolbarItem(placement: .confirmationAction) {
                        Button("common.done") { showsTableOfContents = false }
                    }
                }
            }
            .presentationDetents([.medium, .large])
        }
        .sheet(isPresented: $showsSettings) { IosPdfReaderSettingsSheet(session: session) }
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
                PdfNavigatorHost(navigator: navigator).ignoresSafeArea()
            } else if let navigator = session.pdfiumNavigator {
                PdfiumNavigatorHost(navigator: navigator).ignoresSafeArea()
            }
        }
    }

    private var controls: some View {
        VStack {
            HStack {
                Button(action: close) { Image(systemName: "chevron.backward").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.close"))
                    .accessibilityIdentifier("reader.close")
                Text(session.displayTitle).font(.headline).lineLimit(1).frame(maxWidth: .infinity)
                Button { showsTableOfContents = true } label: {
                    Image(systemName: "list.bullet").frame(width: 44, height: 44)
                }.accessibilityLabel(Text("reader.toc"))
                    .accessibilityIdentifier("reader.toc")
                Button { showsSettings = true } label: { Image(systemName: "gearshape").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.settings"))
                Button { session.zoomOut() } label: { Image(systemName: "minus.magnifyingglass").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.pdf.zoom.out"))
                Button { session.zoomToFit() } label: { Image(systemName: "arrow.down.right.and.arrow.up.left").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.pdf.zoom.fit"))
                Button { session.zoomIn() } label: { Image(systemName: "plus.magnifyingglass").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.pdf.zoom.in"))
            }
            .padding(.horizontal, 8).background(.regularMaterial)
            Spacer()
            VStack(spacing: 8) {
                HStack {
                    Button { Task { await session.goPrevious() } } label: {
                        Image(systemName: "chevron.backward").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text("reader.previous"))
                        .accessibilityIdentifier("reader.previous")
                    Slider(
                        value: $sliderPage,
                        in: 0 ... Double(max(0, session.canonicalPageCount - 1)),
                        step: 1
                    ) { editing in
                        sliderIsEditing = editing
                        if !editing { Task { _ = await session.goToPage(Int(sliderPage.rounded())) } }
                    }
                    .accessibilityLabel(Text("reader.progress"))
                    .accessibilityValue(Text(session.pageLabel))
                    .accessibilityIdentifier("reader.progress")
                    Button { Task { await session.goNext() } } label: {
                        Image(systemName: "chevron.forward").frame(width: 44, height: 44)
                    }.accessibilityLabel(Text("reader.next"))
                        .accessibilityIdentifier("reader.next")
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

private struct IosPdfReaderSettingsSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var session: IosPdfReaderSession
    @State private var draft: IosReaderPreferences
    @State private var applyFailed = false

    init(session: IosPdfReaderSession) {
        self.session = session
        _draft = State(initialValue: session.preferences)
    }

    var body: some View {
        NavigationStack {
            Form {
                if applyFailed { Text("reader.preferences.apply.failed").foregroundStyle(.red) }
                Section("reader.settings.layout") {
                    ReaderValueSlider(
                        title: "reader.settings.pdfZoom",
                        value: $draft.pdfZoom,
                        range: 0.6 ... 2.4,
                        step: 0.1,
                        valueText: draft.pdfZoom.formatted(.percent.precision(.fractionLength(0)))
                    )
                    Picker("reader.settings.pdfFit", selection: $draft.pdfFit) {
                        Text("reader.settings.pdfFit.page").tag(IosPdfFit.page)
                        Text("reader.settings.pdfFit.width").tag(IosPdfFit.width)
                    }
                    Picker("reader.settings.pdfRotation", selection: $draft.pdfRotation) {
                        ForEach([0, 90, 180, 270], id: \.self) { Text("\($0)°").tag($0) }
                    }
                    Picker("reader.settings.pdfCrop", selection: $draft.pdfCropMargins) {
                        Text("reader.settings.pdfCrop.off").tag(IosPdfCropMargins.off)
                        Text("reader.settings.pdfCrop.auto").tag(IosPdfCropMargins.auto)
                    }
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

struct IosPageRemoteProgressNotice: View {
    let snapshot: ErmaoShared.ReaderProgressSnapshotV4
    let position: String
    let onOpen: () -> Void
    let onClose: () -> Void

    var body: some View {
        VStack {
            Spacer()
            HStack(spacing: 12) {
                Button(action: onOpen) {
                    Text(message).multilineTextAlignment(.leading)
                }
                .buttonStyle(.plain)
                Spacer(minLength: 4)
                Button(action: onClose) {
                    Image(systemName: "xmark").frame(width: 32, height: 32)
                }
                .accessibilityLabel(Text("common.close"))
            }
            .padding(14)
            .background(.regularMaterial)
            .clipShape(RoundedRectangle(cornerRadius: 14))
            .padding()
        }
        .accessibilityElement(children: .combine)
    }

    private var message: String {
        let date = Date(
            timeIntervalSince1970: TimeInterval(snapshot.effectiveCapturedAtEpochMillis) / 1_000
        )
        return String(
            format: String(localized: "reader.remote.notice.format"),
            locale: .current,
            position,
            date.formatted(date: .abbreviated, time: .shortened)
        )
    }
}

private struct PdfNavigatorHost: UIViewControllerRepresentable {
    let navigator: PDFNavigatorViewController
    func makeUIViewController(context: Context) -> PDFNavigatorViewController { navigator }
    func updateUIViewController(_ uiViewController: PDFNavigatorViewController, context: Context) {}
}

private struct PdfiumNavigatorHost: UIViewControllerRepresentable {
    let navigator: IosPdfiumNavigatorViewController
    func makeUIViewController(context: Context) -> IosPdfiumNavigatorViewController { navigator }
    func updateUIViewController(_ uiViewController: IosPdfiumNavigatorViewController, context: Context) {}
}
