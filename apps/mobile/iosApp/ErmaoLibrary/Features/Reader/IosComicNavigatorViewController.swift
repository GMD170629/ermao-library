import Foundation
@preconcurrency import ErmaoShared
import ImageIO
import ReadiumShared
import UIKit

enum IosComicNavigatorError: Error {
    case emptyPublication
    case resourceMissing(String)
    case imageDecodeFailed(String)
}

enum IosComicNavigationRequest {
    case previous
    case next
    case escape
}

@MainActor
protocol IosComicNavigatorDelegate: AnyObject {
    func comicNavigator(_ navigator: IosComicNavigatorViewController, locationDidChange locator: Locator)
    func comicNavigator(_ navigator: IosComicNavigatorViewController, didTapAt point: CGPoint)
    func comicNavigator(_ navigator: IosComicNavigatorViewController, didRequest navigation: IosComicNavigationRequest)
    func comicNavigator(_ navigator: IosComicNavigatorViewController, didFail error: Error)
}

/// Native comic presentation which keeps Readium Publication/Resource as its sole
/// byte source while owning the UI-only spread, flow and gesture behavior.
@MainActor
final class IosComicNavigatorViewController: UIViewController {
    weak var delegate: IosComicNavigatorDelegate?

    let publication: Publication
    let pages: [IosCbzPage]

    private(set) var currentPageIndex: Int
    private(set) var currentLocation: Locator?
    var currentProgress: Double { plan.progress }
    var visiblePageLabel: String {
        let visiblePage = plan.logicalPageIndices.last.map { Int($0.intValue) } ?? Int(plan.currentPageIndex)
        return "\(visiblePage + 1) / \(max(1, pages.count))"
    }

    private var preferences: IosReaderPreferences
    private var viewport: ErmaoShared.ComicViewport
    private var runtime: ErmaoShared.ComicReaderRuntime
    private var plan: ErmaoShared.ComicPresentationPlan
    private var spreadAnchors: [Int] = []
    private var renderUnits: [[Int]] = []
    private var currentDisplayIndex = 0
    private var hasPresentedInitialLocation = false
    private var isApplyingPreferences = false
    private var loadTasks: [Int: Task<Void, Never>] = [:]
    private var loadGeneration = 0
    private var imageSizes: [Int: CGSize] = [:]
    private var imageCache: [Int: UIImage] = [:]
    private let reuseIdentifier = "IosComicImageCell"
    private var collectionView: UICollectionView?
    private var continuousScrollView: UIScrollView?
    private var continuousCanvasView: UIView?
    private var continuousPageViews: [Int: IosComicContinuousPageView] = [:]
    private var continuousPageFrames: [Int: CGRect] = [:]
    private var lastLaidOutViewSize = CGSize.zero
    private var singleTapGesture: UITapGestureRecognizer!

    init(
        publication: Publication,
        pages: [IosCbzPage],
        initialLocation: Locator?,
        preferences: IosReaderPreferences
    ) throws {
        guard !pages.isEmpty else { throw IosComicNavigatorError.emptyPublication }
        self.publication = publication
        self.pages = pages
        self.preferences = preferences
        if let href = initialLocation?.href.removingQuery().removingFragment().string,
           let index = pages.firstIndex(where: { $0.resourceHref == href }) {
            currentPageIndex = index
        } else {
            currentPageIndex = 0
        }
        let initialViewport = Self.initialViewport()
        let sharedPreferences = Self.sharedComicPreferences(preferences)
        self.viewport = initialViewport
        self.runtime = ErmaoShared.ComicReaderRuntime(
            input: ErmaoShared.ComicPresentationInput(
                pageCount: Int32(pages.count),
                preferences: sharedPreferences,
                currentPageIndex: Int32(currentPageIndex),
                viewport: initialViewport,
                resourceHrefs: pages.map(\.resourceHref),
                reducedMotion: UIAccessibility.isReduceMotionEnabled
            )
        )
        self.plan = runtime.plan
        super.init(nibName: nil, bundle: nil)
        rebuildRenderUnits()
        updateCurrentLocation()
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) {
        nil
    }

    deinit {
        loadTasks.values.forEach { $0.cancel() }
    }

    override var canBecomeFirstResponder: Bool { true }

    override var keyCommands: [UIKeyCommand]? {
        guard preferences.keyboardPageTurn else { return [] }
        return [
            UIKeyCommand(input: UIKeyCommand.inputLeftArrow, modifierFlags: [], action: #selector(handleKey(_:))),
            UIKeyCommand(input: UIKeyCommand.inputRightArrow, modifierFlags: [], action: #selector(handleKey(_:))),
            UIKeyCommand(input: UIKeyCommand.inputUpArrow, modifierFlags: [], action: #selector(handleKey(_:))),
            UIKeyCommand(input: UIKeyCommand.inputDownArrow, modifierFlags: [], action: #selector(handleKey(_:))),
            UIKeyCommand(input: " ", modifierFlags: [], action: #selector(handleKey(_:))),
            UIKeyCommand(input: UIKeyCommand.inputEscape, modifierFlags: [], action: #selector(handleKey(_:))),
        ]
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        configurePresentationSurface(resetZoom: true)
        configureGestures()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        becomeFirstResponder()
        presentInitialLocationIfNeeded()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        let nextViewport = Self.viewport(for: view.bounds.size)
        if nextViewport != viewport {
            let oldFlow = plan.flow
            viewport = nextViewport
            plan = runtime.update(
                preferences: Self.sharedComicPreferences(preferences),
                viewport: viewport,
                reducedMotion: UIAccessibility.isReduceMotionEnabled
            )
            rebuildRenderUnits()
            if oldFlow != plan.flow {
                configurePresentationSurface(resetZoom: true)
            } else if plan.flow == .continuousscroll {
                updateContinuousLayout()
            } else {
                collectionView?.reloadData()
            }
            preloadPages()
        }
        if lastLaidOutViewSize != view.bounds.size {
            lastLaidOutViewSize = view.bounds.size
            if plan.flow == .continuousscroll {
                updateContinuousLayout()
            } else {
                collectionView?.collectionViewLayout.invalidateLayout()
            }
        }
        presentInitialLocationIfNeeded()
    }

    func close() {
        cancelLoads()
        collectionView?.delegate = nil
        collectionView?.dataSource = nil
        continuousScrollView?.delegate = nil
        continuousPageViews.removeAll()
        delegate = nil
    }

    func applyPreferences(_ updated: IosReaderPreferences) async -> Bool {
        guard !isApplyingPreferences else { return false }
        guard updated.comicImageVariant == preferences.comicImageVariant else {
            return false
        }
        isApplyingPreferences = true
        defer { isApplyingPreferences = false }

        let previousPreferences = preferences
        let previousPlan = plan
        let previousFlow = plan.flow
        let baseZoomChanged = abs(updated.comicZoom - preferences.comicZoom) > 0.001
        preferences = updated
        plan = runtime.update(
            preferences: Self.sharedComicPreferences(updated),
            viewport: viewport,
            reducedMotion: UIAccessibility.isReduceMotionEnabled
        )
        rebuildRenderUnits()
        cancelLoads()
        trimImageCache()

        guard isViewLoaded else {
            updateCurrentLocation()
            return true
        }
        if previousFlow != plan.flow {
            configurePresentationSurface(resetZoom: true)
            scrollToDisplayIndex(currentDisplayIndex, animated: false)
        } else if plan.flow == .continuousscroll {
            if baseZoomChanged {
                resetContinuousZoomAndPosition()
            } else {
                updateContinuousLayout()
            }
        } else {
            collectionView?.semanticContentAttribute = .forceLeftToRight
            configureCollectionLayout()
            collectionView?.reloadData()
            collectionView?.layoutIfNeeded()
            scrollToDisplayIndex(currentDisplayIndex, animated: false)
        }
        guard await prepareCurrentPresentation() else {
            restorePreferences(previousPreferences, previousPlan: previousPlan)
            return false
        }
        preloadPages()
        if plan.flow == .continuousscroll { updateContinuousPageViews() }
        updateCurrentLocation()
        return true
    }

    private func restorePreferences(
        _ previousPreferences: IosReaderPreferences,
        previousPlan: ErmaoShared.ComicPresentationPlan
    ) {
        preferences = previousPreferences
        plan = runtime.update(
            preferences: Self.sharedComicPreferences(previousPreferences),
            viewport: viewport,
            reducedMotion: UIAccessibility.isReduceMotionEnabled
        )
        rebuildRenderUnits()
        if previousPlan.flow != plan.flow {
            configurePresentationSurface(resetZoom: true)
            scrollToDisplayIndex(currentDisplayIndex, animated: false)
        } else if plan.flow == .continuousscroll {
            updateContinuousLayout()
            updateContinuousPageViews()
        } else {
            collectionView?.semanticContentAttribute = .forceLeftToRight
            configureCollectionLayout()
            collectionView?.reloadData()
            collectionView?.layoutIfNeeded()
            scrollToDisplayIndex(currentDisplayIndex, animated: false)
        }
        updateCurrentLocation()
    }

    func prepareCurrentPresentation() async -> Bool {
        for pageIndex in plan.logicalPageIndices.map({ Int($0.intValue) }) {
            if imageCache[pageIndex] != nil { continue }
            do {
                let image = try await readPageImage(pageIndex)
                guard !Task.isCancelled else { return false }
                imageCache[pageIndex] = image
                imageSizes[pageIndex] = image.size
                if isViewLoaded { apply(image: image, toPage: pageIndex) }
            } catch {
                delegate?.comicNavigator(self, didFail: error)
                return false
            }
        }
        trimImageCache()
        return true
    }

    func goBackward(animated: Bool = true) async -> Bool {
        applyNavigationResult(
            runtime.dispatch(command: ErmaoShared.PublicKt.comicNavigationPrevious()),
            animated: animated
        )
    }

    func goForward(animated: Bool = true) async -> Bool {
        applyNavigationResult(
            runtime.dispatch(command: ErmaoShared.PublicKt.comicNavigationNext()),
            animated: animated
        )
    }

    func go(to locator: Locator, animated: Bool = true) async -> Bool {
        let href = locator.href.removingQuery().removingFragment().string
        guard let index = pages.firstIndex(where: { $0.resourceHref == href }) else { return false }
        return applyNavigationResult(
            runtime.dispatch(command: ErmaoShared.PublicKt.comicNavigationGoToIndex(pageIndex: Int32(index))),
            animated: animated
        )
    }

    private func configurePresentationSurface(resetZoom: Bool) {
        removePresentationSurface()
        if plan.flow == .continuousscroll {
            configureContinuousSurface(resetZoom: resetZoom)
        } else {
            configurePagedSurface()
        }
        lastLaidOutViewSize = .zero
    }

    private func removePresentationSurface() {
        collectionView?.dataSource = nil
        collectionView?.delegate = nil
        collectionView?.removeFromSuperview()
        collectionView = nil
        continuousScrollView?.delegate = nil
        continuousScrollView?.removeFromSuperview()
        continuousScrollView = nil
        continuousCanvasView?.removeFromSuperview()
        continuousCanvasView = nil
        continuousPageViews.removeAll()
        continuousPageFrames.removeAll()
    }

    private func configurePagedSurface() {
        let layout = IosComicPagingFlowLayout()
        layout.scrollDirection = .horizontal
        let collectionView = UICollectionView(frame: .zero, collectionViewLayout: layout)
        collectionView.translatesAutoresizingMaskIntoConstraints = false
        collectionView.backgroundColor = .clear
        collectionView.contentInsetAdjustmentBehavior = .never
        collectionView.showsVerticalScrollIndicator = false
        collectionView.showsHorizontalScrollIndicator = false
        collectionView.decelerationRate = .fast
        collectionView.semanticContentAttribute = .forceLeftToRight
        collectionView.register(IosComicImageCell.self, forCellWithReuseIdentifier: reuseIdentifier)
        collectionView.dataSource = self
        collectionView.delegate = self
        self.collectionView = collectionView
        view.addSubview(collectionView)
        NSLayoutConstraint.activate([
            collectionView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            collectionView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            collectionView.topAnchor.constraint(equalTo: view.topAnchor),
            collectionView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        configureCollectionLayout()
    }

    private func configureContinuousSurface(resetZoom: Bool) {
        let scrollView = UIScrollView()
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.backgroundColor = .clear
        scrollView.contentInsetAdjustmentBehavior = .never
        scrollView.showsVerticalScrollIndicator = false
        scrollView.showsHorizontalScrollIndicator = false
        scrollView.alwaysBounceVertical = true
        scrollView.alwaysBounceHorizontal = false
        scrollView.isDirectionalLockEnabled = true
        scrollView.decelerationRate = .normal
        scrollView.minimumZoomScale = 0.6
        scrollView.maximumZoomScale = 2.4
        scrollView.bouncesZoom = true
        scrollView.delegate = self
        let canvas = UIView()
        canvas.backgroundColor = .clear
        scrollView.addSubview(canvas)
        self.continuousScrollView = scrollView
        self.continuousCanvasView = canvas
        view.addSubview(scrollView)
        NSLayoutConstraint.activate([
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scrollView.topAnchor.constraint(equalTo: view.topAnchor),
            scrollView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
        ])
        if resetZoom {
            scrollView.zoomScale = Self.clampedZoom(plan.zoom)
        }
        updateContinuousLayout()
    }

    private func configureCollectionLayout() {
        guard let collectionView,
              let layout = collectionView.collectionViewLayout as? IosComicPagingFlowLayout else { return }
        layout.scrollDirection = .horizontal
        layout.minimumLineSpacing = 0
        layout.minimumInteritemSpacing = 0
        layout.sectionInset = .zero
        collectionView.isScrollEnabled = preferences.swipePageTurn
        collectionView.alwaysBounceVertical = false
        collectionView.alwaysBounceHorizontal = true
    }

    /// Rebuilds the continuous document canvas. This method never writes the
    /// scroll position; viewport movement belongs exclusively to UIScrollView
    /// gestures or an explicit navigation command.
    private func updateContinuousLayout() {
        guard plan.flow == .continuousscroll,
              let scrollView = continuousScrollView,
              let canvas = continuousCanvasView,
              scrollView.bounds.width > 0,
              scrollView.bounds.height > 0 else { return }

        let width = min(
            max(1, CGFloat(plan.effectivePageWidth)),
            max(1, scrollView.bounds.width)
        )
        var nextFrames: [Int: CGRect] = [:]
        var offsetY: CGFloat = 0
        for pageIndex in pages.indices {
            let height = continuousPageHeight(for: pageIndex, width: width)
            nextFrames[pageIndex] = CGRect(x: 0, y: offsetY, width: width, height: height)
            offsetY += height
        }
        continuousPageFrames = nextFrames
        canvas.frame = CGRect(x: 0, y: 0, width: width, height: max(1, offsetY))
        scrollView.contentSize = canvas.bounds.size
        updateContinuousContentInsets()
        updateContinuousPageViews()
    }

    private func resetContinuousZoomAndPosition() {
        guard let scrollView = continuousScrollView else { return }
        scrollView.setZoomScale(Self.clampedZoom(plan.zoom), animated: false)
        updateContinuousLayout()
        scrollToContinuousDisplayIndex(currentDisplayIndex, animated: false)
    }

    private func updateContinuousContentInsets() {
        guard let scrollView = continuousScrollView,
              let canvas = continuousCanvasView else { return }
        let scale = max(0.01, scrollView.zoomScale)
        let horizontal = max(0, (scrollView.bounds.width - canvas.bounds.width * scale) / 2)
        // A top-to-bottom document never vertically recenters itself when its
        // decoded content height changes. Pinching may change horizontal
        // centering, while the vertical viewport remains owned by UIScrollView.
        let nextInset = UIEdgeInsets(
            top: 0,
            left: horizontal,
            bottom: 0,
            right: horizontal
        )
        if scrollView.contentInset != nextInset {
            scrollView.contentInset = nextInset
        }
    }

    private func continuousPageHeight(for pageIndex: Int, width: CGFloat) -> CGFloat {
        let sourceSize = continuousLayoutSourceSize(for: pageIndex, width: width)
        let rendered = IosComicImageSizing.renderedSize(
            sourceSize: sourceSize,
            fit: plan.imageFit.wireValue,
            availableSize: CGSize(width: width, height: max(1, CGFloat(viewport.height)))
        )
        return max(1, rendered.height)
    }

    /// Unknown archive dimensions use a placeholder until the image decodes.
    /// Resolving that intrinsic size is ordinary document reflow; callers must
    /// not compensate for it by writing the scroll position.
    private func continuousLayoutSourceSize(for pageIndex: Int, width: CGFloat) -> CGSize {
        pages[pageIndex].sourceSize
            ?? imageSizes[pageIndex]
            ?? CGSize(width: width, height: width / 0.707)
    }

    private func continuousVisibleRect() -> CGRect {
        guard let scrollView = continuousScrollView else { return .zero }
        let scale = max(0.01, scrollView.zoomScale)
        let inset = scrollView.contentInset
        return CGRect(
            x: max(0, (scrollView.contentOffset.x + inset.left) / scale),
            y: max(0, (scrollView.contentOffset.y + inset.top) / scale),
            width: scrollView.bounds.width / scale,
            height: scrollView.bounds.height / scale
        )
    }

    private func continuousVisiblePageIndex(in rect: CGRect? = nil) -> Int? {
        guard !continuousPageFrames.isEmpty else { return nil }
        let visibleRect = rect ?? continuousVisibleRect()
        let best = continuousPageFrames.max { lhs, rhs in
            let lhsArea = lhs.value.intersection(visibleRect).area
            let rhsArea = rhs.value.intersection(visibleRect).area
            if lhsArea == rhsArea { return lhs.key > rhs.key }
            return lhsArea < rhsArea
        }
        return best?.key
    }

    private func updateContinuousPageViews() {
        guard let canvas = continuousCanvasView,
              !continuousPageFrames.isEmpty else { return }
        let visibleRect = continuousVisibleRect()
        let visibleIndexes = continuousPageFrames.compactMap { pageIndex, frame in
            frame.intersects(visibleRect) ? pageIndex : nil
        }
        let anchor = continuousVisiblePageIndex(in: visibleRect)
        var keep = Set(visibleIndexes)
        if let anchor {
            keep.insert(anchor - 1)
            keep.insert(anchor + 1)
        }
        keep = keep.filter { continuousPageFrames[$0] != nil }

        for pageIndex in Array(continuousPageViews.keys) where !keep.contains(pageIndex) {
            continuousPageViews.removeValue(forKey: pageIndex)?.removeFromSuperview()
        }
        for pageIndex in keep.sorted() {
            guard let frame = continuousPageFrames[pageIndex] else { continue }
            let pageView = continuousPageViews[pageIndex] ?? {
                let pageView = IosComicContinuousPageView()
                continuousPageViews[pageIndex] = pageView
                canvas.addSubview(pageView)
                return pageView
            }()
            pageView.frame = frame
            pageView.configure(
                image: imageCache[pageIndex],
                sourceSize: continuousLayoutSourceSize(for: pageIndex, width: frame.width),
                fit: plan.imageFit.wireValue,
                viewportHeight: max(1, CGFloat(viewport.height))
            )
            if imageCache[pageIndex] == nil { loadPage(pageIndex) }
        }
    }

    private func scrollToContinuousDisplayIndex(_ index: Int, animated: Bool) {
        guard let scrollView = continuousScrollView,
              let anchor = renderUnits.indices.contains(index) ? renderUnits[index].first : nil,
              let frame = continuousPageFrames[anchor] else { return }
        let y = frame.minY * scrollView.zoomScale - scrollView.contentInset.top
        scrollView.setContentOffset(
            CGPoint(x: scrollView.contentOffset.x, y: max(-scrollView.contentInset.top, y)),
            animated: animated
        )
    }

    private func configureGestures() {
        singleTapGesture = UITapGestureRecognizer(target: self, action: #selector(handleSingleTap(_:)))
        singleTapGesture.numberOfTapsRequired = 1
        singleTapGesture.cancelsTouchesInView = false
        view.addGestureRecognizer(singleTapGesture)
    }

    @objc private func handleSingleTap(_ gesture: UITapGestureRecognizer) {
        guard gesture.state == .ended else { return }
        delegate?.comicNavigator(self, didTapAt: gesture.location(in: view))
    }

    @objc private func handleKey(_ command: UIKeyCommand) {
        guard preferences.keyboardPageTurn else { return }
        if command.input == UIKeyCommand.inputEscape {
            delegate?.comicNavigator(self, didRequest: .escape)
            return
        }
        let isBackwardKey = command.input == UIKeyCommand.inputLeftArrow || command.input == UIKeyCommand.inputUpArrow
        let isForwardKey = command.input == UIKeyCommand.inputRightArrow || command.input == UIKeyCommand.inputDownArrow || command.input == " "
        guard isBackwardKey || isForwardKey else { return }
        let rtl = plan.direction == .righttoleft
        let shouldGoForward = isForwardKey != rtl
        delegate?.comicNavigator(self, didRequest: shouldGoForward ? .next : .previous)
    }

    private func rebuildRenderUnits() {
        let orderedPages = ErmaoShared.PublicKt.comicOrderedPages(pageCount: Int32(pages.count))
        let starts = ErmaoShared.PublicKt.comicSpreadStarts(
            orderedPages: orderedPages,
            mode: plan.spreadMode,
            pairing: plan.pairingPolicy
        )
        spreadAnchors = starts.map { Int($0.intValue) }
        renderUnits = spreadAnchors.map { anchor in
            let visualPages = ErmaoShared.PublicKt.comicVisualPages(
                orderedPages: orderedPages,
                page: Int32(anchor),
                mode: plan.spreadMode,
                direction: plan.direction,
                pairing: plan.pairingPolicy
            )
            return visualPages.compactMap { pageIndex in
                let index = Int(pageIndex.intValue)
                return pages.indices.contains(index) ? index : nil
            }
        }
        currentDisplayIndex = displayIndex(containing: Int(plan.anchorPageIndex))
        trimImageCache()
    }

    private func displayIndex(containing pageIndex: Int) -> Int {
        spreadAnchors.indices.first { index in
            renderUnits[index].contains(pageIndex)
        } ?? 0
    }

    private func displayPageIndices(at displayIndex: Int) -> [Int] {
        guard renderUnits.indices.contains(displayIndex) else { return [] }
        return renderUnits[displayIndex]
    }

    private func presentInitialLocationIfNeeded() {
        guard !hasPresentedInitialLocation, isViewLoaded, view.bounds.width > 0 else { return }
        hasPresentedInitialLocation = true
        scrollToDisplayIndex(currentDisplayIndex, animated: false)
        preloadPages()
    }

    @discardableResult
    private func applyNavigationResult(
        _ result: ErmaoShared.ComicNavigationResult,
        animated: Bool
    ) -> Bool {
        let oldUnits = renderUnits
        let oldDisplayIndex = currentDisplayIndex
        plan = result.plan
        currentPageIndex = Int(plan.currentPageIndex)
        rebuildRenderUnits()
        if isViewLoaded {
            if plan.flow == .continuousscroll {
                if currentDisplayIndex != oldDisplayIndex {
                    scrollToDisplayIndex(currentDisplayIndex, animated: animated && plan.animatePageTurn)
                }
            } else if let collectionView {
                if oldUnits != renderUnits { collectionView.reloadData() }
                collectionView.layoutIfNeeded()
                if currentDisplayIndex != oldDisplayIndex {
                    scrollToDisplayIndex(currentDisplayIndex, animated: animated && plan.animatePageTurn)
                }
            }
            preloadPages()
        }
        updateCurrentLocation()
        if result.moved, let currentLocation {
            delegate?.comicNavigator(self, locationDidChange: currentLocation)
        }
        return result.outcome == .moved || result.outcome == .noop
    }

    private func scrollToDisplayIndex(_ index: Int, animated: Bool) {
        guard isViewLoaded, renderUnits.indices.contains(index) else { return }
        if plan.flow == .continuousscroll {
            scrollToContinuousDisplayIndex(index, animated: animated)
            return
        }
        let path = IndexPath(item: index, section: 0)
        collectionView?.layoutIfNeeded()
        collectionView?.scrollToItem(at: path, at: .centeredHorizontally, animated: animated)
    }

    private func updateCurrentLocation() {
        currentPageIndex = Int(plan.currentPageIndex)
        guard pages.indices.contains(currentPageIndex),
              let mediaType = MediaType(pages[currentPageIndex].mediaType),
              let href = AnyURL(string: pages[currentPageIndex].resourceHref)
        else {
            currentLocation = nil
            return
        }
        currentLocation = Locator(
            href: href,
            mediaType: mediaType,
            title: pages[currentPageIndex].title ?? String(currentPageIndex + 1),
            locations: Locator.Locations(
                progression: 0,
                totalProgression: plan.progress,
                position: currentPageIndex + 1
            )
        )
    }

    private func loadPage(_ pageIndex: Int) {
        guard pages.indices.contains(pageIndex), loadTasks[pageIndex] == nil else { return }
        if let image = imageCache[pageIndex] {
            imageSizes[pageIndex] = image.size
            apply(image: image, toPage: pageIndex)
            return
        }
        let generation = loadGeneration
        loadTasks[pageIndex] = Task { [weak self] in
            do {
                guard let self else { return }
                let image = try await self.readPageImage(pageIndex)
                guard !Task.isCancelled, self.loadGeneration == generation else { return }
                self.imageCache[pageIndex] = image
                self.imageSizes[pageIndex] = image.size
                if self.loadGeneration == generation { self.loadTasks[pageIndex] = nil }
                self.trimImageCache()
                self.apply(image: image, toPage: pageIndex)
            } catch {
                guard let self, !Task.isCancelled, self.loadGeneration == generation else { return }
                self.loadTasks[pageIndex] = nil
                self.delegate?.comicNavigator(self, didFail: error)
            }
        }
    }

    private func readPageImage(_ pageIndex: Int) async throws -> UIImage {
        guard pages.indices.contains(pageIndex) else {
            throw IosComicNavigatorError.resourceMissing("pages/\(pageIndex)")
        }
        let page = pages[pageIndex]
        guard let href = AnyURL(string: page.resourceHref),
              let link = publication.linkWithHREF(href),
              let resource = publication.get(link)
        else { throw IosComicNavigatorError.resourceMissing(page.resourceHref) }
        let data = try await IosComicResourceBox(resource).resource.read().get()
        let logicalMaximum = max(plan.decodeMaxWidth, plan.decodeMaxHeight)
        let maximumPixelSize = min(8_192, max(1, Int(Double(logicalMaximum) * UIScreen.main.scale * 2.4)))
        guard let source = CGImageSourceCreateWithData(data as CFData, nil),
              let image = CGImageSourceCreateThumbnailAtIndex(source, 0, [
                kCGImageSourceCreateThumbnailFromImageAlways: true,
                kCGImageSourceCreateThumbnailWithTransform: true,
                kCGImageSourceThumbnailMaxPixelSize: maximumPixelSize,
              ] as CFDictionary)
        else { throw IosComicNavigatorError.imageDecodeFailed(page.resourceHref) }
        return UIImage(cgImage: image)
    }

    private func trimImageCache() {
        var allowed = Set(plan.cachePageIndices.map { Int($0.intValue) })
        if plan.flow == .continuousscroll {
            // During a fast fling the visible window can move ahead of the
            // last settled shared anchor. Keep only that mounted window in
            // addition to the shared cache plan so a just-decoded visible page
            // is not evicted before scrolling settles.
            allowed.formUnion(continuousPageViews.keys)
        }
        let staleTaskIndexes = loadTasks.keys.filter { !allowed.contains($0) }
        for pageIndex in staleTaskIndexes {
            loadTasks.removeValue(forKey: pageIndex)?.cancel()
        }
        imageCache = imageCache.filter { allowed.contains($0.key) }
        imageSizes = imageSizes.filter { allowed.contains($0.key) }
    }

    private func cancelLoads() {
        loadGeneration &+= 1
        loadTasks.values.forEach { $0.cancel() }
        loadTasks.removeAll()
    }

    private func preloadPages() {
        guard isViewLoaded else { return }
        if plan.flow == .continuousscroll { updateContinuousPageViews() }
        for pageIndex in plan.preloadPageIndices.map({ Int($0.intValue) }) {
            loadPage(pageIndex)
        }
    }

    private func apply(image: UIImage, toPage pageIndex: Int) {
        if plan.flow == .continuousscroll {
            // Intrinsic height may become known here. Let the document reflow
            // naturally, but never preserve an anchor or write contentOffset.
            updateContinuousLayout()
            return
        }
        for case let cell as IosComicImageCell in collectionView?.visibleCells ?? [] {
            guard let offset = cell.pageIndices.firstIndex(of: pageIndex) else { continue }
            cell.setImage(image, at: offset)
        }
        collectionView?.collectionViewLayout.invalidateLayout()
    }

    private func updateCurrentPageFromVisibleItems() {
        guard !isApplyingPreferences else { return }
        if plan.flow == .continuousscroll {
            guard let visiblePage = continuousVisiblePageIndex() else { return }
            let displayIndex = displayIndex(containing: visiblePage)
            guard spreadAnchors.indices.contains(displayIndex) else { return }
            currentDisplayIndex = displayIndex
            let targetPage = spreadAnchors[displayIndex]
            // A double-page spread can make the exact current page differ from
            // its anchor. Only dispatch when the user actually entered another
            // spread; this preserves exact page restoration and avoids a
            // duplicate location event inside the same spread.
            guard targetPage != Int(plan.anchorPageIndex) else { return }
            _ = applyNavigationResult(
                runtime.dispatch(command: ErmaoShared.PublicKt.comicNavigationGoToIndex(pageIndex: Int32(targetPage))),
                animated: false
            )
            return
        }
        guard let collectionView,
              let indexPath = closestVisibleIndexPath(in: collectionView)
        else { return }
        let displayIndex = indexPath.item
        guard spreadAnchors.indices.contains(displayIndex) else { return }
        let targetPage = spreadAnchors[displayIndex]
        currentDisplayIndex = displayIndex
        guard targetPage != Int(plan.anchorPageIndex) else { return }
        _ = applyNavigationResult(
            runtime.dispatch(command: ErmaoShared.PublicKt.comicNavigationGoToIndex(pageIndex: Int32(targetPage))),
            animated: false
        )
    }

    private func closestVisibleIndexPath(in collectionView: UICollectionView) -> IndexPath? {
        let visible = collectionView.indexPathsForVisibleItems
        guard !visible.isEmpty else { return nil }
        let viewportCenter = collectionView.contentOffset.x + collectionView.bounds.width / 2
        return visible.min { lhs, rhs in
            let l = collectionView.layoutAttributesForItem(at: lhs)?.center.x ?? .greatestFiniteMagnitude
            let r = collectionView.layoutAttributesForItem(at: rhs)?.center.x ?? .greatestFiniteMagnitude
            return abs(l - viewportCenter) < abs(r - viewportCenter)
        }
    }

    private static func initialViewport() -> ErmaoShared.ComicViewport {
        viewport(for: UIScreen.main.bounds.size)
    }

    private static func clampedZoom(_ value: Double) -> CGFloat {
        CGFloat(min(2.4, max(0.6, value)))
    }

    private static func viewport(for size: CGSize) -> ErmaoShared.ComicViewport {
        ErmaoShared.ComicViewport(
            width: Int32(max(1, Int(size.width.rounded()))),
            height: Int32(max(1, Int(size.height.rounded()))),
            wide: size.width > 640
        )
    }

    /// Converts the native persistence model at the platform boundary. The
    /// shared ReaderComicPreferences remains the only owner of comic rules.
    private static func sharedComicPreferences(
        _ preferences: IosReaderPreferences
    ) -> ErmaoShared.ReaderComicPreferences {
        let direction = ErmaoShared.ReaderComicDirection.entries.first {
            $0.wireValue == preferences.comicDirection.rawValue
        } ?? .lefttoright
        let spread = ErmaoShared.ReaderComicSpreadMode.entries.first {
            $0.wireValue == preferences.comicSpread.rawValue
        } ?? .single
        let flowWireValue = preferences.comicFlow == .scrolled ? "scrolled" : "paginated"
        let flow = ErmaoShared.ReaderReadingMode.entries.first {
            $0.wireValue == flowWireValue
        } ?? .paged
        let fit = ErmaoShared.ReaderComicImageFit.entries.first {
            $0.wireValue == preferences.comicImageFit
        } ?? .width
        let variant = ErmaoShared.ReaderComicImageVariant.entries.first {
            $0.wireValue == preferences.comicImageVariant
        } ?? .original
        let animation = ErmaoShared.ReaderPageTurnAnimation.entries.first {
            $0.wireValue == preferences.comicPageTurnAnimation
        } ?? .slide
        return ErmaoShared.ReaderComicPreferences(
            direction: direction,
            spreadMode: spread,
            pageTurnAnimation: animation,
            imageFit: fit,
            imageVariant: variant,
            zoom: preferences.comicZoom,
            pageWidth: Int32(preferences.comicPageWidth),
            flow: flow,
            coverSingle: preferences.comicCoverSingle,
            pageGap: Int32(preferences.comicPageGap)
        )
    }
}

extension IosComicNavigatorViewController: UICollectionViewDataSource {
    func collectionView(_ collectionView: UICollectionView, numberOfItemsInSection section: Int) -> Int {
        renderUnits.count
    }

    func collectionView(_ collectionView: UICollectionView, cellForItemAt indexPath: IndexPath) -> UICollectionViewCell {
        let cell = collectionView.dequeueReusableCell(withReuseIdentifier: reuseIdentifier, for: indexPath)
        guard let comicCell = cell as? IosComicImageCell else { return cell }
        let indices = displayPageIndices(at: indexPath.item)
        let images = indices.map { pageIndex in imageCache[pageIndex] }
        comicCell.configure(
            pageIndices: indices,
            images: images,
            imageSizes: indices.map { pageIndex in
                imageSizes[pageIndex] ?? pages[pageIndex].width.flatMap { width in
                    pages[pageIndex].height.map { height in CGSize(width: CGFloat(width), height: CGFloat(height)) }
                }
            },
            fit: plan.imageFit.wireValue,
            zoom: CGFloat(plan.zoom),
            gap: CGFloat(plan.pageGap),
            effectivePageWidth: CGFloat(plan.effectivePageWidth)
        )
        indices.enumerated().forEach { offset, pageIndex in
            if let image = images[offset] {
                comicCell.setImage(image, at: offset)
            } else {
                loadPage(pageIndex)
            }
        }
        return comicCell
    }
}

extension IosComicNavigatorViewController: UICollectionViewDelegateFlowLayout {
    func collectionView(
        _ collectionView: UICollectionView,
        layout collectionViewLayout: UICollectionViewLayout,
        sizeForItemAt indexPath: IndexPath
    ) -> CGSize {
        _ = indexPath
        return CGSize(width: max(1, collectionView.bounds.width), height: max(1, collectionView.bounds.height))
    }
}

extension IosComicNavigatorViewController: UIScrollViewDelegate {
    func viewForZooming(in scrollView: UIScrollView) -> UIView? {
        guard scrollView === continuousScrollView else { return nil }
        return continuousCanvasView
    }

    func scrollViewDidScroll(_ scrollView: UIScrollView) {
        guard scrollView === continuousScrollView else { return }
        updateContinuousPageViews()
    }

    func scrollViewDidZoom(_ scrollView: UIScrollView) {
        guard scrollView === continuousScrollView else { return }
        updateContinuousContentInsets()
        updateContinuousPageViews()
    }

    func scrollViewDidEndDecelerating(_ scrollView: UIScrollView) {
        updateCurrentPageFromVisibleItems()
    }

    func scrollViewDidEndScrollingAnimation(_ scrollView: UIScrollView) {
        updateCurrentPageFromVisibleItems()
    }

    func scrollViewDidEndDragging(_ scrollView: UIScrollView, willDecelerate decelerate: Bool) {
        if !decelerate { updateCurrentPageFromVisibleItems() }
    }

    func scrollViewWillEndDragging(
        _ scrollView: UIScrollView,
        withVelocity velocity: CGPoint,
        targetContentOffset: UnsafeMutablePointer<CGPoint>
    ) {
        guard scrollView === collectionView,
              plan.flow != .continuousscroll,
              preferences.swipePageTurn,
              abs(velocity.x) > 0.1 else { return }
        // A leftward drag activates the physical right-side turn affordance;
        // the shared policy maps that affordance for LTR/RTL. The collection
        // itself remains in canonical order and is held at its current offset
        // while the KMP adjacent anchor performs the actual navigation.
        let side: ErmaoShared.ReaderPhysicalHorizontalSide = velocity.x < 0 ? .right : .left
        let progression: ErmaoShared.ReaderReadingProgression = plan.direction == .righttoleft ? .righttoleft : .lefttoright
        let turn = ErmaoShared.ReaderNavigationPolicy.shared.physicalHorizontalPageTurn(
            side: side,
            readingProgression: progression
        )
        targetContentOffset.pointee = scrollView.contentOffset
        Task { @MainActor [weak self] in
            guard let self else { return }
            let command = turn == .next
                ? ErmaoShared.PublicKt.comicNavigationNext()
                : ErmaoShared.PublicKt.comicNavigationPrevious()
            _ = self.applyNavigationResult(
                self.runtime.dispatch(command: command),
                animated: self.plan.animatePageTurn
            )
        }
    }
}

/// Readium resources are safe to read concurrently, but the SDK's legacy
/// protocol is not annotated Sendable. This wrapper keeps that adapter detail
/// at the native byte-source boundary without copying or re-parsing content.
private final class IosComicResourceBox: @unchecked Sendable {
    let resource: any ReadiumShared.Resource

    init(_ resource: any ReadiumShared.Resource) {
        self.resource = resource
    }
}

private final class IosComicPagingFlowLayout: UICollectionViewFlowLayout {
    override func targetContentOffset(
        forProposedContentOffset proposedContentOffset: CGPoint,
        withScrollingVelocity velocity: CGPoint
    ) -> CGPoint {
        guard let collectionView else { return proposedContentOffset }
        // Continuous reading must preserve the user's exact scroll position.
        // Only horizontal pagination snaps to the nearest spread.
        guard scrollDirection == .horizontal else { return proposedContentOffset }
        let proposedCenter: CGPoint
        proposedCenter = CGPoint(
            x: proposedContentOffset.x + collectionView.bounds.width / 2,
            y: collectionView.bounds.midY
        )
        let attributes = layoutAttributesForElements(in: CGRect(
            x: proposedContentOffset.x - collectionView.bounds.width,
            y: proposedContentOffset.y - collectionView.bounds.height,
            width: collectionView.bounds.width * 3,
            height: collectionView.bounds.height * 3
        )) ?? []
        guard let closest = attributes.min(by: {
            let l = $0.center.x
            let r = $1.center.x
            let p = proposedCenter.x
            return abs(l - p) < abs(r - p)
        }) else { return proposedContentOffset }
        return CGPoint(x: closest.center.x - collectionView.bounds.width / 2, y: proposedContentOffset.y)
    }
}

private extension CGRect {
    var area: CGFloat { guard !isNull else { return 0 }; return max(0, width) * max(0, height) }
}

private extension IosCbzPage {
    var sourceSize: CGSize? {
        guard let width, let height, width > 0, height > 0 else { return nil }
        return CGSize(width: width, height: height)
    }
}

/// Native image fitting is a renderer concern; all reader policy values still
/// come from the shared ComicPresentationPlan. This helper is used by both
/// paged cells and the continuous lazy page views so their geometry agrees.
private enum IosComicImageSizing {
    static func renderedSize(
        sourceSize: CGSize,
        fit: String,
        availableSize: CGSize
    ) -> CGSize {
        let sourceWidth = max(1, sourceSize.width)
        let sourceHeight = max(1, sourceSize.height)
        let availableWidth = max(1, availableSize.width)
        let availableHeight = max(1, availableSize.height)
        let ratio = sourceWidth / sourceHeight
        switch fit {
        case "height":
            return CGSize(width: availableHeight * ratio, height: availableHeight)
        case "contain":
            let scale = min(availableWidth / sourceWidth, availableHeight / sourceHeight)
            return CGSize(width: max(1, sourceWidth * scale), height: max(1, sourceHeight * scale))
        case "original":
            // Original is shrink-only: a small source must never be silently
            // upscaled merely because the viewport is larger.
            let scale = min(1, availableWidth / sourceWidth, availableHeight / sourceHeight)
            return CGSize(width: max(1, sourceWidth * scale), height: max(1, sourceHeight * scale))
        default:
            return CGSize(width: availableWidth, height: availableWidth / ratio)
        }
    }
}

/// A single page view used only while it is in the continuous ±1 window.
/// The UIScrollView/canvas above it owns all scrolling and zooming.
private final class IosComicContinuousPageView: UIView {
    private let imageView = UIImageView()
    private var image: UIImage?
    private var sourceSize: CGSize?
    private var fit = "width"
    private var viewportHeight: CGFloat = 1

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        clipsToBounds = false
        imageView.backgroundColor = .clear
        imageView.contentMode = .scaleAspectFit
        imageView.clipsToBounds = false
        addSubview(imageView)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { nil }

    func configure(image: UIImage?, sourceSize: CGSize?, fit: String, viewportHeight: CGFloat) {
        self.image = image
        self.sourceSize = sourceSize
        self.fit = fit
        self.viewportHeight = max(1, viewportHeight)
        imageView.image = image
        setNeedsLayout()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        let source = sourceSize ?? image?.size ?? CGSize(width: bounds.width, height: bounds.height)
        let size = IosComicImageSizing.renderedSize(
            sourceSize: source,
            fit: fit,
            availableSize: CGSize(width: bounds.width, height: viewportHeight)
        )
        imageView.frame = CGRect(
            x: (bounds.width - size.width) / 2,
            y: (bounds.height - size.height) / 2,
            width: size.width,
            height: size.height
        )
    }
}

private final class IosComicImageCell: UICollectionViewCell, UIScrollViewDelegate {
    private let scrollView = UIScrollView()
    private let zoomContentView = UIView()
    private var imageViews: [UIImageView] = []
    private var images: [UIImage?] = []
    private var imageSizes: [CGSize?] = []
    private var fit = "width"
    private var configuredZoom: CGFloat = 1
    private var shouldApplyConfiguredZoom = true
    private var pageGap: CGFloat = 0
    private var effectivePageWidth: CGFloat = 600
    private(set) var pageIndices: [Int] = []

    override init(frame: CGRect) {
        super.init(frame: frame)
        backgroundColor = .clear
        contentView.backgroundColor = .clear
        scrollView.delegate = self
        scrollView.minimumZoomScale = 0.6
        scrollView.maximumZoomScale = 2.4
        scrollView.showsVerticalScrollIndicator = false
        scrollView.showsHorizontalScrollIndicator = false
        scrollView.backgroundColor = .clear
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        zoomContentView.backgroundColor = .clear
        scrollView.addSubview(zoomContentView)
        contentView.addSubview(scrollView)
        NSLayoutConstraint.activate([
            scrollView.leadingAnchor.constraint(equalTo: contentView.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: contentView.trailingAnchor),
            scrollView.topAnchor.constraint(equalTo: contentView.topAnchor),
            scrollView.bottomAnchor.constraint(equalTo: contentView.bottomAnchor),
        ])
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { nil }

    override func prepareForReuse() {
        super.prepareForReuse()
        pageIndices = []
        images = []
        imageSizes = []
        imageViews.forEach { $0.removeFromSuperview() }
        imageViews.removeAll()
        zoomContentView.frame = .zero
        scrollView.setZoomScale(1, animated: false)
        shouldApplyConfiguredZoom = true
    }

    func configure(
        pageIndices: [Int],
        images: [UIImage?],
        imageSizes: [CGSize?],
        fit: String,
        zoom: CGFloat,
        gap: CGFloat,
        effectivePageWidth: CGFloat
    ) {
        self.pageIndices = pageIndices
        self.images = images
        self.imageSizes = imageSizes
        self.fit = fit
        configuredZoom = min(2.4, max(0.6, zoom))
        shouldApplyConfiguredZoom = true
        pageGap = gap
        self.effectivePageWidth = effectivePageWidth
        imageViews.forEach { $0.removeFromSuperview() }
        imageViews = pageIndices.map { _ in
            let imageView = UIImageView()
            imageView.contentMode = .scaleAspectFit
            imageView.clipsToBounds = true
            imageView.backgroundColor = .clear
            zoomContentView.addSubview(imageView)
            return imageView
        }
        setNeedsLayout()
    }

    func setImage(_ image: UIImage, at offset: Int) {
        guard imageViews.indices.contains(offset), images.indices.contains(offset) else { return }
        images[offset] = image
        imageSizes[offset] = image.size
        imageViews[offset].image = image
        setNeedsLayout()
        layoutIfNeeded()
    }

    override func layoutSubviews() {
        super.layoutSubviews()
        let viewport = scrollView.bounds.size
        guard viewport.width > 0, viewport.height > 0, !imageViews.isEmpty else { return }
        let layoutWidth = min(viewport.width, max(1, effectivePageWidth))
        let slotWidth = max(1, (layoutWidth - pageGap * CGFloat(max(0, imageViews.count - 1))) / CGFloat(imageViews.count))
        var x: CGFloat = 0
        var maxHeight: CGFloat = 0
        var sizes: [CGSize] = []
        for offset in imageViews.indices {
            let imageSize = images[offset]?.size ?? imageSizes[offset] ?? CGSize(width: slotWidth, height: slotWidth / 0.707)
            let size = IosComicImageSizing.renderedSize(
                sourceSize: imageSize,
                fit: fit,
                availableSize: CGSize(width: slotWidth, height: viewport.height)
            )
            sizes.append(size)
            maxHeight = max(maxHeight, size.height)
        }
        let totalWidth = sizes.reduce(0) { $0 + $1.width } + pageGap * CGFloat(max(0, sizes.count - 1))
        let contentWidth = max(viewport.width, totalWidth)
        let contentHeight = max(viewport.height, maxHeight)
        zoomContentView.frame = CGRect(origin: .zero, size: CGSize(width: contentWidth, height: contentHeight))
        let pageOriginX = max(0, (viewport.width - layoutWidth) / 2)
        x = pageOriginX + max(0, (layoutWidth - totalWidth) / 2)
        for (offset, size) in sizes.enumerated() {
            let y = max(0, (contentHeight - size.height) / 2)
            imageViews[offset].frame = CGRect(x: x, y: y, width: size.width, height: size.height)
            x += size.width + pageGap
            imageViews[offset].image = images[offset]
        }
        scrollView.contentSize = zoomContentView.bounds.size
        if shouldApplyConfiguredZoom {
            scrollView.setZoomScale(configuredZoom, animated: false)
            shouldApplyConfiguredZoom = false
        }
        updatePanGestureAvailability()
        centerContent()
    }

    func viewForZooming(in scrollView: UIScrollView) -> UIView? { zoomContentView }

    func scrollViewDidZoom(_ scrollView: UIScrollView) {
        updatePanGestureAvailability()
        centerContent()
    }

    private func updatePanGestureAvailability() {
        scrollView.panGestureRecognizer.isEnabled = scrollView.zoomScale > 1.001
        scrollView.pinchGestureRecognizer?.isEnabled = true
    }

    private func centerContent() {
        let boundsSize = scrollView.bounds.size
        let contentSize = zoomContentView.bounds.size
        let scale = scrollView.zoomScale
        let horizontal = max(0, (boundsSize.width - contentSize.width * scale) / 2)
        let vertical = max(0, (boundsSize.height - contentSize.height * scale) / 2)
        scrollView.contentInset = UIEdgeInsets(top: vertical, left: horizontal, bottom: vertical, right: horizontal)
    }
}
