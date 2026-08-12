import Foundation
import ReadiumShared
import ReadiumStreamer

final class MobiPublicationParser: PublicationParser {
    private let factory: MobiPublicationFactory

    init(extractor: any MobiExtracting = NativeMobiExtractor()) {
        factory = MobiPublicationFactory(extractor: extractor)
    }

    func parse(asset: Asset, warnings: WarningLogger?) async -> Result<Publication.Builder, PublicationParseError> {
        guard asset.format.conformsTo(.mobi),
              case let .resource(resourceAsset) = asset,
              let fileURL = resourceAsset.resource.sourceURL?.fileURL
        else {
            return .failure(.formatNotSupported)
        }

        do {
            let result = try await factory.open(fileURL.url)
            return .success(Publication.Builder(
                manifest: result.publication.manifest,
                container: try InMemoryMobiContainer(resources: result.book.allResources),
                servicesBuilder: PublicationServicesBuilder(
                    content: DefaultContentService.makeFactory(
                        resourceContentIteratorFactories: [HTMLResourceContentIterator.Factory()]
                    ),
                    positions: EPUBPositionsService.makeFactory(
                        reflowableStrategy: .archiveEntryLength(pageLength: 1024)
                    ),
                    search: ContentSearchService.makeFactory()
                )
            ))
        } catch {
            return .failure(.reading(.wrap(error) ?? .decoding(error)))
        }
    }
}
