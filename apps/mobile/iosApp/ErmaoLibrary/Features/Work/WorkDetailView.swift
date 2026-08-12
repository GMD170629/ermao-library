import SwiftUI

struct WorkDetailView: View {
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: LibraryCacheStore
    let openFacet: (FacetKind, String) -> Void

    @StateObject private var store: WorkDetailStore
    @State private var selectedSection = WorkDetailSection.about
    @State private var unavailableFeature: UnavailableWorkFeature?
    @Environment(\.appTheme) private var theme
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize

    init(
        context: ContentRequestContext,
        client: any ContentClient,
        cache: LibraryCacheStore,
        workID: String,
        onUnauthorized: @escaping @MainActor () -> Void,
        openFacet: @escaping (FacetKind, String) -> Void
    ) {
        self.context = context
        self.client = client
        self.cache = cache
        self.openFacet = openFacet
        _store = StateObject(
            wrappedValue: WorkDetailStore(
                context: context,
                client: client,
                cache: cache,
                workID: workID,
                onUnauthorized: onUnauthorized
            )
        )
    }

    var body: some View {
        ScrollView {
            content
                .padding(.horizontal, .space2)
                .padding(.bottom, .space4)
        }
        .navigationTitle("work.detail.title")
        .accessibilityIdentifier("work.detail.screen")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar { overflowMenu }
        .confirmationDialog(
            "work.unavailable.title",
            isPresented: Binding(
                get: { unavailableFeature != nil },
                set: { if !$0 { unavailableFeature = nil } }
            ),
            titleVisibility: .visible,
            presenting: unavailableFeature
        ) { _ in
            Button("common.done", role: .cancel) { unavailableFeature = nil }
        } message: { feature in
            Text(feature.message)
        }
        .appCanvas()
        .task { store.load() }
    }

    @ToolbarContentBuilder
    private var overflowMenu: some ToolbarContent {
        ToolbarItem(placement: .topBarTrailing) {
            Menu {
                Button("common.refresh", systemImage: "arrow.clockwise") { store.load() }
                Divider()
                Button("work.reader.continue.action", systemImage: "book") {
                    unavailableFeature = .reader
                }
                Button("work.action.edit", systemImage: "pencil") {
                    unavailableFeature = .editing
                }
                Button("work.action.setCover", systemImage: "photo") {
                    unavailableFeature = .cover
                }
                Button("work.action.download", systemImage: "icloud.and.arrow.down") {
                    unavailableFeature = .download
                }
                Menu("work.action.readingStatus", systemImage: "chart.pie") {
                    ForEach(LibraryReadingStatus.allCases, id: \.self) { status in
                        Button(status.title) { unavailableFeature = .readingStatus }
                    }
                }
            } label: {
                Image(systemName: "ellipsis")
            }
            .accessibilityLabel(Text("common.more"))
        }
    }

    @ViewBuilder
    private var content: some View {
        switch store.state {
        case .loading:
            HStack { Spacer(); ProgressView(); Spacer() }.frame(minHeight: 420)
        case .failure:
            ContentStatusView(
                systemImage: "wifi.exclamationmark",
                title: "work.error.title",
                message: "work.error.message",
                actionTitle: "common.retry",
                action: { store.load() }
            )
        case .inaccessible:
            ContentStatusView(
                systemImage: "eye.slash",
                title: "content.inaccessible.title",
                message: "content.inaccessible.message"
            )
        case .ready(let detail, let cached):
            readyContent(detail, isCached: cached)
        }
    }

    private func readyContent(_ detail: WorkDetailContent, isCached: Bool) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            if isCached {
                Label("library.offline.cached", systemImage: "wifi.slash")
                    .appTextStyle(.caption)
                    .foregroundStyle(theme.textSecondary)
                    .padding(.bottom, .space2)
            }

            hero(detail)
                .padding(.top, .spaceHalf)
                .padding(.bottom, .space2)

            progressSummary(detail)
                .padding(.bottom, .space2)

            readerAction(detail)
                .padding(.bottom, .space2)

            if hasDescription(detail) {
                sectionPicker
                    .padding(.bottom, .space2)

                switch selectedSection {
                case .about:
                    aboutSection(detail)
                case .media:
                    mediaSection(detail)
                }
            } else {
                mediaSection(detail)
            }
        }
    }

    @ViewBuilder
    private func hero(_ detail: WorkDetailContent) -> some View {
        if dynamicTypeSize.isAccessibilitySize {
            VStack(alignment: .leading, spacing: .space1Half) {
                cover(detail).frame(width: 124)
                identity(detail)
            }
        } else {
            HStack(alignment: .top, spacing: .space2) {
                cover(detail).frame(width: 128)
                identity(detail)
                    .frame(height: 192, alignment: .top)
            }
        }
    }

    private func cover(_ detail: WorkDetailContent) -> some View {
        BookCoverView(
            reference: detail.work.cover,
            title: detail.work.title,
            context: context,
            client: client,
            cache: cache,
            cornerRadius: CGFloat(GeneratedDesignTokens.Radii.coverHero)
        )
    }

    private func identity(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .leading, spacing: .spaceHalf) {
            Text(detail.work.title)
                .appTextStyle(.title)
                .fixedSize(horizontal: false, vertical: true)

            if detail.authorFacets.isEmpty {
                Text(detail.work.author)
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
            } else {
                ForEach(detail.authorFacets, id: \.id) { author in
                    facetButton(author, kind: .author)
                }
            }

            if !detail.tags.isEmpty {
                FlowTags(tags: detail.tags)
            }

            if let status = detail.readingStatus, status != .unread {
                readingStatusChip(detail, status: status)
            }

            if let series = detail.seriesFacet {
                Spacer(minLength: .spaceHalf)
                facetButton(series, kind: .series)
            }
        }
    }

    private func facetButton(_ facet: FacetIdentity, kind: FacetKind) -> some View {
        Button {
            openFacet(kind, facet.id)
        } label: {
            Text(facet.name)
                .underline(kind == .series, color: kind == .series ? theme.actionAccent : nil)
            .frame(
                minHeight: .iosMinimumTouchTarget,
                alignment: kind == .series ? .bottomLeading : .topLeading
            )
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .appTextStyle(.label)
        .foregroundStyle(kind == .series ? theme.actionAccent : theme.textSecondary)
        .accessibilityHint(Text(kind == .series ? "work.series.accessibility.hint" : "work.author.accessibility.hint"))
    }

    private func readingStatusChip(_ detail: WorkDetailContent, status: LibraryReadingStatus) -> some View {
        let progress = detail.work.progress ?? detail.volumes.compactMap(\.progress).max()
        return HStack(spacing: .spaceHalf) {
            Text(status.title)
            if let progress, progress > 0 {
                Text("·")
                Text("\(Int(progress))%")
                    .monospacedDigit()
            }
        }
        .appTextStyle(.label)
        .foregroundStyle(theme.actionAccent)
        .padding(.horizontal, .space1)
        .padding(.vertical, .spaceHalf)
        .background(theme.accentSoft)
        .clipShape(RoundedRectangle(cornerRadius: CGFloat(GeneratedDesignTokens.Radii.control)))
        .accessibilityLabel(Text("work.status.accessibility.label"))
    }

    @ViewBuilder
    private func progressSummary(_ detail: WorkDetailContent) -> some View {
        let progress = detail.work.progress ?? detail.volumes.compactMap(\.progress).max()
        if let progress, progress > 0 {
            let selectedTitle = detail.volumes.first(where: \.isSelected)?.title
            VStack(alignment: .leading, spacing: .space1) {
                HStack(alignment: .firstTextBaseline, spacing: .space2) {
                    Text("\(Int(progress))%")
                        .appTextStyle(.sectionTitle)
                        .monospacedDigit()
                    if let selectedTitle {
                        Text(selectedTitle)
                            .appTextStyle(.label)
                            .foregroundStyle(theme.textSecondary)
                            .lineLimit(2)
                    }
                }
                ProgressView(value: min(100, progress), total: 100)
                    .tint(theme.brandAccent)
                    .accessibilityValue(Text("\(Int(progress))%"))
            }
        }
    }

    private func readerAction(_ detail: WorkDetailContent) -> some View {
        PrimaryActionButton(
            detail.readingStatus == .reading ? "work.reader.continue.action" : "work.reader.start.action",
            isDisabled: true,
            action: {}
        )
        .accessibilityHint(Text("work.reader.unavailable.message"))
    }

    private var sectionPicker: some View {
        HStack(spacing: 0) {
            ForEach(WorkDetailSection.allCases, id: \.self) { section in
                Button {
                    withAnimation(.easeOut(duration: 0.18)) { selectedSection = section }
                } label: {
                    VStack(spacing: .space1) {
                        Text(section.title)
                            .appTextStyle(.sectionTitle)
                            .foregroundStyle(selectedSection == section ? theme.actionAccent : theme.textSecondary)
                        Rectangle()
                            .fill(selectedSection == section ? theme.brandAccent : Color.clear)
                            .frame(height: 3)
                    }
                    .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityAddTraits(selectedSection == section ? .isSelected : [])
                .accessibilityIdentifier(section.accessibilityIdentifier)
            }
        }
        .overlay(alignment: .bottom) { Divider() }
        .accessibilityElement(children: .contain)
    }

    @ViewBuilder
    private func aboutSection(_ detail: WorkDetailContent) -> some View {
        if let description = normalizedDescription(detail) {
            VStack(alignment: .leading, spacing: .space2) {
                Text("work.description.title").appTextStyle(.sectionTitle)
                Text(description)
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
        }
    }

    private func hasDescription(_ detail: WorkDetailContent) -> Bool {
        normalizedDescription(detail) != nil
    }

    private func normalizedDescription(_ detail: WorkDetailContent) -> String? {
        guard let value = detail.description?.trimmingCharacters(in: .whitespacesAndNewlines),
              !value.isEmpty else { return nil }
        return value
    }

    private func mediaSection(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .leading, spacing: .space2) {
            mediaPicker(detail)
            if usesChapterFallback(detail) {
                chapterSection(detail)
            } else {
                volumeSection(detail)
            }
        }
    }

    @ViewBuilder
    private func mediaPicker(_ detail: WorkDetailContent) -> some View {
        if detail.availableMediaKinds.count > 1 {
            Picker(
                "work.media.title",
                selection: Binding(
                    get: { detail.selectedMediaKind ?? detail.availableMediaKinds.first ?? .ebook },
                    set: { store.load(mediaKind: $0) }
                )
            ) {
                ForEach(detail.availableMediaKinds, id: \.self) { kind in
                    Text(kind.title).tag(kind)
                }
            }
            .pickerStyle(.segmented)
            .tint(theme.brandAccent)
        }
    }

    private func usesChapterFallback(_ detail: WorkDetailContent) -> Bool {
        detail.selectedMediaKind == .ebook && detail.volumes.count == 1 && !detail.chapters.isEmpty
    }

    @ViewBuilder
    private func volumeSection(_ detail: WorkDetailContent) -> some View {
        if detail.volumes.isEmpty {
            ContentStatusView(
                systemImage: "books.vertical",
                title: "work.volumes.empty.title",
                message: "work.volumes.empty.message"
            )
        } else {
            VStack(alignment: .leading, spacing: 0) {
                Text(volumeCountLabel(detail.volumes.count))
                    .appTextStyle(.sectionTitle)
                    .padding(.vertical, .space1)

                ForEach(detail.volumes) { volume in
                    Divider()
                    HStack(spacing: .space1) {
                        Button {
                            store.load(mediaKind: detail.selectedMediaKind, volumeID: volume.id)
                        } label: {
                            HStack(spacing: .space1) {
                                Rectangle()
                                    .fill(volume.isSelected ? theme.brandAccent : Color.clear)
                                    .frame(width: 3)
                                    .accessibilityHidden(true)
                                VStack(alignment: .leading, spacing: .spaceHalf) {
                                    Text(volume.title)
                                        .appTextStyle(.headline)
                                        .foregroundStyle(theme.textPrimary)
                                        .lineLimit(2)
                                    if let progress = volume.progress {
                                        Text(progressLabel(progress))
                                            .appTextStyle(.caption)
                                            .foregroundStyle(theme.textSecondary)
                                            .monospacedDigit()
                                    }
                                    Text([volume.formatLabel, volume.sizeLabel].compactMap { $0 }.joined(separator: " · "))
                                        .appTextStyle(.caption)
                                        .foregroundStyle(theme.textSecondary)
                                }
                            }
                            .frame(maxWidth: .infinity, minHeight: 72, alignment: .leading)
                            .contentShape(Rectangle())
                        }
                        .buttonStyle(.plain)
                        .disabled(volume.isReadable == false)
                        .accessibilityValue(volumeAccessibilityValue(volume))

                        Button {
                            unavailableFeature = .download
                        } label: {
                            Image(systemName: "icloud.and.arrow.down")
                                .font(.title3)
                                .frame(width: .iosMinimumTouchTarget, height: .iosMinimumTouchTarget)
                        }
                        .buttonStyle(.plain)
                        .foregroundStyle(theme.textSecondary)
                        .accessibilityLabel(Text("work.volume.download.action"))

                        Image(systemName: volume.isSelected ? "checkmark.circle" : "chevron.forward")
                            .foregroundStyle(volume.isSelected ? theme.brandAccent : theme.textTertiary)
                            .accessibilityHidden(true)
                    }
                }
                Divider()
            }
        }
    }

    private func chapterSection(_ detail: WorkDetailContent) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            Label("work.chapters.fallback.message", systemImage: "arrow.turn.down.right")
                .appTextStyle(.caption)
                .foregroundStyle(theme.textSecondary)
                .padding(.vertical, .space1)

            ForEach(detail.chapters) { chapter in
                Divider()
                HStack(spacing: .space1) {
                    Rectangle()
                        .fill(chapter.isCurrent ? theme.brandAccent : Color.clear)
                        .frame(width: 3)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: .spaceHalf) {
                        Text(chapter.title)
                            .appTextStyle(.headline)
                            .lineLimit(2)
                        if let progress = chapter.progress {
                            Text(progressLabel(progress))
                                .appTextStyle(.caption)
                                .foregroundStyle(theme.textSecondary)
                                .monospacedDigit()
                        }
                    }
                    Spacer(minLength: .space1)
                    if chapter.isCurrent {
                        Text("work.chapter.current")
                            .appTextStyle(.label)
                            .foregroundStyle(theme.actionAccent)
                    } else {
                        Image(systemName: "chevron.forward")
                            .foregroundStyle(theme.textTertiary)
                    }
                }
                .frame(minHeight: 64)
            }
            Divider()
        }
    }

    private func progressLabel(_ progress: Double) -> String {
        String(
            format: String(localized: "work.progress.format"),
            locale: .current,
            Int(progress)
        )
    }

    private func volumeCountLabel(_ count: Int) -> String {
        String(
            format: String(localized: "work.volumeCount.format"),
            locale: .current,
            count
        )
    }

    private func volumeAccessibilityValue(_ volume: WorkVolume) -> Text {
        if let progress = volume.progress {
            return Text("\(volume.formatLabel), \(progressLabel(progress))")
        }
        return Text(volume.formatLabel)
    }
}

private struct FlowTags: View {
    let tags: [String]
    @Environment(\.appTheme) private var theme

    var body: some View {
        ViewThatFits(in: .horizontal) {
            HStack(spacing: .spaceHalf) { tagViews }
            VStack(alignment: .leading, spacing: .spaceHalf) { tagViews }
        }
        .accessibilityElement(children: .combine)
    }

    @ViewBuilder
    private var tagViews: some View {
        ForEach(tags.prefix(3), id: \.self) { tag in
            Text(tag)
                .appTextStyle(.label)
                .foregroundStyle(theme.textSecondary)
                .padding(.horizontal, .space1Half)
                .padding(.vertical, .spaceHalf)
                .overlay {
                    RoundedRectangle(cornerRadius: 3)
                        .stroke(theme.divider)
                }
        }
    }
}

private enum WorkDetailSection: CaseIterable {
    case about
    case media

    var title: LocalizedStringKey {
        switch self {
        case .about: "work.section.about"
        case .media: "work.section.media"
        }
    }

    var accessibilityIdentifier: String {
        switch self {
        case .about: "work.section.about"
        case .media: "work.section.media"
        }
    }
}

private enum UnavailableWorkFeature: Identifiable {
    case reader
    case editing
    case cover
    case download
    case readingStatus

    var id: Self { self }

    var message: LocalizedStringKey {
        switch self {
        case .reader: "work.reader.unavailable.message"
        case .editing: "work.action.edit.unavailable"
        case .cover: "work.action.setCover.unavailable"
        case .download: "work.action.download.unavailable"
        case .readingStatus: "work.action.readingStatus.unavailable"
        }
    }
}

private extension LibraryMediaKind {
    var title: LocalizedStringKey {
        switch self {
        case .ebook: "library.media.ebook"
        case .comic: "library.media.comic"
        case .audiobook: "library.media.audiobook"
        }
    }
}

private extension LibraryReadingStatus {
    static let allCases: [LibraryReadingStatus] = [.unread, .reading, .finished]

    var title: LocalizedStringKey {
        switch self {
        case .unread: "work.status.unread"
        case .reading: "work.status.reading"
        case .finished: "work.status.finished"
        }
    }
}
