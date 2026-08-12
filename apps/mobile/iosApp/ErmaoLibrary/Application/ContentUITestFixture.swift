import Foundation

enum ContentUITestFixture {
    static let launchEnvironmentKey = "ERMAO_UI_TEST_CONTENT_FIXTURE"

    @MainActor
    static func makeRuntime() -> PreviewMobileRuntime {
        let profile = RuntimeServerProfile(
            id: "ui-test-profile",
            displayName: "library.example.test",
            baseURL: "https://library.example.test",
            serverIdentity: "ui-test-server",
            isActive: true,
            tlsMode: .systemTrust
        )
        return PreviewMobileRuntime(
            snapshot: RuntimeSessionSnapshot(
                phase: .authenticated,
                profile: profile,
                userID: "ui-test-user",
                userDisplayName: "Reader",
                userEmail: "reader@example.test",
                userAvatarURL: nil,
                userLocale: "en-US",
                authorization: RuntimeAuthorization(
                    isAdmin: false,
                    canManageSystem: false,
                    allLibraryScopes: true,
                    monitorFolderIDs: [],
                    canViewManualImports: false,
                    authorizationVersion: 1
                ),
                reasonCode: nil
            )
        )
    }

    static func makeContentClient() -> any ContentClient {
        FixtureContentClient()
    }

    static func makeSettingsClient() -> any SettingsClient {
        FixtureSettingsClient()
    }
}

private struct FixtureSettingsClient: SettingsClient {
    private var account: SettingsAccount {
        SettingsAccount(
            id: "ui-test-user",
            displayName: "Reader",
            email: "reader@example.test",
            avatarURL: nil
        )
    }

    func loadSettings() async throws -> (account: SettingsAccount, locale: SettingsLocale) {
        (account, .enUS)
    }

    func updateName(_ name: String) async throws -> SettingsAccount { account }
    func updateEmail(_ email: String, currentPassword: String) async throws -> SettingsAccount { account }
    func updatePassword(currentPassword: String, newPassword: String) async throws -> SettingsPasswordChange {
        SettingsPasswordChange(requiresLogin: true)
    }
    func loadAvatar(etag: String?) async throws -> SettingsAvatarContent {
        SettingsAvatarContent(data: Data(), contentType: nil, etag: nil, notModified: false)
    }
    func uploadAvatar(_ upload: SettingsAvatarUpload) async throws -> SettingsAccount { account }
    func deleteAvatar() async throws -> SettingsAccount { account }
    func updateLocale(_ locale: SettingsLocale) async throws -> SettingsLocale { locale }
    func loadServerVersion() async throws -> String { "fixture-server" }
}

private struct FixtureContentClient: ContentClient {
    private let works = [
        WorkCard(
            id: "pride-and-prejudice",
            title: "Pride and Prejudice",
            author: "Jane Austen",
            cover: nil,
            progress: 32,
            availableMediaKinds: [.ebook]
        ),
        WorkCard(
            id: "the-left-hand-of-darkness",
            title: "The Left Hand of Darkness",
            author: "Ursula K. Le Guin",
            cover: nil,
            progress: nil,
            availableMediaKinds: [.ebook, .audiobook]
        ),
        WorkCard(
            id: "a-wizard-of-earthsea",
            title: "A Wizard of Earthsea",
            author: "Ursula K. Le Guin",
            cover: nil,
            progress: 68,
            availableMediaKinds: [.ebook]
        )
    ]

    func fetchContinueReading(context: ContentRequestContext) async throws -> ContinueReadingItem? {
        ContinueReadingItem(work: works[0], volumeTitle: nil, positionLabel: "32%")
    }

    func fetchRecentReading(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] {
        Array(works.prefix(limit))
    }

    func fetchRecentAdded(context: ContentRequestContext, limit: Int) async throws -> [WorkCard] {
        Array(works.reversed().prefix(limit))
    }

    func fetchWorks(context: ContentRequestContext, query: WorksQuery) async throws -> WorkPage {
        let filtered = query.query.isEmpty
            ? works
            : works.filter { $0.title.localizedCaseInsensitiveContains(query.query) }
        return WorkPage(
            works: filtered,
            page: query.page,
            pageSize: query.pageSize,
            total: filtered.count,
            totalPages: filtered.isEmpty ? 0 : 1
        )
    }

    func fetchGroupings(context: ContentRequestContext, query: GroupingsQuery) async throws -> GroupingPage {
        let names = query.kind == .series
            ? ["Earthsea", "Dune", "The Expanse"]
            : ["J.K. Rowling", "Frank Herbert", "Ursula K. Le Guin"]
        let groups = names.enumerated().map { index, name in
            let representativeCount = index + 1
            return LibraryGrouping(
                id: name.lowercased().replacingOccurrences(of: " ", with: "-"),
                kind: query.kind,
                name: name,
                workCount: representativeCount,
                representativeWorks: Array(works.prefix(representativeCount))
            )
        }
        return GroupingPage(groups: groups, page: query.page, pageSize: query.pageSize, total: groups.count, totalPages: 1)
    }

    func fetchFacet(context: ContentRequestContext, query: FacetQuery) async throws -> FacetPage {
        FacetPage(
            facet: FacetIdentity(
                id: query.facetID,
                kind: query.kind,
                name: query.kind == .series ? "Earthsea" : "Ursula K. Le Guin"
            ),
            works: works,
            page: query.page,
            pageSize: query.pageSize,
            total: works.count,
            totalPages: 1
        )
    }

    func fetchWorkDetail(context: ContentRequestContext, query: WorkDetailQuery) async throws -> WorkDetailContent {
        let work = works.first(where: { $0.id == query.workID }) ?? works[0]
        return WorkDetailContent(
            work: work,
            description: work.id == "a-wizard-of-earthsea"
                ? "  \n"
                : "A fixture description used only by the physical-device UI test.",
            tags: ["Classic", "Romance"],
            seriesFacet: FacetIdentity(id: "earthsea", kind: .series, name: "Earthsea"),
            authorFacets: [FacetIdentity(id: "ursula-le-guin", kind: .author, name: work.author)],
            availableMediaKinds: work.availableMediaKinds,
            selectedMediaKind: query.mediaKind ?? work.availableMediaKinds.first,
            selectedVolumeID: query.volumeID ?? "volume-1",
            readingStatus: work.progress == nil ? .unread : .reading,
            volumes: [
                WorkVolume(
                    id: "volume-1",
                    title: "Volume 1",
                    formatLabel: "EPUB",
                    sizeLabel: "2.6 MB",
                    progress: work.progress,
                    isReadable: true,
                    isSelected: true
                )
            ],
            chapters: [
                WorkChapter(id: "chapter-1", title: "Chapter 1", progress: work.progress, isCurrent: true),
                WorkChapter(id: "chapter-2", title: "Chapter 2", progress: nil, isCurrent: false),
            ]
        )
    }

    func fetchCoverData(context: ContentRequestContext, reference: CoverReference) async throws -> Data {
        throw ContentClientError.invalidResponse
    }
}
