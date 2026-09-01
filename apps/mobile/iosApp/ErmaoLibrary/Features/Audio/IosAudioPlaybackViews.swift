import SwiftUI

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
    }
}

private struct AudioMiniPlayer: View {
    let snapshot: AudioPlaybackSnapshot
    let onToggle: () -> Void
    let onRetry: () -> Void
    let onExpand: () -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 10) {
            Button(action: onExpand) {
                HStack(spacing: 10) {
                    AudioArtworkView(size: 42)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(snapshot.bootstrap?.book.title ?? "audio.nowPlaying.title")
                            .font(.subheadline.weight(.semibold))
                            .lineLimit(1)
                            .foregroundStyle(theme.textPrimary)
                        Text(snapshot.chapter?.title ?? snapshot.track?.title ?? "audio.nowPlaying.loading")
                            .font(.caption)
                            .lineLimit(1)
                            .foregroundStyle(theme.textSecondary)
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
            .accessibilityLabel(Text(snapshot.isPlaying ? "audio.action.pause" : "audio.action.play"))
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 7)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        .overlay {
            VStack(spacing: 0) {
                Spacer(minLength: 0)
                ProgressView(value: progress, total: 1)
                    .progressViewStyle(.linear)
                    .tint(theme.brandAccent)
                    .labelsHidden()
            }
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
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
            ScrollView {
                VStack(spacing: 0) {
                    AudioArtworkView(size: 260)
                        .padding(.top, 8)
                        .padding(.bottom, 24)
                    identity
                    timeline
                    primaryControls
                    secondaryControls
                    status
                }
                .padding(.horizontal)
                .padding(.bottom, 24)
            }
            .background(Color(.systemBackground))
            .navigationTitle("audio.nowPlaying.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button {
                        dismiss()
                    } label: {
                        Image(systemName: "chevron.down")
                    }
                    .accessibilityLabel(Text("audio.action.collapse"))
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button("audio.action.stop", role: .destructive) {
                            runtime.stopAndClear()
                            dismiss()
                        }
                    } label: {
                        Image(systemName: "ellipsis")
                    }
                    .accessibilityLabel(Text("audio.action.more"))
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
        }
        .accessibilityIdentifier("audio.nowPlaying")
    }

    @ViewBuilder
    private var identity: some View {
        VStack(spacing: 5) {
            Text(runtime.snapshot.bootstrap?.book.title ?? "audio.nowPlaying.loading")
                .font(.title2.weight(.semibold))
                .multilineTextAlignment(.center)
                .lineLimit(3)
            if let author = runtime.snapshot.bootstrap?.book.author, !author.isEmpty {
                Text(author)
                    .font(.subheadline)
                    .foregroundStyle(theme.textSecondary)
                    .lineLimit(2)
            }
            Text(runtime.snapshot.chapter?.title ?? runtime.snapshot.track?.title ?? "audio.nowPlaying.loading")
                .font(.headline)
                .multilineTextAlignment(.center)
                .lineLimit(3)
                .padding(.top, 4)
        }
        .accessibilityElement(children: .combine)
    }

    private var timeline: some View {
        VStack(spacing: 5) {
            Slider(
                value: Binding(
                    get: { Double(runtime.snapshot.absolutePositionMillis) },
                    set: { runtime.seekAbsolute(to: Int64($0.rounded())) }
                ),
                in: 0...Double(max(1, runtime.snapshot.totalDurationMillis))
            )
            .accessibilityLabel(Text("audio.timeline"))
            .accessibilityValue(Text("\(formattedTime(runtime.snapshot.absolutePositionMillis)) / \(formattedTime(runtime.snapshot.totalDurationMillis))"))
            HStack {
                Text(formattedTime(runtime.snapshot.absolutePositionMillis))
                Spacer()
                Text(formattedTime(runtime.snapshot.totalDurationMillis))
            }
            .font(.caption.monospacedDigit())
            .foregroundStyle(theme.textSecondary)
        }
        .padding(.top, 26)
    }

    private var primaryControls: some View {
        HStack(spacing: 20) {
            AudioCircleButton(
                systemImage: "backward.end.fill",
                label: "audio.action.previous",
                action: runtime.previousChapter
            )
            AudioCircleButton(
                systemImage: "gobackward.15",
                label: "audio.action.seekBackward",
                action: { runtime.seekBy(seconds: -runtime.snapshot.skipBackwardSeconds) }
            )
            Button(action: runtime.togglePlayback) {
                Image(systemName: runtime.snapshot.isPlaying ? "pause.fill" : "play.fill")
                    .font(.title2.weight(.semibold))
                    .frame(width: 64, height: 64)
            }
            .buttonStyle(.borderedProminent)
            .buttonBorderShape(.circle)
            .accessibilityLabel(Text(runtime.snapshot.isPlaying ? "audio.action.pause" : "audio.action.play"))
            AudioCircleButton(
                systemImage: "goforward.30",
                label: "audio.action.seekForward",
                action: { runtime.seekBy(seconds: runtime.snapshot.skipForwardSeconds) }
            )
            AudioCircleButton(
                systemImage: "forward.end.fill",
                label: "audio.action.next",
                action: runtime.nextChapter
            )
        }
        .padding(.top, 22)
        .frame(maxWidth: .infinity)
    }

    private var secondaryControls: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: 20) {
                speedMenu
                chaptersButton
                sleepButton
            }
            VStack(spacing: 10) {
                HStack(spacing: 20) { speedMenu; chaptersButton }
                sleepButton
            }
        }
        .padding(.top, 24)
    }

    private var speedMenu: some View {
        Menu {
            ForEach(AudioPlaybackSnapshot.supportedPlaybackRates, id: \.self) { rate in
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
            Label(rateLabel(runtime.snapshot.playbackRate), systemImage: "speedometer")
        }
        .accessibilityLabel(Text("audio.action.speed"))
    }

    private var chaptersButton: some View {
        Button {
            presentation = .chapters
        } label: {
            Label("audio.action.chapters", systemImage: "list.number")
        }
        .disabled(runtime.snapshot.bootstrap?.chapters.isEmpty != false && runtime.snapshot.bootstrap?.tracks.isEmpty != false)
    }

    private var sleepButton: some View {
        Button {
            presentation = .sleep
        } label: {
            Label("audio.action.sleepTimer", systemImage: "moon.zzz")
        }
    }

    @ViewBuilder
    private var status: some View {
        VStack(spacing: 8) {
            AudioPlaybackStatusView(snapshot: runtime.snapshot)
            if runtime.snapshot.lifecycle == .error {
                Button("audio.action.retry") { runtime.retry() }
                    .buttonStyle(.bordered)
            }
        }
        .padding(.top, 20)
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

    var body: some View {
        Button(action: action) {
            Image(systemName: systemImage)
                .font(.body.weight(.semibold))
        }
        .buttonStyle(.borderless)
        .frame(minWidth: 44, minHeight: 44)
        .contentShape(Rectangle())
        .accessibilityLabel(Text(label))
    }
}

struct AudioChaptersSheet: View {
    @ObservedObject var runtime: AudioPlaybackRuntime
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                if let bootstrap = runtime.snapshot.bootstrap {
                    Section("audio.sheet.tracks") {
                        ForEach(Array(bootstrap.tracks.enumerated()), id: \.element.assetID) { index, track in
                            Button {
                                runtime.selectTrack(index: index)
                            } label: {
                                HStack {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(track.title)
                                        Text(formatDuration(track.durationMillis))
                                            .font(.caption)
                                            .foregroundStyle(.secondary)
                                    }
                                    Spacer()
                                    if index == runtime.snapshot.trackIndex { Image(systemName: "checkmark") }
                                }
                            }
                        }
                    }
                    if !bootstrap.chapters.isEmpty {
                        Section("audio.sheet.chapters") {
                            ForEach(bootstrap.chapters) { chapter in
                                Button {
                                    runtime.selectChapter(chapter.id)
                                } label: {
                                    HStack {
                                        Text(chapter.title)
                                            .multilineTextAlignment(.leading)
                                        Spacer()
                                        if chapter.id == runtime.snapshot.chapter?.id { Image(systemName: "checkmark") }
                                    }
                                }
                            }
                        }
                    }
                } else {
                    ContentUnavailableView("audio.sheet.empty.title", systemImage: "list.number", description: Text("audio.sheet.empty.message"))
                }
            }
            .navigationTitle("audio.sheet.chapters.title")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("common.done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
        .presentationDragIndicator(.visible)
    }

    private func formatDuration(_ milliseconds: Int64) -> String {
        let seconds = max(0, milliseconds) / 1_000
        return "\(seconds / 60):\(String(format: "%02d", seconds % 60))"
    }
}

struct AudioSleepTimerSheet: View {
    @ObservedObject var runtime: AudioPlaybackRuntime
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Button {
                    runtime.setSleepTimer(minutes: nil)
                    dismiss()
                } label: {
                    timerRow("audio.sleep.off", selected: runtime.snapshot.sleepTimerMode == nil)
                }
                ForEach([15, 30, 45, 60], id: \.self) { minutes in
                    Button {
                        runtime.setSleepTimer(minutes: minutes)
                        dismiss()
                    } label: {
                        timerRow(minutesLabel(minutes), selected: isSelected(minutes))
                    }
                }
                Button {
                    runtime.setSleepUntilChapterOrTrackEnd()
                    dismiss()
                } label: {
                    timerRow("audio.sleep.chapter", selected: runtime.snapshot.sleepTimerMode == .chapter)
                }
            }
            .navigationTitle("audio.sleep.title")
            .navigationBarTitleDisplayMode(.inline)
        }
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
}

private struct AudioPlaybackStatusView: View {
    let snapshot: AudioPlaybackSnapshot

    var body: some View {
        Group {
            switch snapshot.lifecycle {
            case .loading: Label("audio.state.loading", systemImage: "hourglass")
            case .ready: Label("audio.state.ready", systemImage: "checkmark.circle")
            case .playing: EmptyView()
            case .paused: Label("audio.state.paused", systemImage: "pause.circle")
            case .buffering: Label("audio.state.buffering", systemImage: "arrow.triangle.2.circlepath")
            case .ended: Label("audio.state.ended", systemImage: "checkmark.circle.fill")
            case .error: Label(errorKey, systemImage: "exclamationmark.triangle")
            case .idle: EmptyView()
            }
            if snapshot.syncState == .pending {
                Label("audio.state.syncPending", systemImage: "arrow.triangle.2.circlepath")
            } else if snapshot.syncState == .failed {
                Label("audio.state.syncFailed", systemImage: "exclamationmark.circle")
            }
        }
        .font(.callout)
        .foregroundStyle(.secondary)
        .multilineTextAlignment(.center)
    }

    private var errorKey: LocalizedStringKey {
        switch snapshot.recoverableError?.code {
        case .codecUnsupported: "audio.error.codecUnsupported"
        case .unauthorized: "audio.error.reauthenticate"
        case .networkRetryable: "audio.error.network"
        case .resourceUnavailable, .localArtifactUnavailable: "audio.error.unavailable"
        case .invalidBootstrap: "audio.error.bootstrap"
        case .interrupted: "audio.error.interrupted"
        case .unknown, .none: "audio.error.generic"
        }
    }
}

private struct AudioArtworkView: View {
    let size: CGFloat
    @Environment(\.appTheme) private var theme

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: size > 100 ? 18 : 10, style: .continuous)
                .fill(theme.brandAccent)
            Image("BrandMark")
                .resizable()
                .scaledToFit()
                .padding(size > 100 ? 38 : 8)
                .opacity(0.9)
        }
        .frame(width: size, height: size)
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
