import SwiftUI
import UIKit

struct BookCoverView: View {
    let reference: CoverReference?
    let title: String
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: LibraryCacheStore
    var cornerRadius: CGFloat = CGFloat(GeneratedDesignTokens.Radii.coverCompact)

    @Environment(\.appTheme) private var theme
    @State private var image: UIImage?
    @State private var cacheIssue: ContentCacheIssue?
    @State private var coverLoadIssue: ContentClientError?

    var body: some View {
        ZStack {
            if let image {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else {
                Image(systemName: "book.closed")
                    .font(.title2)
                    .foregroundStyle(theme.textTertiary)
                    .accessibilityHidden(true)
            }
        }
        .aspectRatio(2 / 3, contentMode: .fit)
        .clipShape(RoundedRectangle(cornerRadius: cornerRadius, style: .continuous))
        .shadow(color: theme.textPrimary.opacity(0.10), radius: 4, x: 0, y: 2)
        .accessibilityLabel(Text(title))
        .task(id: reference) {
            guard let reference else { return }
            let key = "cover|\(reference.path)"
            do {
                if let cached = try await cache.load(
                    Data.self,
                    namespace: context.namespaceKey,
                    key: key
                ), let decoded = UIImage(data: cached) {
                    image = decoded
                    return
                }
            } catch {
                cacheIssue = .readFailed
            }
            let data: Data
            do {
                data = try await client.fetchCoverData(context: context, reference: reference)
            } catch let error as ContentClientError {
                coverLoadIssue = error
                return
            } catch {
                coverLoadIssue = .transport
                return
            }
            guard !Task.isCancelled, let decoded = UIImage(data: data) else { return }
            image = decoded
            do { try await cache.save(data, namespace: context.namespaceKey, key: key) }
            catch { cacheIssue = .writeFailed }
        }
    }
}

struct CoverProgressView: View {
    let progress: Double
    @Environment(\.appTheme) private var theme

    var body: some View {
        if progress >= 100 {
            Image(systemName: "checkmark.circle.fill")
                .font(.caption)
                .foregroundStyle(theme.brandAccent)
                .accessibilityLabel(Text("library.progress.finished"))
        } else if progress > 0 {
            ProgressView(value: min(100, max(0, progress)), total: 100)
                .progressViewStyle(.linear)
                .tint(theme.brandAccent)
                .frame(height: 2)
                .padding(.horizontal, .space1)
                .accessibilityValue(Text(progress / 100, format: .percent.precision(.fractionLength(0))))
        }
    }
}

struct WorkGrid: View {
    let works: [WorkCard]
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: LibraryCacheStore
    let columns: Int
    let onSelect: (String) -> Void
    var onAppearWork: ((String) -> Void)?

    @Environment(\.appTheme) private var theme

    private var gridColumns: [GridItem] {
        Array(repeating: GridItem(.flexible(), spacing: .space2, alignment: .top), count: columns)
    }

    var body: some View {
        LazyVGrid(columns: gridColumns, alignment: .leading, spacing: .space3) {
            ForEach(works) { work in
                Button {
                    onSelect(work.id)
                } label: {
                    VStack(alignment: .leading, spacing: .spaceHalf) {
                        BookCoverView(
                            reference: work.cover,
                            title: work.title,
                            context: context,
                            client: client,
                            cache: cache
                        )
                        Text(work.title)
                            .appTextStyle(.label)
                            .lineLimit(1)
                            .foregroundStyle(theme.textPrimary)
                        Text(work.author)
                            .appTextStyle(.caption)
                            .lineLimit(1)
                            .foregroundStyle(theme.textSecondary)
                        if let progress = work.progress, progress > 0 {
                            CoverProgressView(progress: progress)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .accessibilityIdentifier("work.\(work.id)")
                .accessibilityLabel(Text(accessibilityLabel(for: work)))
                .onAppear { onAppearWork?(work.id) }
            }
        }
    }

    private func accessibilityLabel(for work: WorkCard) -> String {
        if let progress = work.progress, progress > 0 {
            return String(
                format: String(localized: "library.work.accessibility.progress"),
                locale: .current,
                work.title,
                work.author,
                Int(progress)
            )
        }
        return "\(work.title), \(work.author)"
    }
}

struct WorkList: View {
    let works: [WorkCard]
    let context: ContentRequestContext
    let client: any ContentClient
    let cache: LibraryCacheStore
    let onSelect: (String) -> Void
    var onAppearWork: ((String) -> Void)?

    @Environment(\.appTheme) private var theme

    var body: some View {
        LazyVStack(spacing: 0) {
            ForEach(works) { work in
                Button { onSelect(work.id) } label: {
                    HStack(spacing: .space2) {
                        BookCoverView(
                            reference: work.cover,
                            title: work.title,
                            context: context,
                            client: client,
                            cache: cache
                        )
                        .frame(width: 56)
                        VStack(alignment: .leading, spacing: .spaceHalf) {
                            Text(work.title).appTextStyle(.headline).lineLimit(2)
                            Text(work.author)
                                .appTextStyle(.label)
                                .foregroundStyle(theme.textSecondary)
                                .lineLimit(1)
                            if let progress = work.progress, progress > 0 {
                                CoverProgressView(progress: progress)
                            }
                        }
                        Spacer(minLength: 0)
                        Image(systemName: "chevron.forward")
                            .foregroundStyle(theme.textTertiary)
                            .accessibilityHidden(true)
                    }
                    .padding(.vertical, .space1)
                    .contentShape(Rectangle())
                }
                .buttonStyle(.borderless)
                .accessibilityIdentifier("work.\(work.id)")
                .onAppear { onAppearWork?(work.id) }
                Divider()
            }
        }
    }
}

struct ContentStatusView: View {
    let systemImage: String
    let title: LocalizedStringKey
    let message: LocalizedStringKey
    var actionTitle: LocalizedStringKey?
    var action: (() -> Void)?

    @Environment(\.appTheme) private var theme

    var body: some View {
        VStack(spacing: .space1Half) {
            Image(systemName: systemImage)
                .font(.system(size: 40, weight: .light))
                .foregroundStyle(theme.textTertiary)
                .accessibilityHidden(true)
            Text(title).appTextStyle(.headline)
            Text(message)
                .appTextStyle(.callout)
                .foregroundStyle(theme.textSecondary)
                .multilineTextAlignment(.center)
            if let actionTitle, let action {
                Button(actionTitle, action: action)
                    .buttonStyle(.bordered)
                    .tint(theme.actionAccent)
            }
        }
        .padding(.space3)
        .frame(maxWidth: .infinity)
    }
}

struct PaginationStatusView: View {
    let isLoading: Bool
    let hasError: Bool
    let retry: () -> Void

    @Environment(\.appTheme) private var theme

    var body: some View {
        Group {
            if isLoading {
                ProgressView().accessibilityLabel(Text("common.loading"))
            } else if hasError {
                HStack(spacing: .space1Half) {
                    Image(systemName: "wifi.exclamationmark")
                        .font(.title3)
                        .foregroundStyle(theme.textTertiary)
                        .accessibilityHidden(true)
                    VStack(alignment: .leading, spacing: .spaceHalf) {
                        Text("library.pagination.error")
                            .appTextStyle(.label)
                        Text("library.pagination.error.message")
                            .appTextStyle(.caption)
                            .foregroundStyle(theme.textSecondary)
                    }
                    Spacer()
                    Button("common.retry", action: retry)
                        .appTextStyle(.label)
                        .foregroundStyle(theme.actionAccent)
                        .frame(minHeight: .iosMinimumTouchTarget)
                }
                .padding(.top, .space1)
                .overlay(alignment: .top) {
                    Divider()
                }
            }
        }
        .padding(.vertical, .space2)
    }
}
