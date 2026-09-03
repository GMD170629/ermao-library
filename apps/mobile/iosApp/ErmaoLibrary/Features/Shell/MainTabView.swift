import SwiftUI
@preconcurrency import ErmaoShared

enum TabPresentation: String, Codable, Equatable, Sendable {
    case home
    case library
    case shelves
    case me

    init?(sharedTab: TabId) {
        switch sharedTab.stableValue {
        case "home": self = .home
        case "library": self = .library
        case "shelves": self = .shelves
        case "me": self = .me
        default: return nil
        }
    }

    var title: LocalizedStringKey {
        switch self {
        case .home: "tab.home"
        case .library: "tab.library"
        case .shelves: "tab.shelves"
        case .me: "tab.me"
        }
    }

    func systemImage(isSelected: Bool) -> String {
        switch self {
        case .home: isSelected ? "house.fill" : "house"
        case .library: isSelected ? "books.vertical.fill" : "books.vertical"
        case .shelves: isSelected ? "rectangle.split.2x1.fill" : "rectangle.split.2x1"
        case .me: isSelected ? "person.fill" : "person"
        }
    }
}

struct RootTabDefinition: Identifiable, Sendable {
    let id: String
    let presentation: TabPresentation

    init?(sharedTab: TabId) {
        guard let presentation = TabPresentation(sharedTab: sharedTab) else { return nil }
        id = sharedTab.stableValue
        self.presentation = presentation
    }
}

enum RootTabContract {
    static let definitions = MobileNavigation.shared.orderedRootTabs.compactMap {
        RootTabDefinition(sharedTab: $0)
    }

    static var orderedIDs: [String] {
        definitions.map(\.id)
    }

    static func normalizedID(_ stableValue: String) -> String {
        guard let defaultTab = MobileNavigation.shared.orderedRootTabs.first else { return "" }
        return MobileNavigation.shared
            .tabIdOrDefault(stableValue: stableValue, defaultTab: defaultTab)
            .stableValue
    }
}

enum AppRoute: Hashable, Sendable {
    case work(bookID: String)
    case bookContent(bookID: String, destination: BookContentDestination)
    case downloads
    case reader(ReaderHandoff)
    case facet(kind: FacetKind, facetID: String)
    case collection(HomeCollectionKind)
    case shelf(shelfID: String)
    case settings(SettingsRoute)
    case administrative(AdministrativeSettingsRoute)

    var contentDestination: BookContentDestination {
        if case .bookContent(_, let destination) = self { return destination }
        return .root
    }

    var identityKey: String {
        switch self {
        case .work(let bookID): "work:\(bookID)"
        case .bookContent(let bookID, let destination): "book-content:\(bookID):\(destination)"
        case .downloads: "downloads"
        case .reader(let handoff): "reader:\(handoff.resourceID):\(handoff.source)"
        case .facet(let kind, let facetID): "facet:\(kind.rawValue):\(facetID)"
        case .collection(let kind): "collection:\(kind.rawValue)"
        case .shelf(let shelfID): "shelf:\(shelfID)"
        case .settings(let route): "settings:\(route.rawValue)"
        case .administrative(let route): "administrative:\(route.identityKey)"
        }
    }
}

struct RootTabPaths: Equatable {
    private var home: [AppRoute] = []
    private var library: [AppRoute] = []
    private var shelves: [AppRoute] = []
    private var me: [AppRoute] = []

    func path(for tab: TabPresentation) -> [AppRoute] {
        switch tab {
        case .home: home
        case .library: library
        case .shelves: shelves
        case .me: me
        }
    }

    mutating func setPath(_ path: [AppRoute], for tab: TabPresentation) {
        switch tab {
        case .home: home = path
        case .library: library = path
        case .shelves: shelves = path
        case .me: me = path
        }
    }

    mutating func popToRoot(_ tab: TabPresentation) {
        setPath([], for: tab)
    }

    mutating func open(_ route: AppRoute, in tab: TabPresentation) {
        var path = path(for: tab)
        if let existingIndex = path.firstIndex(where: { $0.identityKey == route.identityKey }) {
            path = Array(path.prefix(through: existingIndex))
        } else {
            path.append(route)
        }
        setPath(path, for: tab)
    }
}

struct MainTabView: View {
    @ObservedObject var store: SessionStore
    @ObservedObject var downloads: DownloadCenterStore
    let contentClient: any ContentClient
    let shelfClient: any ShelfClient
    var shelfCatalogClient: any ShelfCatalogClient = ShelfCatalogComposition.makeClient()
    let cache: AuthenticatedCoverCache
    var settingsViewModel: SettingsViewModel? = nil
    var administrativeSettingsStore: AdministrativeSettingsStore? = nil
    var workManagementRepository: (any ErmaoShared.WorkManagementRepository)? = nil
    var readerComposition: IosReaderComposition? = nil
    private let rootTabs = RootTabContract.definitions

    @State private var selectedTabID = RootTabContract.orderedIDs.first ?? ""
    @State private var visitedTabIDs: Set<String> = Set(RootTabContract.orderedIDs.prefix(1))
    @State private var paths = RootTabPaths()
    @State private var restoredNavigationNamespace: String?
    @State private var readerLaunch: IosReaderLaunchRequest?
    @State private var didOpenUITestRoute = false
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass
    @Environment(\.audioPlaybackRuntime) private var audioPlaybackRuntime
    @Environment(\.appTheme) private var theme
    @EnvironmentObject private var audioPresentation: AudioShellPresentation

    @ViewBuilder private func managedTabs(_ context: ContentRequestContext) -> some View {
        if let repository = workManagementRepository {
            NativeBookManagementHost(repository: repository, context: context,
                canManage: store.snapshot.authorization?.canManageSystem == true, cache: cache,
                onChange: { change in
                    if change.deleted && change.resourceID == nil {
                        for tab in [TabPresentation.home, .library, .shelves, .me] {
                            let existing = paths.path(for: tab)
                            if let index = existing.firstIndex(where: { route in
                                switch route {
                                case .work(let id), .bookContent(let id, _): return id == change.bookID
                                default: return false
                                }
                            }) { paths.setPath(Array(existing.prefix(index)), for: tab) }
                        }
                    }
                }, onUnauthorized: store.refreshForForeground,
                onSettings: { selectedTabID = rootTabs.first(where: { $0.presentation == .me })?.id ?? "me"; open(.administrative(.emailAndKindle), in: .me) },
                onQueue: { selectedTabID = rootTabs.first(where: { $0.presentation == .me })?.id ?? "me"; open(.administrative(.kindleQueue), in: .me) }) { tabContent(context) }
        } else { tabContent(context) }
    }

    @ViewBuilder
    private func tabContent(_ context: ContentRequestContext) -> some View {
        if horizontalSizeClass == .compact {
            compactTabContent(context)
        } else {
            regularTabContent(context)
        }
    }

    private func compactTabContent(_ context: ContentRequestContext) -> some View {
        VStack(spacing: 0) {
            ZStack {
                ForEach(rootTabs.filter { visitedTabIDs.contains($0.id) || $0.id == selectedTabID }) { tab in
                    let isSelected = selectedTabID == tab.id
                    tabRoot(presentation: tab.presentation, context: context)
                        .opacity(isSelected ? 1 : 0)
                        .allowsHitTesting(isSelected)
                        .accessibilityHidden(!isSelected)
                        .zIndex(isSelected ? 1 : 0)
                        .id(tab.id)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)

            unifiedBottomChrome
        }
    }

    private func regularTabContent(_ context: ContentRequestContext) -> some View {
        TabView(selection: selection) {
            ForEach(rootTabs) { tab in
                tabRoot(presentation: tab.presentation, context: context)
                    .tabItem {
                        Label(
                            tab.presentation.title,
                            systemImage: tab.presentation.systemImage(isSelected: selectedTabID == tab.id)
                        )
                    }
                    .tag(tab.id)
            }
        }
        .safeAreaInset(edge: .bottom, spacing: 0) {
            audioMiniPlayer
        }
        .toolbarBackground(theme.surface, for: .tabBar)
        .toolbarBackground(.visible, for: .tabBar)
    }

    private var unifiedBottomChrome: some View {
        VStack(spacing: 0) {
            audioMiniPlayer
            RootTabControls(
                tabs: rootTabs,
                selectedTabID: selectedTabID,
                onSelect: { selection.wrappedValue = $0 }
            )
        }
        .background(theme.surface)
        .background(theme.surface.ignoresSafeArea(edges: .bottom))
        .overlay(alignment: .top) {
            Divider()
                .overlay(theme.divider)
                .allowsHitTesting(false)
        }
        .animation(.easeInOut(duration: 0.2), value: audioPresentation.isMiniPlayerVisible)
    }

    @ViewBuilder
    private var audioMiniPlayer: some View {
        if audioPresentation.isMiniPlayerVisible,
           let audioPlaybackRuntime,
           audioPlaybackRuntime.snapshot.hasSession {
            let snapshot = audioPlaybackRuntime.snapshot
            AudioMiniPlayer(
                snapshot: snapshot,
                onToggle: {
                    if snapshot.isPlaying {
                        audioPresentation.handle(.pausefrommini, snapshot: snapshot)
                    }
                    audioPlaybackRuntime.togglePlayback()
                },
                onRetry: audioPlaybackRuntime.retry,
                onExpand: {
                    audioPresentation.handle(.requestnowplaying, snapshot: snapshot)
                }
            )
            .transition(.move(edge: .bottom).combined(with: .opacity))
        }
    }

    private var selection: Binding<String> {
        Binding(
            get: { selectedTabID },
            set: { newValue in
                let normalized = RootTabContract.normalizedID(newValue)
                if normalized == selectedTabID {
                    popSelectedTabToRoot()
                } else {
                    selectedTabID = normalized
                }
            }
        )
    }

    var body: some View {
        Group {
            if let context = contentContext {
                managedTabs(context).id(context.namespaceKey)
            } else {
                ProgressView().accessibilityLabel(Text("common.loading"))
            }
        }
        .fullScreenCover(item: $readerLaunch) { request in
            if let readerComposition {
                IosReaderBootstrapView(request: request, composition: readerComposition)
            }
        }

        .onChange(of: selectedTabID) { _, value in
            visitedTabIDs.insert(value)
            guard let namespace = restoredNavigationNamespace else { return }
            UserDefaults.standard.set(value, forKey: "book-content.tab.\(namespace)")
        }
        .onChange(of: paths) { _, value in
            guard let namespace = restoredNavigationNamespace else { return }
            persistContentPaths(value, namespace: namespace)
        }
        .task(id: contentContext?.namespaceKey) {
            if let contentContext {
                downloads.activate(context: contentContext)
                if restoredNavigationNamespace != contentContext.namespaceKey {
                    restoredNavigationNamespace = contentContext.namespaceKey
                    paths = restoreContentPaths(namespace: contentContext.namespaceKey)
                    if let tab = UserDefaults.standard.string(forKey: "book-content.tab.\(contentContext.namespaceKey)") {
                        selectedTabID = RootTabContract.normalizedID(tab)
                    }
                }
                openInitialUITestRouteIfNeeded()
            }
        }
    }

    private var contentContext: ContentRequestContext? {
        guard
            let profile = store.snapshot.profile,
            let userID = store.snapshot.userID,
            let authorization = store.snapshot.authorization
        else { return nil }
        return ContentRequestContext(
            profileID: profile.id,
            profileDisplayName: profile.displayName,
            serverIdentity: profile.serverIdentity,
            userID: userID,
            authorizationVersion: authorization.authorizationVersion,
            baseURL: profile.baseURL,
            acceptsInsecureTLS: profile.tlsMode == .insecureSkipAllValidation
        )
    }

    private func openInitialUITestRouteIfNeeded() {
        #if DEBUG
        let environment = ProcessInfo.processInfo.environment
        if !didOpenUITestRoute,
           environment["ERMAO_UI_TEST_INITIAL_DOWNLOADS"] == "1" {
            didOpenUITestRoute = true
            if let resourceID = environment["ERMAO_UI_TEST_INITIAL_DOWNLOAD_RESOURCE_ID"],
               !resourceID.isEmpty {
                downloads.uiTestResourceFilterID = resourceID
            }
            openDownloadsCenter()
            return
        }
        let fixtureBookID = environment[ContentUITestFixture.launchEnvironmentKey] == "1"
            ? environment["ERMAO_UI_TEST_INITIAL_WORK_ID"]
            : nil
        let liveBookID = environment["ERMAO_UI_TEST_LIVE_INITIAL_WORK_ID"]
        guard !didOpenUITestRoute,
              let bookID = fixtureBookID ?? liveBookID,
              !bookID.isEmpty
        else { return }
        didOpenUITestRoute = true
        // The explicit test destination takes precedence over a restored selected tab.
        selectedTabID = rootTabs.first(where: { $0.presentation == .home })?.id ?? "home"
        if let resourceID = environment["ERMAO_UI_TEST_LIVE_INITIAL_RESOURCE_ID"], !resourceID.isEmpty {
            open(.bookContent(bookID: bookID, destination: .resource(resourceID: resourceID)), in: .home)
        } else {
            open(.work(bookID: bookID), in: .home)
        }
        #endif
    }

    private func tabRoot(presentation: TabPresentation, context: ContentRequestContext) -> some View {
        HStack(spacing: 0) {
            if presentation == .library && horizontalSizeClass == .regular {
                libraryList(context: context)
                    .frame(minWidth: 320, idealWidth: 400, maxWidth: 480)
                Divider()
            }
            NavigationStack(path: path(for: presentation)) {
                Group {
                    switch presentation {
                    case .home:
                        HomeView(
                            context: context,
                            client: contentClient,
                            cache: cache,
                            onUnauthorized: store.refreshForForeground,
                            openWork: { open(.work(bookID: $0), in: .home) },
                            openCollection: { open(.collection($0), in: .home) }
                        )
                        .id(context.namespaceKey)
                    case .library:
                        libraryRoot(context: context)
                        .id(context.namespaceKey)
                    case .me:
                        if let settingsViewModel, let administrativeSettingsStore {
                            MeRootView(
                                viewModel: settingsViewModel,
                                administrativeStore: administrativeSettingsStore,
                                onOpenRoute: { open(.settings($0), in: .me) },
                                onOpenDownloads: openDownloadsCenter,
                                downloadStatus: downloads.records.isEmpty ? nil : "\(downloads.records.count)",
                                onOpenEmailAndKindle: {
                                    open(.administrative(.emailAndKindle), in: .me)
                                },
                                onOpenKindleQueue: {
                                    open(.administrative(.kindleQueue), in: .me)
                                },
                                onOpenAdministrativeRoute: {
                                    open(.administrative($0), in: .me)
                                }
                            )
                        } else {
                            Color.clear
                                .navigationTitle("tab.me")
                                .appCanvas()
                        }
                    case .shelves:
                        ShelfCatalogView(
                            context: context, client: shelfCatalogClient, contentClient: contentClient, cache: cache,
                            onUnauthorized: store.refreshForForeground,
                            openShelf: { open(.shelf(shelfID: $0), in: .shelves) },
                            openBook: { open(.work(bookID: $0), in: .shelves) }
                        )
                        .id(context.namespaceKey)
                    }
                }
                .navigationDestination(for: AppRoute.self) { route in
                    destination(route, presentation: presentation, context: context)
                }
                .administrativeNavigation { route in
                    open(.administrative(route), in: .me)
                }
                .environment(
                    \.administrativeCopy,
                    AdministrativeCopyCatalog(
                        locale: settingsViewModel?.snapshot.locale == .zhCN ? .zhCN : .enUS
                    )
                )
            }
        }
    }

    private func libraryList(context: ContentRequestContext) -> some View {
        LibraryView(
            context: context,
            client: contentClient,
            cache: cache,
            onUnauthorized: store.refreshForForeground,
            openWork: { open(.work(bookID: $0), in: .library) },
            openFacet: { open(.facet(kind: $0, facetID: $1), in: .library) }
        )
    }

    @ViewBuilder
    private func libraryRoot(context: ContentRequestContext) -> some View {
        if horizontalSizeClass == .regular {
            ContentStatusView(
                systemImage: "book.closed",
                title: "library.expanded.empty.title",
                message: "library.expanded.empty.message"
            )
        } else {
            libraryList(context: context)
        }
    }

    @ViewBuilder
    private func destination(
        _ route: AppRoute,
        presentation: TabPresentation,
        context: ContentRequestContext
    ) -> some View {
        switch route {
        case .work(let bookID), .bookContent(let bookID, _):
            WorkDetailView(
                context: context,
                client: contentClient,
                shelfClient: shelfClient,
                cache: cache,
                downloads: downloads,
                managementRepository: workManagementRepository,
                canManageSystem: store.snapshot.authorization?.canManageSystem == true,
                bookID: bookID,
                destination: route.contentDestination,
                openContent: { target in openBookContent(bookID: bookID, target: target, in: presentation) },
                onUnauthorized: store.refreshForForeground,
                openFacet: { open(.facet(kind: $0, facetID: $1), in: presentation) },
                openDownloads: openDownloadsCenter,
                openReader: { openReader($0, context: context, fallbackTab: presentation) }
            )
        case .downloads:
            DownloadCenterView(
                store: downloads,
                openAudio: { openAudioDownload($0, context: context) },
                openReader: { openReader($0, context: context, fallbackTab: presentation) }
            )
        case .reader(let handoff):
            ReaderHandoffView(handoff: handoff)
        case .facet(let kind, let facetID):
            FacetView(
                context: context,
                client: contentClient,
                cache: cache,
                kind: kind,
                facetID: facetID,
                onUnauthorized: store.refreshForForeground,
                openWork: { open(.work(bookID: $0), in: presentation) }
            )
        case .collection(let kind):
            WorkCollectionView(
                context: context,
                client: contentClient,
                cache: cache,
                kind: kind,
                onUnauthorized: store.refreshForForeground,
                openWork: { open(.work(bookID: $0), in: presentation) }
            )
        case .shelf(let shelfID):
            ShelfCatalogView(
                context: context, client: shelfCatalogClient, contentClient: contentClient, cache: cache, shelfID: shelfID,
                onUnauthorized: store.refreshForForeground,
                openShelf: { open(.shelf(shelfID: $0), in: presentation) },
                openBook: { open(.work(bookID: $0), in: presentation) }
            )
        case .settings(let route):
            if let settingsViewModel {
                SettingsDestinationView(route: route, viewModel: settingsViewModel)
            } else {
                Color.clear
                    .navigationTitle("tab.me")
                    .appCanvas()
            }
        case .administrative(let route):
            if let administrativeSettingsStore,
               administrativeSettingsStore.permissions.permits(route) {
                AdministrativeSettingsDestination(
                    route: route,
                    store: administrativeSettingsStore
                )
            } else {
                Color.clear
                    .navigationTitle("tab.me")
                    .appCanvas()
            }
        }
    }

    private func path(for presentation: TabPresentation) -> Binding<[AppRoute]> {
        Binding(
            get: { paths.path(for: presentation) },
            set: { paths.setPath($0, for: presentation) }
        )
    }

    private func popSelectedTabToRoot() {
        let selected = rootTabs.first(where: { $0.id == selectedTabID })?.presentation ?? .home
        paths.popToRoot(selected)
    }

    private func open(_ route: AppRoute, in tab: TabPresentation) {
        paths.open(route, in: tab)
    }

    private func openBookContent(bookID: String, target: BookContentDestination, in tab: TabPresentation) {
        if target == .root {
            open(.work(bookID: bookID), in: tab)
        } else {
            open(.bookContent(bookID: bookID, destination: target), in: tab)
        }
    }

    private func closeCurrentRoute(in tab: TabPresentation) {
        var path = paths.path(for: tab)
        _ = path.popLast()
        paths.setPath(path, for: tab)
    }

    private func openReader(
        _ selection: WorkReaderSelection,
        context: ContentRequestContext,
        managedDownloadRecordID: String? = nil,
        initialTargetPayload: String? = nil
    ) {
        guard readerComposition != nil else { return }
        readerLaunch = IosReaderLaunchRequest(
            context: context,
            bookID: selection.bookID,
            resourceID: selection.resourceID,
            displayTitle: selection.displayTitle,
            managedDownloadRecordID: managedDownloadRecordID,
            initialTargetPayload: initialTargetPayload
        )
    }

    private func openAudioDownload(
        _ record: ManagedDownloadRecord,
        context: ContentRequestContext
    ) {
        guard record.namespace == context.namespaceKey,
              record.readerType == .audio,
              record.verifiedSharedArtifact != nil,
              let expectedBytes = record.expectedBytes,
              expectedBytes == record.receivedBytes,
              let mimeType = record.mimeType,
              let audioPlaybackRuntime else { return }
        Task { @MainActor in
            guard let fileURL = await downloads.localFileURL(for: record) else { return }
            audioPlaybackRuntime.launchVerifiedLocalArtifact(
                namespace: context.namespaceKey,
                userID: context.userID,
                bookID: record.bookID,
                bookTitle: record.bookTitle,
                author: record.bookAuthor,
                resourceID: record.resourceID,
                resourceTitle: record.resourceTitle,
                assetID: record.assetID,
                fileURL: fileURL,
                mimeType: mimeType,
                sizeBytes: expectedBytes
            )
        }
    }

    private func openReader(
        _ handoff: ReaderHandoff,
        context: ContentRequestContext,
        fallbackTab: TabPresentation
    ) {
        if ManagedReaderAccessPolicy.supportsNativeHandoff(handoff),
           readerComposition != nil {
            let recordID: String?
            if case .verifiedLocal(let value) = handoff.source {
                recordID = value
            } else {
                recordID = nil
            }
            openReader(
                WorkReaderSelection(
                    bookID: handoff.bookID,
                    resourceID: handoff.resourceID,
                    displayTitle: handoff.title
                ),
                context: context,
                managedDownloadRecordID: recordID,
                initialTargetPayload: handoff.initialTargetPayload
            )
        } else {
            open(.reader(handoff), in: fallbackTab)
        }
    }

    private func openDownloadsCenter() {
        selectedTabID = rootTabs.first(where: { $0.presentation == .me })?.id ?? "me"
        paths.open(.downloads, in: .me)
    }

}

private struct RootTabControls: View {
    let tabs: [RootTabDefinition]
    let selectedTabID: String
    let onSelect: (String) -> Void
    @Environment(\.appTheme) private var theme

    var body: some View {
        HStack(spacing: 0) {
            ForEach(tabs) { tab in
                let isSelected = selectedTabID == tab.id
                Button {
                    onSelect(tab.id)
                } label: {
                    VStack(spacing: .spaceHalf) {
                        Image(systemName: tab.presentation.systemImage(isSelected: isSelected))
                            .font(.title3.weight(.semibold))
                            .frame(height: 24)
                        Text(tab.presentation.title)
                            .appTextStyle(.caption)
                            .lineLimit(2)
                            .multilineTextAlignment(.center)
                    }
                    .foregroundStyle(isSelected ? theme.brandAccent : theme.textPrimary)
                    .frame(maxWidth: .infinity, minHeight: .iosMinimumTouchTarget)
                    .padding(.vertical, .spaceHalf)
                    .background {
                        if isSelected {
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .fill(theme.accentSoft)
                                .padding(.horizontal, .spaceHalf)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
                .accessibilityLabel(Text(tab.presentation.title))
                .accessibilityAddTraits(isSelected ? .isSelected : [])
                .accessibilityIdentifier("tab-select-\(tab.id)")
            }
        }
        .padding(.horizontal, .space1)
        .padding(.top, .spaceHalf)
    }
}

private extension AdministrativeSettingsRoute {
    var identityKey: String {
        switch self {
        case .emailAndKindle: "email-kindle"
        case .kindleQueue: "kindle-queue"
        case .users: "users"
        case .userEditor(let userID): "user-editor:\(userID ?? "new")"
        case .userAccess(let userID): "user-access:\(userID)"
        case .librarySources: "library-sources"
        case .librarySourceEditor(let sourceID): "library-source:\(sourceID ?? "new")"
        case .serverDirectoryPicker(let purpose): "server-directory:\(purpose.identityKey)"
        case let .importTasks(libraryID): "import-tasks-\(libraryID)"
        case .importTaskDetail(let taskID): "import-task:\(taskID)"
        case .importScans: "import-scans"
        case .importPreferences: "import-preferences"
        case .organizeQueue: "organize-queue"
        case .organizeCandidates: "organize-candidates"
        case .organizeRuns: "organize-runs"
        case .recognitionPolicy: "recognition-policy"
        case .libraryOperations: "library-operations"
        case .categoryGovernance: "category-governance"
        case .metadataProviders: "metadata-providers"
        case .metadataProvider(let providerID): "metadata-provider:\(providerID)"
        case .opds: "opds"
        case .backups: "backups"
        case .workDetailOrder: "work-detail-order"
        case .health: "health"
        case .logs: "logs"
        case .about: "about"
        }
    }
}

private extension ServerDirectoryPurpose {
    var identityKey: String {
        switch self {
        case .createSource: "create"
        case .updateSource(let sourceID): "update:\(sourceID)"
        case .scanDirectory: "scan"
        }
    }
}

private struct ContentRouteRecord: Codable {
    let tab: TabPresentation
    let bookID: String
    let destination: BookContentDestination
    var shelfID: String? = nil
}

/// IDs only; restored destinations always reload and authorize against the server.
private func persistContentPaths(_ paths: RootTabPaths, namespace: String) {
    let records = [TabPresentation.home, .library, .shelves, .me].flatMap { tab in
        paths.path(for: tab).compactMap { route -> ContentRouteRecord? in
            switch route {
            case .work(let id): ContentRouteRecord(tab: tab, bookID: id, destination: .root)
            case .bookContent(let id, let destination): ContentRouteRecord(tab: tab, bookID: id, destination: destination)
            case .shelf(let id): ContentRouteRecord(tab: tab, bookID: "", destination: .root, shelfID: id)
            default: nil
            }
        }
    }
    guard records.count <= 64, let payload = try? JSONEncoder().encode(records) else { return }
    UserDefaults.standard.set(payload, forKey: "book-content.paths.\(namespace)")
}

private func restoreContentPaths(namespace: String) -> RootTabPaths {
    var result = RootTabPaths()
    guard let payload = UserDefaults.standard.data(forKey: "book-content.paths.\(namespace)"),
          payload.count <= 65536,
          let records = try? JSONDecoder().decode([ContentRouteRecord].self, from: payload),
          records.count <= 64
    else { return result }
    for record in records {
        if let shelfID = record.shelfID,
           !shelfID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, shelfID.count <= 512 {
            result.open(.shelf(shelfID: shelfID), in: record.tab)
            continue
        }
        guard !record.bookID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
              record.bookID.count <= 512, record.destination.isValid else { continue }
        let route: AppRoute = record.destination == .root
            ? .work(bookID: record.bookID) : .bookContent(bookID: record.bookID, destination: record.destination)
        result.open(route, in: record.tab)
    }
    return result
}
