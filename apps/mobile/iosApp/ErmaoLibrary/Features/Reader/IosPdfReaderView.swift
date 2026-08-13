import ReadiumNavigator
import SwiftUI

struct IosPdfReaderView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: IosPdfReaderSession
    @State private var sliderPage = 0.0
    @State private var sliderIsEditing = false
    @State private var showsTableOfContents = false
    @State private var closingFailure = false

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
                        List(session.tableOfContents) { entry in
                            Button {
                                Task { await session.goToTOCEntry(entry); showsTableOfContents = false }
                            } label: {
                                Text(entry.title).padding(.leading, CGFloat(entry.depth) * 16)
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
        .alert(String(localized: "reader.save.failure.title"), isPresented: $closingFailure) {
            Button(String(localized: "common.ok"), role: .cancel) {}
        } message: { Text("reader.save.failure.message") }
        .alert(
            String(localized: "reader.error.title"),
            isPresented: Binding(
                get: { session.presentationError != nil && !closingFailure },
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
                Button("common.close") { dismiss() }
            }
            .padding(24).foregroundStyle(.white)
        default:
            if let navigator = session.navigator {
                PdfNavigatorHost(navigator: navigator).ignoresSafeArea()
            }
        }
    }

    private var controls: some View {
        VStack {
            HStack {
                Button(action: close) { Image(systemName: "chevron.backward").frame(width: 44, height: 44) }
                    .accessibilityLabel(Text("reader.close"))
                Text(session.displayTitle).font(.headline).lineLimit(1).frame(maxWidth: .infinity)
                Button { showsTableOfContents = true } label: {
                    Image(systemName: "list.bullet").frame(width: 44, height: 44)
                }.accessibilityLabel(Text("reader.toc"))
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
                    Slider(
                        value: $sliderPage,
                        in: 0 ... Double(max(0, session.canonicalPageCount - 1)),
                        step: 1
                    ) { editing in
                        sliderIsEditing = editing
                        if !editing { Task { await session.goToPage(Int(sliderPage.rounded())) } }
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
            do { try await session.close(); dismiss() } catch { closingFailure = true }
        }
    }
}

private struct PdfNavigatorHost: UIViewControllerRepresentable {
    let navigator: PDFNavigatorViewController
    func makeUIViewController(context: Context) -> PDFNavigatorViewController { navigator }
    func updateUIViewController(_ uiViewController: PDFNavigatorViewController, context: Context) {}
}
