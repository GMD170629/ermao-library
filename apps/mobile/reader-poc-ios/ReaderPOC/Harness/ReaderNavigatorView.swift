import ReadiumNavigator
import ReadiumShared
import SwiftUI
import UIKit

struct ReaderNavigatorView: UIViewControllerRepresentable {
    let publication: Publication
    let fingerprint: LocatorPublicationFingerprint
    @ObservedObject var session: NavigatorSession

    func makeCoordinator() -> Coordinator {
        Coordinator(session: session)
    }

    func makeUIViewController(context: Context) -> UIViewController {
        do {
            let preferences = EPUBPreferences(publisherStyles: true, scroll: false)
            let navigator = try EPUBNavigatorViewController(
                publication: publication,
                initialLocation: nil,
                config: EPUBNavigatorViewController.Configuration(
                    preferences: preferences,
                    debugState: true
                )
            )
            navigator.delegate = context.coordinator
            session.attach(navigator, fingerprint: fingerprint)
            return navigator
        } catch {
            let controller = UIViewController()
            let label = UILabel()
            label.text = error.localizedDescription
            label.numberOfLines = 0
            label.textAlignment = .center
            label.translatesAutoresizingMaskIntoConstraints = false
            controller.view.addSubview(label)
            NSLayoutConstraint.activate([
                label.leadingAnchor.constraint(equalTo: controller.view.safeAreaLayoutGuide.leadingAnchor, constant: 24),
                label.trailingAnchor.constraint(equalTo: controller.view.safeAreaLayoutGuide.trailingAnchor, constant: -24),
                label.centerYAnchor.constraint(equalTo: controller.view.centerYAnchor),
            ])
            return controller
        }
    }

    func updateUIViewController(_ uiViewController: UIViewController, context: Context) {}

    @MainActor
    final class Coordinator: NSObject, EPUBNavigatorDelegate {
        private let session: NavigatorSession

        init(session: NavigatorSession) {
            self.session = session
        }

        func navigator(_ navigator: any ViewportObservingNavigator, viewportDidChange viewport: NavigatorViewport?) {
            if viewport != nil {
                session.markReady()
            }
        }

        func navigator(_ navigator: Navigator, didFailToLoadResourceAt href: RelativeURL, withError error: ReadError) {
            session.recordResourceFailure(href: href.string, error: error)
        }

        func navigator(_ navigator: Navigator, presentError error: NavigatorError) {
            session.recordNavigatorWarning(error.localizedDescription)
        }
    }
}
