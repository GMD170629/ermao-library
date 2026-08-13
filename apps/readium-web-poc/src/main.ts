import { EpubNavigator, EpubPreferences, type EpubNavigatorListeners } from '@readium/navigator';
import { getCssSelector, Locator, LocatorLocations, LocatorText, type Publication } from '@readium/shared';
import { fetchPublicationCatalog, openPublication, type PublicationFingerprint } from './api';
import { translate, type Locale, type MessageKey } from './i18n';
import {
  compareLocators,
  locatorSummary,
  parseImportedLocator,
  serializeWebEngineLocator,
  type LocatorComparison
} from './locator';
import './styles.css';

type ProbeState = 'pass' | 'pending' | 'fail';
type ProbeResult = Readonly<{ state: ProbeState; detail: string }>;
type ProbeResults = Readonly<{
  text: ProbeResult;
  css: ProbeResult;
  font: ProbeResult;
  images: ProbeResult;
}>;

const app = document.querySelector<HTMLDivElement>('#app');
if (!app) throw new Error('app_root_missing');

app.innerHTML = `
  <main class="lab">
    <header class="masthead">
      <div>
        <h1 data-i18n="title"></h1>
        <p data-i18n="subtitle"></p>
      </div>
      <div class="masthead-actions">
        <span class="runtime-chip">READIUM TS 2.8.2</span>
        <button id="locale-toggle" type="button" data-i18n="language"></button>
      </div>
    </header>
    <section class="control-strip" aria-label="Reader controls">
      <label class="field publication-field">
        <span data-i18n="publication"></span>
        <select id="publication-select"></select>
      </label>
      <button id="open-publication" type="button" data-i18n="open"></button>
      <span class="divider" aria-hidden="true"></span>
      <button id="previous" type="button" data-i18n="previous" disabled></button>
      <button id="next" type="button" data-i18n="next" disabled></button>
      <div class="segmented" role="group" aria-label="Layout">
        <button id="paginated" type="button" class="is-active" data-i18n="paginated" disabled></button>
        <button id="scroll" type="button" data-i18n="scroll" disabled></button>
      </div>
      <label class="range-field">
        <span>Aa</span>
        <input id="font-size" type="range" min="0.8" max="2" step="0.1" value="1" disabled />
        <output id="font-size-output">1.0×</output>
      </label>
    </section>
    <section class="workspace">
      <aside class="evidence-panel">
        <section>
          <div class="section-heading"><h2 data-i18n="probes"></h2><span id="status-led"></span></div>
          <div id="status-message" class="status-message" data-i18n="loading"></div>
          <dl id="probes" class="probe-list"></dl>
        </section>
        <section>
          <h2 data-i18n="manifest"></h2>
          <pre id="manifest-output" class="manifest-output">—</pre>
        </section>
      </aside>
      <section class="reader-stage" aria-label="Readium publication viewport">
        <div id="reader-container"></div>
        <div id="reader-empty" class="reader-empty">
          <span>RWPM</span>
          <p>libmobi runtime Publication</p>
        </div>
      </section>
      <aside class="locator-panel">
        <section>
          <div class="section-heading">
            <h2 data-i18n="locator"></h2>
            <button id="capture" type="button" data-i18n="capture" disabled></button>
          </div>
          <pre id="current-locator" class="locator-output"></pre>
          <button id="export" type="button" data-i18n="exportLocator" disabled></button>
        </section>
        <section>
          <h2 data-i18n="importLocator"></h2>
          <textarea id="locator-input" spellcheck="false" data-i18n-placeholder="importPlaceholder"></textarea>
          <button id="go-locator" type="button" data-i18n="go" disabled></button>
        </section>
        <section class="comparison-block">
          <h2 data-i18n="comparison"></h2>
          <strong id="precision" data-precision="unverified"></strong>
          <pre id="comparison"></pre>
          <p data-i18n="exactDefinition"></p>
        </section>
      </aside>
    </section>
  </main>
`;

function requiredElement<T extends Element>(selector: string): T {
  const element = document.querySelector<T>(selector);
  if (!element) throw new Error(`element_missing:${selector}`);
  return element;
}

const elements = {
  publicationSelect: requiredElement<HTMLSelectElement>('#publication-select'),
  open: requiredElement<HTMLButtonElement>('#open-publication'),
  previous: requiredElement<HTMLButtonElement>('#previous'),
  next: requiredElement<HTMLButtonElement>('#next'),
  paginated: requiredElement<HTMLButtonElement>('#paginated'),
  scroll: requiredElement<HTMLButtonElement>('#scroll'),
  fontSize: requiredElement<HTMLInputElement>('#font-size'),
  fontSizeOutput: requiredElement<HTMLOutputElement>('#font-size-output'),
  reader: requiredElement<HTMLDivElement>('#reader-container'),
  readerEmpty: requiredElement<HTMLDivElement>('#reader-empty'),
  statusLed: requiredElement<HTMLSpanElement>('#status-led'),
  statusMessage: requiredElement<HTMLDivElement>('#status-message'),
  probes: requiredElement<HTMLDListElement>('#probes'),
  manifest: requiredElement<HTMLPreElement>('#manifest-output'),
  currentLocator: requiredElement<HTMLPreElement>('#current-locator'),
  capture: requiredElement<HTMLButtonElement>('#capture'),
  export: requiredElement<HTMLButtonElement>('#export'),
  input: requiredElement<HTMLTextAreaElement>('#locator-input'),
  go: requiredElement<HTMLButtonElement>('#go-locator'),
  precision: requiredElement<HTMLElement>('#precision'),
  comparison: requiredElement<HTMLPreElement>('#comparison'),
  locale: requiredElement<HTMLButtonElement>('#locale-toggle')
};

let locale: Locale = navigator.language.toLowerCase().startsWith('zh') ? 'zh-CN' : 'en-US';
let activeNavigator: EpubNavigator | null = null;
let activePublication: Publication | null = null;
let activeFingerprint: PublicationFingerprint | undefined;
let currentLocator: Locator | null = null;
let importedLocator: Locator | null = null;
let importedFingerprint: PublicationFingerprint | undefined;
let comparison: LocatorComparison = compareLocators(null, null);
let captureResolver: ((locator: Locator) => void) | null = null;
let captureTimer: number | null = null;

function applyLocale(): void {
  document.documentElement.lang = locale;
  document.querySelectorAll<HTMLElement>('[data-i18n]').forEach((element) => {
    const key = element.dataset.i18n as MessageKey | undefined;
    if (key) element.textContent = translate(locale, key);
  });
  document.querySelectorAll<HTMLElement>('[data-i18n-placeholder]').forEach((element) => {
    const key = element.dataset.i18nPlaceholder as MessageKey | undefined;
    if (key && element instanceof HTMLTextAreaElement) element.placeholder = translate(locale, key);
  });
  renderComparison();
}

function setControlsEnabled(enabled: boolean): void {
  [elements.previous, elements.next, elements.paginated, elements.scroll, elements.capture,
    elements.export, elements.go, elements.fontSize].forEach((element) => {
      element.disabled = !enabled;
    });
}

function callbackNavigation(operation: (callback: (ok: boolean) => void) => void): Promise<boolean> {
  return new Promise((resolve) => operation(resolve));
}

function updateCurrentLocator(locator: Locator): void {
  currentLocator = locator;
  elements.currentLocator.textContent = JSON.stringify(locatorSummary(locator), null, 2);
  comparison = compareLocators(importedLocator, currentLocator, importedFingerprint, activeFingerprint);
  renderComparison();
  const hasExactAnchor = Boolean(getCssSelector(locator.locations) || locator.text?.highlight);
  if (hasExactAnchor && captureResolver) {
    captureResolver(locator);
    captureResolver = null;
    if (captureTimer !== null) window.clearTimeout(captureTimer);
    captureTimer = null;
  }
}

function renderComparison(): void {
  const labelKey: MessageKey = comparison.precision === 'exact-block'
    ? 'exactBlock'
    : comparison.precision === 'approximate-resource'
      ? 'approximate'
      : comparison.precision === 'fallback'
        ? 'fallback'
        : 'unverified';
  elements.precision.textContent = translate(locale, labelKey);
  elements.precision.dataset.precision = comparison.precision;
  elements.comparison.textContent = JSON.stringify(comparison, null, 2);
}

function probeLabel(key: keyof ProbeResults): MessageKey {
  return key === 'text' ? 'probeText' : key === 'css' ? 'probeCss' : key === 'font' ? 'probeFont' : 'probeImages';
}

function renderProbes(results: ProbeResults): void {
  elements.probes.replaceChildren();
  (Object.entries(results) as Array<[keyof ProbeResults, ProbeResult]>).forEach(([key, result]) => {
    const term = document.createElement('dt');
    term.textContent = translate(locale, probeLabel(key));
    const description = document.createElement('dd');
    description.dataset.state = result.state;
    description.textContent = `${translate(locale, result.state)} · ${result.detail}`;
    elements.probes.append(term, description);
  });
}

async function runFrameProbes(frameWindow: Window): Promise<void> {
  const frameDocument = frameWindow.document;
  await frameDocument.fonts.ready;
  const textLength = frameDocument.body?.textContent?.trim().length ?? 0;
  const stylesheets = frameDocument.styleSheets.length;
  const fontProof = frameDocument.querySelector<HTMLElement>('#font-proof');
  const images = Array.from(frameDocument.images);
  const computedFont = fontProof ? frameWindow.getComputedStyle(fontProof).fontFamily : '';
  renderProbes({
    text: { state: textLength > 0 ? 'pass' : 'fail', detail: `${textLength} chars` },
    css: { state: stylesheets > 0 ? 'pass' : 'fail', detail: `${stylesheets} stylesheets` },
    font: fontProof
      ? {
          state: computedFont.includes('Shuku Test Font') && frameDocument.fonts.check('16px "Shuku Test Font"') ? 'pass' : 'fail',
          detail: computedFont || 'font unavailable'
        }
      : { state: 'pending', detail: 'fixture has no font marker' },
    images: images.length > 0
      ? {
          state: images.every((image) => image.complete && image.naturalWidth > 0) ? 'pass' : 'fail',
          detail: `${images.filter((image) => image.complete && image.naturalWidth > 0).length}/${images.length} decoded`
        }
      : { state: 'pending', detail: 'fixture has no image resources' }
  });
}

function listeners(): EpubNavigatorListeners {
  return {
    frameLoaded: (frameWindow) => {
      void runFrameProbes(frameWindow);
    },
    positionChanged: updateCurrentLocator,
    timelineItemChanged: () => undefined,
    tap: () => false,
    click: () => false,
    zoom: () => undefined,
    miscPointer: () => undefined,
    scroll: () => undefined,
    customEvent: () => undefined,
    handleLocator: () => false,
    textSelected: () => undefined,
    contentProtection: () => undefined,
    contextMenu: () => undefined,
    peripheral: () => undefined
  };
}

async function destroyNavigator(): Promise<void> {
  if (activeNavigator) await activeNavigator.destroy();
  activeNavigator = null;
  activePublication = null;
  activeFingerprint = undefined;
  currentLocator = null;
  importedLocator = null;
  importedFingerprint = undefined;
  comparison = compareLocators(null, null);
  elements.reader.replaceChildren();
}

async function openSelectedPublication(): Promise<void> {
  elements.open.disabled = true;
  setControlsEnabled(false);
  elements.statusLed.dataset.state = 'loading';
  elements.statusMessage.textContent = translate(locale, 'loading');
  try {
    await destroyNavigator();
    const opened = await openPublication(elements.publicationSelect.value);
    activePublication = opened.publication;
    activeFingerprint = opened.fingerprint;
    elements.manifest.textContent = JSON.stringify(opened.manifestJson, null, 2);
    activeNavigator = new EpubNavigator(
      elements.reader,
      opened.publication,
      listeners(),
      opened.positions,
      opened.positions[0],
      {
        preferences: { scroll: false, fontSize: Number(elements.fontSize.value) },
        defaults: { optimalLineLength: 66 }
      }
    );
    await activeNavigator.load();
    elements.readerEmpty.hidden = true;
    elements.statusLed.dataset.state = 'ready';
    elements.statusMessage.textContent = translate(locale, 'ready');
    setControlsEnabled(true);
    if (!currentLocator) elements.currentLocator.textContent = translate(locale, 'noLocator');
    renderComparison();
  } catch (error) {
    elements.statusLed.dataset.state = 'error';
    elements.statusMessage.textContent = `${translate(locale, 'error')}: ${error instanceof Error ? error.message : String(error)}`;
    elements.readerEmpty.hidden = false;
  } finally {
    elements.open.disabled = false;
  }
}

async function captureExactLocator(): Promise<Locator> {
  const navigatorInstance = activeNavigator;
  if (!navigatorInstance) throw new Error('navigator_not_ready');
  return new Promise<Locator>((resolve) => {
    captureResolver = resolve;
    navigatorInstance._cframes.forEach((frame) => {
      frame?.msg?.send('first_visible_locator', undefined);
    });
    captureTimer = window.setTimeout(() => {
      captureResolver = null;
      captureTimer = null;
      resolve(captureVisibleBlockLocator(navigatorInstance) ?? navigatorInstance.currentLocator);
    }, 1500);
  });
}

function selectorForElement(element: Element): string {
  if (element.id) return `#${CSS.escape(element.id)}`;
  const parts: string[] = [];
  let current: Element | null = element;
  while (current && current.tagName.toLowerCase() !== 'body') {
    const tag = current.tagName.toLowerCase();
    const parent: Element | null = current.parentElement;
    if (!parent) break;
    const siblings = Array.from(parent.children).filter((sibling) => sibling.tagName === current?.tagName);
    const suffix = siblings.length > 1 ? `:nth-of-type(${siblings.indexOf(current) + 1})` : '';
    parts.unshift(`${tag}${suffix}`);
    current = parent;
  }
  return `body > ${parts.join(' > ')}`;
}

function captureVisibleBlockLocator(navigatorInstance: EpubNavigator): Locator | null {
  const frame = navigatorInstance._cframes.find((candidate) => candidate?.iframe.contentWindow);
  const frameWindow = frame?.iframe.contentWindow;
  if (!frameWindow) return null;
  const blockSelector = 'h1,h2,h3,h4,h5,h6,p,li,pre,blockquote,figcaption,td,th';
  const candidates = Array.from(frameWindow.document.querySelectorAll<HTMLElement>(blockSelector))
    .filter((element) => {
      const rect = element.getBoundingClientRect();
      return Boolean(element.textContent?.trim())
        && rect.bottom > 0
        && rect.right > 0
        && rect.top < frameWindow.innerHeight
        && rect.left < frameWindow.innerWidth;
    })
    .sort((left, right) => {
      const leftRect = left.getBoundingClientRect();
      const rightRect = right.getBoundingClientRect();
      return Math.max(0, leftRect.left) - Math.max(0, rightRect.left)
        || Math.max(0, leftRect.top) - Math.max(0, rightRect.top);
    });
  const element = candidates[0];
  if (!element) return null;
  const base = navigatorInstance.currentLocator;
  return new Locator({
    href: base.href,
    type: base.type,
    title: base.title,
    locations: new LocatorLocations({
      progression: base.locations.progression,
      totalProgression: base.locations.totalProgression,
      position: base.locations.position,
      otherLocations: new Map([['cssSelector', selectorForElement(element)]])
    }),
    text: new LocatorText({ highlight: element.textContent?.trim() })
  });
}

async function submitPreferences(preferences: ConstructorParameters<typeof EpubPreferences>[0]): Promise<void> {
  if (!activeNavigator) return;
  await activeNavigator.submitPreferences(new EpubPreferences(preferences));
}

elements.open.addEventListener('click', () => void openSelectedPublication());
elements.previous.addEventListener('click', () => {
  if (activeNavigator) void callbackNavigation((callback) => activeNavigator?.goBackward(false, callback));
});
elements.next.addEventListener('click', () => {
  if (activeNavigator) void callbackNavigation((callback) => activeNavigator?.goForward(false, callback));
});
elements.paginated.addEventListener('click', () => {
  elements.paginated.classList.add('is-active');
  elements.scroll.classList.remove('is-active');
  void submitPreferences({ scroll: false });
});
elements.scroll.addEventListener('click', () => {
  elements.scroll.classList.add('is-active');
  elements.paginated.classList.remove('is-active');
  void submitPreferences({ scroll: true });
});
elements.fontSize.addEventListener('input', () => {
  elements.fontSizeOutput.value = `${Number(elements.fontSize.value).toFixed(1)}×`;
  void submitPreferences({ fontSize: Number(elements.fontSize.value) });
});
elements.capture.addEventListener('click', () => {
  void captureExactLocator().then(updateCurrentLocator);
});
elements.export.addEventListener('click', () => {
  void captureExactLocator().then((locator) => {
    updateCurrentLocator(locator);
    elements.input.value = serializeWebEngineLocator(locator, activeFingerprint);
    elements.input.focus();
    elements.input.select();
  });
});
elements.go.addEventListener('click', async () => {
  if (!activeNavigator) return;
  try {
    const imported = parseImportedLocator(elements.input.value);
    importedLocator = imported.locator;
    importedFingerprint = imported.fingerprint;
    const target = imported.locator;
    const navigated = await callbackNavigation((callback) => activeNavigator?.go(target, false, callback));
    if (!navigated) throw new Error('locator_navigation_failed');
    const actual = await captureExactLocator();
    updateCurrentLocator(actual);
  } catch (error) {
    elements.statusLed.dataset.state = 'error';
    elements.statusMessage.textContent = `${translate(locale, 'error')}: ${error instanceof Error ? error.message : String(error)}`;
  }
});
elements.locale.addEventListener('click', () => {
  locale = locale === 'zh-CN' ? 'en-US' : 'zh-CN';
  applyLocale();
});

async function bootstrap(): Promise<void> {
  applyLocale();
  renderProbes({
    text: { state: 'pending', detail: '—' },
    css: { state: 'pending', detail: '—' },
    font: { state: 'pending', detail: '—' },
    images: { state: 'pending', detail: '—' }
  });
  const catalog = await fetchPublicationCatalog();
  catalog.forEach(({ id }) => {
    const option = document.createElement('option');
    option.value = id;
    option.textContent = id;
    elements.publicationSelect.append(option);
  });
  const preferred = Array.from(elements.publicationSelect.options).find((option) => option.value === '08-zh-hans.azw3');
  if (preferred) elements.publicationSelect.value = preferred.value;
}

void bootstrap().catch((error) => {
  elements.statusLed.dataset.state = 'error';
  elements.statusMessage.textContent = `${translate(locale, 'error')}: ${error instanceof Error ? error.message : String(error)}`;
});
