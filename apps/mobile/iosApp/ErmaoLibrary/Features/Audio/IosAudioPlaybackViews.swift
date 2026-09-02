import SwiftUI
@preconcurrency import ErmaoShared

private enum AudioPresentation: String, Identifiable {
    case chapters
    case sleep

    var id: String { rawValue }
}

/// App-wide shell adapter. It provides the real safe-area inset for the mini
/// player and owns the only Now Playing presentation.
struct AudioApplicationHost<Content: View>: View {
    @ObservedObject var runtime: AudioPlaybackRuntime
    private let content: Content
    @State private var isNowPlayingPresented = false

    init(
        runtime: AudioPlaybackRuntime,
        @ViewBuilder content: () -> Content
    ) {
        self.runtime = runtime
        self.content = content()
    }

    var body: some View {
        content
            .safeAreaInset(edge: .bottom, spacing: 0) {
                if runtime.snapshot.hasSession {
                    AudioMiniPlayer(
                        snapshot: runtime.snapshot,
                        onToggle: runtime.togglePlayback,
                        onRetry: runtime.retry,
                        onExpand: { isNowPlayingPresented = true }
                    )
                    .padding(.horizontal, 8)
                    .padding(.bottom, 4)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
            .fullScreenCover(isPresented: $isNowPlayingPresented) {
                AudioNowPlayingView(runtime: runtime)
            }
            .environment(\.audioPlaybackRuntime, runtime)
            .onChange(of: runtime.snapshot.lifecycle) { _, lifecycle in
                if lifecycle == .idle { isNowPlayingPresented = false }
            }
            .onChange(of: runtime.nowPlayingPresentationRequestID) { _, requestID in
                if requestID != nil { isNowPlayingPresented = true }
            }
    }
}

private struct AudioMiniPlayer: View {
    let snapshot: AudioPlaybackSnapshot
    let onToggle: () -> Void
    let onRetry: () -> Void
    let onExpand: () -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: .space1) {
            Button(action: onExpand) {
                HStack(spacing: .space1) {
                    AudioArtworkView(size: 42)
                    VStack(alignment: .leading, spacing: 2) {
                        if let title = snapshot.bootstrap?.book.title, !title.isEmpty {
                            Text(title)
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(1)
                                .foregroundStyle(theme.textPrimary)
                        } else {
                            Text("audio.nowPlaying.loading")
                                .font(.subheadline.weight(.semibold))
                                .lineLimit(1)
                                .foregroundStyle(theme.textPrimary)
                        }
                        if let chapter = snapshot.chapter?.title ?? snapshot.track?.title,
                           !chapter.isEmpty {
                            Text(chapter)
                                .font(.caption)
                                .lineLimit(1)
                                .foregroundStyle(theme.textSecondary)
                        } else {
                            Text("audio.nowPlaying.loading")
                                .font(.caption)
                                .lineLimit(1)
                                .foregroundStyle(theme.textSecondary)
                        }
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text("audio.nowPlaying.open"))
            .accessibilityHint(Text("audio.nowPlaying.open.hint"))

            if snapshot.lifecycle == .buffering || snapshot.lifecycle == .loading {
                ProgressView()
                    .controlSize(.small)
                    .accessibilityLabel(Text("audio.state.buffering"))
            } else if snapshot.lifecycle == .error {
                Button(action: onRetry) {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .accessibilityLabel(Text("audio.action.retry"))
            }

            Button(action: onToggle) {
                Image(systemName: snapshot.isPlaying ? "pause.fill" : "play.fill")
                    .font(.headline)
            }
            .buttonStyle(.bordered)
            .buttonBorderShape(.circle)
            .controlSize(.regular)
            .tint(theme.textPrimary)
            .disabled(snapshot.lifecycle == .loading)
            .accessibilityLabel(Text(LocalizedStringKey(snapshot.isPlaying ? "audio.action.pause" : "audio.action.play")))
        }
        .padding(.horizontal, .space1Half)
        .padding(.vertical, .space1)
        .background(theme.surface, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .stroke(theme.divider.opacity(0.8), lineWidth: 1)
                .allowsHitTesting(false)
        }
        .overlay(alignment: .bottom) {
            ProgressView(value: progress, total: 1)
                .progressViewStyle(.linear)
                .tint(theme.brandAccent)
                .frame(height: 2)
                .padding(.horizontal, 2)
                .allowsHitTesting(false)
        }
        .accessibilityElement(children: .contain)
        .accessibilityIdentifier("audio.miniPlayer")
    }

    private var progress: Double {
        guard snapshot.totalDurationMillis > 0 else { return 0 }
        return min(1, max(0, Double(snapshot.absolutePositionMillis) / Double(snapshot.totalDurationMillis)))
    }
}

struct AudioNowPlayingView: View {
    @ObservedObject var runtime: AudioPlaybackRuntime
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme
    @State private var presentation: AudioPresentation?

    var body: some View {
        NavigationStack {
            GeometryReader { viewport in
                ScrollView {
                    VStack(spacing: 0) {
                        VStack(spacing: 0) {
                            AudioArtworkView(size: artworkSize(for: viewport.size))
                                .padding(.top, .space2)
                                .padding(.bottom, .space4)
                            identity
                        }

                        // Keep the controls anchored to the bottom on a comfortably sized
                        // screen. The minimum spacer remains scrollable on short screens.
                        Spacer(minLength: .space5)

                        VStack(spacing: 0) {
                            timeline
                            errorFeedback
                            primaryControls
                            secondaryControls
                        }
                    }
                    .frame(maxWidth: .infinity, minHeight: viewport.size.height, alignment: .top)
                    .padding(.horizontal, .space2)
                    .padding(.bottom, .space2)
                }
                .scrollIndicators(.hidden)
                .background(theme.surfaceRaised.ignoresSafeArea())
            }
            .navigationTitle("audio.nowPlaying.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbarBackground(theme.surfaceRaised, for: .navigationBar)
            .toolbarBackground(.visible, for: .navigationBar)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "chevron.down")
                            .foregroundStyle(theme.textPrimary)
                    }
                        .accessibilityLabel(Text("audio.action.collapse"))
                }
            }
            .sheet(item: $presentation) { value in
                switch value {
                case .chapters:
                    AudioChaptersSheet(runtime: runtime)
                case .sleep:
                    AudioSleepTimerSheet(runtime: runtime)
                }
            }
            .tint(theme.textPrimary)
        }
        .background(theme.surfaceRaised.ignoresSafeArea())
        .onDisappear {
            runtime.cancelScrubbing()
        }
        .accessibilityIdentifier("audio.nowPlaying")
    }

    @ViewBuilder
    private var identity: some View {
        VStack(spacing: 5) {
            if let title = runtime.snapshot.bootstrap?.book.title, !title.isEmpty {
                Text(title)
                    .font(.title2.weight(.semibold))
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
            } else {
                Text("audio.nowPlaying.loading")
                    .font(.title2.weight(.semibold))
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
            }
            if let author = runtime.snapshot.bootstrap?.book.author, !author.isEmpty {
                Text(author)
                    .font(.subheadline)
                    .foregroundStyle(theme.textSecondary)
                    .lineLimit(2)
            }
            if let chapter = runtime.snapshot.chapter?.title ?? runtime.snapshot.track?.title,
               !chapter.isEmpty {
                Text(chapter)
                    .font(.headline)
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
                    .padding(.top, 4)
            } else {
                Text("audio.nowPlaying.loading")
                    .font(.headline)
                    .multilineTextAlignment(.center)
                    .lineLimit(3)
                    .padding(.top, 4)
            }
        }
        .accessibilityElement(children: .combine)
    }

    private var timeline: some View {
        let maximumPosition = max(1, runtime.snapshot.totalDurationMillis)
        return VStack(spacing: 5) {
            Slider(
                value: Binding(
                    get: { Double(runtime.snapshot.absolutePositionMillis) },
                    set: { value in
                        runtime.updateScrubbing(to: Int64(clampedScrubValue(value).rounded()))
                    }
                ),
                in: 0...Double(maximumPosition),
                onEditingChanged: handleScrubEditingChanged
            )
            .tint(theme.brandAccent)
            .accessibilityLabel(Text("audio.timeline"))
            .accessibilityValue(Text("\(formattedTime(displayedPositionMillis)) / \(formattedTime(runtime.snapshot.totalDurationMillis))"))
            HStack {
                Text(formattedTime(displayedPositionMillis))
                Spacer()
                Text(formattedTime(runtime.snapshot.totalDurationMillis))
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(theme.textSecondary)
        }
        .padding(.top, 26)
        .disabled(isLoading)
    }

    private var primaryControls: some View {
        HStack(spacing: .space1) {
            AudioCircleButton(
                systemImage: "backward.end.fill",
                label: "audio.action.previous",
                action: runtime.previousChapter
            )
            AudioCircleButton(
                systemImage: "gobackward.15",
                label: "audio.action.seekBackward",
                action: runtime.skipBackward
            )
            Button(action: runtime.togglePlayback) {
                ZStack {
                    Circle()
                        .fill(theme.brandAccent)
                    if isLoading {
                        ProgressView()
                            .progressViewStyle(.circular)
                            .tint(theme.onAction)
                            .scaleEffect(1.15)
                            .accessibilityHidden(true)
                    } else {
                        Image(systemName: runtime.snapshot.isPlaying ? "pause.fill" : "play.fill")
                            .font(.title2.weight(.semibold))
                            .foregroundStyle(theme.onAction)
                    }
                }
                .frame(width: 64, height: 64)
            }
            .buttonStyle(.plain)
            .accessibilityLabel(Text(LocalizedStringKey(primaryControlAccessibilityKey)))
            AudioCircleButton(
                systemImage: "goforward.30",
                label: "audio.action.seekForward",
                action: runtime.skipForward
            )
            AudioCircleButton(
                systemImage: "forward.end.fill",
                label: "audio.action.next",
                action: runtime.nextChapter
            )
        }
        .padding(.top, .space3)
        .frame(maxWidth: .infinity)
        .disabled(isLoading)
    }

    private var secondaryControls: some View {
        VStack(spacing: 0) {
            Divider()
                .overlay(theme.divider)
            HStack(spacing: 0) {
                speedMenu
                    .frame(maxWidth: .infinity)
                chaptersButton
                    .frame(maxWidth: .infinity)
                sleepButton
                    .frame(maxWidth: .infinity)
                worksButton
                    .frame(maxWidth: .infinity)
            }
            .frame(maxWidth: .infinity, minHeight: 76)
        }
        .padding(.top, .space4)
        .disabled(isLoading)
    }

    private var speedMenu: some View {
        Menu {
            ForEach(runtime.snapshot.supportedPlaybackRates, id: \.self) { rate in
                Button {
                    runtime.setPlaybackRate(rate)
                } label: {
                    if abs(rate - runtime.snapshot.playbackRate) < 0.001 {
                        Label(rateLabel(rate), systemImage: "checkmark")
                    } else {
                        Text(rateLabel(rate))
                    }
                }
            }
        } label: {
            AudioSecondaryControlLabel(
                value: rateLabel(runtime.snapshot.playbackRate),
                title: "audio.action.speed"
            )
        }
        .accessibilityLabel(Text("audio.action.speed"))
        .accessibilityValue(Text(rateLabel(runtime.snapshot.playbackRate)))
    }

    private var chaptersButton: some View {
        Button {
            presentation = .chapters
        } label: {
            AudioSecondaryControlLabel(
                systemImage: "list.number",
                title: "audio.action.chapters"
            )
        }
        .disabled(runtime.snapshot.bootstrap?.chapters.isEmpty != false && runtime.snapshot.bootstrap?.tracks.isEmpty != false)
        .accessibilityLabel(Text("audio.action.chapters"))
    }

    private var sleepButton: some View {
        Button {
            presentation = .sleep
        } label: {
            AudioSecondaryControlLabel(
                systemImage: "moon.zzz",
                title: "audio.action.sleepTimer"
            )
        }
        .accessibilityLabel(Text("audio.action.sleepTimer"))
    }

    private var worksButton: some View {
        Button {
            // There is no native works destination in the audio presentation contract yet.
            // Dismissing returns to the host, which is the least surprising existing action.
            dismiss()
        } label: {
            AudioSecondaryControlLabel(
                systemImage: "books.vertical",
                title: "audio.action.works"
            )
        }
        .accessibilityLabel(Text("audio.action.works"))
        .accessibilityHint(Text("audio.action.works.hint"))
    }

    @ViewBuilder
    private var errorFeedback: some View {
        if runtime.snapshot.lifecycle == .error {
            HStack(spacing: .space1) {
                Label(errorMessageKey, systemImage: "exclamationmark.triangle")
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Button("audio.action.retry") { runtime.retry() }
                    .buttonStyle(.borderless)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(theme.brandAccent)
            }
            .font(.caption)
            .foregroundStyle(theme.textSecondary)
            .padding(.top, .space1)
            .accessibilityElement(children: .contain)
        }
    }

    private var isLoading: Bool {
        runtime.snapshot.lifecycle == .loading || runtime.snapshot.lifecycle == .buffering
    }

    private var displayedPositionMillis: Int64 {
        runtime.snapshot.absolutePositionMillis
    }

    private var primaryControlAccessibilityKey: String {
        if isLoading {
            return runtime.snapshot.lifecycle == .buffering ? "audio.state.buffering" : "audio.state.loading"
        }
        return runtime.snapshot.isPlaying ? "audio.action.pause" : "audio.action.play"
    }

    private var errorMessageKey: LocalizedStringKey {
        switch runtime.snapshot.recoverableError?.code {
        case .codecUnsupported: "audio.error.codecUnsupported"
        case .unauthorized: "audio.error.reauthenticate"
        case .networkRetryable: "audio.error.network"
        case .resourceUnavailable, .localArtifactUnavailable: "audio.error.unavailable"
        case .invalidBootstrap: "audio.error.bootstrap"
        case .interrupted: "audio.error.interrupted"
        case .unknown, .none: "audio.error.generic"
        }
    }

    private func clampedScrubValue(_ value: Double) -> Double {
        let maximumPosition = max(1, Double(runtime.snapshot.totalDurationMillis))
        guard value.isFinite else {
            return Double(runtime.snapshot.absolutePositionMillis)
        }
        return min(max(0, value), maximumPosition)
    }

    private func handleScrubEditingChanged(_ isEditing: Bool) {
        if isEditing {
            runtime.beginScrubbing()
            return
        }
        runtime.finishScrubbing(at: runtime.snapshot.absolutePositionMillis)
    }

    private func artworkSize(for viewport: CGSize) -> CGFloat {
        // The slot contracts on short screens but never below a readable cover
        // size. Its height is independent of the artwork's intrinsic ratio.
        min(260, max(180, min(viewport.width - 32, viewport.height * 0.38)))
    }

    private func rateLabel(_ value: Double) -> String {
        value.formatted(.number.precision(.fractionLength(value.rounded() == value ? 0 : 2))) + "×"
    }

    private func formattedTime(_ milliseconds: Int64) -> String {
        let totalSeconds = max(0, milliseconds) / 1_000
        let hours = totalSeconds / 3_600
        let minutes = (totalSeconds % 3_600) / 60
        let seconds = totalSeconds % 60
        if hours > 0 { return "\(hours):\(String(format: "%02d", minutes)):\(String(format: "%02d", seconds))" }
        return "\(minutes):\(String(format: "%02d", seconds))"
    }
}

private struct AudioCircleButton: View {
    let systemImage: String
    let label: LocalizedStringKey
    let action: () -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.body.weight(.semibold))
        }
        .buttonStyle(.borderless)
        .foregroundStyle(theme.textPrimary)
        .frame(minWidth: 44, minHeight: 44)
        .contentShape(Rectangle())
        .accessibilityLabel(Text(label))
    }
}

private struct AudioSecondaryControlLabel: View {
    let systemImage: String?
    let value: String?
    let title: LocalizedStringKey
    @Environment(\.appTheme) private var theme

    init(
        systemImage: String? = nil,
        value: String? = nil,
        title: LocalizedStringKey
    ) {
        self.systemImage = systemImage
        self.value = value
        self.title = title
    }

    var body: some View {
        VStack(spacing: 5) {
            if let value {
                Text(value)
                    .font(.title3.weight(.medium))
                    .foregroundStyle(theme.textPrimary)
                    .lineLimit(1)
            } else if let systemImage {
                Image(systemName: systemImage)
                    .font(.title3.weight(.medium))
                    .foregroundStyle(theme.textPrimary)
                    .accessibilityHidden(true)
            }
            Text(title)
                .font(.caption)
                .foregroundStyle(theme.textSecondary)
                .lineLimit(1)
        }
        .frame(maxWidth: .infinity, minHeight: 64)
        .contentShape(Rectangle())
    }
}

struct AudioChaptersSheet: View {
    private static let pageSize = 20

    private enum Entry {
        case chapter(AudioChapter)
        case track(AudioTrack)

        var id: String {
            switch self {
            case .chapter(let chapter):
                "chapter:\(chapter.assetID):\(chapter.id)"
            case .track(let track):
                "track:\(track.assetID)"
            }
        }

        var assetID: String {
            switch self {
            case .chapter(let chapter): chapter.assetID
            case .track(let track): track.assetID
            }
        }
    }

    @ObservedObject var runtime: AudioPlaybackRuntime
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme
    @State private var windowStart: Int
    @State private var windowEnd: Int
    @State private var hasAppliedInitialScroll = false
    @State private var isLoadingBefore = false
    @State private var isLoadingAfter = false

    init(runtime: AudioPlaybackRuntime) {
        self.runtime = runtime

        let snapshot = runtime.snapshot
        let entries = Self.makeEntries(from: snapshot.bootstrap)
        let currentIndex = Self.currentIndex(in: entries, snapshot: snapshot) ?? 0
        let start = max(0, currentIndex - Self.pageSize)
        let end = min(entries.count, currentIndex + Self.pageSize + 1)
        _windowStart = State(initialValue: start)
        _windowEnd = State(initialValue: end)
    }

    var body: some View {
        NavigationStack {
            Group {
            if itemCount == 0 {
                ContentUnavailableView(
                    "audio.sheet.empty.title",
                    systemImage: "list.number",
                    description: Text("audio.sheet.empty.message")
                )
            } else {
                ScrollViewReader { proxy in
                    List {
                        ForEach(visibleIndices, id: \.self) { index in
                            row(for: index)
                                .id(itemID(for: index))
                                .onAppear {
                                    handleAppearance(of: index, using: proxy)
                                }
                        }
                    }
                    .listStyle(.plain)
                    .scrollContentBackground(.hidden)
                    .onAppear {
                        applyInitialScroll(using: proxy)
                    }
                }
            }
            }
            .navigationTitle("audio.sheet.chapters.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("common.done") { dismiss() }
                }
            }
            .tint(theme.textPrimary)
        }
        .background(theme.canvas.ignoresSafeArea())
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    private var entries: [Entry] {
        Self.makeEntries(from: runtime.snapshot.bootstrap)
    }

    private var itemCount: Int {
        entries.count
    }

    private var visibleIndices: Range<Int> {
        let start = min(max(0, windowStart), itemCount)
        let end = min(max(start, windowEnd), itemCount)
        return start..<end
    }

    private var currentItemID: String? {
        guard let index = Self.currentIndex(in: entries, snapshot: runtime.snapshot) else { return nil }
        return itemID(for: index)
    }

    @ViewBuilder
    private func row(for index: Int) -> some View {
        if entries.indices.contains(index) {
            switch entries[index] {
            case .chapter(let chapter):
            Button {
                runtime.selectChapter(chapter.id)
                dismiss()
            } label: {
                audioRow(
                    title: chapter.title,
                    subtitle: chapterDuration(chapter),
                    selected: chapter.id == runtime.snapshot.chapter?.id
                )
            }
            .buttonStyle(.plain)
            .disabled(isLoading)

            case .track(let track):
            Button {
                runtime.selectAsset(track.assetID)
                dismiss()
            } label: {
                audioRow(
                    title: track.title,
                    subtitle: formatDuration(track.durationMillis),
                    selected: runtime.snapshot.track?.assetID == track.assetID
                )
            }
            .buttonStyle(.plain)
            .disabled(isLoading)
            }
        }
    }

    private func audioRow(title: String, subtitle: String?, selected: Bool) -> some View {
        HStack(spacing: .space1) {
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .foregroundStyle(theme.textPrimary)
                    .multilineTextAlignment(.leading)
                    .lineLimit(2)
                if let subtitle {
                    Text(subtitle)
                        .font(.caption)
                        .foregroundStyle(theme.textSecondary)
                }
            }
            Spacer(minLength: .space1)
            if selected {
                Image(systemName: "checkmark")
                    .foregroundStyle(theme.brandAccent)
                    .accessibilityHidden(true)
            }
        }
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .contentShape(Rectangle())
    }

    private var isLoading: Bool {
        runtime.snapshot.lifecycle == .loading || runtime.snapshot.lifecycle == .buffering
    }

    private func itemID(for index: Int) -> String {
        guard entries.indices.contains(index) else { return "audio-entry-\(index)" }
        return entries[index].id
    }

    private func applyInitialScroll(using proxy: ScrollViewProxy) {
        guard !hasAppliedInitialScroll else { return }
        hasAppliedInitialScroll = true
        if let currentItemID {
            proxy.scrollTo(currentItemID, anchor: .center)
        }
    }

    private func handleAppearance(of index: Int, using proxy: ScrollViewProxy) {
        guard hasAppliedInitialScroll else { return }
        let start = windowStart
        let end = windowEnd
        if index == start {
            loadPreviousPage(using: proxy)
        }
        if index == end - 1 {
            loadNextPage()
        }
    }

    private func loadPreviousPage(using proxy: ScrollViewProxy) {
        guard windowStart > 0, !isLoadingBefore else { return }
        isLoadingBefore = true
        let oldFirstIndex = windowStart
        windowStart = max(0, oldFirstIndex - Self.pageSize)
        // Keep the row that was at the top anchored after prepending 20 items.
        proxy.scrollTo(itemID(for: oldFirstIndex), anchor: .top)
        isLoadingBefore = false
    }

    private func loadNextPage() {
        guard windowEnd < itemCount, !isLoadingAfter else { return }
        isLoadingAfter = true
        windowEnd = min(itemCount, windowEnd + Self.pageSize)
        isLoadingAfter = false
    }

    private static func makeEntries(from bootstrap: AudioBootstrap?) -> [Entry] {
        guard let bootstrap else { return [] }
        let chaptersByAsset = Dictionary(grouping: bootstrap.chapters, by: \.assetID)
        return bootstrap.tracks.flatMap { track in
            let chapters = chaptersByAsset[track.assetID] ?? []
            return chapters.isEmpty ? [.track(track)] : chapters.map(Entry.chapter)
        }
    }

    private static func currentIndex(
        in entries: [Entry],
        snapshot: AudioPlaybackSnapshot
    ) -> Int? {
        if let chapter = snapshot.chapter,
           let exactIndex = entries.firstIndex(where: { entry in
               if case .chapter(let candidate) = entry {
                   return candidate.id == chapter.id && candidate.assetID == chapter.assetID
               }
               return false
           }) {
            return exactIndex
        }

        guard let currentAssetID = snapshot.track?.assetID else {
            return entries.indices.contains(snapshot.trackIndex) ? snapshot.trackIndex : entries.indices.first
        }
        return entries.firstIndex(where: { $0.assetID == currentAssetID })
    }

    private func chapterDuration(_ chapter: AudioChapter) -> String? {
        let duration = chapter.endMillis - chapter.startMillis
        return duration > 0 ? formatDuration(duration) : nil
    }

    private func formatDuration(_ milliseconds: Int64) -> String {
        let seconds = max(0, milliseconds) / 1_000
        return "\(seconds / 60):\(String(format: "%02d", seconds % 60))"
    }
}

struct AudioSleepTimerSheet: View {
    @ObservedObject var runtime: AudioPlaybackRuntime
    @Environment(\.dismiss) private var dismiss
    @Environment(\.appTheme) private var theme

    var body: some View {
        NavigationStack {
            List {
                Button {
                    runtime.setSleepTimer(.off)
                    dismiss()
                } label: {
                    timerRow("audio.sleep.off", selected: runtime.snapshot.sleepTimerMode == nil)
                }
                ForEach([15, 30, 45, 60], id: \.self) { minutes in
                    Button {
                        runtime.setSleepTimer(sharedMode(minutes))
                        dismiss()
                    } label: {
                        timerRow(minutesLabel(minutes), selected: isSelected(minutes))
                    }
                }
                Button {
                    runtime.setSleepTimer(.endofchapter)
                    dismiss()
                } label: {
                    timerRow("audio.sleep.chapter", selected: runtime.snapshot.sleepTimerMode == .chapter)
                }
                Button {
                    runtime.setSleepTimer(.endoftrack)
                    dismiss()
                } label: {
                    timerRow("audio.sleep.track", selected: runtime.snapshot.sleepTimerMode == .track)
                }
            }
            .disabled(runtime.snapshot.lifecycle == .loading)
            .navigationTitle("audio.sleep.title")
            .navigationBarTitleDisplayMode(.inline)
            .tint(theme.textPrimary)
        }
        .background(theme.canvas.ignoresSafeArea())
        .presentationDetents([.medium])
        .presentationDragIndicator(.visible)
    }

    private func timerRow(_ title: LocalizedStringKey, selected: Bool) -> some View {
        HStack {
            Text(title)
            Spacer()
            if selected { Image(systemName: "checkmark") }
        }
    }

    private func minutesLabel(_ minutes: Int) -> LocalizedStringKey {
        switch minutes {
        case 15: return "audio.sleep.15"
        case 30: return "audio.sleep.30"
        case 45: return "audio.sleep.45"
        default: return "audio.sleep.60"
        }
    }

    private func isSelected(_ minutes: Int) -> Bool {
        guard let deadline = runtime.snapshot.sleepTimerEndsAtEpochMillis else { return false }
        let remaining = deadline - Int64(Date().timeIntervalSince1970 * 1_000)
        return abs(remaining - Int64(minutes * 60_000)) < 2_000
    }

    private func sharedMode(_ minutes: Int) -> ErmaoShared.AudioSleepTimerMode {
        switch minutes {
        case 15: .minutes15
        case 30: .minutes30
        case 45: .minutes45
        default: .minutes60
        }
    }
}

private struct AudioArtworkView: View {
    let size: CGFloat
    @Environment(\.appTheme) private var theme

    var body: some View {
        let cornerRadius = CGFloat(
            size > 100
                ? GeneratedDesignTokens.Radii.coverHero
                : GeneratedDesignTokens.Radii.coverCompact
        )
        ZStack {
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .fill(theme.surfaceRaised)
            Image("BrandMark")
                .resizable()
                .scaledToFit()
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .padding(size > 100 ? .space3 : .space1)
        }
        // Keep a stable square media slot. Real covers can be 1:1, 2:3 or
        // landscape; when a trusted image is wired in, scaledToFit keeps it
        // contained without changing the slot height or cropping it.
        .frame(width: size, height: size)
        .aspectRatio(1, contentMode: .fit)
        .background(theme.surfaceRaised)
        .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        .overlay {
            RoundedRectangle(cornerRadius: cornerRadius, style: .continuous)
                .stroke(theme.divider.opacity(0.85), lineWidth: 1)
                .allowsHitTesting(false)
        }
        .shadow(color: theme.textPrimary.opacity(0.10), radius: size > 100 ? 4 : 3, x: 0, y: size > 100 ? 2 : 1)
        .accessibilityLabel(Text("audio.artwork"))
    }
}

extension EnvironmentValues {
    var audioPlaybackRuntime: AudioPlaybackRuntime? {
        get { self[AudioPlaybackRuntimeKey.self] }
        set { self[AudioPlaybackRuntimeKey.self] = newValue }
    }
}

struct AudioPlaybackRuntimeKey: EnvironmentKey {
    static let defaultValue: AudioPlaybackRuntime? = nil
}
