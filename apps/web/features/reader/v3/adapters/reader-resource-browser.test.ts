import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { readFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import test from 'node:test';
import { chromium, webkit } from '@playwright/test';
import {
  BlobWriter,
  TextReader,
  Uint8ArrayReader,
  ZipWriter
} from '@zip.js/zip.js';
import type { MobiOpenResult } from '../original-publication/mobi-worker-protocol';

type EsbuildBuildOptions = Readonly<{
  stdin: Readonly<{
    contents: string;
    resolveDir: string;
    sourcefile: string;
    loader: 'ts';
  }>;
  bundle: true;
  format: 'esm';
  globalName: string;
  platform: 'browser';
  target: 'es2022';
  define?: Readonly<Record<string, string>>;
  write: false;
}>;

type EsbuildModule = Readonly<{
  build: (options: EsbuildBuildOptions) => Promise<Readonly<{
    outputFiles?: readonly Readonly<{ text: string }>[];
  }>>;
}>;

type BrowserResourceReport = Readonly<{
  epub: Readonly<{
    navigation: unknown;
    encodedChapterText: string;
    damagedSvgError: string | null;
    svgInternalUri: string | null;
    chapterMarkup: string;
    chapterText: string;
    chapterScriptCount: number;
    chapterType: string | null;
    svgMarkup: string;
    svgScriptCount: number;
    svgExternalReferenceCount: number;
    svgRectCount: number;
    svgText: string;
    svgUnknownCount: number;
    svgUnknownAttribute: string | null;
    svgUnknownUri: string | null;
    sourceUnchanged: boolean;
  }>;
  mobi: Readonly<{
    damagedSvgError: string | null;
    chapterMarkup: string;
    chapterText: string;
    chapterScriptCount: number;
    chapterType: string | null;
    svgMarkup: string;
    svgScriptCount: number;
    svgExternalReferenceCount: number;
    svgRectCount: number;
    svgText: string;
    svgUnknownCount: number;
    svgUnknownAttribute: string | null;
    svgUnknownUri: string | null;
    sourceUnchanged: boolean;
  }>;
}>;

const webRoot = path.resolve(import.meta.dirname, '../../../..');
const chapterArtifactRoot = path.resolve(webRoot, 'public/vendor/chapter-core');
const testRequire = createRequire(import.meta.url);

async function buildReaderBundle(): Promise<string> {
  const esbuildPath = testRequire.resolve('esbuild', { paths: [testRequire.resolve('tsx')] });
  const esbuild = await import(pathToFileURL(esbuildPath).href) as unknown as EsbuildModule;
  const result = await esbuild.build({
    stdin: {
      contents: [
        "import { openReadiumPublication } from './features/reader/v3/adapters/readium-publication';",
        '(globalThis as unknown as { __openReadiumPublication: typeof openReadiumPublication }).__openReadiumPublication = openReadiumPublication;'
      ].join('\n'),
      resolveDir: webRoot,
      sourcefile: 'reader-resource-browser-entry.ts',
      loader: 'ts'
    },
    bundle: true,
    format: 'esm',
    globalName: '__readerResourceBrowserBundle',
    platform: 'browser',
    target: 'es2022',
    define: {
      'import.meta.url': '"http://localhost/reader-resource-browser.js"',
      'process.env.NEXT_PUBLIC_BASE_PATH': '""'
    },
    write: false
  });
  const bundle = result.outputFiles?.[0]?.text;
  if (!bundle) throw new Error('READER_BROWSER_BUNDLE_EMPTY');
  return bundle;
}

function base64(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString('base64');
}

async function epubBytes(navigation: 'nav' | 'ncx' = 'nav'): Promise<Uint8Array> {
  const writer = new ZipWriter(new BlobWriter('application/epub+zip'), { useWebWorkers: false });
  await writer.add('mimetype', new TextReader('application/epub+zip'), { level: 0 });
  await writer.add(
    'META-INF/container.xml',
    new TextReader('<?xml version="1.0"?><container><rootfiles><rootfile full-path="OPS/content.opf"/></rootfiles></container>'),
    { level: 0 }
  );
  await writer.add(
    'OPS/content.opf',
    new TextReader([
      '<package version="3.0">',
      '<metadata><title>Browser fixture</title></metadata>',
      '<manifest>',
      '<item id="chapter" href="text/chapter.xhtml" media-type="application/x-future-chapter"/>',
      '<item id="encoded-chapter" href="text/encoded.xhtml" media-type="application/xhtml+xml"/>',
      '<item id="nav" href="Navigation/nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>',
      '<item id="ncx" href="Navigation/toc.ncx" media-type="application/future-navigation"/>',
      '<item id="svg" href="images/asset.svg" media-type="image/svg+xml"/>',
      '<item id="damaged-svg" href="images/damaged.svg" media-type="image/svg+xml; charset=utf-8"/>',
      '<item id="fragment-svg" href="images/fragment.svg" media-type="image/svg+xml"/>',
      '</manifest>',
      '<spine toc="ncx"><itemref idref="chapter"/><itemref idref="encoded-chapter"/></spine>',
      '</package>'
    ].join('')),
    { level: 0 }
  );
  await writer.add('OPS/Navigation/nav.xhtml', new TextReader(
    `<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops"><body>
    <nav epub:type="${navigation === 'nav' ? 'toc' : 'landmarks'}"><ol>
    <li><span>Part 😀</span><ol><li><a href="../text/chapter.xhtml#chapter-body">Chapter</a>
    <ol><li><a href="../text/chapter.xhtml#section">Section</a></li></ol></li>
    <li><a href="#self">Navigation section</a></li><li><a href="missing.xhtml">Missing</a></li></ol></li>
    </ol></nav><section id="self">Body</section></body></html>`
  ), { level: 0 });
  await writer.add('OPS/Navigation/toc.ncx', new TextReader(
    '<ncx><navMap><navPoint><navLabel><text>NCX chapter</text></navLabel><content src="../text/chapter.xhtml#chapter-body"/>'
    + '<navPoint><navLabel><text>NCX section</text></navLabel><content src="../text/chapter.xhtml#section"/></navPoint>'
    + '</navPoint></navMap></ncx>'
  ), { level: 0 });
  await writer.add(
    'OPS/text/chapter.xhtml',
    new TextReader([
      '<?xml version="1.0"?>',
      '<html xmlns="http://www.w3.org/1999/xhtml"><body>',
      '<p id="chapter-body">Unknown MIME chapter body</p>',
      '<img src="../images/damaged.svg"/>',
      '<script>window.__shouldNotRun = true;</script>',
      '</body></html>'
    ].join('')),
    { level: 0 }
  );
  await writer.add(
    'OPS/text/encoded.xhtml',
    new Uint8ArrayReader(Uint8Array.from([
      ...new TextEncoder().encode('<?xml version="1.0" encoding="windows-1251"?><html xmlns="http://www.w3.org/1999/xhtml"><body><p>'),
      0xcf, 0xf0, 0xe8, 0xe2, 0xe5, 0xf2,
      ...new TextEncoder().encode('</p></body></html>')
    ])),
    { level: 0 }
  );
  await writer.add(
    'OPS/images/asset.svg',
    new TextReader([
      '<svg xmlns="http://www.w3.org/2000/svg" xmlns:booklink="http://www.w3.org/1999/xlink">',
      '<script>window.__svgShouldNotRun = true;</script>',
      '<foreignObject><div>remove active content</div></foreignObject>',
      '<rect x="1" y="2" width="3" height="4"/>',
      '<text x="2" y="3">SVG text remains</text>',
      '<image href="https://example.invalid/remote.svg"/>',
      '<image href="future-resource:asset.svg"/>',
      '<image id="internal-image" booklink:href="fragment.svg"/>',
      '<future-shape data-preserve="yes">unknown SVG remains</future-shape>',
      '</svg>'
    ].join('')),
    { level: 0 }
  );
  await writer.add('OPS/images/damaged.svg', new TextReader('<svg><path></svg>'), { level: 0 });
  await writer.add('OPS/images/fragment.svg', new TextReader('<svg xmlns="http://www.w3.org/2000/svg"><rect width="4" height="4"/></svg>'), { level: 0 });
  return new Uint8Array(await (await writer.close()).arrayBuffer());
}

const mobiChapter = new TextEncoder().encode([
  '<html><body>',
  '<p id="chapter-body">Unknown MIME MOBI chapter body</p>',
  '<img src="damaged.svg"/>',
  '<script>window.__shouldNotRun = true;</script>',
  '</body></html>'
].join(''));

const mobiSvg = new TextEncoder().encode([
  '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">',
  '<script>window.__svgShouldNotRun = true;</script>',
  '<foreignObject><div>remove active content</div></foreignObject>',
  '<rect x="1" y="2" width="3" height="4"/>',
  '<text x="2" y="3">MOBI SVG text remains</text>',
  '<image href="https://example.invalid/remote.svg"/>',
  '<image href="future-resource:asset.svg"/>',
  '<future-shape data-preserve="yes">unknown SVG remains</future-shape>',
  '</svg>'
].join(''));

const damagedMobiSvg = new TextEncoder().encode('<svg><path></svg>');

const mobiResult: MobiOpenResult = {
  title: 'Browser MOBI fixture',
  language: 'en',
  readingOrder: [1],
  toc: [{ title: 'Chapter', resourceIndex: 1, fragment: null, parentIndex: null }],
  resources: [
    {
      index: 1,
      category: 0,
      sourceName: 'chapter.xhtml',
      mediaType: 'application/x-future-chapter',
      decodedLength: mobiChapter.byteLength
    },
    {
      index: 2,
      category: 1,
      sourceName: 'images/asset.svg',
      mediaType: 'image/svg+xml; charset=utf-8',
      decodedLength: mobiSvg.byteLength
    },
    { index: 3, category: 1, sourceName: 'damaged.svg', mediaType: 'image/svg+xml', decodedLength: damagedMobiSvg.byteLength },
    { index: 4, category: 1, sourceName: 'unknown.bin', mediaType: '', decodedLength: 0
    }
  ]
};

function browserEvaluationSource(): string {
  return `
    const decodeBase64 = (value) => Uint8Array.from(atob(value), (character) => character.charCodeAt(0));
    const equalBytes = (left, right) => left.byteLength === right.byteLength
      && left.every((value, index) => value === right[index]);
    const parseSvg = (bytes) => {
      const markup = new TextDecoder().decode(bytes);
      const document = new DOMParser().parseFromString(markup, 'image/svg+xml');
      if (document.querySelector('parsererror')) throw new Error('TEST_SVG_PARSE_FAILED');
      const attributes = [...document.querySelectorAll('*')].flatMap((element) => [...element.attributes]);
      const externalReferences = attributes.filter((attribute) =>
        !attribute.name.toLowerCase().startsWith('xmlns')
        && /^(?:https?:|data:|file:)/iu.test(attribute.value)
      );
      const unknownElement = document.querySelector('future-shape');
      const unknownImage = [...document.querySelectorAll('image')]
        .find((element) => element.getAttribute('href')?.startsWith('future-resource:'));
      return {
        svgMarkup: markup,
        svgScriptCount: document.querySelectorAll('script').length,
        svgExternalReferenceCount: externalReferences.length,
        svgRectCount: document.querySelectorAll('rect').length,
        svgText: document.querySelector('text')?.textContent ?? '',
        svgUnknownCount: document.querySelectorAll('future-shape').length,
        svgUnknownAttribute: unknownElement?.getAttribute('data-preserve') ?? null,
        svgUnknownUri: unknownImage?.getAttribute('href') ?? null,
        svgInternalUri: document.querySelector('#internal-image')?.getAttributeNS('http://www.w3.org/1999/xlink', 'href') ?? null
      };
    };
    const parseChapter = (bytes, type) => {
      const markup = new TextDecoder().decode(bytes);
      const document = new DOMParser().parseFromString(markup, 'text/html');
      return {
        chapterMarkup: markup,
        chapterText: document.body?.textContent ?? '',
        chapterScriptCount: document.querySelectorAll('script').length,
        chapterType: type ?? null
      };
    };
    const readLink = async (publication, link) => new Uint8Array(await publication.publication.get(link).read());
    const open = globalThis.__openReadiumPublication;
    if (typeof open !== 'function') throw new Error('TEST_OPEN_READER_PUBLICATION_MISSING');

    const epubSource = decodeBase64(input.epubBase64);
    const epubOriginal = epubSource.slice();
    const epubPublication = await open(
      new Blob([epubSource], { type: 'application/octet-stream' }),
      'epub',
      'Browser EPUB fixture',
      'ltr',
      'horizontal'
    );
    let epub;
    try {
      const chapterLink = epubPublication.publication.readingOrder.items[0];
      const encodedChapterLink = epubPublication.publication.readingOrder.items[1];
      const svgLink = epubPublication.publication.resources?.items.find((link) => link.href === 'OPS/images/asset.svg');
      if (!chapterLink || !encodedChapterLink || !svgLink) throw new Error('TEST_EPUB_RESOURCES_MISSING');
      const encodedChapterText = parseChapter(await readLink(epubPublication, encodedChapterLink), encodedChapterLink.type).chapterText;
      const chapter = parseChapter(
        await readLink(epubPublication, chapterLink),
        chapterLink.type
      );
      const damagedSvg = epubPublication.publication.resources?.items.find((link) => link.href === 'OPS/images/damaged.svg');
      if (!damagedSvg) throw new Error('TEST_EPUB_DAMAGED_RESOURCE_MISSING');
      let damagedSvgError = null;
      try { await readLink(epubPublication, damagedSvg); }
      catch (error) { damagedSvgError = error.errorCode ?? error.code ?? error.message; }
      epub = { ...chapter, ...parseSvg(await readLink(epubPublication, svgLink)), navigation: epubPublication.publication.toc?.serialize(), encodedChapterText, damagedSvgError, sourceUnchanged: equalBytes(epubSource, epubOriginal) };
    } finally {
      epubPublication.close();
    }

    const mobiResources = new Map(Object.entries(input.mobiResources)
      .map(([index, value]) => [index, decodeBase64(value)]));
    const mobiOriginals = new Map([...mobiResources].map(([index, bytes]) => [index, bytes.slice()]));
    class OwnedMobiWorker {
      listeners = new Map();
      addEventListener(type, listener) {
        this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
      }
      postMessage(request) {
        const data = request.type === 'open'
          ? { requestId: request.requestId, ok: true, type: 'open', result: input.mobiResult }
          : request.type === 'read'
            ? { requestId: request.requestId, ok: true, type: 'read', bytes: mobiResources.get(String(request.resourceIndex))?.slice().buffer }
            : { requestId: request.requestId, ok: true, type: 'close' };
        queueMicrotask(() => {
          for (const listener of this.listeners.get('message') ?? []) listener({ data });
        });
      }
      terminate() {}
    }
    Object.defineProperty(globalThis, 'Worker', { configurable: true, value: OwnedMobiWorker });
    const mobiPublication = await open(
      new Blob([], { type: 'application/octet-stream' }),
      'mobi',
      'Browser MOBI fixture',
      'ltr',
      'horizontal'
    );
    let mobi;
    try {
      const chapterLink = mobiPublication.publication.readingOrder.items[0];
      const svgLink = mobiPublication.publication.resources?.items.find((link) => link.href === 'mobi/resource-2');
      if (!chapterLink || !svgLink) throw new Error('TEST_MOBI_RESOURCES_MISSING');
      const chapter = parseChapter(
        await readLink(mobiPublication, chapterLink),
        chapterLink.type
      );
      const damagedSvg = mobiPublication.publication.resources?.items.find((link) => link.href === 'mobi/resource-3');
      if (!damagedSvg) throw new Error('TEST_MOBI_DAMAGED_RESOURCE_MISSING');
      let damagedSvgError = null;
      try { await readLink(mobiPublication, damagedSvg); }
      catch (error) { damagedSvgError = error.errorCode ?? error.code ?? error.message; }
      mobi = { ...chapter, ...parseSvg(await readLink(mobiPublication, svgLink)), damagedSvgError, sourceUnchanged: [...mobiResources].every(([index, bytes]) => equalBytes(bytes, mobiOriginals.get(index))) };
    } finally {
      mobiPublication.close();
    }
    return { epub, mobi };
  `;
}

async function runBrowser(
  browserType: typeof chromium,
  bundle: string,
  epubBase64: string,
  mobiResources: Readonly<Record<string, string>>
): Promise<BrowserResourceReport> {
  const browser = await browserType.launch({ headless: true });
  try {
    const page = await browser.newPage();
    const requests: string[] = [];
    page.on('request', (request) => requests.push(request.url()));
    await page.route('http://localhost/**', async (route) => {
      const requestUrl = new URL(route.request().url());
      const artifactName = requestUrl.pathname.split('/vendor/chapter-core/')[1] ?? '';
      const artifactPath = artifactName === 'artifact-manifest.json'
        ? path.join(chapterArtifactRoot, artifactName)
        : artifactName === 'ermao-chapters.mjs'
          ? path.join(chapterArtifactRoot, artifactName)
          : artifactName === 'ermao-chapters.wasm'
            ? path.join(chapterArtifactRoot, artifactName)
            : null;
      if (artifactPath) {
        const body = await readFile(artifactPath);
        const contentType = artifactName.endsWith('.json')
          ? 'application/json'
          : artifactName.endsWith('.wasm')
            ? 'application/wasm'
            : 'text/javascript';
        await route.fulfill({ status: 200, contentType, body });
        return;
      }
      await route.fulfill({
        status: 200,
        contentType: 'text/html',
        body: '<!doctype html><html><body></body></html>'
      });
    });
    await page.goto('http://localhost/');
    await page.addScriptTag({ content: bundle, type: 'module' });
    await page.waitForFunction('typeof globalThis.__openReadiumPublication === "function"');
    const input = {
      epubBase64,
      mobiResources,
      mobiResult
    };
    const report = await page.evaluate(`(async (input) => {\n${browserEvaluationSource()}\n})(${JSON.stringify(input)})`);
    assert.deepEqual(
      requests.filter((url) => (
        !url.startsWith('http://localhost/') && !url.startsWith('blob:')
      )),
      [],
      'resource reads must not make external network requests'
    );
    return report as BrowserResourceReport;
  } finally {
    await browser.close();
  }
}

function assertSanitizedReport(report: BrowserResourceReport): void {
  assert.match(report.epub.encodedChapterText, /Привет/u);
  assert.equal(report.epub.damagedSvgError, 'PUBLICATION_RESOURCE_BLOCKED');
  assert.equal(report.mobi.damagedSvgError, 'PUBLICATION_RESOURCE_BLOCKED');
  assert.match(report.epub.svgInternalUri ?? '', /^blob:/u);
  for (const candidate of [report.epub, report.mobi]) {
    assert.equal(candidate.chapterScriptCount, 0);
    assert.match(candidate.chapterText, /chapter body/iu);
    assert.ok(['application/xhtml+xml', 'application/x-future-chapter'].includes(candidate.chapterType ?? ''));
    assert.equal(candidate.svgScriptCount, 0);
    assert.equal(candidate.svgExternalReferenceCount, 0, candidate.svgMarkup);
    assert.equal(candidate.svgRectCount, 1);
    assert.match(candidate.svgText, /SVG text remains/iu);
    assert.equal(candidate.svgUnknownCount, 1);
    assert.equal(candidate.svgUnknownAttribute, 'yes');
    assert.equal(candidate.svgUnknownUri, 'future-resource:asset.svg');
    assert.equal(candidate.sourceUnchanged, true);
    assert.doesNotMatch(candidate.svgMarkup, /example\.invalid/iu);
    assert.doesNotMatch(candidate.svgMarkup, /<script\b/iu);
  }
}

const mobiBrowserResources = {
    '1': base64(mobiChapter),
    '2': base64(mobiSvg),
    '3': base64(damagedMobiSvg),
    '4': ''
};

test('real Chromium and WebKit preserve core navigation and sanitize resources on first read', async () => {
  const [epub, bundle] = await Promise.all([epubBytes(), buildReaderBundle()]);
  const reports: BrowserResourceReport[] = [];
  reports.push(await runBrowser(chromium, bundle, base64(epub), mobiBrowserResources));
  reports.push(await runBrowser(webkit, bundle, base64(epub), mobiBrowserResources));
  reports.forEach(assertSanitizedReport);
  reports.forEach((report) => assert.deepEqual(report.epub.navigation, [{
    href: '', title: 'Part 😀', type: 'application/xhtml+xml',
    properties: { 'shuku:navigationKey': 'chapter-0' },
    children: [{
      href: 'OPS/text/chapter.xhtml#chapter-body', title: 'Chapter', type: 'application/xhtml+xml',
      properties: { 'shuku:navigationKey': 'chapter-1' },
      children: [{
        href: 'OPS/text/chapter.xhtml#section', title: 'Section', type: 'application/xhtml+xml',
        properties: { 'shuku:navigationKey': 'chapter-2' }
      }]
    }, {
      href: 'OPS/Navigation/nav.xhtml#self', title: 'Navigation section', type: 'application/xhtml+xml',
      properties: { 'shuku:navigationKey': 'chapter-3' }
    }]
  }]));
});

test('real engines ignore landmark NAV and parse the declared unfamiliar-MIME NCX through the core', async () => {
  const [epub, bundle] = await Promise.all([epubBytes('ncx'), buildReaderBundle()]);
  for (const engine of [chromium, webkit]) {
    const report = await runBrowser(engine, bundle, base64(epub), mobiBrowserResources);
    assert.deepEqual(report.epub.navigation, [{
      href: 'OPS/text/chapter.xhtml#chapter-body', title: 'NCX chapter', type: 'application/xhtml+xml',
      properties: { 'shuku:navigationKey': 'chapter-0' },
      children: [{
        href: 'OPS/text/chapter.xhtml#section', title: 'NCX section', type: 'application/xhtml+xml',
        properties: { 'shuku:navigationKey': 'chapter-1' }
      }]
    }]);
  }
});
