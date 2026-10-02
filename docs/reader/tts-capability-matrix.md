# Native TTS capability baseline (M0)

Baseline: `develop@033e429db26fd7afea0e49880b1322b1e0a480a0`, inspected 2026-09-30.
This records source-level capability and remaining gates, not completed device acceptance.
The first delivery is native iOS/Android reflowable reading with the platform speech engine.
Cloud synthesis, audio export/caching, PDF/comic OCR and background playback are outside this gate.

## Ownership

- Reuse the Publication already opened by the Reader and its security-decorated container. Do not
  reopen/download the book, extract a separate body, persist converted publications or invent chapters.
- Carry Readium Locators through `ReaderOpaqueLocator`. TTS character offsets and estimated
  percentages must not replace engine Locators or create a second Reader v5 progress slot.
- A ContentService is an API prerequisite, not evidence that a particular book has readable text.
  Fixed-layout, image-only, empty, unavailable and failed content need explicit admission results.
- TTS state/lifecycle belongs to the shared capability; SDK objects, content iteration, voices and
  platform audio operations stay in native adapters. Do not turn text into fake AudioAsset records.

## Format matrix

| Format | Android 3.3.0 | iOS 3.9.0 | M0 evidence still required |
| --- | --- | --- | --- |
| Reflowable EPUB | Official EpubParser registers DefaultContentService and HTML iterator | Official EPUBParser registers the equivalent services | Actual protected Publication iteration, empty/image-only/broken resources and start Locator |
| TXT | Custom factory previously registered only positions; this change adds the official HTML ContentService to its existing in-memory XHTML | IosTxtPublicationFactory already registers content, positions and search | Unicode/paragraph Locator, no-heading source, no derivative, long single-resource latency/memory |
| FB2 | Same missing service; added to the existing safe XHTML container | IosFb2PublicationFactory already registers content | Reading-order traversal, mixed inline text, nested sections/notes, resource errors |
| MOBI/AZW/AZW3/PRC | Same missing service; added using the final transformed lazy container | IosMobiPublicationFactory already registers content | Actual libmobi samples, safe lazy resource reads and Locator, close/cancel cleanup |
| Fixed-layout EPUB, PDF, comics, audio | Not admitted for this first TTS delivery | Not admitted for this first TTS delivery | Existing Reader/audio behavior unchanged |

The three Android additions use the same factory as the pinned SDK's EpubParser. They do not
create a second parser, positions service, text store or network path. In MOBI, the ContentService
receives `Publication.Service.Context.container`, which is the security-transformed container;
the existing descriptor-only positions strategy remains unchanged.

## Pinned SDK evidence

Android is pinned to Readium Kotlin **3.3.0**, tag commit
`3bb9c88d505d43c8e9f8d3b6b30c69927071c7fe` (`apps/mobile/gradle/libs.versions.toml`).

- [ServicesBuilder](https://github.com/readium/kotlin-toolkit/blob/3bb9c88d505d43c8e9f8d3b6b30c69927071c7fe/readium/shared/src/main/java/org/readium/r2/shared/publication/Publication.kt)
  does not install ContentService by default.
- [DefaultContentService](https://github.com/readium/kotlin-toolkit/blob/3bb9c88d505d43c8e9f8d3b6b30c69927071c7fe/readium/shared/src/main/java/org/readium/r2/shared/publication/services/content/ContentService.kt)
  and `HtmlResourceContentIterator.Factory` are public experimental APIs; opt in locally.
- [TtsNavigatorFactory](https://github.com/readium/kotlin-toolkit/blob/3bb9c88d505d43c8e9f8d3b6b30c69927071c7fe/readium/navigators/media/tts/src/main/java/org/readium/navigator/media/tts/TtsNavigatorFactory.kt)
  first checks for the service, then `createNavigator(listener, initialLocator, initialPreferences)`
  checks that iteration yields an utterance and initializes the engine, returning `Try`.
  Its docs contain older shorthand examples; use the pinned source signature.
- Android foreground TTS uses `org.readium.kotlin-toolkit:readium-navigator-media-tts:3.3.0`
  and declares the Android 11+ `android.intent.action.TTS_SERVICE` query.

iOS is pinned to Readium Swift **3.9.0**, revision
`de07026e9f825a5791f27a7ac4cd6bb1a784ab8d`; `verify_readium.py` owns the pin check.

- [PublicationSpeechSynthesizer](https://github.com/readium/swift-toolkit/blob/de07026e9f825a5791f27a7ac4cd6bb1a784ab8d/Sources/Navigator/TTS/PublicationSpeechSynthesizer.swift)
  is in the already-linked ReadiumNavigator product. It defaults to AVTTSEngine and accepts a
  Publication and starting Locator. `canSpeak` only checks whether the ContentService exists.
- Its configuration has language and voice, **not** a rate field. The
  [AVTTSEngine delegate](https://github.com/readium/swift-toolkit/blob/de07026e9f825a5791f27a7ac4cd6bb1a784ab8d/Sources/Navigator/TTS/AVTTSEngine.swift)
  can set `AVSpeechUtterance.rate` when constructing an utterance.
- The existing `IosReflowableReaderSession` owns the opened Publication and visual navigator.
  `firstVisibleElementLocator()` and the public decoration API are the integration points.

## Gate before opening foreground controls

The first Android foreground slice now borrows the Reader's open Publication and uses the existing
shared session controller. Explicit play starts at the current visual Reader Locator; pause/resume
retains the native session, and stop, background, Reader exit and book replacement end that playback.
The toolbar has play/pause and stop controls with English/Chinese failure feedback. Returning to the
foreground, restoring Reader or opening another book does not start speech.

This slice deliberately does not follow speech positions or persist them. Visual Reader remains the
sole durable position writer, and speech callbacks only update transient shared TTS state. The
position-owner/follow-page gates below remain for any future follow-page feature. There is no new
MediaSession, notification, foreground service, voice-management screen or background-playback path.
The platform's configured system engine is used; actual voice availability, audible output and
offline capability must be verified separately, never inferred from service existence or Playing.

### Android foreground paragraph feedback

Fresh play uses the visual navigator's `firstVisibleElementLocator()` CSS anchor. A resource-relative
progression alone cannot start the pinned Android HTML iterator mid-chapter. This is a block-level
start; it does not promise an exact glyph offset within a paragraph spanning several pages.

The next bounded slice uses the public `DecorableNavigator.applyDecorations` API and built-in
Highlight style, in the separate transient `reader-tts` group. Playing highlights the spoken block;
Paused retains it. Stop/background/end/failure clear it; Reader teardown discards its observer and
native fragment, and another book starts without it. Speech positions never navigate the visual
Reader or write its durable position report. A paragraph outside the current viewport is not brought
into view automatically. This does not add word highlighting, page following or a second progress
owner. Rendered DOM, pause/stop/background/book replacement and unchanged durable progress require
runtime verification; compilation alone is insufficient.

2026-10-02 local physical Xiaomi/API 31 verification: seven foreground TTS tests plus the existing
TXT Reader regression passed (8/8), including rendered highlight geometry, exact block selector,
pause/stop/foreground return/book replacement and unchanged full visual/durable progress. A normal
UI check on an existing offline EPUB captured the highlighted paragraph while paused and its removal
after Stop. This establishes paragraph feedback on that device, not word accuracy or offline voice.

Stop invalidates a pending setup token immediately. SDK initialization is allowed to return its
owned navigator, which is closed without playing when the token is obsolete. Setup completion may
depend on the system engine; this is not a bounded initialization-time or heap-leak guarantee.

SDK source-level cleanup observations are not reproduced application failures and do not block this
public-API integration. No SDK fork, reflection or copied player implementation is used.

1. Prove a nonempty spoken unit and valid native Locator using the actual Publication content
   iterator, without collecting the whole book. Service existence and successful compilation do
   not prove speech availability. Surface reading/engine failures separately from normal end.
2. Use one explicit Reader position owner before allowing TTS follow-page navigation. Both native
   visual navigator callbacks currently persist progress; a follow-page callback must not overwrite
   a newer spoken Locator. Background/close flush must use that same owner and matching presentation.
3. Reject callbacks from stopped, replaced, closed and previous-account sessions. Do not automatically
   speak on opening, authorization recovery, foreground return or process restoration.
4. Keep the first gate foreground-only. iOS already declares background audio, so an explicit
   lifecycle pause is necessary. Existing audiobook playback and TTS must not independently claim
   system media controls or audio focus.
5. Validate actual system voice availability and language on physical devices. Default platform
   engine does not establish that every installed voice works offline. Do not silently select a
   remote/custom engine or send book text to a new provider.

## Accuracy and failure limits that tests must preserve

- HTML ContentIterator materializes a resource. The original-file and chapter contracts stay intact;
  this is not proof of streaming within a chapter or low first-utterance latency for long TXT.
- The fixed iOS iterator starts from a CSS selector or approximates an element from progression.
  Restarting from an utterance Locator can repeat the containing paragraph. In-session resume
  restarts the current utterance. Do not promise word-exact or sentence-exact cold restoration.
- On iOS the synthesizer logs content iteration/tokenizer failures and can report `stopped`, which
  is also a normal-end state. Android's HTML iterator can log read failure and return no elements.
  Neither event alone proves the book is finished; never infer 100% or mark read from it.
- Chinese, emoji, combining marks and multi-sentence paragraphs need real engine tests. iOS word
  callbacks involve Foundation ranges; sentence-level evidence must not be advertised as word accuracy.

## Verification for this change

`ReadiumTtsContentInstrumentedTest` adds actual TXT/FB2/MOBI ContentService checks: text and Unicode,
paragraph restart using an emitted Locator, reading-order hrefs, unchanged originals and absence of
derived files. A separate two-resource AZW3 probe supplies a distinct final-container body and
requests only the first content element: its canary and recorded resource reads check that extraction
uses the final transformed bytes without traversing later resources. These are unexecuted device
tests until run on physical Android; ordinary nonempty-text/href assertions alone do not prove the
decorator boundary.

The full-iteration helpers deliberately use small fixtures and do not establish bounded first-speech
latency or memory. Even the first-element resource-read probe does not measure within-resource
materialization, tokenizer cost or actual speech onset. Long single-resource TXT/MOBI and real-engine
latency/memory remain explicit M0/foreground gates; no timing or bounded-memory pass is claimed.

Suggested existing entry point, after building the test target with the repository toolchain:

```sh
cd apps/mobile
./gradlew :androidApp:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=com.ermao.library.features.reader.infrastructure.ReadiumTtsContentInstrumentedTest
```

Select and verify a physical device as required by the mobile guide. A connected-test invocation
without an attached device, source inspection, shared tests or an iOS pin check is not acceptance.
Cloud Linux verification on 2026-09-30, using the project's Gradle tasks and pinned dependencies:

- `:shared:testAndroidHostTest --tests '*TtsSessionControllerTest'`: 16 passed.
- `:androidApp:testDebugUnitTest` filtered to `TxtReadiumPublicationFactoryTest` and
  `Fb2ReadiumPublicationFactoryTest`: 26 TXT decoding cases and 11 FB2 parser cases passed.
  These existing parser tests do not execute the ContentService iterator.
- `:androidApp:assembleDebug` and `:androidApp:assembleDebugAndroidTest`: passed, including
  compilation of all four new ContentService instrumented tests. Building their APK is not running them.
- `:androidApp:lintDebug` and `:mobiCore:lintDebug`: passed with the repository's existing
  `warningsAsErrors` configuration.

An authorized supplemental runtime attempt used official Android Emulator 37.1.11 and the AOSP
API 36 x86_64 image, revision 2. Without KVM, software mode booted and installed both APKs, but
instrumentation returned `Process crashed` before any test began. Android's log identifies a process
startup ANR; several system apps also suffered startup ANRs. A recovery using the initialized AVD
and installed APKs had the same outcome, with guest CPU usage remaining at 99–100%. Neither attempt
produced a ContentService assertion result. The emulator was stopped; no assertion, startup timeout
or system security setting was relaxed to obtain a pass.

There is no attached physical Android/iOS device and no Xcode. The ContentService runtime gate
remains unverified and requires a usable Android runtime; speech, performance and physical-device
acceptance also remain open. No iOS compilation or runtime test was performed.
