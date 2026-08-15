import UIKit

@MainActor
final class IosPdfiumNavigatorViewController: UIViewController, UIScrollViewDelegate {
    var onPageChanged: ((Int) -> Void)?
    var onFailure: ((IosReaderFailureCode) -> Void)?
    var onCenterTap: (() -> Void)?

    private(set) var pageIndex: Int
    private let document: IosPdfiumDocument
    private let scrollView = UIScrollView()
    private let imageView = UIImageView()
    private var renderTask: Task<Void, Never>?
    private var prefetchTask: Task<Void, Never>?

    init(document: IosPdfiumDocument, initialPageIndex: Int) {
        self.document = document
        pageIndex = initialPageIndex
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .black
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.backgroundColor = .black
        scrollView.delegate = self
        scrollView.minimumZoomScale = 1
        scrollView.maximumZoomScale = 5
        scrollView.bouncesZoom = true
        imageView.translatesAutoresizingMaskIntoConstraints = false
        imageView.contentMode = .scaleAspectFit
        imageView.isAccessibilityElement = true
        scrollView.addSubview(imageView)
        view.addSubview(scrollView)
        NSLayoutConstraint.activate([
            scrollView.leadingAnchor.constraint(equalTo: view.leadingAnchor),
            scrollView.trailingAnchor.constraint(equalTo: view.trailingAnchor),
            scrollView.topAnchor.constraint(equalTo: view.topAnchor),
            scrollView.bottomAnchor.constraint(equalTo: view.bottomAnchor),
            imageView.leadingAnchor.constraint(equalTo: scrollView.frameLayoutGuide.leadingAnchor),
            imageView.trailingAnchor.constraint(equalTo: scrollView.frameLayoutGuide.trailingAnchor),
            imageView.topAnchor.constraint(equalTo: scrollView.frameLayoutGuide.topAnchor),
            imageView.bottomAnchor.constraint(equalTo: scrollView.frameLayoutGuide.bottomAnchor),
        ])
        installGestures()
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        renderCurrentPage()
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        if imageView.image == nil { renderCurrentPage() }
    }

    func goPrevious() -> Bool { goToPage(pageIndex - 1) }
    func goNext() -> Bool { goToPage(pageIndex + 1) }

    @discardableResult
    func goToPage(_ index: Int) -> Bool {
        guard index >= 0, index < document.pageCount, index != pageIndex else {
            return index == pageIndex
        }
        pageIndex = index
        scrollView.setZoomScale(1, animated: false)
        renderCurrentPage()
        onPageChanged?(index)
        return true
    }

    func zoomIn() {
        scrollView.setZoomScale(min(scrollView.maximumZoomScale, scrollView.zoomScale * 1.25), animated: true)
    }

    func zoomOut() {
        scrollView.setZoomScale(max(scrollView.minimumZoomScale, scrollView.zoomScale / 1.25), animated: true)
    }

    func zoomToFit() { scrollView.setZoomScale(1, animated: true) }

    func close() {
        renderTask?.cancel()
        prefetchTask?.cancel()
        document.close()
    }

    func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }

    private func renderCurrentPage() {
        guard view.bounds.width > 0, view.bounds.height > 0 else { return }
        let requestedPage = pageIndex
        renderTask?.cancel()
        prefetchTask?.cancel()
        renderTask = Task { [weak self] in
            guard let self else { return }
            do {
                let image = try await document.render(
                    pageIndex: requestedPage,
                    viewport: view.bounds.size,
                    scale: UIScreen.main.scale
                )
                guard !Task.isCancelled, requestedPage == pageIndex else { return }
                imageView.image = image
                imageView.accessibilityLabel = String(
                    format: String(localized: "reader.pdf.page.description"),
                    requestedPage + 1,
                    document.pageCount
                )
                prefetchAdjacentPage(from: requestedPage)
            } catch is CancellationError {
                return
            } catch let failure as IosReaderFailure {
                onFailure?(failure.code)
            } catch {
                onFailure?(.pdfRenderFailed)
            }
        }
    }

    private func prefetchAdjacentPage(from index: Int) {
        let neighbor = index + 1 < document.pageCount ? index + 1 : index - 1
        guard neighbor >= 0 else { return }
        prefetchTask = Task { [document] in await document.prefetch(pageIndex: neighbor) }
    }

    private func installGestures() {
        let left = UISwipeGestureRecognizer(target: self, action: #selector(didSwipe(_:)))
        left.direction = .left
        let right = UISwipeGestureRecognizer(target: self, action: #selector(didSwipe(_:)))
        right.direction = .right
        let tap = UITapGestureRecognizer(target: self, action: #selector(didTap(_:)))
        view.addGestureRecognizer(left)
        view.addGestureRecognizer(right)
        view.addGestureRecognizer(tap)
    }

    @objc private func didSwipe(_ gesture: UISwipeGestureRecognizer) {
        guard scrollView.zoomScale <= 1.01 else { return }
        _ = gesture.direction == .left ? goNext() : goPrevious()
    }

    @objc private func didTap(_ gesture: UITapGestureRecognizer) {
        let x = gesture.location(in: view).x / max(1, view.bounds.width)
        switch x {
        case ..<0.3: _ = goPrevious()
        case 0.7...: _ = goNext()
        default: onCenterTap?()
        }
    }
}
