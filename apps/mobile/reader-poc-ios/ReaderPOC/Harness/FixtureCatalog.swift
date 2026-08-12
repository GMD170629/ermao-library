import Foundation

struct FixtureDescriptor: Identifiable, Hashable, Sendable {
    let id: String
    let filename: String
    let featureKey: String
    let isLongChapter: Bool

    var fileExtension: String {
        URL(fileURLWithPath: filename).pathExtension
    }

    var baseName: String {
        URL(fileURLWithPath: filename).deletingPathExtension().lastPathComponent
    }

    func bundledURL(in bundle: Bundle = .main) -> URL? {
        bundle.url(forResource: baseName, withExtension: fileExtension, subdirectory: "Fixtures")
            ?? bundle.url(forResource: baseName, withExtension: fileExtension)
    }
}

enum FixtureCatalog {
    static let all: [FixtureDescriptor] = [
        FixtureDescriptor(id: "basic-mobi6", filename: "01-basic-mobi6.mobi", featureKey: "fixture.basicMobi6", isLongChapter: false),
        FixtureDescriptor(id: "basic-kf8", filename: "test.azw3", featureKey: "fixture.basicKF8", isLongChapter: false),
        FixtureDescriptor(id: "css", filename: "03-css.azw3", featureKey: "fixture.css", isLongChapter: false),
        FixtureDescriptor(id: "font", filename: "04-font.azw3", featureKey: "fixture.font", isLongChapter: false),
        FixtureDescriptor(id: "images", filename: "05-images.azw3", featureKey: "fixture.images", isLongChapter: false),
        FixtureDescriptor(id: "footnotes", filename: "06-footnotes.azw3", featureKey: "fixture.footnotes", isLongChapter: false),
        FixtureDescriptor(id: "complex-toc", filename: "07-complex-toc.azw3", featureKey: "fixture.complexTOC", isLongChapter: false),
        FixtureDescriptor(id: "zh-hans", filename: "08-zh-hans.azw3", featureKey: "fixture.zhHans", isLongChapter: false),
        FixtureDescriptor(id: "ja-vertical", filename: "09-ja-vertical.azw3", featureKey: "fixture.jaVertical", isLongChapter: false),
        FixtureDescriptor(id: "long-chapter", filename: "10-long-chapter.azw3", featureKey: "fixture.longChapter", isLongChapter: true),
    ]
}
