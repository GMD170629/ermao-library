import CryptoKit
import Foundation
import XCTest
import UIKit
@preconcurrency import ErmaoShared
@preconcurrency import ReadiumShared
@testable import ErmaoLibrary

@MainActor
final class DownloadStoreTests: XCTestCase {
    func testTwoGiBAdmissionDoesNotPromiseWholeArrayOpening() {
        let admission = ReaderAdmission.shared
        let limit = admission.maximumPublicationBytes
        XCTAssertEqual(limit, 2_147_483_648)
        XCTAssertTrue(admission.accepts(bytes: limit - 1))
        XCTAssertTrue(admission.accepts(bytes: limit))
        XCTAssertFalse(admission.accepts(bytes: limit + 1))
        XCTAssertNotNil(admission.localFailure(format: "txt", bytes: limit))
        XCTAssertEqual(admission.progress(received: limit / 2, total: limit), 0.5)
        XCTAssertEqual(admission.progress(received: limit, total: limit), 1.0)
    }

    @MainActor
    func testReaderReusesTheAccountDownloadAndAccountChangeCancelsIt() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let repository = ManagedDownloadStore(rootDirectory: root)
        let transfer = SuspendedReaderDownloadTransfer()
        let store = DownloadCenterStore(repository: repository, transfer: transfer)
        let context = ContentRequestContext(profileID: "profile", profileDisplayName: "Books", serverIdentity: "server",
                                            userID: "user", authorizationVersion: 1, baseURL: "https://books.example", acceptsInsecureTLS: false)
        store.activate(context: context)
        let descriptor = DownloadDescriptor(identity: DownloadIdentity(namespace: context.downloadRequestContext.namespace_,
            bookId: "book", resourceId: "resource", assetId: "asset"), bookTitle: "Book", bookAuthor: nil,
            coverApiPath: nil, resourceTitle: "Resource", format: "epub", readerType: .reflowable,
            source: DownloadSource(apiPath: "/api/assets/asset", mimeType: "application/epub+zip", totalBytes: 4,
                                   sourceModifiedAtMillis: nil), resourceIndex: nil, resourceSortOrder: nil,
            isDownloadable: true, artifactKind: .singleoriginalasset, members: [])
        XCTAssertTrue(store.beginReaderDownload(resourceID: "resource", descriptor: descriptor))
        XCTAssertFalse(store.beginReaderDownload(resourceID: "resource", descriptor: descriptor))
        try await waitUntil { transfer.started == 1 }
        let other = ContentRequestContext(profileID: "profile", profileDisplayName: "Books", serverIdentity: "server",
                                         userID: "other", authorizationVersion: 1, baseURL: "https://books.example", acceptsInsecureTLS: false)
        store.activate(context: other)
        try await waitUntil { transfer.cancelled == 1 }
        XCTAssertFalse(store.isCurrent(context))
        XCTAssertTrue(store.isCurrent(other))
        await store.cancelAllTransfers()
    }
    func testOriginalPageSetPublishesAsOneVerifiedDirectoryArtifact() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let pageSize = Self.imageDirectoryFixtureSize
        let pages = Self.makeImageDirectoryFixturePages()
        let totalBytes = pages.reduce(0) { $0 + $1.count }
        let record = try await store.seedDownload(
            namespace: namespace,
            book: BookCard(id: "book", title: "Book", author: "Author", cover: nil, progress: nil),
            resource: BookResource(
                id: "image-resource", bookID: "book", sourceNodeID: "directory", title: "Pages",
                format: "IMAGE_DIR", sizeLabel: nil, progress: nil, isReadable: true, isSelected: true
            ),
            assetID: "page-set:image-resource",
            readerType: .comic,
            expectedBytes: Int64(totalBytes),
            artifactKind: .originalPageSet
        )
        let destination = try await store.destination(for: record)
        try FileManager.default.createDirectory(at: destination.partialFileURL, withIntermediateDirectories: true)
        for (index, page) in pages.enumerated() {
            try page.write(to: destination.partialFileURL.appendingPathComponent("page-\(index).png"))
        }
        let manifest: [String: Any] = [
            "contractVersion": 4,
            "artifactKind": "OriginalPageSet",
            "resourceId": "image-resource",
            "artifactId": "page-set:image-resource",
            "totalBytes": totalBytes,
            "members": pages.enumerated().map { index, page -> [String: Any] in [
                "assetId": "page-\(index)", "sequenceIndex": index, "mimeType": "image/png",
                "sizeBytes": page.count, "fileName": "page-\(index).png",
            ] },
        ]
        try JSONSerialization.data(withJSONObject: manifest).write(
            to: destination.partialFileURL.appendingPathComponent("bundle.json")
        )

        let completed = try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(receivedBytes: Int64(totalBytes), expectedBytes: Int64(totalBytes))
        )
        let resolvedLocalURL = await store.fileURL(for: completed)
        let localURL = try XCTUnwrap(resolvedLocalURL)
        let bundle = try IosImageDirectoryBundle(directory: localURL, expectedResourceID: "image-resource")

        XCTAssertTrue(completed.isVerifiedOfflineCopy)
        XCTAssertTrue((try localURL.resourceValues(forKeys: [.isDirectoryKey])).isDirectory == true)
        XCTAssertEqual(bundle.pages.map(\.resourceHref), ["pages/0", "pages/1"])
        let managed = IosManagedPublication(
            resourceID: "image-resource", displayTitle: "Pages", fileURL: localURL,
            byteCount: Int64(totalBytes), bookID: "book", assetID: "page-set:image-resource",
            namespace: namespace, sourceFormat: .imagedir
        )
        let opened = try IosImageDirectoryPublicationFactory().open(managed, pageTitleHints: bundle.pages)
        for (index, link) in opened.publication.readingOrder.enumerated() {
            let resource = try XCTUnwrap(opened.publication.get(link))
            let bytes = try await FixtureResourceBox(resource).resource.read().get()
            XCTAssertEqual(bytes, pages[index], "Reader must return each original PAGE in order")
            let image = try XCTUnwrap(UIImage(data: bytes))
            XCTAssertEqual(image.size, pageSize)
            let pixel = try XCTUnwrap(Self.rgbaPixel(in: image, normalizedPoint: CGPoint(x: 0.9, y: 0.5)))
            Self.assertFixtureBackground(pixel, pageIndex: index)
            let attachment = XCTAttachment(image: image)
            attachment.name = "original-image-directory-page-\(index)"
            attachment.lifetime = .keepAlways
            add(attachment)
        }
        await opened.close()
    }

    @MainActor
    func testRemoteImageDirectoryPublicationResourcesReturnDecodableFixture() async throws {
        let pages = Self.makeImageDirectoryFixturePages()
        let pageHints = pages.enumerated().map { index, _ in
            IosCbzPage(
                pageIndex: index,
                resourceHref: "pages/\(index)",
                mediaType: "image/png",
                width: Int(Self.imageDirectoryFixtureSize.width),
                height: Int(Self.imageDirectoryFixtureSize.height)
            )
        }
        let sourcePages = pageHints.map {
            ErmaoShared.RemoteComicPage(
                pageIndex: Int32($0.pageIndex),
                resourceHref: $0.resourceHref,
                mediaType: $0.mediaType,
                width: KotlinInt(int: Int32($0.width ?? 0)),
                height: KotlinInt(int: Int32($0.height ?? 0))
            )
        }
        let source = ErmaoShared.RemoteComicReaderSource(
            resourceId: "remote-image-directory",
            displayTitle: "Remote image directory",
            bookId: "book",
            assetId: nil,
            namespace: ErmaoShared.PublicKt.createReaderSyncNamespace(
                serverIdentity: "fixture-server",
                userId: "fixture-user",
                authorizationVersion: 1
            ),
            sourceFormat: .imagedir,
            manifestApiPath: "/api/resources/remote-image-directory/comic-manifest",
            pageApiPathTemplate: "/api/resources/remote-image-directory/comic-pages/{pageIndex}",
            revision: "sha256:\(String(repeating: "a", count: 64))",
            pages: sourcePages
        )
        let server = FixtureComicPageServer(pages: pages)
        let opened = try IosRemoteComicPublicationFactory().open(
            source: source,
            pages: pageHints,
            server: server,
            imageVariant: .original,
            onFailure: { _ in }
        )

        for (index, link) in opened.publication.readingOrder.enumerated() {
            let resource = try XCTUnwrap(opened.publication.get(link))
            let bytes = try await FixtureResourceBox(resource).resource.read().get()
            XCTAssertEqual(bytes, pages[index])
            let image = try XCTUnwrap(UIImage(data: bytes))
            XCTAssertEqual(image.size, Self.imageDirectoryFixtureSize)
            let pixel = try XCTUnwrap(Self.rgbaPixel(in: image, normalizedPoint: CGPoint(x: 0.9, y: 0.5)))
            Self.assertFixtureBackground(pixel, pageIndex: index)
        }
        let requestedPageIndexes = await server.requestedPageIndexes
        XCTAssertEqual(requestedPageIndexes, [0, 1])
        await opened.close()
    }

    @MainActor
    func testImageDirectoryNavigatorRendersFixturePixels() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let directory = root.appendingPathComponent("pages", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let pages = Self.makeImageDirectoryFixturePages()
        for (index, page) in pages.enumerated() {
            try page.write(to: directory.appendingPathComponent("page-\(index).png"))
        }
        let manifest: [String: Any] = [
            "contractVersion": 4,
            "artifactKind": "OriginalPageSet",
            "resourceId": "navigator-image-directory",
            "artifactId": "page-set:navigator-image-directory",
            "totalBytes": pages.reduce(0) { $0 + $1.count },
            "members": pages.enumerated().map { index, page -> [String: Any] in [
                "assetId": "page-\(index)", "sequenceIndex": index, "mimeType": "image/png",
                "sizeBytes": page.count, "fileName": "page-\(index).png",
            ] },
        ]
        try JSONSerialization.data(withJSONObject: manifest).write(to: directory.appendingPathComponent("bundle.json"))
        let managed = IosManagedPublication(
            resourceID: "navigator-image-directory",
            displayTitle: "Navigator image directory",
            fileURL: directory,
            byteCount: Int64(pages.reduce(0) { $0 + $1.count }),
            bookID: "book",
            assetID: "page-set:navigator-image-directory",
            namespace: namespace,
            sourceFormat: .imagedir
        )
        let pageHints = pages.enumerated().map { index, _ in
            IosCbzPage(pageIndex: index, resourceHref: "pages/\(index)", mediaType: "image/png", width: 320, height: 480)
        }
        let opened = try IosImageDirectoryPublicationFactory().open(managed, pageTitleHints: pageHints)
        let navigator = try IosComicNavigatorViewController(
            publication: opened.publication,
            pages: pageHints,
            initialLocation: nil,
            preferences: IosReaderPreferences()
        )
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let originalWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        window.rootViewController = navigator
        window.makeKeyAndVisible()
        defer {
            window.isHidden = true
            window.rootViewController = nil
            originalWindow?.makeKey()
        }
        navigator.view.frame = window.bounds
        window.layoutIfNeeded()

        let first = try await Self.waitForFixturePixel(
            in: window,
            navigator: navigator,
            expectedPageIndex: 0
        )
        XCTAssertEqual(first.pageIndex, 0)
        XCTAssertEqual(first.imageSize, Self.imageDirectoryFixtureSize)
        let movedForward = await navigator.goForward(animated: false)
        XCTAssertTrue(movedForward)
        let second = try await Self.waitForFixturePixel(
            in: window,
            navigator: navigator,
            expectedPageIndex: 1
        )
        XCTAssertEqual(second.pageIndex, 1)
        XCTAssertEqual(second.imageSize, Self.imageDirectoryFixtureSize)
        XCTAssertNotEqual(first.pixel, second.pixel)

        var doublePage = IosReaderPreferences()
        doublePage.comicSpread = .double
        doublePage.comicDirection = .rtl
        doublePage.comicPageGap = 16
        let appliedDoublePage = await navigator.applyPreferences(doublePage)
        XCTAssertTrue(appliedDoublePage)
        window.layoutIfNeeded()
        try await Task.sleep(for: .milliseconds(100))
        let visibleImages = Self.visibleImageViews(in: navigator.view)
            .filter { imageView in
                guard imageView.image != nil,
                      !imageView.isHidden,
                      imageView.alpha > 0,
                      imageView.window === window
                else { return false }
                let frame = imageView.convert(imageView.bounds, to: window)
                return frame.width > 0 && frame.height > 0 && frame.intersects(window.bounds)
            }
            .sorted { $0.convert($0.bounds, to: window).minX < $1.convert($1.bounds, to: window).minX }
        XCTAssertEqual(visibleImages.count, 2, "Narrow iPhone must still honor the double-page preference")
        if visibleImages.count == 2 {
            let leftFrame = visibleImages[0].convert(visibleImages[0].bounds, to: window)
            let rightFrame = visibleImages[1].convert(visibleImages[1].bounds, to: window)
            XCTAssertEqual(rightFrame.minX - leftFrame.maxX, 16, accuracy: 1)
        }
        if visibleImages.count == 2 {
            let spreadScreenshot = Self.render(window: window)
            let leftFrame = visibleImages[0].convert(visibleImages[0].bounds, to: window)
            let rightFrame = visibleImages[1].convert(visibleImages[1].bounds, to: window)
            let leftPixel = try XCTUnwrap(Self.rgbaPixel(in: spreadScreenshot, point: CGPoint(x: leftFrame.midX, y: leftFrame.maxY - 10)))
            let rightPixel = try XCTUnwrap(Self.rgbaPixel(in: spreadScreenshot, point: CGPoint(x: rightFrame.midX, y: rightFrame.maxY - 10)))
            XCTAssertTrue(Self.isFixtureBackground(leftPixel, pageIndex: 1), "RTL must put logical page 1 in the left visual slot")
            XCTAssertTrue(Self.isFixtureBackground(rightPixel, pageIndex: 0), "RTL must put logical page 0 in the right visual slot")
        }

        var continuous = doublePage
        continuous.comicFlow = .scrolled
        continuous.comicImageFit = "height"
        continuous.comicZoom = 1.25
        let appliedContinuous = await navigator.applyPreferences(continuous)
        XCTAssertTrue(appliedContinuous)
        window.layoutIfNeeded()
        try await Task.sleep(for: .milliseconds(100))

        XCTAssertFalse(navigator.view.gestureRecognizers?.contains { gesture in
            (gesture as? UITapGestureRecognizer)?.numberOfTapsRequired == 2
        } ?? false)
        let continuousScrollView = try XCTUnwrap(
            navigator.view.subviews.compactMap { $0 as? UIScrollView }.first
        )
        XCTAssertEqual(continuousScrollView.decelerationRate, .normal)
        XCTAssertEqual(continuousScrollView.zoomScale, 1.25, accuracy: 0.001)
        let continuousCanvas = try XCTUnwrap(continuousScrollView.subviews.first)
        let continuousFrames = continuousCanvas.subviews.map(\.frame).sorted { $0.minY < $1.minY }
        XCTAssertEqual(continuousFrames.count, 2)
        if continuousFrames.count == 2 {
            XCTAssertEqual(continuousFrames[0].minY, 0, accuracy: 0.001)
            XCTAssertEqual(continuousFrames[1].minY, continuousFrames[0].maxY, accuracy: 0.001)
            XCTAssertEqual(continuousFrames[0].width, window.bounds.width, accuracy: 0.001)
            XCTAssertEqual(continuousFrames[0].height / continuousFrames[0].width, 1.5, accuracy: 0.001)
        }
        XCTAssertLessThanOrEqual(continuousCanvas.subviews.count, 3)
        await opened.close()
    }

    @MainActor
    func testContinuousDecodeCompletionReflowsPagesWithoutMovingViewport() async throws {
        let fixturePages = Self.makeImageDirectoryFixturePages()
        let pages = fixturePages.indices.map { index in
            // Local archive indexes do not currently expose image dimensions.
            // This exercises placeholder geometry before the decoded image
            // supplies its real intrinsic dimensions.
            IosCbzPage(
                pageIndex: index,
                resourceHref: "pages/\(index)",
                mediaType: "image/png",
                width: nil,
                height: nil
            )
        }
        let container = try DelayedComicFixtureContainer(
            resources: Dictionary(uniqueKeysWithValues: zip(pages, fixturePages).map {
                ($0.resourceHref, $1)
            }),
            delay: .milliseconds(350)
        )
        let readingOrder = pages.compactMap { page -> Link? in
            guard let mediaType = MediaType(page.mediaType) else { return nil }
            return Link(href: page.resourceHref, mediaType: mediaType)
        }
        XCTAssertEqual(readingOrder.count, pages.count)
        let publication = Publication(
            manifest: Manifest(
                metadata: Metadata(
                    identifier: "urn:shuku:test:continuous-stability",
                    conformsTo: [.divina],
                    title: "Continuous stability",
                    layout: .fixed,
                    readingProgression: .ltr,
                    numberOfPages: pages.count
                ),
                readingOrder: readingOrder
            ),
            container: container
        )
        defer { publication.close() }

        var preferences = IosReaderPreferences()
        preferences.comicFlow = .scrolled
        let navigator = try IosComicNavigatorViewController(
            publication: publication,
            pages: pages,
            initialLocation: nil,
            preferences: preferences
        )
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }.first)
        let originalWindow = scene.windows.first(where: \.isKeyWindow)
        let window = UIWindow(windowScene: scene)
        window.rootViewController = navigator
        window.makeKeyAndVisible()
        defer {
            navigator.close()
            window.isHidden = true
            window.rootViewController = nil
            originalWindow?.makeKey()
        }
        navigator.view.frame = window.bounds
        window.layoutIfNeeded()

        let scrollView = try XCTUnwrap(navigator.view.subviews.compactMap { $0 as? UIScrollView }.first)
        let maximumOffset = max(0, scrollView.contentSize.height - scrollView.bounds.height)
        XCTAssertGreaterThan(maximumOffset, 0)
        let simulatedUserOffset = CGPoint(x: scrollView.contentOffset.x, y: min(80, maximumOffset))
        scrollView.setContentOffset(simulatedUserOffset, animated: false)
        window.layoutIfNeeded()

        let offsetBeforeDecode = scrollView.contentOffset
        let canvas = try XCTUnwrap(scrollView.subviews.first)
        let pageFramesBeforeDecode = canvas.subviews.map(\.frame).sorted { $0.minY < $1.minY }
        XCTAssertEqual(pageFramesBeforeDecode.count, pages.count)

        try await Task.sleep(for: .milliseconds(700))
        window.layoutIfNeeded()

        let offsetAfterDecode = scrollView.contentOffset
        XCTAssertEqual(offsetAfterDecode.x, offsetBeforeDecode.x, accuracy: 0.001)
        XCTAssertEqual(offsetAfterDecode.y, offsetBeforeDecode.y, accuracy: 0.001)
        let pageFramesAfterDecode = canvas.subviews.map(\.frame).sorted { $0.minY < $1.minY }
        XCTAssertEqual(pageFramesAfterDecode.count, pages.count)
        if pageFramesBeforeDecode.count == pages.count, pageFramesAfterDecode.count == pages.count {
            XCTAssertNotEqual(
                pageFramesAfterDecode[0].height,
                pageFramesBeforeDecode[0].height,
                "Resolving an unknown intrinsic image size must be allowed to reflow the document"
            )
            XCTAssertEqual(
                pageFramesAfterDecode[0].height / pageFramesAfterDecode[0].width,
                1.5,
                accuracy: 0.001
            )
            XCTAssertEqual(pageFramesAfterDecode[1].minY, pageFramesAfterDecode[0].maxY, accuracy: 0.001)
        }
    }

    private static let imageDirectoryFixtureSize = CGSize(width: 320, height: 480)

    private static func makeImageDirectoryFixturePages() -> [Data] {
        let rendererFormat = UIGraphicsImageRendererFormat()
        rendererFormat.scale = 1
        let colors: [UIColor] = [
            UIColor(red: 0.02, green: 0.32, blue: 0.96, alpha: 1),
            UIColor(red: 0.98, green: 0.42, blue: 0.02, alpha: 1),
        ]
        return colors.enumerated().map { index, color in
            UIGraphicsImageRenderer(size: imageDirectoryFixtureSize, format: rendererFormat).pngData { context in
                color.setFill()
                context.fill(CGRect(origin: .zero, size: imageDirectoryFixtureSize))
                UIColor.white.setFill()
                context.fill(CGRect(x: 40, y: 80, width: 80 + index * 80, height: 200))
            }
        }
    }

    private static func assertFixtureBackground(_ pixel: FixturePixel, pageIndex: Int,
                                                file: StaticString = #filePath, line: UInt = #line) {
        switch pageIndex {
        case 0:
            XCTAssertGreaterThan(pixel.blue, 0.65, file: file, line: line)
            XCTAssertLessThan(pixel.red, 0.35, file: file, line: line)
            XCTAssertLessThan(pixel.green, 0.55, file: file, line: line)
        case 1:
            XCTAssertGreaterThan(pixel.red, 0.65, file: file, line: line)
            XCTAssertGreaterThan(pixel.green, 0.20, file: file, line: line)
            XCTAssertLessThan(pixel.blue, 0.35, file: file, line: line)
        default:
            XCTFail("Unexpected image directory fixture page \(pageIndex)", file: file, line: line)
        }
    }

    @MainActor
    private static func waitForFixturePixel(
        in window: UIWindow,
        navigator: IosComicNavigatorViewController,
        expectedPageIndex: Int
    ) async throws -> FixturePixelEvidence {
        var lastPixel: FixturePixel?
        var lastImageSize: CGSize?
        for _ in 0 ..< 120 {
            guard navigator.currentLocation?.href.string == "pages/\(expectedPageIndex)" else {
                try await Task.sleep(for: .milliseconds(100))
                continue
            }
            let screenshot = Self.render(window: window)
            let pixel = Self.rgbaPixel(in: screenshot, normalizedPoint: CGPoint(x: 0.9, y: 0.5))
            let image = Self.visibleImage(in: navigator.view)
            lastPixel = pixel
            lastImageSize = image?.size
            if let pixel, let image, Self.isFixtureBackground(pixel, pageIndex: expectedPageIndex) {
                return FixturePixelEvidence(
                    pageIndex: expectedPageIndex,
                    imageSize: image.size,
                    pixel: pixel
                )
            }
            try await Task.sleep(for: .milliseconds(100))
        }
        XCTFail(
            "Timed out waiting for IMAGE_DIR page \(expectedPageIndex) to render; " +
                "pixel=\(String(describing: lastPixel)) imageSize=\(String(describing: lastImageSize))"
        )
        throw FixturePixelEvidenceError.notRendered
    }

    private static func isFixtureBackground(_ pixel: FixturePixel, pageIndex: Int) -> Bool {
        switch pageIndex {
        case 0: pixel.blue > 0.65 && pixel.red < 0.35 && pixel.green < 0.55
        case 1: pixel.red > 0.65 && pixel.green > 0.20 && pixel.blue < 0.35
        default: false
        }
    }

    private static func render(window: UIWindow) -> UIImage {
        let format = UIGraphicsImageRendererFormat()
        format.scale = window.screen.scale
        return UIGraphicsImageRenderer(bounds: window.bounds, format: format).image { _ in
            window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
        }
    }

    private static func visibleImage(in view: UIView) -> UIImage? {
        if let imageView = view as? UIImageView,
           !imageView.isHidden,
           imageView.alpha > 0,
           imageView.window != nil,
           let image = imageView.image {
            return image
        }
        for child in view.subviews.reversed() {
            if let image = visibleImage(in: child) { return image }
        }
        return nil
    }

    private static func visibleImageViews(in view: UIView) -> [UIImageView] {
        let own = (view as? UIImageView).map { [$0] } ?? []
        return own + view.subviews.flatMap(visibleImageViews(in:))
    }

    private static func rgbaPixel(in image: UIImage, normalizedPoint: CGPoint) -> FixturePixel? {
        guard let cgImage = image.cgImage, cgImage.width > 0, cgImage.height > 0 else { return nil }
        let x = min(max(Int(CGFloat(cgImage.width) * normalizedPoint.x), 0), cgImage.width - 1)
        let y = min(max(Int(CGFloat(cgImage.height) * normalizedPoint.y), 0), cgImage.height - 1)
        guard let sample = cgImage.cropping(to: CGRect(x: x, y: y, width: 1, height: 1)) else { return nil }
        var bytes = [UInt8](repeating: 0, count: 4)
        bytes.withUnsafeMutableBytes { rawBuffer in
            guard let baseAddress = rawBuffer.baseAddress,
                  let context = CGContext(
                      data: baseAddress,
                      width: 1,
                      height: 1,
                      bitsPerComponent: 8,
                      bytesPerRow: 4,
                      space: CGColorSpaceCreateDeviceRGB(),
                      bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
                  )
            else { return }
            context.draw(sample, in: CGRect(x: 0, y: 0, width: 1, height: 1))
        }
        return FixturePixel(
            red: CGFloat(bytes[0]) / 255,
            green: CGFloat(bytes[1]) / 255,
            blue: CGFloat(bytes[2]) / 255,
            alpha: CGFloat(bytes[3]) / 255
        )
    }

    private static func rgbaPixel(in image: UIImage, point: CGPoint) -> FixturePixel? {
        guard image.size.width > 0, image.size.height > 0 else { return nil }
        return rgbaPixel(
            in: image,
            normalizedPoint: CGPoint(x: point.x / image.size.width, y: point.y / image.size.height)
        )
    }

    func testManifestV3RecordMigratesToV4WithoutDeletingCompletedFile() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let record = try await makeRecord(store: store)
        let completed = try await complete(record, in: store)
        let namespaceDirectory = try XCTUnwrap(
            FileManager.default.contentsOfDirectory(at: root, includingPropertiesForKeys: [.isDirectoryKey])
                .first(where: { (try? $0.resourceValues(forKeys: [.isDirectoryKey]).isDirectory) == true })
        )
        let manifestURL = namespaceDirectory.appendingPathComponent("manifest.json")
        var manifest = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any]
        )
        manifest["contractVersion"] = 3
        try JSONSerialization.data(withJSONObject: manifest).write(to: manifestURL, options: .atomic)

        let migrated = try await store.records(namespace: namespace)

        XCTAssertEqual(migrated.single?.id, completed.id)
        XCTAssertEqual(migrated.single?.effectiveArtifactKind, .singleOriginalAsset)
        let migratedLocalURL = await store.fileURL(for: migrated.single!)
        XCTAssertNotNil(migratedLocalURL)
        let persisted = try XCTUnwrap(
            JSONSerialization.jsonObject(with: Data(contentsOf: manifestURL)) as? [String: Any]
        )
        XCTAssertEqual(persisted["contractVersion"] as? Int, 4)
    }

    func testLiveStylesResourceTransferDiagnostic() async throws {
        let profileID = "03139ac0-7820-4e10-9f9e-73f177327398"
        let context = ContentRequestContext(
            profileID: profileID,
            profileDisplayName: "192.168.18.228",
            serverIdentity: "server_d25920669ac94839b6ee9a7054d4dc00",
            userID: "py_48e39b93790f4057995840a18f4302a3",
            authorizationVersion: 1,
            baseURL: "http://192.168.18.228:3000",
            acceptsInsecureTLS: false
        )
        let cookieStore = KeychainCookiePayloadStore()
        XCTAssertNotNil(try cookieStore.load(profileID: profileID), "The live device session cookie must be available")
        let transfer = SharedManagedDownloadTransfer(cookieStore: cookieStore)
        let resource = BookResource(
            id: "py_db7f936c9cda4a5a865892029c18d1ff",
            bookID: "py_75b1eb8b3f5c4a0386a7f06ffc956563",
            sourceNodeID: "py_c380d324fe7d4aa8ae579d6f6051fd86",
            title: "EPUB acceptance fixture",
            format: "EPUB",
            sizeLabel: nil,
            progress: nil,
            isReadable: true,
            isSelected: true
        )
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        try await transfer.download(context: context, resourceID: resource.id, repository: store) { _ in }
        let records = try await store.records(namespace: context.namespaceKey)
        let completed = try XCTUnwrap(records.single)
        XCTAssertTrue(completed.isVerifiedOfflineCopy)
        let storedURL = await store.fileURL(for: completed)
        let file = try XCTUnwrap(storedURL)
        XCTAssertEqual(try file.resourceValues(forKeys: [.fileSizeKey]).fileSize, completed.expectedBytes.map(Int.init))
        // A repeated explicit request must reuse the same verified task and artifact.
        try await transfer.download(context: context, resourceID: resource.id, repository: store) { _ in }
        let repeated = try await store.records(namespace: context.namespaceKey)
        XCTAssertEqual(repeated.map(\.id), [completed.id])
    }

    func testLiveAzw3TransferPreservesOriginalBytesAndParses() async throws {
        let context = ContentRequestContext(
            profileID: "03139ac0-7820-4e10-9f9e-73f177327398",
            profileDisplayName: "192.168.18.228",
            serverIdentity: "server_d25920669ac94839b6ee9a7054d4dc00",
            userID: "py_48e39b93790f4057995840a18f4302a3",
            authorizationVersion: 1,
            baseURL: "http://192.168.18.228:3000",
            acceptsInsecureTLS: false
        )
        let cookieStore = KeychainCookiePayloadStore()
        XCTAssertNotNil(try cookieStore.load(profileID: context.profileID))
        let gateway = IosCompositionKt.createIosDownloadsGateway(
            cookieStore: cookieStore,
            profileId: context.profileID,
            displayName: context.profileDisplayName,
            baseUrl: context.baseURL,
            serverIdentity: context.serverIdentity,
            acceptsInsecureTls: context.acceptsInsecureTLS
        )
        let sharedContext = PublicKt.createDownloadRequestContext(
            profileId: context.profileID,
            displayName: context.profileDisplayName,
            baseUrl: context.baseURL,
            serverIdentity: context.serverIdentity,
            acceptsInsecureTls: context.acceptsInsecureTLS,
            userId: context.userID,
            authorizationVersion: context.authorizationVersion
        )
        if let failure = try await gateway.load(
            context: sharedContext,
            resourceId: "py_35ecd0b1eb7b4e90ad34f38fdbff4465"
        ) as? ErmaoShared.DownloadBootstrapResultFailure {
            XCTFail("bootstrap \(failure.error.code): \(failure.error.diagnosticMessage ?? "no diagnostic")")
            return
        }
        let transfer = SharedManagedDownloadTransfer(cookieStore: cookieStore)
        let resource = BookResource(
            id: "py_35ecd0b1eb7b4e90ad34f38fdbff4465",
            bookID: "py_a0469b0ed7a74bb382372f69d8895b54",
            sourceNodeID: "live-source-node",
            title: "Reader Sample 03",
            format: "AZW3",
            sizeLabel: nil,
            progress: nil,
            isReadable: true,
            isSelected: true
        )
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        try await transfer.download(context: context, resourceID: resource.id, repository: store) { _ in }
        let records = try await store.records(namespace: context.namespaceKey)
        let completed = try XCTUnwrap(records.single)
        let storedURL = await store.fileURL(for: completed)
        let file = try XCTUnwrap(storedURL)
        XCTAssertEqual(completed.format, "AZW3")
        XCTAssertEqual(completed.mimeType, "application/vnd.amazon.ebook")
        XCTAssertEqual(file.pathExtension, "azw3")
        let bytes = try Data(contentsOf: file)
        XCTAssertEqual(Int64(bytes.count), completed.expectedBytes)
        XCTAssertEqual(
            SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined(),
            "528c43db8b2df3190dbf42f96fe6be68391d9239a186fb77d0670dda832863dc"
        )
        let book = try IosMobiBook.open(fileURL: file)
        let info = try await book.info()
        await book.close()
        XCTAssertGreaterThan(info.readingOrderCount, 0)
    }

    func testPublishRequiresCompleteVerifiedPartialFile() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let record = try await makeRecord(store: store)
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3]).write(to: destination.partialFileURL)

        do {
            _ = try await store.seedCompleted(
                record: record,
                destination: destination,
                receipt: CompletedFixtureBytes(
                    receivedBytes: 3,
                    expectedBytes: 4
                )
            )
            XCTFail("A partial file must never be published as completed")
        } catch let error as ManagedDownloadTransferError {
            XCTAssertEqual(error, .invalidResponse)
        }

        let loaded = try await store.records(namespace: namespace)
        XCTAssertEqual(loaded.single?.state, .queued)
        XCTAssertEqual(loaded.single?.verification, .pending)
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.partialFileURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.finalFileURL.path))
    }

    func testPublishAtomicallyMovesContentThenMarksManifestVerified() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let record = try await makeRecord(store: store)
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3, 4]).write(to: destination.partialFileURL)

        let completed = try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(
                receivedBytes: 4,
                expectedBytes: 4
            )
        )

        XCTAssertTrue(completed.isVerifiedOfflineCopy)
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.partialFileURL.path))
        XCTAssertEqual(try Data(contentsOf: destination.finalFileURL), Data([1, 2, 3, 4]))
        let loaded = try await store.records(namespace: namespace)
        XCTAssertTrue(loaded.single?.isVerifiedOfflineCopy == true)
        let localFileURL = await store.fileURL(for: completed)
        XCTAssertEqual(
            localFileURL?.resolvingSymlinksInPath(),
            destination.finalFileURL.resolvingSymlinksInPath()
        )
    }

    func testReloadInvalidatesCompletedManifestWhenLocalFileIsMissing() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let record = try await makeRecord(store: store)
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3, 4]).write(to: destination.partialFileURL)
        let completed = try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(
                receivedBytes: 4,
                expectedBytes: 4
            )
        )
        try FileManager.default.removeItem(at: destination.finalFileURL)

        let loaded = try await store.records(namespace: namespace)

        XCTAssertEqual(loaded.single?.id, completed.id)
        XCTAssertEqual(loaded.single?.state, .failedTerminal)
        XCTAssertEqual(loaded.single?.verification, .invalid)
        XCTAssertEqual(loaded.single?.stableErrorCode, "DOWNLOAD_LOCAL_FILE_INVALID")
    }

    func testDiscardRemovesPublishedAndPartialBytesBeforeTaskRebuild() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let record = try await makeRecord(store: store)
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3, 4]).write(to: destination.partialFileURL)
        let completed = try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(receivedBytes: 4, expectedBytes: 4)
        )

        try await store.discardStoredBytes(for: completed)

        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.partialFileURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: destination.finalFileURL.path))
        let discardedFile = await store.fileURL(for: completed)
        XCTAssertNil(discardedFile)
    }

    func testNamespacesRemainIsolatedAndCanBePurgedIndependently() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        _ = try await makeRecord(store: store, namespace: "server|one|1", resourceID: "one")
        _ = try await makeRecord(store: store, namespace: "server|two|1", resourceID: "two")

        try await store.removeNamespace("server|one|1")

        let firstNamespaceRecords = try await store.records(namespace: "server|one|1")
        let secondNamespaceRecords = try await store.records(namespace: "server|two|1")
        XCTAssertTrue(firstNamespaceRecords.isEmpty)
        XCTAssertEqual(secondNamespaceRecords.map(\.resourceID), ["two"])
    }

    func testUpdatingCatalogProjectionPreservesTaskIdentity() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let original = try await makeRecord(store: store)
        var updated = original
        updated.receivedBytes = 2
        updated.state = .paused
        try await store.update(updated)
        let records = try await store.records(namespace: namespace)
        XCTAssertEqual(records.map(\.id), [original.id])
        XCTAssertEqual(records.single?.receivedBytes, 2)
        XCTAssertEqual(records.single?.state, .paused)
    }

    func testExactMobiFamilySourceFormatPreservesExtensionAndMime() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let resource = BookResource(
            id: "resource", bookID: "book", sourceNodeID: "source-node-azw3",
            title: "Resource", format: "AZW3", sizeLabel: "4 bytes",
            progress: nil, isReadable: true, isSelected: true
        )
        let book = BookCard(id: "book", title: "Book", author: nil, cover: nil, progress: nil)
        let exact = try await store.seedDownload(
            namespace: namespace,
            book: book,
            resource: resource,
            assetID: "asset",
            sourceFormat: "AZW3",
            mimeType: "application/vnd.amazon.ebook",
            readerType: .reflowable,
            expectedBytes: 4
        )
        let destination = try await store.destination(for: exact)

        XCTAssertEqual(exact.format, "AZW3")
        XCTAssertEqual(exact.mimeType, "application/vnd.amazon.ebook")
        XCTAssertEqual(destination.finalFileURL.lastPathComponent, "asset.azw3")
        let persisted = try await store.records(namespace: namespace)
        XCTAssertEqual(persisted.map(\.id), [exact.id])
    }

    func testChangedAssetIdentityPreservesPreviousTask() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let original = try await makeRecord(store: store)
        let resource = BookResource(
            id: original.resourceID,
            bookID: original.bookID,
            sourceNodeID: "source-node-new",
            title: "Resource",
            format: "EPUB",
            sizeLabel: "4 bytes",
            progress: nil,
            isReadable: true,
            isSelected: true
        )

        let replacement = try await store.seedDownload(
            namespace: namespace,
            book: BookCard(
                id: "book",
                title: "Book",
                author: "Author",
                cover: nil,
                progress: nil
            ),
            resource: resource,
            assetID: "asset-new",
            readerType: .reflowable,
            expectedBytes: 4
        )

        XCTAssertNotEqual(replacement.id, original.id)
        XCTAssertEqual(replacement.assetID, "asset-new")
    }

    func testReaderRecordSelectsOnlyTheExactAssetVersion() async throws {
        let repository = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        var stale = try await makeRecord(store: repository)
        var current = try await makeRecord(store: repository)
        let staleDescriptor = try exactDescriptor(for: stale, totalBytes: 3)
        let currentDescriptor = try exactDescriptor(for: current, totalBytes: 4)
        stale.sharedTaskJSON = DownloadCatalogCodec.shared.encode(task: DownloadTask(
            id: stale.id,
            descriptor: staleDescriptor,
            status: .queued,
            transferredBytes: 0,
            failureCode: nil,
            artifact: nil
        ))
        current.sharedTaskJSON = DownloadCatalogCodec.shared.encode(task: DownloadTask(
            id: current.id,
            descriptor: currentDescriptor,
            status: .queued,
            transferredBytes: 0,
            failureCode: nil,
            artifact: nil
        ))
        let center = DownloadCenterStore(repository: repository)

        XCTAssertEqual(
            center.readerRecord(descriptor: currentDescriptor, records: [stale, current])?.id,
            current.id
        )
        XCTAssertNil(center.readerRecord(
            descriptor: try exactDescriptor(for: current, totalBytes: 5),
            records: [stale, current]
        ))
    }

    func testAssetIdentityPersistsAndGroupsResourcesBelowBook() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let first = try await makeRecord(store: store, resourceID: "resource-1", assetID: "asset-1")
        let second = try await makeRecord(store: store, resourceID: "resource-2", assetID: "asset-2")
        let firstCompleted = try await complete(first, in: store)
        let secondCompleted = try await complete(second, in: store)

        let reloaded = try await store.records(namespace: namespace)
        XCTAssertEqual(Set(reloaded.map(\.assetID)), ["asset-1", "asset-2"])

        let groups = ManagedDownloadGrouping.completed(
            records: [firstCompleted, secondCompleted],
            query: "Book"
        )
        XCTAssertEqual(groups.count, 1)
        XCTAssertEqual(groups.single?.resources.count, 2)
        XCTAssertEqual(groups.single?.resources.flatMap(\.records).count, 2)
    }

    func testDownloadLocalizationKeepsStorageAndImplicitVersionKeys() throws {
        for locale in ["en", "zh-Hans"] {
            let localizationPath = try XCTUnwrap(
                Bundle.main.path(forResource: locale, ofType: "lproj")
            )
            let bundle = try XCTUnwrap(Bundle(path: localizationPath))
            for key in ["downloads.storage.used", "downloads.version.implicit"] {
                let localized = bundle.localizedString(forKey: key, value: nil, table: nil)
                XCTAssertNotEqual(localized, key, "Missing \(key) in \(locale)")
                XCTAssertFalse(localized.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    func testCatalogWithoutAssetIdentityIsDiscarded() async throws {
        let root = temporaryDirectory()
        defer { try? FileManager.default.removeItem(at: root) }
        let store = ManagedDownloadStore(rootDirectory: root)
        let record = try await makeRecord(store: store)
        let encoded = try JSONEncoder().encode(record)
        var object = try XCTUnwrap(JSONSerialization.jsonObject(with: encoded) as? [String: Any])
        object.removeValue(forKey: "assetID")
        let legacyData = try JSONSerialization.data(withJSONObject: object)

        XCTAssertThrowsError(try JSONDecoder().decode(ManagedDownloadRecord.self, from: legacyData))
    }

    func testOfflineHandoffOnlyAcceptsCompletedVerifiedArtifacts() async throws {
        let store = ManagedDownloadStore(rootDirectory: temporaryDirectory())
        let queued = try await makeRecord(store: store)
        XCTAssertNil(ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: queued,
            resourceID: queued.resourceID
        ))

        let completedWithoutDescriptor = try await complete(queued, in: store)
        XCTAssertNil(ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: completedWithoutDescriptor,
            resourceID: completedWithoutDescriptor.resourceID
        ))
        var completed = completedWithoutDescriptor
        completed.mimeType = "application/epub+zip"
        let descriptor = try exactDescriptor(for: completed)
        let artifact = CompletedDownloadArtifact(
            descriptor: descriptor,
            localReference: try XCTUnwrap(completed.localRelativePath),
            verifiedBytes: completed.receivedBytes,
            completedAtEpochMillis: Int64((completed.completedAt ?? completed.updatedAt).timeIntervalSince1970 * 1_000),
            lastOpenedAtEpochMillis: nil
        )
        completed.sharedTaskJSON = DownloadCatalogCodec.shared.encode(task: DownloadTask(
            id: completed.id,
            descriptor: descriptor,
            status: .completed,
            transferredBytes: completed.receivedBytes,
            failureCode: nil,
            artifact: artifact
        ))
        let handoff = ManagedReaderAccessPolicy.verifiedLocalHandoff(
            record: completed,
            resourceID: completed.resourceID
        )

        XCTAssertEqual(handoff?.source, .verifiedLocal(recordID: completed.id))
        XCTAssertEqual(ManagedReaderAccessPolicy.completedRecord(
            records: [completed],
            recordID: completed.id
        )?.id, completed.id)
    }

    func testNativeReaderPolicyRequiresExactMobiFamilyFormatAndAcceptsAllComicArchives() {
        XCTAssertFalse(ReaderFormatSupport.shared.canReadOriginal(
            readerType: "reflowable",
            format: "KINDLE"
        ))
        for format in ["MOBI", "AZW", "AZW3", "PRC"] {
            XCTAssertTrue(
                ReaderFormatSupport.shared.canReadOriginal(readerType: "reflowable", format: format),
                "Expected exact native reflowable support for \(format)"
            )
        }
        for format in ["EPUB", "MOBI", "AZW", "AZW3", "PRC", "FB2", "TXT"] {
            XCTAssertEqual(
                ReaderFormatSupport.shared.deliveryMode(readerType: "reflowable", format: format),
                .downloadoriginal
            )
        }
        XCTAssertEqual(ReaderFormatSupport.shared.deliveryMode(readerType: "pdf", format: "PDF"), .stream)
        for format in ["CBZ", "ZIP", "CBR", "RAR", "IMAGE_DIR"] {
            XCTAssertTrue(
                ReaderFormatSupport.shared.canReadOriginal(readerType: "comic", format: format),
                "Expected native comic support for \(format)"
            )
            XCTAssertEqual(ReaderFormatSupport.shared.deliveryMode(readerType: "comic", format: format), .stream)
        }
        XCTAssertEqual(ReaderFormatSupport.shared.deliveryMode(readerType: "audio", format: "MP3"), .unsupported)
    }

    func testReaderHandoffUsesDeliveryModeAndRejectsGenericKindle() {
        func handoff(
            _ source: ReaderHandoffSource,
            format: String,
            readerType: ManagedDownloadReaderType
        ) -> ReaderHandoff {
            ReaderHandoff(
                bookID: "book", resourceID: "resource", assetID: nil,
                title: "Book", resourceTitle: "Resource", format: format,
                readerType: readerType, source: source
            )
        }
        XCTAssertTrue(ManagedReaderAccessPolicy.supportsNativeHandoff(
            handoff(.remoteStream, format: "EPUB", readerType: .reflowable)
        ))
        XCTAssertTrue(ManagedReaderAccessPolicy.supportsNativeHandoff(
            handoff(.remoteStream, format: "PDF", readerType: .pdf)
        ))
        XCTAssertTrue(ManagedReaderAccessPolicy.supportsNativeHandoff(
            handoff(.remoteStream, format: "CBZ", readerType: .comic)
        ))
        XCTAssertFalse(ManagedReaderAccessPolicy.supportsNativeHandoff(
            handoff(.remoteStream, format: "MP3", readerType: .audio)
        ))
        XCTAssertFalse(ManagedReaderAccessPolicy.supportsNativeHandoff(
            handoff(.remoteStream, format: "KINDLE", readerType: .reflowable)
        ))
        XCTAssertFalse(ManagedReaderAccessPolicy.supportsNativeHandoff(
            handoff(.verifiedLocal(recordID: "record"), format: "KINDLE", readerType: .reflowable)
        ))
    }

    private func waitUntil(
        timeout: TimeInterval = 1,
        _ condition: @MainActor () -> Bool
    ) async throws {
        let deadline = Date().addingTimeInterval(timeout)
        while Date() < deadline {
            if condition() { return }
            try await Task.sleep(nanoseconds: 10_000_000)
        }
        XCTFail("timed out waiting for download catalog to load")
    }

    private var namespace: String { "server|user|1" }

    private func exactDescriptor(
        for record: ManagedDownloadRecord,
        totalBytes: Int64? = nil
    ) throws -> DownloadDescriptor {
        let namespaceParts = record.namespace.split(separator: "|", omittingEmptySubsequences: false)
        XCTAssertEqual(namespaceParts.count, 3)
        let serverIdentity = try XCTUnwrap(namespaceParts.first.map(String.init))
        let userID = try XCTUnwrap(namespaceParts.dropFirst().first.map(String.init))
        let authorizationVersion = try XCTUnwrap(namespaceParts.last.flatMap { Int64($0) })
        let expectedTotalBytes: Int64
        if let totalBytes {
            expectedTotalBytes = totalBytes
        } else {
            expectedTotalBytes = try XCTUnwrap(record.expectedBytes)
        }
        let readerType: ErmaoShared.DownloadReaderType = switch record.readerType {
        case .reflowable: .reflowable
        case .comic: .comic
        case .pdf: .pdf
        case .audio: .audio
        }
        let artifactKind: ErmaoShared.DownloadArtifactKind = record.effectiveArtifactKind == .originalPageSet
            ? .originalpageset
            : .singleoriginalasset
        return DownloadDescriptor(
            identity: DownloadIdentity(
                namespace: PublicKt.createDownloadNamespace(
                    serverIdentity: serverIdentity,
                    userId: userID,
                    authorizationVersion: authorizationVersion
                ),
                bookId: record.bookID,
                resourceId: record.resourceID,
                assetId: record.assetID
            ),
            bookTitle: record.bookTitle,
            bookAuthor: record.bookAuthor,
            coverApiPath: nil,
            resourceTitle: record.resourceTitle,
            format: record.format,
            readerType: readerType,
            source: DownloadSource(
                apiPath: "/api/assets/\(record.assetID)",
                mimeType: record.mimeType ?? "application/epub+zip",
                totalBytes: expectedTotalBytes,
                sourceModifiedAtMillis: nil
            ),
            resourceIndex: nil,
            resourceSortOrder: nil,
            isDownloadable: true,
            artifactKind: artifactKind,
            members: []
        )
    }

    private func makeRecord(
        store: ManagedDownloadStore,
        namespace: String? = nil,
        resourceID: String = "resource",
        assetID: String = "asset"
    ) async throws -> ManagedDownloadRecord {
        try await store.seedDownload(
            namespace: namespace ?? self.namespace,
            book: BookCard(
                id: "book",
                title: "Book",
                author: "Author",
                cover: nil,
                progress: nil
            ),
            resource: BookResource(
                id: resourceID,
                bookID: "book",
                sourceNodeID: "source-node-ebook",
                title: "Resource",
                format: "EPUB",
                sizeLabel: "4 bytes",
                progress: nil,
                isReadable: true,
                isSelected: true
            ),
            assetID: assetID,
            readerType: .reflowable,
            expectedBytes: 4
        )
    }

    private func temporaryDirectory() -> URL {
        FileManager.default.temporaryDirectory
            .appendingPathComponent("ermao-download-tests-\(UUID().uuidString)", isDirectory: true)
    }

    private func complete(
        _ record: ManagedDownloadRecord,
        in store: ManagedDownloadStore
    ) async throws -> ManagedDownloadRecord {
        let destination = try await store.destination(for: record)
        try Data([1, 2, 3, 4]).write(to: destination.partialFileURL)
        return try await store.seedCompleted(
            record: record,
            destination: destination,
            receipt: CompletedFixtureBytes(
                receivedBytes: 4,
                expectedBytes: 4
            )
        )
    }
}

private extension Array {
    var single: Element? { count == 1 ? first : nil }
}

@MainActor
private final class SuspendedReaderDownloadTransfer: ManagedDownloadTransferring {
    private(set) var started = 0
    private(set) var cancelled = 0
    func download(context: ErmaoLibrary.ContentRequestContext, resourceID: String, repository: ManagedDownloadStore,
                  expectedDescriptor: DownloadDescriptor?, changed: @escaping @Sendable (ManagedDownloadRecord) async -> Void) async throws {
        started += 1
        do { try await Task.sleep(for: .seconds(60)) }
        catch is CancellationError { cancelled += 1; throw CancellationError() }
    }
}

// Storage fixtures create explicit persisted states; production transitions are tested through shared Downloads.
private struct CompletedFixtureBytes {
    let receivedBytes: Int64
    let expectedBytes: Int64?
}

private extension ManagedDownloadStore {
    func seedDownload(namespace: String, book: BookCard, resource: BookResource, assetID: String,
                      sourceFormat: String? = nil, mimeType: String? = nil,
                      readerType: ManagedDownloadReaderType, expectedBytes: Int64?,
                      artifactKind: ManagedDownloadArtifactKind = .singleOriginalAsset, now: Date = Date()) throws -> ManagedDownloadRecord {
        let record = ManagedDownloadRecord(id: UUID().uuidString, namespace: namespace,
            bookID: book.id, bookTitle: book.title, bookAuthor: book.author,
            resourceID: resource.id, resourceTitle: resource.title, assetID: assetID,
            format: sourceFormat ?? resource.format, mimeType: mimeType, readerType: readerType,
            state: .queued, verification: .pending, expectedBytes: expectedBytes, artifactKind: artifactKind,
            receivedBytes: 0, localRelativePath: nil, stableErrorCode: nil, createdAt: now, updatedAt: now,
            completedAt: nil, lastOpenedAt: nil)
        try update(record)
        return record
    }

    func seedCompleted(record: ManagedDownloadRecord, destination: ManagedDownloadDestination,
                       receipt: CompletedFixtureBytes, now: Date = Date()) throws -> ManagedDownloadRecord {
        let reference = try publishFile(record: record, destination: destination, verifiedBytes: receipt.receivedBytes)
        var fixture = record
        fixture.state = .completed
        fixture.verification = .verified
        fixture.localRelativePath = reference
        fixture.receivedBytes = receipt.receivedBytes
        fixture.completedAt = now
        try update(fixture)
        return fixture
    }
}

private final class DelayedComicFixtureContainer: Container, @unchecked Sendable {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>
    private let resources: [String: Data]
    private let delay: Duration

    init(resources: [String: Data], delay: Duration) throws {
        self.resources = resources
        self.delay = delay
        entries = try Set(resources.keys.map { href in
            guard let url = AnyURL(string: href) else {
                throw FixtureComicPageServerError.pageUnavailable
            }
            return url
        })
    }

    subscript(url: any URLConvertible) -> (any ReadiumShared.Resource)? {
        let href = url.anyURL.removingQuery().removingFragment().string
        guard let data = resources[href] else { return nil }
        return DataResource { [delay] in
            try? await Task.sleep(for: delay)
            return .success(data)
        }
    }

    func close() {}
}

private struct FixturePixel: Equatable, CustomStringConvertible {
    let red: CGFloat
    let green: CGFloat
    let blue: CGFloat
    let alpha: CGFloat

    var description: String {
        String(format: "rgba(%.3f, %.3f, %.3f, %.3f)", red, green, blue, alpha)
    }
}

private struct FixturePixelEvidence {
    let pageIndex: Int
    let imageSize: CGSize
    let pixel: FixturePixel
}

private enum FixturePixelEvidenceError: Error {
    case notRendered
}

private enum FixtureComicPageServerError: Error {
    case pageUnavailable
}

private final class FixtureResourceBox: @unchecked Sendable {
    let resource: any ReadiumShared.Resource

    init(_ resource: any ReadiumShared.Resource) {
        self.resource = resource
    }
}

private final class FixtureComicPageServer: ErmaoShared.ComicPageServerPort, @unchecked Sendable {
    private let pages: [Data]
    private let requestLog = FixturePageRequestLog()

    init(pages: [Data]) {
        self.pages = pages
    }

    var requestedPageIndexes: [Int32] {
        get async {
            await requestLog.values()
        }
    }

    func read(
        source: ErmaoShared.RemoteComicReaderSource,
        pageIndex: Int32,
        variant: ErmaoShared.ReaderComicImageVariant
    ) async throws -> any ErmaoShared.ComicPageReadResult {
        await requestLog.append(pageIndex)
        guard pages.indices.contains(Int(pageIndex)) else {
            throw FixtureComicPageServerError.pageUnavailable
        }
        let bytes = KotlinByteArray(size: Int32(pages[Int(pageIndex)].count))
        for (index, byte) in pages[Int(pageIndex)].enumerated() {
            bytes.set(index: Int32(index), value: Int8(bitPattern: byte))
        }
        return ErmaoShared.ComicPageReadResultContent(
            pageIndex: pageIndex,
            mediaType: "image/png",
            actualVariant: variant,
            bytes: bytes
        )
    }
}

private actor FixturePageRequestLog {
    private var indexes: [Int32] = []

    func append(_ pageIndex: Int32) {
        indexes.append(pageIndex)
    }

    func values() -> [Int32] {
        indexes
    }
}
