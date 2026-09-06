# RG04 Android real HTTP audio gate

This source directory is included only with `-PenableReleaseLiveProbe=true`.
It is a separate release acceptance gate; its result must not be added to the
ordinary instrumentation suite's count. There are no assumptions, skips or
weakened default tests. Build and run the exact class separately:

`com.ermao.library.release.live.AndroidAudioOnlineConfirmationInstrumentedTest`

Host compile, from `apps/mobile`:

```
gradlew.bat :androidApp:compileDebugAndroidTestKotlin -PenableReleaseLiveProbe=true --offline --console=plain
```

The primary operator owns real backend setup/import, exact port authorization,
device provisioning and execution. Use `scripts/python_android_release_live_fixture.py`,
which reuses the existing release fixture and public setup/catalog scan owners.
Do not seed users through SQL or modify an installed user's server configuration.

The required instrumentation argument `releaseFixture` is the private absolute
device path returned in `android-probe.json`, or `rg04-live-UUID/fixture.json`
relative to the target app's `filesDir`. The canonical file must be named
`fixture.json` in a fresh immediate `rg04-live-UUID` child of that canonical root.
Escapes, reused/nonempty directories and missing fixtures fail. The test reads
and immediately deletes this one input before parsing/login, including on a read
failure. It never prints the raw JSON. Reprovision a fresh directory for each run.

Required JSON fields, with no defaults or extra keys:

| Field | Required real fixture value |
| --- | --- |
| `baseUrl` | Device-reachable origin of the isolated initialized backend |
| `email`, `password` | Newly provisioned real account credentials |
| `bookId`, `resourceId`, `assetId` | IDs from real import/catalog/bootstrap |
| `mimeType`, `sourceApiPath` | The single bootstrap audio asset's MIME and API path |
| `expectedDurationMillis` | Actual sample duration; greater than 12 seconds for this gate |

The production login creates a new profile using in-memory profile and verified
session repositories. Login, bootstrap, media transport and position sync share
one test Context and that authenticated profile. The Context maps the production
SQLite filename into the fixture directory and prefixes all preferences with
the unique directory name, including cookies and reader device identity. Database
observations open and close separate `AndroidReaderV5Database` connections. No
test database schema, auth, media engine, transport or progress workflow is copied.

The actual Media3 service uses `app.audioTransportRegistry`; the test requires
`app.audioPlaybackRuntime.snapshot.value.hasSession == false` before launching.
Normal login uses the production cookie vault: it creates the key only when the
fixed alias is absent and reuses an existing key, without deleting or replacing it.
The test does not pre-read the keystore. App startup runs before
JUnit: the primary must ensure the installed app has already completed the current
`AndroidMobileStorageContract` migration before instrumentation. This test Context
cannot isolate or undo `Application.onCreate` or an external concurrent user session.

At absolute 5/10-second playback checkpoints, a fresh local capture with cleared
pending state and increased confirmed revision must match a fresh GET through
`createAndroidReaderPositionSyncPort` (same adapter/profile as the runtime's
upload port): resource/client, capture time, revision and complete position. DB
reads bracket both concurrent local writes and the GET. HTTP time consumes the
checkpoint deadline. The player must still be playing, with confirmed Locator
at most five seconds behind. Pause must also confirm within five seconds.

Reopening constructs a new runtime and calls `launchRemote` without an explicit
chapter/position. Restored paused playback must be within two seconds of the
confirmed original pause, and its outbox/GET must converge through production
retry. `close()` can create a Stop pending capture; the report records
`CLOSED_PENDING` or `CLOSED_CONFIRMED` without deleting/acknowledging it manually.
This verifies the real restore owner's choice, not exclusively server-only
restoration when Stop leaves a local pending capture.

`online-evidence.log` and the matching `RG04ReleaseLive` logcat tag contain only
result codes, resource/asset IDs, positions and revisions. The isolated DB and
prefixed encrypted preferences remain private for collection; no cleanup clears
app settings, sessions, keystore or other directories. A PASS is the JUnit result,
not merely a log line. Host compilation is not real HTTP/device evidence.

Original sample SHA-256 belongs to the primary's fixture/source evidence in
`android-probe.json`: compare the same host sample before and after device
execution. The fixed private schema has no sample path/hash. This test does not
download an extra complete media copy or claim to hash the backend source on
Android. Provisioning success, actual instrumented results and unchanged original
hash must be combined by the primary for release acceptance.
