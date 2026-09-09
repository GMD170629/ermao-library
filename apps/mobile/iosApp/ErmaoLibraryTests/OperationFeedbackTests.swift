import XCTest
@preconcurrency import ErmaoShared
@testable import ErmaoLibrary

@MainActor
final class OperationFeedbackTests: XCTestCase {
    func testSuccessUsesSharedTimeoutAndStartsDwellAfterVisibility() async throws {
        let clock = TestFeedbackClock()
        let presenter = makePresenter(clock: clock)

        let expired = expectation(description: "Visible success expires")
        let eventID = try XCTUnwrap(presenter.present(message: "Saved", kind: .success, onDismiss: { expired.fulfill() }))
        presenter.markVisible(id: eventID, entranceDurationMillis: 180)

        try await clock.waitUntilScheduled(count: 1)
        let entranceSchedule = await clock.scheduledNanoseconds()
        XCTAssertEqual(entranceSchedule, [180_000_000])
        XCTAssertEqual(presenter.lastScheduledTimeoutMillis, 1_000)
        XCTAssertEqual(presenter.current?.id, eventID)

        await clock.releaseNext()
        try await clock.waitUntilScheduled(count: 2)
        let dwellSchedule = await clock.scheduledNanoseconds()
        XCTAssertEqual(dwellSchedule, [180_000_000, 1_000_000_000])
        XCTAssertEqual(presenter.current?.id, eventID)

        await clock.releaseNext()
        await fulfillment(of: [expired], timeout: 1)
        XCTAssertNil(presenter.current)
    }

    func testStaleDismissCannotClearTheReplacement() throws {
        let presenter = OperationFeedbackPresenter(
            sleep: { _ in try await Task.sleep(for: .seconds(3600)) },
            voiceOverRunning: { false }
        )

        let firstID = try XCTUnwrap(presenter.present(message: "First", kind: .success))
        presenter.markVisible(id: firstID, entranceDurationMillis: 0)
        let secondID = try XCTUnwrap(presenter.present(message: "Second", kind: .success))
        presenter.markVisible(id: secondID, entranceDurationMillis: 0)

        presenter.dismiss(id: firstID)

        XCTAssertEqual(presenter.current?.id, secondID)
    }

    func testSuccessCannotReplaceAnUnresolvedFailure() throws {
        let presenter = OperationFeedbackPresenter(
            sleep: { _ in try await Task.sleep(for: .seconds(3600)) },
            voiceOverRunning: { false }
        )

        let failureID = try XCTUnwrap(presenter.present(message: "Failed", kind: .failure))
        XCTAssertNil(presenter.present(message: "Saved", kind: .success))
        XCTAssertEqual(presenter.current?.id, failureID)
    }

    func testRepeatedSameMessageGetsAFreshEventID() throws {
        let presenter = OperationFeedbackPresenter(
            sleep: { _ in try await Task.sleep(for: .seconds(3600)) },
            voiceOverRunning: { false }
        )

        let firstID = try XCTUnwrap(presenter.present(message: "Saved", kind: .success))
        let secondID = try XCTUnwrap(presenter.present(message: "Saved", kind: .success))

        XCTAssertNotEqual(firstID, secondID)
        XCTAssertEqual(presenter.current?.id, secondID)
    }

    func testSuccessWithActionsUsesRetainedActionTiming() throws {
        let presenter = OperationFeedbackPresenter(
            sleep: { _ in try await Task.sleep(for: .seconds(3600)) },
            voiceOverRunning: { false }
        )
        let action = OperationFeedbackAction(id: "close", title: "common.close") {}

        let eventID = try XCTUnwrap(
            presenter.present(
                message: "Needs attention",
                kind: .success,
                actions: [action],
                retainedTimeoutMillis: Int64.max
            )
        )

        XCTAssertEqual(presenter.current?.id, eventID)
        XCTAssertEqual(presenter.current?.kind, .action)
        XCTAssertEqual(presenter.lastScheduledTimeoutMillis, Int64.max)
    }

    func testReplacementAndClearConsumeOnlyTheirOwnEventOnce() throws {
        let presenter = OperationFeedbackPresenter(voiceOverRunning: { false })
        var finished: [String] = []
        let firstID = try XCTUnwrap(presenter.present(message: "Saved", kind: .success, onDismiss: { finished.append("first") }))
        let secondID = try XCTUnwrap(presenter.present(message: "Saved", kind: .success, onDismiss: { finished.append("second") }))
        XCTAssertEqual(finished, ["first"])
        presenter.dismiss(id: firstID)
        XCTAssertEqual(presenter.current?.id, secondID)
        presenter.clear()
        presenter.clear()
        XCTAssertEqual(finished, ["first", "second"])
    }

    func testVoiceOverExtendsTheSuccessWindow() throws {
        let presenter = OperationFeedbackPresenter(voiceOverRunning: { true })
        let id = try XCTUnwrap(presenter.present(message: "Saved", kind: .success))
        XCTAssertEqual(presenter.lastScheduledTimeoutMillis, 3_000)
        XCTAssertEqual(presenter.current?.id, id)
    }

    func testIndefiniteRetainedFeedbackDoesNotOverflowOrExpire() async throws {
        let clock = TestFeedbackClock()
        let presenter = makePresenter(clock: clock)

        let eventID = try XCTUnwrap(
            presenter.present(
                message: "Needs attention",
                kind: .partialsuccess,
                retainedTimeoutMillis: Int64.max
            )
        )
        presenter.markVisible(id: eventID, entranceDurationMillis: 0)
        await Task.yield()

        let schedule = await clock.scheduledNanoseconds()
        XCTAssertEqual(schedule, [])
        XCTAssertEqual(presenter.current?.id, eventID)
    }

    private func makePresenter(clock: TestFeedbackClock) -> OperationFeedbackPresenter {
        OperationFeedbackPresenter(
            sleep: { nanoseconds in try await clock.sleep(nanoseconds) },
            voiceOverRunning: { false }
        )
    }
}

private actor TestFeedbackClock {
    private var pending: [UUID: CheckedContinuation<Void, Error>] = [:]
    private var scheduled: [UInt64] = []

    func sleep(_ nanoseconds: UInt64) async throws {
        let token = UUID()
        try await withTaskCancellationHandler(operation: {
            try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<Void, Error>) in
                register(token: token, nanoseconds: nanoseconds, continuation: continuation)
            }
        }, onCancel: {
            Task { await cancel(token: token) }
        })
    }

    func scheduledNanoseconds() -> [UInt64] { scheduled }

    func waitUntilScheduled(count: Int) async throws {
        let deadline = ContinuousClock.now.advanced(by: .seconds(1))
        while scheduled.count < count {
            if ContinuousClock.now >= deadline { throw ClockError.timerWasNotScheduled }
            await Task.yield()
        }
    }

    private enum ClockError: Error { case timerWasNotScheduled }

    func releaseNext() {
        guard let token = pending.keys.sorted(by: { $0.uuidString < $1.uuidString }).first,
              let continuation = pending.removeValue(forKey: token)
        else { return }
        continuation.resume()
    }

    private func register(
        token: UUID,
        nanoseconds: UInt64,
        continuation: CheckedContinuation<Void, Error>
    ) {
        if Task.isCancelled {
            continuation.resume(throwing: CancellationError())
            return
        }
        scheduled.append(nanoseconds)
        pending[token] = continuation
    }

    private func cancel(token: UUID) {
        guard let continuation = pending.removeValue(forKey: token) else { return }
        continuation.resume(throwing: CancellationError())
    }
}
