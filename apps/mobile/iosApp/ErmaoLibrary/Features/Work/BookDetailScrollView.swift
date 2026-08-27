import SwiftUI
import UIKit

/// UIKit owns scrolling and gestures; the content destination owns its restoration offset.
struct BookDetailScrollView<Content: View>: UIViewControllerRepresentable {
    @Binding var offset: Double
    @Binding var anchorID: String
    @Binding var anchorOffset: Double
    let anchors: [String: CGRect]
    let ready: Bool
    let content: Content

    init(offset: Binding<Double>, anchorID: Binding<String>, anchorOffset: Binding<Double>, anchors: [String: CGRect], ready: Bool, @ViewBuilder content: () -> Content) {
        _offset = offset
        _anchorID = anchorID
        _anchorOffset = anchorOffset
        self.anchors = anchors
        self.ready = ready
        self.content = content()
    }

    func makeUIViewController(context: Context) -> Controller {
        Controller(content: content)
    }

    func updateUIViewController(_ controller: Controller, context: Context) {
        controller.host.rootView = content
        controller.ready = ready
        controller.savedOffset = max(0, offset.isFinite ? offset : 0)
        controller.anchors = anchors
        controller.savedAnchorID = anchorID
        controller.savedAnchorOffset = anchorOffset.isFinite ? anchorOffset : 0
        controller.onOffset = { value in
            offset = value
            if let anchor = anchors.filter({ $0.value.minY <= value + 1 }).max(by: { $0.value.minY < $1.value.minY }) {
                anchorID = anchor.key
                anchorOffset = value - anchor.value.minY
            }
        }
        controller.view.setNeedsLayout()
    }

    final class Controller: UIViewController, UIScrollViewDelegate {
        let host: UIHostingController<Content>
        private let scroll = UIScrollView()
        var ready = false
        var savedOffset = 0.0
        var anchors: [String: CGRect] = [:]
        var savedAnchorID = ""
        var savedAnchorOffset = 0.0
        var onOffset: (Double) -> Void = { _ in }
        private var restoring = true

        init(content: Content) {
            host = UIHostingController(rootView: content)
            super.init(nibName: nil, bundle: nil)
        }

        @available(*, unavailable)
        required init?(coder: NSCoder) { fatalError("Storyboard construction is unavailable") }

        override func viewDidLoad() {
            super.viewDidLoad()
            view.backgroundColor = .clear
            scroll.translatesAutoresizingMaskIntoConstraints = false
            scroll.alwaysBounceVertical = true
            scroll.accessibilityIdentifier = "work.detail.screen"
            scroll.delegate = self
            view.addSubview(scroll)
            addChild(host)
            host.sizingOptions = .intrinsicContentSize
            host.safeAreaRegions = []
            host.view.backgroundColor = .clear
            host.view.translatesAutoresizingMaskIntoConstraints = false
            scroll.addSubview(host.view)
            host.didMove(toParent: self)
            NSLayoutConstraint.activate([
                scroll.leadingAnchor.constraint(equalTo: view.leadingAnchor),
                scroll.trailingAnchor.constraint(equalTo: view.trailingAnchor),
                scroll.topAnchor.constraint(equalTo: view.topAnchor),
                scroll.bottomAnchor.constraint(equalTo: view.bottomAnchor),
                host.view.leadingAnchor.constraint(equalTo: scroll.contentLayoutGuide.leadingAnchor),
                host.view.trailingAnchor.constraint(equalTo: scroll.contentLayoutGuide.trailingAnchor),
                host.view.topAnchor.constraint(equalTo: scroll.contentLayoutGuide.topAnchor),
                host.view.bottomAnchor.constraint(equalTo: scroll.contentLayoutGuide.bottomAnchor),
                host.view.widthAnchor.constraint(equalTo: scroll.frameLayoutGuide.widthAnchor),
            ])
        }

        override func viewWillAppear(_ animated: Bool) {
            super.viewWillAppear(animated)
            restoring = true
        }

        override func viewDidLayoutSubviews() {
            super.viewDidLayoutSubviews()
            guard ready, restoring, scroll.bounds.height > 0 else { return }
            if !savedAnchorID.isEmpty && anchors.isEmpty { return }
            let restoredOffset = anchors[savedAnchorID].map { $0.minY + savedAnchorOffset } ?? savedOffset
            let maximum = max(0, scroll.contentSize.height + scroll.adjustedContentInset.bottom - scroll.bounds.height)
            scroll.setContentOffset(CGPoint(x: 0, y: min(CGFloat(restoredOffset) - scroll.adjustedContentInset.top, maximum)), animated: false)
            restoring = false
        }

        func scrollViewDidScroll(_ scrollView: UIScrollView) {
            guard ready, !restoring, scrollView.isDragging || scrollView.isDecelerating else { return }
            onOffset(max(0, Double(scrollView.contentOffset.y + scrollView.adjustedContentInset.top)))
        }
    }
}

struct BookContentAnchorFrames: PreferenceKey {
    static let defaultValue: [String: CGRect] = [:]

    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue(), uniquingKeysWith: { _, incoming in incoming })
    }
}

extension View {
    func bookContentAnchor(_ id: String) -> some View {
        background {
            GeometryReader { geometry in
                Color.clear.preference(
                    key: BookContentAnchorFrames.self,
                    value: [id: geometry.frame(in: .named("book-content-scroll"))]
                )
            }
        }
    }
}
