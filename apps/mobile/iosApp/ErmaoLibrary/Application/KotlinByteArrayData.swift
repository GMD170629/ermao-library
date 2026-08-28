import Foundation
@preconcurrency import ErmaoShared

extension KotlinByteArray {
    nonisolated func foundationData() -> Data {
        Data((0 ..< Int(size)).map { UInt8(bitPattern: get(index: Int32($0))) })
    }
}
