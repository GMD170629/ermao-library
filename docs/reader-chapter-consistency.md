# Unified chapter parsing

For a fresh installation, Book Detail and each Reader derive their table of contents
from the same original resource through `packages/reader-core/native/chapters`.
The C99 core owns chapter recognition, title text, nesting, filtering and final
preorder identity. Python, Web WASM and native adapters supply decoded UTF-8 text,
source-order XML events or the existing MOBI parser's navigation nodes. Archive,
XML, encoding, safety and renderer operations stay in the existing adapters.

Keep this implementation bounded: TXT recognizes headings; EPUB reads authored
NAV/NCX, FB2 reads authored section/title structure, and MOBI consumes the existing
parser's navigation nodes. Do not infer extra chapters from rendering positions or
add a general publication parser. Adapters resolve resources and render targets;
they do not repeat chapter filtering, title normalization or parent validation.
The XML core retains one source-ordered text representation. Web FB2 renders the
resource events already collected by its existing parser; it does not reconstruct
resource boundaries or paragraph indexes. No migration or compatibility layer is
needed for this fresh-install contract.

## Result contract

- `chapter-N` is the zero-based final preorder key within one resource. A database
  navigation row is namespaced as `resourceId:chapter-N`.
- A group retains its title and children with no target. It cannot navigate and
  does not contribute to the chapter count.
- No authored or recognized chapters means an empty TOC. Reading order still
  renders the body; it never supplies substitute chapters.
- TXT frontmatter remains readable but is not a chapter. An initial printed
  heading list repeated by the body is not counted again. TXT ranges use bytes in
  the core's normalized UTF-8 text, not UTF-16 or platform character indices.
- TXT chapter resources use `text/chapter-0001.xhtml#heading-000001`, etc.
  Each independent resource has its own `heading-000001` anchor.
- FB2 section targets use the source document's zero-based XML start-element
  ordinal (`chapter-node-N`). Unnamed parents promote their named children in the
  TOC while their body text stays in reading order. Loose body content stays in
  `fb2/body-B-part-P.xhtml` resources at its original position.
- Audio exposes explicit embedded chapters separately from its playable track
  queue. A track without chapters remains playable and contributes no synthetic
  chapter.

Detail links carry `chapterKey`. After opening the verified original, the Reader
resolves this key against its local core result. Unknown keys and group keys cannot
silently select another chapter. Reader presentation carries nullable
`chapter.navigationKey`; detail resolves that key against the resource projection.
Neither the server nor detail inspects the opaque engine Locator. When the engine
does not distinguish multiple chapters in one resource, current chapter stays
unknown rather than being inferred from reading-order index.

There is no migration, legacy chapter-link decoder or alternate chapter parser.
Existing complete-original download, in-memory publication and safety contracts
remain in force. No derived publication is persisted.

## Build and verification

```sh
cmake -S packages/reader-core/native/chapters -B packages/reader-core/native/chapters/build
cmake --build packages/reader-core/native/chapters/build --config Release
ctest --test-dir packages/reader-core/native/chapters/build -C Release --output-on-failure
```

The backend loads `ERMAO_CHAPTER_CORE_LIBRARY` or the local core build. Its Docker
image builds and bundles the shared library. Web uses the existing fixed
Emscripten 3.1.74 convention with `pnpm --dir apps/web build:chapters-wasm` and
`verify:chapters-wasm`; missing artifacts fail explicitly.

`packages/reader-contracts/fixtures/chapters-v1/manifest.json` is the cross-binding
corpus. Verify titles, keys, parents, targets and TXT ranges, then exercise actual
format adapters. Interface tests must also cover direct navigation, empty TOC,
group non-navigation and reported chapter identity. Compilation and fixture
replay do not substitute for browser or physical-device runtime acceptance.

On Windows without an installed Windows SDK, a local portable Zig C compiler can
build the same DLL without a separate implementation:

```powershell
zig cc -std=c99 -O2 -shared -I packages/reader-core/native/chapters/include packages/reader-core/native/chapters/chapters.c -o packages/reader-core/native/chapters/build/ermao_chapters.dll
```

The core has no third-party runtime dependency. Local toolchains and native build
outputs are ignored; the checked-in Web artifact is verified against source before
production builds and tests. Rebuild all consumers together after semantic changes.
