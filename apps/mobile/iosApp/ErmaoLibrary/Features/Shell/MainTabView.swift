import SwiftUI
@preconcurrency import ErmaoShared

enum TabPresentation: Equatable, Sendable {
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
    case downloads
    case reader(ReaderHandoff)
    case facet(kind: FacetKind, facetID: String)
    case collection(HomeCollectionKind)
    case settings(SettingsRoute)
    case administrative(AdministrativeSettingsRoute)

    var identityKey: String {
        switch self {
        case .work(let bookID): "work:\(bookID)"
        case .downloads: "downloads"
        case .reader(let handoff): "reader:\(handoff.resourceID):\(handoff.source)"
        case .facet(let kind, let facetID): "facet:\(kind.rawValue):\(facetID)"
        case .collection(let kind): "collection:\(kind.rawValue)"
        case .settings(let route): "settings:\(route.rawValue)"
        case .administrative(let route): "administrative:\(route.identityKey)"
        }
    }
}

struct RootTabPaths {
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
    let cache: LibraryCacheStore
    var settingsViewModel: SettingsViewModel? = nil
    var administrativeSettingsStore: AdministrativeSettingsStore? = nil
    var workManagementRepository: (any ErmaoShared.WorkManagementRepository)? = nil
    var readerComposition: IosReaderComposition? = nil
    private let rootTabs = RootTabContract.definitions

    @State private var selectedTabID = RootTabContract.orderedIDs.first ?? ""
    @State private var paths = RootTabPaths()
    @State private var expandedLibraryWorkID: String?
    @State private var readerLaunch: IosReaderLaunchRequest?
    @State private var readerPreparation: ReaderPreparationRequest?
    @Environment(\.horizontalSizeClass) private var horizontalSizeClass

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
            } else {
                ProgressView().accessibilityLabel(Text("common.loading"))
            }
        }
        .fullScreenCover(item: $readerLaunch) { request in
            if let readerComposition {
                IosReaderBootstrapView(request: request, composition: readerComposition)
            }
        }
        .fullScreenCover(item: $readerPreparation) { request in
            ReaderDownloadTransitionView(
                request: request,
                store: downloads,
                client: contentClient,
                cache: cache,
                readerComposition: readerComposition
            )
        }
        .task(id: contentContext?.namespaceKey) {
            if let contentContext {
                downloads.activate(context: contentContext)
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

    private func tabRoot(presentation: TabPresentation, context: ContentRequestContext) -> some View {
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
                    if let settingsViewModel {
                        MeRootView(
                            viewModel: settingsViewModel,
                            onOpenRoute: { open(.settings($0), in: .me) },
                            onOpenDownloads: openDownloadsCenter,
                            canOpenAdministration: administrativeSettingsStore?.permissions.isAdmin == true ||
                                administrativeSettingsStore?.permissions.canManageSystem == true,
                            onOpenEmailAndKindle: {
                                open(.administrative(.emailAndKindle), in: .me)
                            },
                            onOpenKindleQueue: {
                                open(.administrative(.kindleQueue), in: .me)
                            },
                            onOpenAdministration: {
                                open(.administrative(.management), in: .me)
                            }
                        )
                    } else {
                        Color.clear
                            .navigationTitle("tab.me")
                            .appCanvas()
                    }
                case .shelves:
                    Color.clear
                        .navigationTitle(presentation.title)
                        .appCanvas()
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
                administrativeSettingsStore?.copy ?? AdministrativeCopyCatalog(locale: .enUS)
            )
        }
    }

    @ViewBuilder
    private func libraryRoot(context: ContentRequestContext) -> some View {
        let library = LibraryView(
            context: context,
            client: contentClient,
            cache: cache,
            onUnauthorized: store.refreshForForeground,
            openWork: { bookID in
                if horizontalSizeClass == .regular {
                    expandedLibraryWorkID = bookID
                } else {
                    open(.work(bookID: bookID), in: .library)
                }
            },
            openFacet: { open(.facet(kind: $0, facetID: $1), in: .library) }
        )
        if horizontalSizeClass == .regular {
            HStack(spacing: 0) {
                library
                    .frame(minWidth: 360, idealWidth: 460, maxWidth: 520)
                Divider()
                Group {
                    if let bookID = expandedLibraryWorkID {
                        WorkDetailView(
                            context: context,
                            client: contentClient,
                            shelfClient: shelfClient,
                            cache: cache,
                            downloads: downloads,
                            managementRepository: workManagementRepository,
                            canManageSystem: store.snapshot.authorization?.canManageSystem == true,
                            bookID: bookID,
                            onUnauthorized: store.refreshForForeground,
                            openFacet: { open(.facet(kind: $0, facetID: $1), in: .library) },
                            openDownloads: openDownloadsCenter,
                            openReader: { openReader($0, context: context, fallbackTab: .library) },
                            prepareReader: { readerPreparation = $0 }
                        )
                        .id(bookID)
                    } else {
                        ContentStatusView(
                            systemImage: "book.closed",
                            title: "library.expanded.empty.title",
                            message: "library.expanded.empty.message"
                        )
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        } else {
            library
        }
    }

    @ViewBuilder
    private func destination(
        _ route: AppRoute,
        presentation: TabPresentation,
        context: ContentRequestContext
    ) -> some View {
        switch route {
        case .work(let bookID):
            WorkDetailView(
                context: context,
                client: contentClient,
                shelfClient: shelfClient,
                cache: cache,
                downloads: downloads,
                managementRepository: workManagementRepository,
                canManageSystem: store.snapshot.authorization?.canManageSystem == true,
                bookID: bookID,
                onUnauthorized: store.refreshForForeground,
                openFacet: { open(.facet(kind: $0, facetID: $1), in: presentation) },
                openDownloads: openDownloadsCenter,
                openReader: { openReader($0, context: context, fallbackTab: presentation) },
                prepareReader: { readerPreparation = $0 }
            )
        case .downloads:
            DownloadCenterView(
                store: downloads,
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

    private func closeCurrentRoute(in tab: TabPresentation) {
        var path = paths.path(for: tab)
        _ = path.popLast()
        paths.setPath(path, for: tab)
    }

    private func openReader(
        _ selection: WorkReaderSelection,
        context: ContentRequestContext,
        managedDownloadRecordID: String? = nil
    ) {
        guard readerComposition != nil else { return }
        readerLaunch = IosReaderLaunchRequest(
            context: context,
            bookID: selection.bookID,
            resourceID: selection.resourceID,
            displayTitle: selection.displayTitle,
            managedDownloadRecordID: managedDownloadRecordID
        )
    }

    private func openReader(
        _ handoff: ReaderHandoff,
        context: ContentRequestContext,
        fallbackTab: TabPresentation
    ) {
        if ManagedReaderAccessPolicy.supportsNativeReader(
               readerType: handoff.readerType,
               format: handoff.format
           ),
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
                managedDownloadRecordID: recordID
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

private extension AdministrativeSettingsRoute {
    var identityKey: String {
        switch self {
        case .management: "management"
        case .emailAndKindle: "email-kindle"
        case .kindleQueue: "kindle-queue"
        case .users: "users"
        case .userEditor(let userID): "user-editor:\(userID ?? "new")"
        case .userAccess(let userID): "user-access:\(userID)"
        case .librarySources: "library-sources"
        case .librarySourceEditor(let sourceID): "library-source:\(sourceID ?? "new")"
        case .serverDirectoryPicker(let purpose): "server-directory:\(purpose.identityKey)"
        case .importTasks: "import-tasks"
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
        case .metadataPipeline: "metadata-pipeline"
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
