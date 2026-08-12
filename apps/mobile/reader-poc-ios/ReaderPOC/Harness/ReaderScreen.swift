import SwiftUI

struct ReaderScreen: View {
    @Environment(\.dismiss) private var dismiss
    let loaded: ReaderPOCStore.LoadedFixture

    @StateObject private var session = NavigatorSession()
    @State private var isRunningStress = false
    @State private var reportURL: URL?
    @State private var reportError: String?

    var body: some View {
        NavigationStack {
            ReaderNavigatorView(publication: loaded.result.publication, session: session)
                .background(POCTheme.readerPaper)
                .navigationTitle(loaded.result.book.metadata.title)
                .navigationBarTitleDisplayMode(.inline)
                .toolbar {
                    ToolbarItem(placement: .topBarLeading) {
                        Button(String(localized: "action.close")) { dismiss() }
                            .accessibilityIdentifier("reader.close")
                    }
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button(String(localized: "action.featureProbe")) {
                                Task { await session.evaluateFeatureProbe(fixtureID: loaded.descriptor.id) }
                            }
                            Button(String(localized: "action.saveReport")) {
                                saveReport()
                            }
                        } label: {
                            Label(String(localized: "action.more"), systemImage: "ellipsis.circle")
                        }
                    }
                }
                .safeAreaInset(edge: .bottom) {
                    controls
                }
        }
        .tint(POCTheme.actionAccent)
    }

    private var controls: some View {
        VStack(spacing: 8) {
            HStack(spacing: 24) {
                Button {
                    Task { _ = await session.navigator?.goBackward(options: .animated) }
                } label: {
                    Label(String(localized: "action.previousPage"), systemImage: "chevron.backward")
                }
                .accessibilityIdentifier("reader.previousPage")
                Button {
                    Task { _ = await session.navigator?.goForward(options: .animated) }
                } label: {
                    Label(String(localized: "action.nextPage"), systemImage: "chevron.forward")
                }
                .accessibilityIdentifier("reader.nextPage")
            }
            .labelStyle(.iconOnly)
            .font(.title2)

            Button {
                Task {
                    isRunningStress = true
                    await session.runPageTurnStress()
                    isRunningStress = false
                    saveReport()
                }
            } label: {
                if isRunningStress {
                    ProgressView(value: Double(session.pageTurnProgress), total: 500) {
                        Text(String(format: String(localized: "stress.progress"), session.pageTurnProgress))
                    }
                } else {
                    Text(String(localized: "action.run500Turns"))
                }
            }
            .disabled(isRunningStress || !session.isReady)
            .accessibilityIdentifier("reader.run500Turns")

            Button(String(localized: "action.featureProbe")) {
                Task { await session.evaluateFeatureProbe(fixtureID: loaded.descriptor.id) }
            }
            .disabled(!session.isReady)
            .accessibilityIdentifier("reader.runFeatureProbe")

            if let stress = session.lastStressResult {
                Text(String(format: String(localized: "stress.result"), stress.grade.rawValue, stress.p95Milliseconds))
                    .font(.caption.monospacedDigit())
                    .accessibilityIdentifier("reader.stressResult")
            }
            if !session.javascriptResult.isEmpty {
                Text(session.javascriptResult)
                    .font(.caption.monospaced())
                    .lineLimit(2)
                    .accessibilityIdentifier("reader.featureProbeResult")
            }
            if let reportURL {
                Text(String(format: String(localized: "report.saved"), reportURL.lastPathComponent))
                    .font(.caption)
            }
            if let reportError {
                Text(reportError).font(.caption).foregroundStyle(.red)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(16)
        .background(.regularMaterial)
    }

    private func saveReport() {
        do {
            reportURL = try TechnicalReportWriter.write(
                TechnicalReportWriter.makeReport(loaded: loaded, session: session)
            )
            reportError = nil
        } catch {
            reportError = error.localizedDescription
        }
    }
}
