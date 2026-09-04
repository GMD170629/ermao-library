import Foundation
@preconcurrency import ErmaoShared
import ReadiumShared

struct ReadiumSwiftLocatorMapper {
    func opaqueLocator(from locator: Locator) throws -> ErmaoShared.ReaderOpaqueLocator {
        try ErmaoShared.ReaderOpaqueLocator.companion.parse(json: locator.jsonString())
    }

    func locator(from opaque: ErmaoShared.ReaderOpaqueLocator) throws -> Locator? {
        try Locator(jsonString: opaque.canonicalJson)
    }
}
