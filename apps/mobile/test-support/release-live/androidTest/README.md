# RG04 Android real HTTP audio gate

This source directory is included only with `-PenableReleaseLiveProbe=true`.
It is a separate release acceptance gate; its result must not be added to the
ordinary instrumentation suite's count. There are no assumptions, skips or
weakened default tests. Build separately and select one exact method:

- Fresh-server confirmation and runtime reopen:
  `com.ermao.library.release.live.AndroidAudioOnlineConfirmationInstrumentedTest#realHttpConfirmsPlaybackAtFiveAndTenSecondsAndRestoresAfterReopen`
- MP3 Web-to-Android handoff:
  `com.ermao.library.release.live.AndroidAudioOnlineConfirmationInstrumentedTest#restoresWebMp3ProgressAndConfirmsPlaybackForWebHandoff`
- POS-06 late ACK with durable newer pending and coordinator/database reopen:
  `com.ermao.library.release.live.AndroidAudioOnlineConfirmationInstrumentedTest#realHttpLateAckKeepsNewerAudioPositionDurableAcrossCoordinatorRestart`

Do not run the whole class with one input: each method consumes its own fresh
private fixture, and their initial server-progress requirements differ.

Host compile, from `apps/mobile`:

```
gradlew.bat -I test-support/release-live/android-ui.init.gradle :androidApp:assembleReleaseAndroidTest -PenableReleaseLiveProbe=true --offline --console=plain
```

The opt-in init script selects the existing release source set with empty login
defaults, debug signing, and the isolated `com.ermao.library.releasecheck` UID.
Its release-named APKs are development acceptance artifacts, not formal delivery.
The provisioner targets only that package; install the matching test APK without
clearing either app's data. Never run this probe against `com.ermao.library`.
With this explicit init script and opt-in flag, the test APK compiles only this
live source directory. The ordinary debug instrumentation suite, including its
debug-only visual hosts, retains its separate normal build and acceptance path.

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

Locator comparison uses the complete JSON object value, including unknown engine
members, while presentation keeps typed equality. The server canonicalizes object
key order and the engine preserves insertion order; byte-string equality would
reject a valid round trip. Identity, capture time, revision, pending-state and all
timing checks remain mandatory. The original failed run is retained in release
evidence; no production serialization is changed to match this observation.

Reopening constructs a new runtime and calls `launchRemote` without an explicit
chapter/position. Restored paused playback must be within two seconds of the
confirmed original pause, and its outbox/GET must converge through production
retry. `close()` can create a Stop pending capture; the report records
`CLOSED_PENDING` or `CLOSED_CONFIRMED` without deleting/acknowledging it manually.
This verifies the real restore owner's choice, not exclusively server-only
restoration when Stop leaves a local pending capture.

For the MP3 handoff method, provision first, then use the real Web player under
the same isolated account to play, pause and close the selected MP3 before
Android consumes the fixture. The primary privately supplies that account's
credentials to the isolated browser; `android-probe.json` contains no password.
Confirm the final Web write with a fresh GET. Choose a Web position clearly
above zero with enough sample remaining for the unchanged 10-second playback
and pause checks. Do not synthesize a progress PUT.

The handoff method keeps the same fresh local DB/prefs requirements, requires a
nonzero remote MP3 position from a different client, and opens with
`autoplay=false` and no chapter/position target. `WEB_RESTORE_OBSERVATION` records
the actual engine value before the mandatory two-second comparison. Playback
then uses the same 5/10-second and pause-confirmation owner as the fresh-server
test, with the Web snapshot as the initial position/revision baseline.
Per [ADR0028](../../../../../docs/adr/0028-reader-v5-opaque-position-report.md),
different clients are ordered by committed server revision; their capture clocks
need not agree. Capture time must still increase for subsequent same-client
checkpoints, and the original empty-server case retains its positive initial
capture-time requirement. All confirmation deadlines and exact local/GET
identity, capture and complete-position comparisons remain unchanged.
`ANDROID_HANDOFF_CONFIRMED` records the Android client, capture time, position and
revision; close still records any Stop pending state without manual ACK.

`ANDROID_HANDOFF_PASS` and this method's JUnit PASS cover only the Android leg.
After Android closes, the primary must fresh-GET the latest confirmed Android
snapshot, reopen the same resource in the real Web player without a direct
chapter/asset target, and verify the restored position within two seconds. Gate
RG04 bidirectional SYNC requires that actual Web-to-Android-to-Web result plus
one fresh-server run of the original online method. Compilation cannot satisfy
that stop condition. There are no new fixture fields, phase options or
force-stop steps.

The POS-06 method captures two distinct reports through the real player and the
unchanged HTTP/SQLite confirmation helper. It reuses those complete reports as
new M/N mutations in the production coordinator with a separate case database
inside the same private fixture directory. This avoids a closed player's Stop
write interfering with the controlled sequence. No Locator is derived from a
percentage or modified for the test.

The test port delegates M to real HTTP, verifies its committed value by a fresh
GET, and holds only the decoded ACK's delivery to the coordinator. After N is
durable, releasing M must lead to the exact N upload; that second call is held
before transmission so an independent SQLite connection can verify the whole
N state remains unchanged. The test cancels and joins its scope, reopens the case
database and coordinator, and confirms retry of that exact mutation through real
HTTP within five seconds. This covers the Android sync-owner/HTTP/SQLite boundary;
it is not a socket-drop test, process kill, ordinary UI race or Chrome result.

`online-evidence.log` and the matching `RG04ReleaseLive` logcat tag contain only
result codes, resource/asset/client IDs and scalar capture, position, revision
and engine observations. The isolated DB and
prefixed encrypted preferences remain private for collection; no cleanup clears
app settings, sessions, keystore or other directories. A PASS is the JUnit result,
not merely a log line. Host compilation is not real HTTP/device evidence.

Original sample SHA-256 belongs to the primary's fixture/source evidence in
`android-probe.json`: compare the same host sample before and after device
execution. The fixed private schema has no sample path/hash. This test does not
download an extra complete media copy or claim to hash the backend source on
Android. Provisioning success, actual instrumented results and unchanged original
hash must be combined by the primary for release acceptance.
