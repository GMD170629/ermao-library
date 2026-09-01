import UIKit

enum IosPdfiumKeyCommand: Equatable {
    case previous
    case next
    case escape
}

@MainActor
final class IosPdfiumNavigatorViewController: UIViewController, UIScrollViewDelegate {
    var onPageChanged: ((Int) -> Void)?
    var onFailure: ((IosReaderFailure) -> Void)?
    var onTapFraction: ((CGFloat) -> Void)?
    var onSwipe: ((IosPdfiumKeyCommand) -> Void)?
    var onKeyCommand: ((IosPdfiumKeyCommand) -> Void)?

    private(set) var pageIndex: Int
    private let document: IosPdfiumDocument
    private let scrollView = UIScrollView()
    private let imageView = UIImageView()
    private var readerBackgroundColor: UIColor = .systemBackground
    private var preferredZoom = 1.0
    private var renderedPageIndex: Int?
    private var renderingPageIndex: Int?
    private var renderGeneration = 0
    private var renderTask: Task<Bool, Never>?

    init(document: IosPdfiumDocument, initialPageIndex: Int) {
        self.document = document
        pageIndex = initialPageIndex
        super.init(nibName: nil, bundle: nil)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { fatalError("init(coder:) is unavailable") }

    override var canBecomeFirstResponder: Bool { true }

    override var keyCommands: [UIKeyCommand]? {
        [
            UIKeyCommand(input: UIKeyCommand.inputLeftArrow, modifierFlags: [], action: #selector(didPressKeyCommand(_:))),
            UIKeyCommand(input: UIKeyCommand.inputPageUp, modifierFlags: [], action: #selector(didPressKeyCommand(_:))),
            UIKeyCommand(input: UIKeyCommand.inputRightArrow, modifierFlags: [], action: #selector(didPressKeyCommand(_:))),
            UIKeyCommand(input: UIKeyCommand.inputPageDown, modifierFlags: [], action: #selector(didPressKeyCommand(_:))),
            UIKeyCommand(input: " ", modifierFlags: [], action: #selector(didPressKeyCommand(_:))),
            UIKeyCommand(input: UIKeyCommand.inputEscape, modifierFlags: [], action: #selector(didPressKeyCommand(_:))),
        ]
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = readerBackgroundColor
        scrollView.translatesAutoresizingMaskIntoConstraints = false
        scrollView.backgroundColor = readerBackgroundColor
        scrollView.delegate = self
        scrollView.minimumZoomScale = 0.6
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
        becomeFirstResponder()
        renderCurrentPage()
    }

    override func viewDidDisappear(_ animated: Bool) {
        resignFirstResponder()
        super.viewDidDisappear(animated)
    }

    override func viewDidLayoutSubviews() {
        super.viewDidLayoutSubviews()
        if imageView.image == nil { renderCurrentPage() }
    }

    func goPrevious() async -> Bool { await goToPage(pageIndex - 1) }
    func goNext() async -> Bool { await goToPage(pageIndex + 1) }

    @discardableResult
    func goToPage(_ index: Int) async -> Bool {
        guard index >= 0, index < document.pageCount else { return false }
        if index == pageIndex {
            return await ensureCurrentPageRendered()
        }
        let task = startRender(pageIndex: index, commitsNavigation: true)
        return await task.value
    }

    func ensureCurrentPageRendered() async -> Bool {
        if renderedPageIndex == pageIndex, imageView.image != nil { return true }
        let task = startRender(pageIndex: pageIndex, commitsNavigation: false)
        return await task.value
    }

    func zoomIn() {
        scrollView.setZoomScale(min(scrollView.maximumZoomScale, scrollView.zoomScale * 1.25), animated: true)
    }

    func zoomOut() {
        scrollView.setZoomScale(max(scrollView.minimumZoomScale, scrollView.zoomScale / 1.25), animated: true)
    }

    func setZoom(_ factor: Double) {
        preferredZoom = factor
        loadViewIfNeeded()
        scrollView.setZoomScale(CGFloat(factor), animated: false)
    }

    func zoomToFit() { scrollView.setZoomScale(1, animated: true) }

    func setReaderBackgroundColor(_ color: UIColor) {
        readerBackgroundColor = color
        guard isViewLoaded else { return }
        view.backgroundColor = color
        scrollView.backgroundColor = color
    }

    func close() {
        renderTask?.cancel()
        renderGeneration += 1
        renderingPageIndex = nil
        document.close()
    }

    func viewForZooming(in scrollView: UIScrollView) -> UIView? { imageView }

    private func renderCurrentPage() {
        guard renderedPageIndex != pageIndex || imageView.image == nil else { return }
        _ = startRender(pageIndex: pageIndex, commitsNavigation: false)
    }

    private func startRender(
        pageIndex requestedPage: Int,
        commitsNavigation: Bool
    ) -> Task<Bool, Never> {
        loadViewIfNeeded()
        view.layoutIfNeeded()
        if renderingPageIndex == requestedPage, let renderTask { return renderTask }
        renderTask?.cancel()
        renderGeneration += 1
        let generation = renderGeneration
        renderingPageIndex = requestedPage
        let task = Task { [weak self] in
            guard let self else { return false }
            defer {
                if renderGeneration == generation {
                    renderingPageIndex = nil
                    renderTask = nil
                }
            }
            guard view.bounds.width > 0, view.bounds.height > 0 else { return false }
            do {
                let image = try await document.render(
                    pageIndex: requestedPage,
                    viewport: view.bounds.size,
                    scale: UIScreen.main.scale
                )
                guard !Task.isCancelled else { return false }
                imageView.image = image
                renderedPageIndex = requestedPage
                imageView.accessibilityLabel = String(
                    format: String(localized: "reader.pdf.page.description"),
                    requestedPage + 1,
                    document.pageCount
                )
                if commitsNavigation {
                    pageIndex = requestedPage
                    scrollView.setZoomScale(CGFloat(preferredZoom), animated: false)
                    onPageChanged?(requestedPage)
                }
                return true
            } catch is CancellationError {
                return false
            } catch let failure as IosReaderFailure {
                guard !Task.isCancelled,
                      renderGeneration == generation,
                      renderingPageIndex == requestedPage,
                      commitsNavigation || requestedPage == pageIndex else {
                    return false
                }
                onFailure?(failure)
                return false
            } catch {
                guard !Task.isCancelled,
                      renderGeneration == generation,
                      renderingPageIndex == requestedPage,
                      commitsNavigation || requestedPage == pageIndex else {
                    return false
                }
                onFailure?(IosReaderFailure(code: .pdfRenderFailed, underlyingError: error as NSError))
                return false
            }
        }
        renderTask = task
        return task
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
        onSwipe?(gesture.direction == .left ? .next : .previous)
    }

    @objc private func didTap(_ gesture: UITapGestureRecognizer) {
        let x = gesture.location(in: view).x / max(1, view.bounds.width)
        onTapFraction?(x)
    }

    @objc private func didPressKeyCommand(_ command: UIKeyCommand) {
        switch command.input {
        case UIKeyCommand.inputLeftArrow, UIKeyCommand.inputPageUp:
            onKeyCommand?(.previous)
        case UIKeyCommand.inputRightArrow, UIKeyCommand.inputPageDown, " ":
            onKeyCommand?(.next)
        case UIKeyCommand.inputEscape:
            onKeyCommand?(.escape)
        default:
            break
        }
    }
}
