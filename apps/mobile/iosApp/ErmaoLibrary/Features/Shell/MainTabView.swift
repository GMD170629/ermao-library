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

struct RootTabPaths {
    private var home = NavigationPath()
    private var library = NavigationPath()
    private var shelves = NavigationPath()
    private var me = NavigationPath()

    func path(for tab: TabPresentation) -> NavigationPath {
        switch tab {
        case .home: home
        case .library: library
        case .shelves: shelves
        case .me: me
        }
    }

    mutating func setPath(_ path: NavigationPath, for tab: TabPresentation) {
        switch tab {
        case .home: home = path
        case .library: library = path
        case .shelves: shelves = path
        case .me: me = path
        }
    }

    mutating func popToRoot(_ tab: TabPresentation) {
        setPath(NavigationPath(), for: tab)
    }
}

struct MainTabView: View {
    @ObservedObject var store: SessionStore
    private let rootTabs = RootTabContract.definitions

    @State private var selectedTabID = RootTabContract.orderedIDs.first ?? ""
    @State private var paths = RootTabPaths()

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
        TabView(selection: selection) {
            ForEach(rootTabs) { tab in
                tabRoot(presentation: tab.presentation)
                    .tabItem {
                        Label(
                            tab.presentation.title,
                            systemImage: tab.presentation.systemImage(isSelected: selectedTabID == tab.id)
                        )
                    }
                    .tag(tab.id)
            }
        }
    }

    private func tabRoot(presentation: TabPresentation) -> some View {
        NavigationStack(path: path(for: presentation)) {
            if presentation == .me {
                MeSummaryView(store: store)
            } else {
                Color.clear
                .navigationTitle(presentation.title)
                .appCanvas()
            }
        }
    }

    private func path(for presentation: TabPresentation) -> Binding<NavigationPath> {
        Binding(
            get: { paths.path(for: presentation) },
            set: { paths.setPath($0, for: presentation) }
        )
    }

    private func popSelectedTabToRoot() {
        let selected = rootTabs.first(where: { $0.id == selectedTabID })?.presentation ?? .home
        paths.popToRoot(selected)
    }
}

private struct MeSummaryView: View {
    @ObservedObject var store: SessionStore
    @Environment(\.appTheme) private var theme
    @State private var confirmsLogout = false

    var body: some View {
        List {
            Section("me.account.section") {
                LabeledContent("me.name") {
                    Text(store.snapshot.userDisplayName ?? "—")
                }
                LabeledContent("me.email") {
                    Text(store.snapshot.userEmail ?? "—")
                }
            }

            Section("me.server.section") {
                if let profile = store.snapshot.profile {
                    VStack(alignment: .leading, spacing: .spaceHalf) {
                        Text(profile.displayName)
                            .foregroundStyle(theme.textPrimary)
                        Text(profile.baseURL)
                            .font(.caption)
                            .foregroundStyle(theme.textSecondary)
                    }
                }
                Button("me.server.manage") { store.chooseAnotherServer() }
            }

            Section {
                Button("me.logout.action", role: .destructive) {
                    confirmsLogout = true
                }
            }
        }
        .scrollContentBackground(.hidden)
        .background(theme.canvas)
        .navigationTitle("tab.me")
        .confirmationDialog(
            "me.logout.confirm.title",
            isPresented: $confirmsLogout,
            titleVisibility: .visible
        ) {
            Button("me.logout.confirm.action", role: .destructive) { store.logout() }
            Button("common.cancel", role: .cancel) {}
        } message: {
            Text("me.logout.confirm.message")
        }
    }
}

struct OfflineShellView: View {
    @ObservedObject var store: SessionStore
    @Environment(\.appTheme) private var theme

    var body: some View {
        NavigationStack {
            VStack(spacing: .space2) {
                Image(systemName: "arrow.down.circle")
                    .font(.system(size: 44))
                    .foregroundStyle(theme.textSecondary)
                    .accessibilityHidden(true)
                Text("offline.empty.title")
                    .appTextStyle(.headline)
                Text("offline.empty.message")
                    .appTextStyle(.body)
                    .foregroundStyle(theme.textSecondary)
                    .multilineTextAlignment(.center)
                if let email = store.snapshot.userEmail {
                    Text(email)
                        .appTextStyle(.caption)
                        .foregroundStyle(theme.textTertiary)
                }
                Button("offline.reauthenticate.action") { store.retry() }
                    .buttonStyle(.borderedProminent)
                Button("auth.chooseServer") { store.chooseAnotherServer() }
                    .buttonStyle(.bordered)
            }
            .padding(.space3)
            .frame(maxWidth: 520)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .navigationTitle("offline.shell.title")
            .appCanvas()
        }
    }
}
