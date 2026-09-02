import XCTest
@preconcurrency import ErmaoShared
import MediaPlayer
import UniformTypeIdentifiers
@testable import ErmaoLibrary

@MainActor
final class AudioPlaybackTests: XCTestCase {
    func testResourceLoaderBuildsUniqueContainerAwareURLs() {
        let firstSource: Int64 = 1
        let secondSource: Int64 = 2

        let first = IosAudioResourceLoader.url(
            assetID: "asset one",
            mimeType: "audio/mp4",
            sourceID: firstSource
        )
        let second = IosAudioResourceLoader.url(
            assetID: "asset one",
            mimeType: "audio/mp4",
            sourceID: secondSource
        )

        XCTAssertEqual(first.scheme, "ermao-audio")
        XCTAssertEqual(first.lastPathComponent, "asset%20one.m4a")
        XCTAssertNotEqual(first, second)
        XCTAssertEqual(
            IosAudioMediaType.uniformTypeIdentifier(for: "audio/mp4; charset=binary"),
            UTType(filenameExtension: "m4a")?.identifier
        )
        XCTAssertEqual(IosAudioMediaType.avFoundationMIMEType(for: "audio/mp4"), "audio/x-m4a")
    }

    func testResourceLoaderPreservesOpenEndedAndClampsBoundedRanges() {
        XCTAssertEqual(
            IosAudioResourceLoader.requestedRange(
                offset: 128,
                length: Int.max,
                requestsAllDataToEnd: true,
                assetSize: 1_024
            ),
            AudioMediaByteRange(start: 128)
        )
        XCTAssertEqual(
            IosAudioResourceLoader.requestedRange(
                offset: 900,
                length: 500,
                requestsAllDataToEnd: false,
                assetSize: 1_024
            ),
            AudioMediaByteRange(start: 900, end: 1_024)
        )
    }

    func testNativeNamespaceRemainsAuthoritativeAcrossKmpProjection() throws {
        let session = IosAudioSessionContext(
            profile: RuntimeServerProfile(
                id: "profile-1",
                displayName: "Books",
                baseURL: "https://books.example",
                serverIdentity: "server-1",
                isActive: true,
                tlsMode: .systemTrust
            ),
            userID: "user-1",
            authorizationVersion: 7
        )

        XCTAssertNotEqual(session.namespaceKey, session.sharedNamespace.stableKey)
        XCTAssertEqual(
            try KmpAudioBootstrapGateway.presentationNamespace(
                session: session,
                requestedNamespace: session.namespaceKey
            ),
            session.namespaceKey
        )
        XCTAssertThrowsError(
            try KmpAudioBootstrapGateway.presentationNamespace(
                session: session,
                requestedNamespace: "stale|user|6"
            )
        )
    }
}

@MainActor
final class AudioPlaybackRuntimeStateMachineTests: XCTestCase {
    func testLaunchCommitsOnlyAfterEnginePreparedAndCommittedFacts() async throws {
        let context = makeAudioTestContext()
        let envelope = makeAudioEnvelope(resourceID: "resource-a", context: context)
        let gateway = RuntimeFakeBootstrapGateway(envelopes: ["resource-a": envelope])
        let progress = RuntimeFakeProgressAdapter()
        let engine = RuntimeFakeAudioEngine()
        let system = RuntimeFakeSystemMedia()
        let runtime = makeRuntime(gateway: gateway, progress: progress, engine: engine, system: system)
        runtime.sessionDidChange(isAuthenticated: true, session: context)

        runtime.launch(
            AudioLaunchIntent(resourceID: "resource-a", autoplay: true),
            namespace: context.namespaceKey
        )
        try await waitUntil { engine.pendingSourceID != nil }
        let candidate = try XCTUnwrap(engine.pendingSourceID)
        XCTAssertEqual(runtime.snapshot.lifecycle, .loading)
        XCTAssertNil(runtime.snapshot.resourceID)

        engine.emit(.prepared(sourceID: candidate, durationMillis: 60_000))
        XCTAssertEqual(engine.commitRequests.count, 1)
        XCTAssertEqual(runtime.snapshot.lifecycle, .loading)
        XCTAssertNil(runtime.snapshot.resourceID)

        engine.confirmCommit()
        try await waitUntil { progress.committedResourceIDs == ["resource-a"] }
        XCTAssertEqual(runtime.snapshot.resourceID, "resource-a")
        XCTAssertEqual(runtime.snapshot.lifecycle, .ready)
        XCTAssertEqual(progress.committedResourceIDs, ["resource-a"])
        engine.emit(.playing(sourceID: candidate))
        XCTAssertEqual(runtime.snapshot.lifecycle, .playing)
        XCTAssertEqual(system.activationCount, 1)
    }

    func testReplacementCommitFailureKeepsOldCommittedPlayer() async throws {
        let context = makeAudioTestContext()
        let gateway = RuntimeFakeBootstrapGateway(envelopes: [
            "resource-a": makeAudioEnvelope(resourceID: "resource-a", context: context),
            "resource-b": makeAudioEnvelope(resourceID: "resource-b", context: context)
        ])
        let progress = RuntimeFakeProgressAdapter()
        let engine = RuntimeFakeAudioEngine()
        let runtime = makeRuntime(
            gateway: gateway,
            progress: progress,
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)

        runtime.launch(AudioLaunchIntent(resourceID: "resource-a", autoplay: true), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil }
        let first = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: first, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.playing(sourceID: first))
        try await waitUntil { progress.committedResourceIDs == ["resource-a"] }
        XCTAssertEqual(engine.currentSourceID, first)

        runtime.launch(AudioLaunchIntent(resourceID: "resource-b", autoplay: true), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil && engine.pendingSourceID != first }
        let candidate = try XCTUnwrap(engine.pendingSourceID)
        XCTAssertEqual(engine.currentSourceID, first)
        XCTAssertEqual(runtime.snapshot.resourceID, "resource-a")

        engine.emit(.prepared(sourceID: candidate, durationMillis: 60_000))
        XCTAssertEqual(engine.commitRequests.last?.sourceID, candidate)
        engine.emit(.failed(
            sourceID: candidate,
            failure: AudioEngineFailure(code: .network, detail: nil)
        ))
        XCTAssertEqual(engine.currentSourceID, first)
        XCTAssertNil(engine.pendingSourceID)
        XCTAssertEqual(engine.teardownCount, 0)
        XCTAssertEqual(runtime.snapshot.resourceID, "resource-a")
        XCTAssertEqual(runtime.snapshot.lifecycle, .paused)
        XCTAssertGreaterThan(engine.playCount, 0)
        engine.emit(.playing(sourceID: first))
        XCTAssertEqual(runtime.snapshot.lifecycle, .playing)
        XCTAssertEqual(progress.committedResourceIDs, ["resource-a"])
        try await waitUntil { progress.discardedResourceIDs == ["resource-b"] }
        XCTAssertEqual(progress.discardedResourceIDs, ["resource-b"])
    }

    func testReplacementRendersLoadingAndRejectsPlaybackCommandsUntilCommit() async throws {
        let context = makeAudioTestContext()
        let progress = RuntimeFakeProgressAdapter()
        let engine = RuntimeFakeAudioEngine()
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: [
                "resource-a": makeAudioEnvelope(resourceID: "resource-a", context: context),
                "resource-b": makeAudioEnvelope(resourceID: "resource-b", context: context),
                "resource-c": makeAudioEnvelope(resourceID: "resource-c", context: context)
            ]),
            progress: progress,
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(AudioLaunchIntent(resourceID: "resource-a", autoplay: true), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil }
        let first = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: first, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.playing(sourceID: first))

        runtime.launch(AudioLaunchIntent(resourceID: "resource-b", autoplay: true), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil && engine.pendingSourceID != first }
        let candidate = try XCTUnwrap(engine.pendingSourceID)
        let playCount = engine.playCount
        let pauseCount = engine.pauseCount
        let seekCount = engine.seeks.count

        XCTAssertEqual(runtime.snapshot.lifecycle, .loading)
        runtime.play()
        runtime.pause()
        runtime.seekAbsolute(to: 12_000)
        runtime.nextChapter()
        runtime.setPlaybackRate(2)
        runtime.launch(
            AudioLaunchIntent(resourceID: "resource-c", autoplay: true),
            namespace: context.namespaceKey
        )

        XCTAssertEqual(engine.pendingSourceID, candidate)
        XCTAssertEqual(engine.playCount, playCount)
        XCTAssertEqual(engine.pauseCount, pauseCount)
        XCTAssertEqual(engine.seeks.count, seekCount)

        engine.emit(.prepared(sourceID: candidate, durationMillis: 60_000))
        engine.confirmCommit()
        XCTAssertEqual(runtime.snapshot.lifecycle, .ready)
        XCTAssertEqual(runtime.snapshot.resourceID, "resource-b")
    }

    func testProgressOperationsRemainOrderedAcrossReplacementCommit() async throws {
        let context = makeAudioTestContext()
        let progress = RuntimeFakeProgressAdapter()
        let engine = RuntimeFakeAudioEngine()
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: [
                "resource-a": makeAudioEnvelope(resourceID: "resource-a", context: context),
                "resource-b": makeAudioEnvelope(resourceID: "resource-b", context: context)
            ]),
            progress: progress,
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(AudioLaunchIntent(resourceID: "resource-a", autoplay: true), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil }
        let first = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: first, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.playing(sourceID: first))
        try await waitUntil { progress.committedResourceIDs == ["resource-a"] }

        progress.suspendNextSave = true
        runtime.launch(AudioLaunchIntent(resourceID: "resource-b", autoplay: false), namespace: context.namespaceKey)
        try await waitUntil { progress.saveIsSuspended }
        XCTAssertNil(engine.pendingSourceID)
        XCTAssertEqual(progress.committedResourceIDs, ["resource-a"])
        progress.resumeSuspendedSave()

        try await waitUntil { engine.pendingSourceID != nil }
        let candidate = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: candidate, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.paused(sourceID: candidate))

        XCTAssertEqual(progress.committedResourceIDs, ["resource-a"])
        try await waitUntil {
            progress.committedResourceIDs == ["resource-a", "resource-b"] &&
                progress.saved.contains(where: { $0.progressReason == .pause })
        }
        XCTAssertEqual(
            progress.saved.suffix(2).compactMap(\.progressReason),
            [.trackchange, .pause]
        )
    }

    func testRestoreAndSaveUseKmpProgressSessionWithoutSwiftCoalescing() async throws {
        let context = makeAudioTestContext()
        let envelope = makeAudioEnvelope(resourceID: "resource-a", context: context)
        let progress = RuntimeFakeProgressAdapter(
            restored: ErmaoShared.AudioReaderLocation(
                assetId: envelope.publication.assets[0].assetId,
                chapterId: nil,
                positionMillis: 24_000,
                engineLocator: nil
            )
        )
        let engine = RuntimeFakeAudioEngine()
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: ["resource-a": envelope]),
            progress: progress,
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)

        runtime.launch(AudioLaunchIntent(resourceID: "resource-a", autoplay: false), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil }
        let source = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: source, durationMillis: 60_000))
        XCTAssertEqual(engine.commitRequests.last?.positionMillis, 24_000)
        engine.confirmCommit()

        runtime.seekAbsolute(to: 31_000)
        try await waitUntil { progress.saved.contains(where: { $0.progressReason == .seek }) }
        engine.emit(.paused(sourceID: source))
        try await waitUntil { progress.saved.contains(where: { $0.progressReason == .pause }) }
        let seek = try XCTUnwrap(progress.saved.first(where: { $0.progressReason == .seek }))
        XCTAssertEqual(seek.positionMillis, 31_000)
        XCTAssertEqual(seek.durationMillis?.int64Value, 60_000)
    }

    func testStopSavesLocallyBeforeTeardownAndNowPlayingClear() async throws {
        let context = makeAudioTestContext()
        let log = RuntimeAudioEventLog()
        let envelope = makeAudioEnvelope(resourceID: "resource-a", context: context)
        let progress = RuntimeFakeProgressAdapter(log: log)
        let engine = RuntimeFakeAudioEngine(log: log)
        let system = RuntimeFakeSystemMedia(log: log)
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: ["resource-a": envelope]),
            progress: progress,
            engine: engine,
            system: system
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(AudioLaunchIntent(resourceID: "resource-a", autoplay: false), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil }
        let source = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: source, durationMillis: 60_000))
        engine.confirmCommit()

        runtime.stopAndClear()
        runtime.stopAndClear()
        try await waitUntil { engine.teardownCount == 1 && system.clearCount > 0 }
        let stopSave = try XCTUnwrap(log.values.lastIndex(of: "save:Stop"))
        let teardown = try XCTUnwrap(log.values.lastIndex(of: "teardown"))
        let clear = try XCTUnwrap(log.values.lastIndex(of: "clear"))
        XCTAssertLessThan(stopSave, teardown)
        XCTAssertLessThan(teardown, clear)
        XCTAssertEqual(runtime.snapshot.lifecycle, .idle)
    }

    func testStopDuringInitialCommitWindowStillTearsDownNativeEngine() async throws {
        let context = makeAudioTestContext()
        let envelope = makeAudioEnvelope(resourceID: "resource-a", context: context)
        let engine = RuntimeFakeAudioEngine()
        let system = RuntimeFakeSystemMedia()
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: ["resource-a": envelope]),
            progress: RuntimeFakeProgressAdapter(),
            engine: engine,
            system: system
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(
            AudioLaunchIntent(resourceID: "resource-a", autoplay: true),
            namespace: context.namespaceKey
        )
        try await waitUntil { engine.pendingSourceID != nil }
        let source = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: source, durationMillis: 60_000))
        XCTAssertEqual(engine.commitRequests.count, 1)

        runtime.stopAndClear()

        try await waitUntil { engine.teardownCount == 1 && system.clearCount == 1 }
        XCTAssertNil(engine.currentSourceID)
        XCTAssertNil(engine.pendingSourceID)
        XCTAssertEqual(runtime.snapshot.lifecycle, .idle)
    }

    func testStopCancelsCandidateAndPausesBeforeWaitingForProgressSave() async throws {
        let context = makeAudioTestContext()
        let progress = RuntimeFakeProgressAdapter()
        let engine = RuntimeFakeAudioEngine()
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: [
                "resource-a": makeAudioEnvelope(resourceID: "resource-a", context: context),
                "resource-b": makeAudioEnvelope(resourceID: "resource-b", context: context)
            ]),
            progress: progress,
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(AudioLaunchIntent(resourceID: "resource-a", autoplay: true), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil }
        let first = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: first, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.playing(sourceID: first))

        runtime.launch(AudioLaunchIntent(resourceID: "resource-b", autoplay: true), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil && engine.pendingSourceID != first }
        let candidate = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: candidate, durationMillis: 60_000))
        try await waitUntil {
            progress.saved.contains(where: { $0.progressReason == .trackchange })
        }
        progress.suspendNextSave = true
        let pausesBeforeStop = engine.pauseCount

        runtime.stopAndClear()

        try await waitUntil { progress.saveIsSuspended }
        XCTAssertNil(engine.pendingSourceID)
        XCTAssertEqual(engine.pauseCount, pausesBeforeStop + 1)
        XCTAssertEqual(engine.teardownCount, 0)
        engine.confirmCommit()
        XCTAssertEqual(engine.currentSourceID, first)

        progress.resumeSuspendedSave()
        try await waitUntil { engine.teardownCount == 1 }
        XCTAssertEqual(engine.teardownCount, 1)
        XCTAssertNil(engine.currentSourceID)
    }

    func testStopWhileBootstrapIsPendingStillRunsNativeTeardown() async throws {
        let context = makeAudioTestContext()
        let engine = RuntimeFakeAudioEngine()
        let system = RuntimeFakeSystemMedia()
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(
                envelopes: ["resource-a": makeAudioEnvelope(resourceID: "resource-a", context: context)]
            ),
            progress: RuntimeFakeProgressAdapter(),
            engine: engine,
            system: system
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)

        runtime.launch(
            AudioLaunchIntent(resourceID: "resource-a", autoplay: true),
            namespace: context.namespaceKey
        )
        runtime.stopAndClear()

        try await waitUntil { engine.teardownCount == 1 && system.clearCount == 1 }
        XCTAssertEqual(runtime.snapshot.lifecycle, .idle)
    }

    func testInterruptionEndNeverAutoResumes() async throws {
        let context = makeAudioTestContext()
        let envelope = makeAudioEnvelope(resourceID: "resource-a", context: context)
        let engine = RuntimeFakeAudioEngine()
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: ["resource-a": envelope]),
            progress: RuntimeFakeProgressAdapter(),
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(AudioLaunchIntent(resourceID: "resource-a", autoplay: true), namespace: context.namespaceKey)
        try await waitUntil { engine.pendingSourceID != nil }
        let source = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: source, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.playing(sourceID: source))
        let playsBeforeInterruption = engine.playCount

        runtime.audioSystemDidBeginInterruption()
        engine.emit(.paused(sourceID: source))
        runtime.audioSystemDidEndInterruption(shouldResume: true)
        XCTAssertEqual(engine.playCount, playsBeforeInterruption)
        XCTAssertEqual(runtime.snapshot.lifecycle, .paused)
    }

    func testScrubbingFreezesTargetUntilEngineConfirmsThenResumes() async throws {
        let context = makeAudioTestContext()
        let progress = RuntimeFakeProgressAdapter()
        let engine = RuntimeFakeAudioEngine()
        engine.completesSeeksAutomatically = false
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: [
                "resource-a": makeAudioEnvelope(resourceID: "resource-a", context: context)
            ]),
            progress: progress,
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(
            AudioLaunchIntent(resourceID: "resource-a", autoplay: true),
            namespace: context.namespaceKey
        )
        try await waitUntil { engine.pendingSourceID != nil }
        let source = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: source, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.playing(sourceID: source))
        engine.emit(.position(sourceID: source, positionMillis: 10_000, durationMillis: 60_000))

        let pauseCount = engine.pauseCount
        runtime.beginScrubbing()
        XCTAssertEqual(engine.pauseCount, pauseCount + 1)
        runtime.updateScrubbing(to: 42_000)
        XCTAssertEqual(runtime.snapshot.absolutePositionMillis, 42_000)
        engine.emit(.position(sourceID: source, positionMillis: 11_000, durationMillis: 60_000))
        XCTAssertEqual(runtime.snapshot.absolutePositionMillis, 42_000)

        runtime.finishScrubbing(at: 42_000)
        XCTAssertEqual(runtime.snapshot.lifecycle, .loading)
        XCTAssertEqual(engine.seekRequests.last?.positionMillis, 42_000)
        engine.emit(.position(sourceID: source, positionMillis: 12_000, durationMillis: 60_000))
        XCTAssertEqual(runtime.snapshot.absolutePositionMillis, 42_000)
        let playCount = engine.playCount
        engine.completeLastSeek()
        XCTAssertEqual(runtime.snapshot.absolutePositionMillis, 42_000)
        XCTAssertEqual(engine.playCount, playCount + 1)
        engine.emit(.playing(sourceID: source))
        engine.emit(.position(sourceID: source, positionMillis: 43_000, durationMillis: 60_000))
        XCTAssertEqual(runtime.snapshot.absolutePositionMillis, 43_000)
        try await waitUntil {
            progress.saved.contains(where: {
                $0.progressReason == .seek && $0.positionMillis == 42_000
            })
        }
    }

    func testScrubbingFailureDropsUnconfirmedTargetAndRestoresPriorPlayback() async throws {
        let context = makeAudioTestContext()
        let progress = RuntimeFakeProgressAdapter()
        let engine = RuntimeFakeAudioEngine()
        engine.completesSeeksAutomatically = false
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: [
                "resource-a": makeAudioEnvelope(resourceID: "resource-a", context: context)
            ]),
            progress: progress,
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(
            AudioLaunchIntent(resourceID: "resource-a", autoplay: true),
            namespace: context.namespaceKey
        )
        try await waitUntil { engine.pendingSourceID != nil }
        let source = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: source, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.playing(sourceID: source))
        engine.emit(.position(sourceID: source, positionMillis: 9_000, durationMillis: 60_000))

        runtime.beginScrubbing()
        runtime.updateScrubbing(to: 40_000)
        runtime.finishScrubbing(at: 40_000)
        let playCount = engine.playCount

        engine.failLastSeek()

        XCTAssertEqual(runtime.snapshot.absolutePositionMillis, 9_000)
        XCTAssertEqual(runtime.snapshot.lifecycle, .paused)
        XCTAssertEqual(engine.playCount, playCount + 1)
        XCTAssertFalse(progress.saved.contains(where: {
            $0.progressReason == .seek && $0.positionMillis == 40_000
        }))
    }

    func testPausedScrubbingRejectsALatePlayingFactUntilTheUserPlays() async throws {
        let context = makeAudioTestContext()
        let engine = RuntimeFakeAudioEngine()
        let runtime = makeRuntime(
            gateway: RuntimeFakeBootstrapGateway(envelopes: [
                "resource-a": makeAudioEnvelope(resourceID: "resource-a", context: context)
            ]),
            progress: RuntimeFakeProgressAdapter(),
            engine: engine,
            system: RuntimeFakeSystemMedia()
        )
        runtime.sessionDidChange(isAuthenticated: true, session: context)
        runtime.launch(
            AudioLaunchIntent(resourceID: "resource-a", autoplay: false),
            namespace: context.namespaceKey
        )
        try await waitUntil { engine.pendingSourceID != nil }
        let source = try XCTUnwrap(engine.pendingSourceID)
        engine.emit(.prepared(sourceID: source, durationMillis: 60_000))
        engine.confirmCommit()
        engine.emit(.paused(sourceID: source))
        engine.emit(.position(sourceID: source, positionMillis: 7_000, durationMillis: 60_000))

        runtime.beginScrubbing()
        runtime.updateScrubbing(to: 30_000)
        runtime.finishScrubbing(at: 30_000)
        engine.emit(.playing(sourceID: source))

        XCTAssertEqual(runtime.snapshot.lifecycle, .paused)
        runtime.play()
        engine.emit(.playing(sourceID: source))
        XCTAssertEqual(runtime.snapshot.lifecycle, .playing)
    }

    private func makeRuntime(
        gateway: RuntimeFakeBootstrapGateway,
        progress: RuntimeFakeProgressAdapter,
        engine: RuntimeFakeAudioEngine,
        system: RuntimeFakeSystemMedia
    ) -> AudioPlaybackRuntime {
        AudioPlaybackRuntime(
            bootstrapGateway: gateway,
            mediaAdapter: RuntimeFakeMediaAdapter(),
            progressAdapter: progress,
            engine: engine,
            systemMedia: system,
            backgroundPlaybackEnabled: false
        )
    }

    private func waitUntil(
        _ condition: @escaping @MainActor () -> Bool,
        file: StaticString = #filePath,
        line: UInt = #line
    ) async throws {
        for _ in 0..<100 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("condition was not met", file: file, line: line)
    }
}

@MainActor
private func makeAudioTestContext() -> IosAudioSessionContext {
    IosAudioSessionContext(
        profile: RuntimeServerProfile(
            id: "profile-1",
            displayName: "Books",
            baseURL: "https://books.example",
            serverIdentity: "server-1",
            isActive: true,
            tlsMode: .systemTrust
        ),
        userID: "user-1",
        authorizationVersion: 7
    )
}

@MainActor
private func makeAudioEnvelope(
    resourceID: String,
    context: IosAudioSessionContext
) -> AudioBootstrapEnvelope {
    let publication = ErmaoShared.LocalAudioPublicationFactory().create(
        namespace: context.sharedNamespace,
        bookId: "book-1",
        bookTitle: "Book",
        author: "Author",
        resourceId: resourceID,
        resourceTitle: "Volume \(resourceID)",
        assetId: "asset-\(resourceID)",
        mimeType: "audio/mp4",
        sizeBytes: 1_000,
        durationMillis: 60_000
    )
    return AudioBootstrapEnvelope(
        publication: publication,
        remoteSnapshot: nil
    )
}

@MainActor
private final class RuntimeFakeBootstrapGateway: AudioBootstrapGateway {
    let envelopes: [String: AudioBootstrapEnvelope]

    init(envelopes: [String: AudioBootstrapEnvelope]) {
        self.envelopes = envelopes
    }

    func loadAudioBootstrap(resourceID: String, namespace: String) async throws -> AudioBootstrapEnvelope {
        guard let envelope = envelopes[resourceID] else { throw AudioAdapterError.resourceUnavailable }
        return envelope
    }
}

@MainActor
private final class RuntimeFakeProgressAdapter: AudioProgressAdapter {
    let restored: ErmaoShared.AudioReaderLocation?
    let log: RuntimeAudioEventLog?
    private(set) var saved: [ErmaoShared.AudioPlaybackEffect] = []
    private(set) var flushedNamespaces: [String] = []
    private(set) var committedResourceIDs: [String] = []
    private(set) var discardedResourceIDs: [String] = []
    var suspendNextSave = false
    private(set) var saveIsSuspended = false
    private var saveContinuation: CheckedContinuation<Void, Never>?

    init(
        restored: ErmaoShared.AudioReaderLocation? = nil,
        log: RuntimeAudioEventLog? = nil
    ) {
        self.restored = restored
        self.log = log
    }

    func configure(bootstrap: AudioBootstrapEnvelope) async -> ErmaoShared.AudioReaderLocation? {
        restored
    }

    func configureLocal(publication: ErmaoShared.AudioPublication) async -> ErmaoShared.AudioReaderLocation? {
        restored
    }

    func commitPrepared(resourceID: String, namespace: String) {
        committedResourceIDs.append(resourceID)
    }

    func discardPrepared(resourceID: String, namespace: String) {
        discardedResourceIDs.append(resourceID)
    }

    func save(_ effect: ErmaoShared.AudioPlaybackEffect) async throws {
        if suspendNextSave {
            suspendNextSave = false
            saveIsSuspended = true
            await withCheckedContinuation { continuation in
                saveContinuation = continuation
            }
            saveIsSuspended = false
        }
        saved.append(effect)
        log?.values.append(effect.progressReason == .stop ? "save:Stop" : "save:Other")
    }

    func resumeSuspendedSave() {
        saveContinuation?.resume()
        saveContinuation = nil
    }

    func flush(namespace: String) async {
        flushedNamespaces.append(namespace)
    }
}

@MainActor
private final class RuntimeFakeMediaAdapter: AudioMediaStreamAdapter {
    func probe(_ request: AudioMediaStreamRequest) async throws -> AudioMediaProbe {
        throw AudioAdapterError.unavailable
    }

    func open(_ request: AudioMediaStreamRequest) async throws -> any ErmaoLibrary.AudioMediaStream {
        throw AudioAdapterError.unavailable
    }
}

@MainActor
private final class RuntimeFakeAudioEngine: AudioPlaybackEngine {
    struct CommitRequest {
        let sourceID: Int64
        let positionMillis: Int64
        let playbackRate: Double
        let autoplay: Bool
    }

    struct SeekRequest {
        let sourceID: Int64
        let operationID: Int64
        let positionMillis: Int64
    }

    var eventHandler: ((AudioEngineEvent) -> Void)?
    let log: RuntimeAudioEventLog?
    private(set) var pendingSourceID: Int64?
    private(set) var currentSourceID: Int64?
    private(set) var commitRequests: [CommitRequest] = []
    private(set) var playCount = 0
    private(set) var pauseCount = 0
    private(set) var teardownCount = 0
    private(set) var seeks: [Int64] = []
    private(set) var seekRequests: [SeekRequest] = []
    var completesSeeksAutomatically = true
    private var candidateAutoplay = false

    init(log: RuntimeAudioEventLog? = nil) {
        self.log = log
    }

    func prepareSource(
        track: AudioTrack,
        resourceID: String,
        namespace: String,
        sourceID: Int64
    ) {
        pendingSourceID = sourceID
    }

    func commitPreparedSource(
        sourceID: Int64,
        positionMillis: Int64,
        playbackRate: Double,
        autoplay: Bool
    ) {
        guard pendingSourceID == sourceID else { return }
        commitRequests.append(CommitRequest(
            sourceID: sourceID,
            positionMillis: positionMillis,
            playbackRate: playbackRate,
            autoplay: autoplay
        ))
        candidateAutoplay = autoplay
    }

    func confirmCommit() {
        guard let sourceID = pendingSourceID else { return }
        currentSourceID = sourceID
        pendingSourceID = nil
        eventHandler?(.committed(sourceID: sourceID))
        if candidateAutoplay { play() }
    }

    func cancelPreparedSource(sourceID: Int64) {
        if pendingSourceID == sourceID {
            pendingSourceID = nil
            log?.values.append("cancel")
        }
    }

    func play() { playCount += 1 }
    func pause() {
        pauseCount += 1
        log?.values.append("pause")
    }
    func seek(sourceID: Int64, operationID: Int64, to positionMillis: Int64) {
        seeks.append(positionMillis)
        seekRequests.append(SeekRequest(
            sourceID: sourceID,
            operationID: operationID,
            positionMillis: positionMillis
        ))
        if completesSeeksAutomatically {
            completeLastSeek()
        }
    }

    func completeLastSeek(positionMillis: Int64? = nil) {
        guard let request = seekRequests.last else { return }
        eventHandler?(.seekCompleted(
            sourceID: request.sourceID,
            operationID: request.operationID,
            positionMillis: positionMillis ?? request.positionMillis,
            durationMillis: 60_000
        ))
    }

    func failLastSeek() {
        guard let request = seekRequests.last else { return }
        eventHandler?(.seekFailed(
            sourceID: request.sourceID,
            operationID: request.operationID,
            failure: AudioEngineFailure(code: .unknown, detail: "AUDIO_SEEK_TIMEOUT")
        ))
    }
    func setPlaybackRate(_ rate: Double) {}

    func teardown() {
        teardownCount += 1
        currentSourceID = nil
        pendingSourceID = nil
        log?.values.append("teardown")
    }

    func emit(_ event: AudioEngineEvent) {
        eventHandler?(event)
    }
}

@MainActor
private final class RuntimeFakeSystemMedia: AudioSystemMediaControlling {
    weak var delegate: (any AudioSystemMediaDelegate)?
    let log: RuntimeAudioEventLog?
    private(set) var activationCount = 0
    private(set) var clearCount = 0
    private(set) var snapshots: [ErmaoLibrary.AudioPlaybackSnapshot] = []

    init(log: RuntimeAudioEventLog? = nil) {
        self.log = log
    }

    func activate() throws { activationCount += 1 }
    func deactivate() {}

    func updateNowPlaying(
        snapshot: ErmaoLibrary.AudioPlaybackSnapshot,
        artwork: MPMediaItemArtwork?
    ) {
        snapshots.append(snapshot)
    }

    func clearNowPlaying() {
        clearCount += 1
        log?.values.append("clear")
    }
}

@MainActor
private final class RuntimeAudioEventLog {
    var values: [String] = []
}
