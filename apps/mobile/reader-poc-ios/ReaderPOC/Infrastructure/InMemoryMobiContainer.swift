import Foundation
import ReadiumShared

struct InMemoryMobiContainer: Container {
    let sourceURL: AbsoluteURL? = nil
    let entries: Set<AnyURL>

    private let resources: [String: Data]

    init(resources: [MobiResource]) throws {
        var contents: [String: Data] = [:]
        var urls: Set<AnyURL> = []
        for resource in resources {
            guard let path = PublicationPath.normalizedResourcePath(resource.href),
                  let url = AnyURL(string: path)
            else {
                throw MobiExtractionError.invalidResourcePath(resource.href)
            }
            guard contents.updateValue(resource.data, forKey: path) == nil else {
                throw MobiExtractionError.duplicateResourcePath(path)
            }
            urls.insert(url)
        }
        self.resources = contents
        entries = urls
    }

    subscript(url: any URLConvertible) -> Resource? {
        guard let path = PublicationPath.normalizedResourcePath(url.anyURL.removingQuery().removingFragment().string),
              let data = resources[path]
        else {
            return nil
        }
        return DataResource(data: data)
    }
}
