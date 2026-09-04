import ReadiumNavigator
import SwiftUI

struct IosComicReaderView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: IosComicReaderSession
    var onRetry: () -> Void = {}

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                palette.background.ignoresSafeArea()
                IosReaderContentStatusLayout(session: session) {
                    content
                        .frame(width: readerContentWidth(available: geometry.size.width, preferred: session.preferences.comicPageWidth))
                }
                if session.phase == .reading || session.phase == .background {
                    IosReaderControls(session: session, onClose: close)
                }
                if let snapshot = session.remoteProgressSnapshot {
                    IosPageRemoteProgressNotice(
                        snapshot: snapshot,
                        position: snapshot.position.presentation.page.map {
                            String(format: String(localized: "reader.page.number.format"), Int($0.number))
                        } ?? String(format: "%d%%", Int(snapshot.position.presentation.displayPercent.rounded())),
                        actionFailed: session.remoteProgressActionFailed,
                        onOpen: { Task { await session.goToRemoteProgress() } },
                        onClose: session.dismissRemoteProgressNotice
                    )
                }
            }
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reader.comic.screen")
        .statusBarHidden(!session.controlsVisible)
        .accessibilityAction(named: Text("reader.controls.show")) { session.showControls() }
        .task {
            await session.open()
            UIApplication.shared.isIdleTimerDisabled = session.preferences.keepScreenAwake
        }
        .onDisappear { UIApplication.shared.isIdleTimerDisabled = false }
        .onChange(of: scenePhase) { _, phase in
            Task {
                switch phase {
                case .background: await session.enterBackground()
                case .active: session.becomeActive()
                default: break
                }
            }
        }
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
            ProgressView("reader.opening").tint(palette.accent)
        case let .failed(code):
            VStack(spacing: 16) {
                Image(systemName: "exclamationmark.triangle").font(.largeTitle)
                Text("reader.error.title").font(.headline)
                Text(code.localizedDescription).multilineTextAlignment(.center)
                Button("reader.retry.open", action: onRetry)
                Button("common.close") { dismiss() }
            }
            .padding(24).foregroundStyle(palette.foreground)
        default:
            if let navigator = session.navigator {
                ComicNavigatorHost(navigator: navigator).ignoresSafeArea()
            }
        }
    }

    private var palette: ReaderPalette {
        ReaderPalette(theme: session.preferences.resolvedTheme(for: colorScheme == .dark ? .dark : .light))
    }

    private func close() {
        Task {
            try? await session.close()
            dismiss()
        }
    }
}

private struct ComicNavigatorHost: UIViewControllerRepresentable {
    let navigator: IosComicNavigatorViewController
    func makeUIViewController(context: Context) -> IosComicNavigatorViewController { navigator }
    func updateUIViewController(_ uiViewController: IosComicNavigatorViewController, context: Context) {}
}
