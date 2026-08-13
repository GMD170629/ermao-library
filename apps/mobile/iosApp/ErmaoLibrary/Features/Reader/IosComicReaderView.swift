import ReadiumNavigator
import SwiftUI

struct IosComicReaderView: View {
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: IosComicReaderSession
    @State private var sliderPage = 0.0
    @State private var sliderIsEditing = false
    @State private var showsPages = false
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
                    .padding()
                    .background(.regularMaterial)
                    .clipShape(RoundedRectangle(cornerRadius: 14))
                    .padding()
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
        .sheet(isPresented: $showsPages) {
            NavigationStack {
                List(session.pages, id: \.pageIndex) { page in
                    Button {
                        Task { await session.goToPage(page.pageIndex); showsPages = false }
                    } label: {
                        HStack {
                            Text(String(format: String(localized: "reader.comic.page.format"), page.pageIndex + 1))
                            Spacer()
                            if page.pageIndex == session.pageIndex { Image(systemName: "location.fill") }
                        }
                    }
                }
                .navigationTitle("reader.toc")
                .toolbar { ToolbarItem(placement: .confirmationAction) { Button("common.done") { showsPages = false } } }
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

private struct ComicNavigatorHost: UIViewControllerRepresentable {
    let navigator: EPUBNavigatorViewController
    func makeUIViewController(context: Context) -> EPUBNavigatorViewController { navigator }
    func updateUIViewController(_ uiViewController: EPUBNavigatorViewController, context: Context) {}
}
