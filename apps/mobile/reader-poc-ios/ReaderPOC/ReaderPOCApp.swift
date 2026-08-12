import SwiftUI

@main
struct ReaderPOCApp: App {
    var body: some Scene {
        WindowGroup {
            ReaderPOCRootView()
                .background(POCTheme.canvas.ignoresSafeArea())
        }
    }
}
