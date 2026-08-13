import Combine
import Foundation
@preconcurrency import ErmaoShared

@MainActor
final class ReaderProgressPresentationCenter {
    static let shared = ReaderProgressPresentationCenter()

    private let subject = PassthroughSubject<ErmaoShared.ReaderProgressPresentationUpdate, Never>()

    var updates: AnyPublisher<ErmaoShared.ReaderProgressPresentationUpdate, Never> {
        subject.eraseToAnyPublisher()
    }

    func publish(_ update: ErmaoShared.ReaderProgressPresentationUpdate) {
        subject.send(update)
    }

    func publish(
        namespaceKey: String,
        workID: String,
        volumeID: String,
        percent: Double,
        currentHref: String,
        chapterTitle: String?,
        capturedAtEpochMillis: Int64
    ) {
        publish(ErmaoShared.ReaderProgressPresentationUpdate(
            namespaceKey: namespaceKey,
            workId: workID,
            volumeId: volumeID,
            percent: percent,
            currentHref: currentHref,
            chapterTitle: chapterTitle,
            capturedAtEpochMillis: capturedAtEpochMillis
        ))
    }
}
