import SwiftUI
@preconcurrency import ErmaoShared

struct IosPdfReaderView: View {
    @Environment(\.colorScheme) private var colorScheme
    @Environment(\.dismiss) private var dismiss
    @Environment(\.scenePhase) private var scenePhase
    @ObservedObject var session: IosPdfReaderSession
    var onRetry: () -> Void = {}

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                palette.background.ignoresSafeArea()
                IosReaderContentStatusLayout(session: session) {
                    content
                        .frame(width: readerContentWidth(available: geometry.size.width, preferred: session.preferences.pdfPageWidth))
                }
                if session.phase == .reading || session.phase == .background {
                    IosReaderControls(session: session, onClose: close)
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
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("reader.pdf.screen")
        .statusBarHidden(!session.controlsVisible)
        .accessibilityAction(named: Text("reader.controls.show")) { session.showControls() }
        .task {
            await session.open()
            await session.verifyRestoredLocationAfterPresentation()
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
                PdfiumNavigatorHost(
                    navigator: navigator,
                    backgroundColor: UIColor(palette.background)
                )
                .ignoresSafeArea()
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

private struct PdfiumNavigatorHost: UIViewControllerRepresentable {
    let navigator: IosPdfiumNavigatorViewController
    let backgroundColor: UIColor

    func makeUIViewController(context: Context) -> IosPdfiumNavigatorViewController {
        navigator.setReaderBackgroundColor(backgroundColor)
        return navigator
    }

    func updateUIViewController(
        _ uiViewController: IosPdfiumNavigatorViewController,
        context: Context
    ) {
        uiViewController.setReaderBackgroundColor(backgroundColor)
    }
}
