import type { ReaderPreferences } from '@shuku/reader-core';
import { normalizeLocale } from '../../../../i18n/config';
import { translateMessage } from '../../../../i18n/messages';
import type { FoliateBook } from './foliate-book';
import { hardenEpubIframe, sanitizeEpubDocument } from './epub-security';
import {
  applyEpubDocumentSpacing,
  applyEpubThemeSnapshot,
  type EpubViewportLayout
} from './epub-theme';
import { fallbackEpubFont } from './epub-font';
import {
  ContinuousOffsetIndex,
  continuousPlaceholderRanges,
  estimatedContinuousHeight,
  type ContinuousItemState
} from './continuous-layout';

export type ReflowableContinuousTarget = {
  index: number;
  fraction?: number;
  anchor?: (document: Document) => unknown;
};

export type ReflowableContinuousRelocate = {
  index: number;
  fraction: number;
  cfi?: string;
};

type ReflowableContinuousOptions = {
  container: HTMLElement;
  book: FoliateBook;
  preferences: ReaderPreferences;
  viewportLayout: EpubViewportLayout;
  onDocument: (document: Document) => void | (() => void);
  onRelocate: (location: ReflowableContinuousRelocate) => void;
  onExternalLink: (href: string) => void;
};

type TextLocator = Readonly<{
  path: readonly number[];
  offset: number;
}>;

type ReflowableViewportAnchor = Readonly<{
  logicalIndex: number;
  fraction: number;
  viewportOffset: number;
  text?: TextLocator;
}>;

type SectionRecord = {
  logicalIndex: number;
  index: number;
  state: ContinuousItemState;
  element: HTMLElement | null;
  iframe: HTMLIFrameElement | null;
  measuredHeight: number;
  resizeObserver: ResizeObserver | null;
  loadSequence: number;
  loadPromise: Promise<void> | null;
  loadController: AbortController | null;
  requestGeneration: number;
  resourceHeld: boolean;
  appliedPreferenceRevision: number;
  documentCleanup: (() => void) | null;
};

type PlaceholderGap = {
  start: number;
  end: number;
  element: HTMLElement;
};

type CaretRangeDocument = Document & {
  caretRangeFromPoint?: (x: number, y: number) => Range | null;
};

const PLACEHOLDER_RANGE_SIZE = 256;
const MAX_CONCURRENT_SECTION_LOADS = 2;
const PREFERENCE_BATCH_SIZE = 8;
const READING_LINE_RATIO = 0.25;

function clamp(value: number, minimum = 0, maximum = 1) {
  return Math.max(minimum, Math.min(maximum, value));
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function resolvedTarget(value: unknown): ReflowableContinuousTarget | null {
  if (!isRecord(value) || !Number.isInteger(value.index) || (value.index as number) < 0) return null;
  return {
    index: value.index as number,
    ...(typeof value.fraction === 'number' && Number.isFinite(value.fraction)
      ? { fraction: clamp(value.fraction) }
      : {}),
    ...(typeof value.anchor === 'function' ? { anchor: value.anchor as (document: Document) => unknown } : {})
  };
}

function localizeFailure(document: Document) {
  const locale = normalizeLocale(document.documentElement.lang || globalThis.navigator?.language);
  return {
    message: translateMessage(locale, '本章节加载失败。'),
    retry: translateMessage(locale, '重试本章节')
  };
}

function childNodeIndex(node: Node) {
  const parent = node.parentNode;
  if (!parent) return -1;
  return Array.prototype.indexOf.call(parent.childNodes, node) as number;
}

function nodePath(node: Node, root: Node): number[] | null {
  const path: number[] = [];
  let cursor: Node | null = node;
  while (cursor && cursor !== root) {
    const index = childNodeIndex(cursor);
    if (index < 0) return null;
    path.push(index);
    cursor = cursor.parentNode;
  }
  return cursor === root ? path.reverse() : null;
}

function nodeAtPath(root: Node, path: readonly number[]) {
  let cursor: Node | undefined = root;
  for (const index of path) cursor = cursor?.childNodes[index];
  return cursor ?? null;
}

export class ReflowableContinuousController {
  private readonly container: HTMLElement;
  private readonly book: FoliateBook;
  private readonly root: HTMLElement;
  private readonly records: SectionRecord[];
  private readonly heightIndex: ContinuousOffsetIndex;
  private readonly weightIndex: ContinuousOffsetIndex;
  private readonly sectionToLogicalIndex = new Map<number, number>();
  private readonly gaps: PlaceholderGap[] = [];
  private readonly onDocument: ReflowableContinuousOptions['onDocument'];
  private readonly onRelocate: ReflowableContinuousOptions['onRelocate'];
  private readonly onExternalLink: ReflowableContinuousOptions['onExternalLink'];
  private preferences: ReaderPreferences;
  private viewportLayout: EpubViewportLayout;
  private currentLogicalIndex = 0;
  private destroyed = false;
  private scrollFrame: number | null = null;
  private relocateTimer: ReturnType<typeof setTimeout> | null = null;
  private preferenceTimer: ReturnType<typeof setTimeout> | null = null;
  private preferenceQueue: number[] = [];
  private preferenceRevision = 0;
  private loadGeneration = 0;
  private activeLoads = 0;
  private readonly loadWaiters: Array<() => void> = [];
  private readonly loadingRecords = new Set<SectionRecord>();
  private lastScrollTop = 0;
  private stableAnchor: ReflowableViewportAnchor | null = null;

  constructor(options: ReflowableContinuousOptions) {
    this.container = options.container;
    this.book = options.book;
    this.preferences = options.preferences;
    this.viewportLayout = options.viewportLayout;
    this.onDocument = options.onDocument;
    this.onRelocate = options.onRelocate;
    this.onExternalLink = options.onExternalLink;
    const document = this.container.ownerDocument;
    this.root = document.createElement('div');
    this.root.dataset.reflowableContinuous = 'true';
    Object.assign(this.root.style, {
      height: '100%',
      overflowX: 'hidden',
      overflowY: 'auto',
      overscrollBehavior: 'contain',
      scrollBehavior: 'auto',
      width: '100%'
    });

    const hasLinearSection = this.book.sections.some((section) => section.linear !== 'no' && section.linear !== false);
    const records: SectionRecord[] = [];
    this.book.sections.forEach((section, index) => {
      if (hasLinearSection && (section.linear === 'no' || section.linear === false)) return;
      const logicalIndex = records.length;
      const measuredHeight = estimatedContinuousHeight(section.size, this.container.clientHeight);
      this.sectionToLogicalIndex.set(index, logicalIndex);
      records.push({
        logicalIndex,
        index,
        state: 'placeholder',
        element: null,
        iframe: null,
        measuredHeight,
        resizeObserver: null,
        loadSequence: 0,
        loadPromise: null,
        loadController: null,
        requestGeneration: 0,
        resourceHeld: false,
        appliedPreferenceRevision: 0,
        documentCleanup: null
      });
    });
    this.records = records;
    this.heightIndex = new ContinuousOffsetIndex(records.map((record) => record.measuredHeight));
    this.weightIndex = new ContinuousOffsetIndex(records.map((record) => Math.max(1, this.book.sections[record.index]?.size ?? 1)));
    continuousPlaceholderRanges(records.length, PLACEHOLDER_RANGE_SIZE).forEach(({ start, end }) => {
      const gap = this.createGap(start, end);
      this.gaps.push(gap);
      this.root.append(gap.element);
    });
    this.root.addEventListener('scroll', this.handleScroll, { passive: true });
    this.container.replaceChildren(this.root);
  }

  async open(target: ReflowableContinuousTarget) {
    await this.goTo(target, false);
    this.emitRelocate();
  }

  async goTo(target: ReflowableContinuousTarget, emit = true) {
    const logicalIndex = this.logicalIndexForSection(target.index);
    this.currentLogicalIndex = logicalIndex;
    const desired = [logicalIndex, logicalIndex + 1];
    const generation = this.beginLoadCycle(desired);
    await this.requestLoad(logicalIndex, generation);
    if (this.destroyed || generation !== this.loadGeneration) return;
    const record = this.records[logicalIndex];
    if (!record) return;
    this.ensureRecordPreferences(record);
    let contentOffset = clamp(target.fraction ?? 0) * Math.max(1, this.heightIndex.valueAt(logicalIndex));
    const document = record.iframe?.contentDocument;
    if (document && target.anchor) {
      try {
        const anchor = target.anchor(document);
        if (isRecord(anchor) && typeof anchor.getBoundingClientRect === 'function') {
          const bounds = anchor.getBoundingClientRect();
          if (isRecord(bounds) && typeof bounds.top === 'number') contentOffset = bounds.top;
        }
      } catch {
        // A damaged publication target falls back to the safe section fraction.
      }
    }
    this.root.scrollTop = Math.max(0, this.recordTop(record) + contentOffset - this.readingLineOffset());
    this.lastScrollTop = this.root.scrollTop;
    this.stableAnchor = this.captureAnchor();
    this.root.dataset.reflowableContinuousCurrent = String(record.index);
    if (record.state === 'ready') void this.requestLoad(logicalIndex + 1, generation);
    if (emit) this.emitRelocate();
  }

  async next() {
    if (this.currentLogicalIndex >= this.records.length - 1) return false;
    await this.goTo({ index: this.records[this.currentLogicalIndex + 1]?.index ?? this.records.length - 1 });
    return true;
  }

  async previous() {
    if (this.currentLogicalIndex <= 0) return false;
    await this.goTo({ index: this.records[this.currentLogicalIndex - 1]?.index ?? 0 });
    return true;
  }

  async goToProgress(progression: number) {
    if (!this.records.length) return;
    const target = clamp(progression) * this.weightIndex.total();
    const logicalIndex = this.weightIndex.indexAtOffset(target);
    const before = this.weightIndex.prefix(logicalIndex);
    const weight = Math.max(1, this.weightIndex.valueAt(logicalIndex));
    await this.goTo({
      index: this.records[logicalIndex]?.index ?? 0,
      fraction: clamp((target - before) / weight)
    });
  }

  async applyPreferences(preferences: ReaderPreferences, viewportLayout: EpubViewportLayout) {
    const anchor = this.stableAnchor ?? this.captureAnchor();
    this.preferences = preferences;
    this.viewportLayout = viewportLayout;
    this.preferenceRevision += 1;
    if (this.preferenceTimer !== null) clearTimeout(this.preferenceTimer);
    const priority = new Set([
      this.currentLogicalIndex - 1,
      this.currentLogicalIndex,
      this.currentLogicalIndex + 1
    ]);
    const priorityRecords = this.records.filter((record) => priority.has(record.logicalIndex) && record.state === 'ready');
    priorityRecords.forEach((record) => this.applyRecordPreferences(record));
    priorityRecords.forEach((record) => this.updateMeasurement(record));
    this.restoreAnchor(anchor);
    this.preferenceQueue = this.records
      .filter((record) => record.state === 'ready' && !priority.has(record.logicalIndex))
      .map((record) => record.logicalIndex);
    this.schedulePreferenceBatch();
    this.stableAnchor = this.captureAnchor();
    this.emitRelocate();
  }

  resolveHref(href: string) {
    return Promise.resolve(this.book.resolveHref?.(href)).then(resolvedTarget);
  }

  resolveCFI(cfi: string) {
    return Promise.resolve(this.book.resolveCFI?.(cfi)).then(resolvedTarget);
  }

  currentTarget() {
    return {
      index: this.records[this.currentLogicalIndex]?.index ?? 0,
      fraction: this.currentFraction()
    };
  }

  destroy() {
    if (this.destroyed) return;
    this.destroyed = true;
    this.loadGeneration += 1;
    if (this.scrollFrame !== null) cancelAnimationFrame(this.scrollFrame);
    if (this.relocateTimer !== null) clearTimeout(this.relocateTimer);
    if (this.preferenceTimer !== null) clearTimeout(this.preferenceTimer);
    this.root.removeEventListener('scroll', this.handleScroll);
    this.records.forEach((record) => {
      record.loadController?.abort();
      record.loadController = null;
      record.resizeObserver?.disconnect();
      record.resizeObserver = null;
      record.documentCleanup?.();
      record.documentCleanup = null;
      record.iframe?.remove();
      record.iframe = null;
      this.releaseSectionResource(record);
    });
    this.loadWaiters.splice(0).forEach((resume) => resume());
    this.root.remove();
  }

  private readonly handleScroll = () => {
    if (this.destroyed || this.scrollFrame !== null) return;
    this.scrollFrame = requestAnimationFrame(() => {
      this.scrollFrame = null;
      const scrollTop = this.root.scrollTop;
      const direction = Math.sign(scrollTop - this.lastScrollTop);
      this.lastScrollTop = scrollTop;
      const logicalIndex = this.logicalIndexAtReadingLine();
      const record = this.records[logicalIndex];
      if (record) {
        const changed = logicalIndex !== this.currentLogicalIndex;
        this.currentLogicalIndex = logicalIndex;
        this.root.dataset.reflowableContinuousCurrent = String(record.index);
        this.ensureRecordPreferences(record);
        if (changed || record.state === 'placeholder') {
          const desired = [logicalIndex, logicalIndex + 1, ...(direction < 0 ? [logicalIndex - 1] : [])];
          const generation = this.beginLoadCycle(desired);
          void this.loadReadingNeighborhood(logicalIndex, generation, direction);
        }
      }
      this.stableAnchor = this.captureAnchor();
      if (this.relocateTimer !== null) clearTimeout(this.relocateTimer);
      this.relocateTimer = setTimeout(() => {
        this.relocateTimer = null;
        this.emitRelocate();
      }, 180);
    });
  };

  private beginLoadCycle(indices: readonly number[]) {
    const generation = ++this.loadGeneration;
    indices.forEach((index) => {
      const record = this.records[index];
      if (record) record.requestGeneration = generation;
    });
    this.loadingRecords.forEach((record) => {
      if (record.state === 'loading' && record.requestGeneration !== generation) record.loadController?.abort();
    });
    return generation;
  }

  private async loadReadingNeighborhood(logicalIndex: number, generation: number, direction: number) {
    await this.requestLoad(logicalIndex, generation);
    if (this.destroyed || generation !== this.loadGeneration) return;
    if (this.records[logicalIndex]?.state !== 'ready') return;
    void this.requestLoad(logicalIndex + 1, generation);
    if (direction < 0) void this.requestLoad(logicalIndex - 1, generation);
  }

  private requestLoad(logicalIndex: number, generation: number, retry = false): Promise<void> {
    const record = this.records[logicalIndex];
    if (!record || this.destroyed) return Promise.resolve();
    record.requestGeneration = Math.max(record.requestGeneration, generation);
    if (record.state === 'ready') return Promise.resolve();
    if (record.state === 'failed' && !retry) return Promise.resolve();
    if (record.loadPromise) {
      return record.loadPromise.then(async () => {
        if (record.state !== 'placeholder' || !this.isLoadDesired(record)) return;
        await this.requestLoad(logicalIndex, generation, retry);
      });
    }
    if (retry) record.state = 'placeholder';
    const promise = this.loadWhenPermitted(record).finally(() => {
      if (record.loadPromise === promise) record.loadPromise = null;
    });
    record.loadPromise = promise;
    return promise;
  }

  private async loadWhenPermitted(record: SectionRecord) {
    await this.acquireLoadPermit();
    try {
      if (!this.isLoadDesired(record)) return;
      await this.load(record);
    } finally {
      this.loadingRecords.delete(record);
      this.releaseLoadPermit();
    }
  }

  private async acquireLoadPermit() {
    if (this.activeLoads >= MAX_CONCURRENT_SECTION_LOADS) {
      await new Promise<void>((resolve) => this.loadWaiters.push(resolve));
    }
    this.activeLoads += 1;
  }

  private releaseLoadPermit() {
    this.activeLoads = Math.max(0, this.activeLoads - 1);
    this.loadWaiters.shift()?.();
  }

  private isLoadDesired(record: SectionRecord) {
    return !this.destroyed && record.requestGeneration === this.loadGeneration;
  }

  private async load(record: SectionRecord) {
    if (record.state === 'ready' || this.destroyed) return;
    const sequence = ++record.loadSequence;
    const controller = new AbortController();
    record.loadController = controller;
    record.state = 'loading';
    this.loadingRecords.add(record);
    const element = this.materialize(record);
    element.dataset.continuousState = 'loading';
    const iframe = this.container.ownerDocument.createElement('iframe');
    iframe.dataset.reflowableContinuousFrame = String(record.index);
    iframe.title = this.titleFor(record.index);
    hardenEpubIframe(iframe);
    Object.assign(iframe.style, {
      border: '0',
      display: 'block',
      height: `${record.measuredHeight}px`,
      width: '100%'
    });
    record.iframe = iframe;
    element.replaceChildren(iframe);
    try {
      const source = await this.book.sections[record.index]?.load();
      if (!source) throw new Error('section-source-unavailable');
      record.resourceHeld = true;
      if (!this.isLoadDesired(record) || sequence !== record.loadSequence) {
        this.discardPendingRecord(record);
        return;
      }
      await this.loadIframe(iframe, source, controller.signal);
      if (!this.isLoadDesired(record) || sequence !== record.loadSequence) {
        this.discardPendingRecord(record);
        return;
      }
      const document = iframe.contentDocument;
      if (!document) throw new Error('section-document-unavailable');
      sanitizeEpubDocument(document);
      applyEpubThemeSnapshot(document, this.preferences, fallbackEpubFont(this.preferences.epub.fontFamily), this.viewportLayout);
      applyEpubDocumentSpacing(document, this.preferences);
      document.documentElement.style.setProperty('overflow', 'hidden', 'important');
      document.body?.style.setProperty('overflow', 'hidden', 'important');
      this.bindScrollBridge(document);
      this.bindLinks(document, record.index);
      record.documentCleanup = this.onDocument(document) ?? null;
      record.state = 'ready';
      record.appliedPreferenceRevision = this.preferenceRevision;
      element.dataset.continuousState = 'ready';
      record.loadController = null;
      const ResizeObserverConstructor = document.defaultView?.ResizeObserver ?? globalThis.ResizeObserver;
      if (ResizeObserverConstructor) {
        record.resizeObserver = new ResizeObserverConstructor(() => this.measure(record));
        record.resizeObserver.observe(document.documentElement);
        if (document.body) record.resizeObserver.observe(document.body);
      }
      document.fonts?.ready.then(() => this.measure(record)).catch(() => undefined);
      document.querySelectorAll('img').forEach((image) => {
        image.addEventListener('load', () => this.measure(record), { once: true });
        image.addEventListener('error', () => this.measure(record), { once: true });
      });
      this.measure(record);
    } catch (reason) {
      if (this.destroyed || controller.signal.aborted || !this.isLoadDesired(record)) {
        this.discardPendingRecord(record);
        return;
      }
      console.warn('reader.continuous-section-load.failed', {
        index: record.index,
        reason: reason instanceof Error ? reason.message : String(reason)
      });
      this.renderFailure(record);
    }
  }

  private loadIframe(iframe: HTMLIFrameElement, source: string, signal: AbortSignal) {
    return new Promise<void>((resolve, reject) => {
      if (signal.aborted) {
        reject(new DOMException('The operation was aborted', 'AbortError'));
        return;
      }
      let settled = false;
      const finish = (action: () => void) => {
        if (settled) return;
        settled = true;
        iframe.removeEventListener('load', onLoad);
        iframe.removeEventListener('error', onError);
        signal.removeEventListener('abort', onAbort);
        action();
      };
      const onLoad = () => finish(resolve);
      const onError = () => finish(() => reject(new Error('section-load-failed')));
      const onAbort = () => finish(() => reject(new DOMException('The operation was aborted', 'AbortError')));
      iframe.addEventListener('load', onLoad, { once: true });
      iframe.addEventListener('error', onError, { once: true });
      signal.addEventListener('abort', onAbort, { once: true });
      iframe.src = source;
    });
  }

  private materialize(record: SectionRecord) {
    if (record.element) return record.element;
    const anchor = this.stableAnchor ?? this.captureAnchor();
    const document = this.container.ownerDocument;
    const element = document.createElement('section');
    element.dataset.reflowableContinuousSection = String(record.index);
    element.dataset.continuousState = record.state;
    Object.assign(element.style, {
      minHeight: `${record.measuredHeight}px`,
      position: 'relative',
      width: '100%'
    });
    const gapIndex = this.gapIndexContaining(record.logicalIndex);
    const gap = this.gaps[gapIndex];
    if (gap) {
      const replacements: Array<PlaceholderGap | HTMLElement> = [];
      const replacementGaps: PlaceholderGap[] = [];
      if (gap.start < record.logicalIndex) {
        const before = this.createGap(gap.start, record.logicalIndex);
        replacements.push(before);
        replacementGaps.push(before);
      }
      replacements.push(element);
      if (record.logicalIndex + 1 < gap.end) {
        const after = this.createGap(record.logicalIndex + 1, gap.end);
        replacements.push(after);
        replacementGaps.push(after);
      }
      gap.element.before(...replacements.map((replacement) => replacement instanceof HTMLElement ? replacement : replacement.element));
      gap.element.remove();
      this.gaps.splice(gapIndex, 1, ...replacementGaps);
    } else {
      const following = this.records.slice(record.logicalIndex + 1).find((candidate) => candidate.element)?.element;
      this.root.insertBefore(element, following ?? null);
    }
    record.element = element;
    this.restoreAnchor(anchor);
    return element;
  }

  private discardPendingRecord(record: SectionRecord) {
    record.loadSequence += 1;
    record.loadController?.abort();
    record.loadController = null;
    record.resizeObserver?.disconnect();
    record.resizeObserver = null;
    record.documentCleanup?.();
    record.documentCleanup = null;
    record.iframe?.remove();
    record.iframe = null;
    this.releaseSectionResource(record);
    record.state = 'placeholder';
    this.dematerialize(record);
  }

  private dematerialize(record: SectionRecord) {
    const element = record.element;
    if (!element) return;
    const anchor = this.stableAnchor ?? this.captureAnchor();
    const following = element.nextSibling;
    element.remove();
    record.element = null;
    const gap = this.createGap(record.logicalIndex, record.logicalIndex + 1);
    this.root.insertBefore(gap.element, following);
    const insertionIndex = this.gaps.findIndex((candidate) => candidate.start > record.logicalIndex);
    const gapIndex = insertionIndex >= 0 ? insertionIndex : this.gaps.length;
    this.gaps.splice(gapIndex, 0, gap);
    this.mergeGapAt(gapIndex);
    this.restoreAnchor(anchor);
  }

  private createGap(start: number, end: number): PlaceholderGap {
    const element = this.container.ownerDocument.createElement('div');
    element.dataset.reflowableContinuousGap = `${start}:${end}`;
    element.setAttribute('aria-hidden', 'true');
    Object.assign(element.style, {
      height: `${this.heightIndex.range(start, end)}px`,
      minHeight: '1px',
      pointerEvents: 'none',
      width: '100%'
    });
    return { start, end, element };
  }

  private mergeGapAt(index: number) {
    let currentIndex = index;
    const current = this.gaps[currentIndex];
    const previous = this.gaps[currentIndex - 1];
    if (current && previous && previous.end === current.start && current.end - previous.start <= PLACEHOLDER_RANGE_SIZE) {
      previous.end = current.end;
      this.updateGap(previous);
      current.element.remove();
      this.gaps.splice(currentIndex, 1);
      currentIndex -= 1;
    }
    const merged = this.gaps[currentIndex];
    const next = this.gaps[currentIndex + 1];
    if (merged && next && merged.end === next.start && next.end - merged.start <= PLACEHOLDER_RANGE_SIZE) {
      merged.end = next.end;
      this.updateGap(merged);
      next.element.remove();
      this.gaps.splice(currentIndex + 1, 1);
    }
  }

  private updateGap(gap: PlaceholderGap) {
    gap.element.dataset.reflowableContinuousGap = `${gap.start}:${gap.end}`;
    gap.element.style.height = `${this.heightIndex.range(gap.start, gap.end)}px`;
  }

  private gapIndexContaining(logicalIndex: number) {
    let start = 0;
    let end = this.gaps.length - 1;
    while (start <= end) {
      const middle = Math.floor((start + end) / 2);
      const gap = this.gaps[middle];
      if (!gap) return -1;
      if (logicalIndex < gap.start) end = middle - 1;
      else if (logicalIndex >= gap.end) start = middle + 1;
      else return middle;
    }
    return -1;
  }

  private measure(record: SectionRecord) {
    const anchor = this.stableAnchor ?? this.captureAnchor();
    if (!this.updateMeasurement(record)) return;
    this.restoreAnchor(anchor);
    this.stableAnchor = this.captureAnchor();
  }

  private updateMeasurement(record: SectionRecord) {
    const document = record.iframe?.contentDocument;
    if (!document || !record.iframe || !record.element) return false;
    const height = Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight ?? 0, 320);
    if (Math.abs(height - record.measuredHeight) < 1) return false;
    record.measuredHeight = height;
    this.heightIndex.set(record.logicalIndex, height);
    record.iframe.style.height = `${height}px`;
    record.element.style.minHeight = `${height}px`;
    return true;
  }

  private renderFailure(record: SectionRecord) {
    record.documentCleanup?.();
    record.documentCleanup = null;
    record.resizeObserver?.disconnect();
    record.resizeObserver = null;
    record.loadController = null;
    record.iframe?.remove();
    record.iframe = null;
    this.releaseSectionResource(record);
    record.state = 'failed';
    const element = this.materialize(record);
    element.dataset.continuousState = 'failed';
    const document = this.container.ownerDocument;
    const copy = localizeFailure(document);
    const surface = document.createElement('div');
    surface.setAttribute('role', 'alert');
    Object.assign(surface.style, {
      alignItems: 'center',
      display: 'flex',
      flexDirection: 'column',
      gap: '12px',
      justifyContent: 'center',
      minHeight: `${record.measuredHeight}px`
    });
    const message = document.createElement('p');
    message.textContent = copy.message;
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.textContent = copy.retry;
    retry.addEventListener('click', () => {
      const generation = this.beginLoadCycle([record.logicalIndex, record.logicalIndex + 1]);
      void this.requestLoad(record.logicalIndex, generation, true).then(() => {
        if (record.state === 'ready') void this.requestLoad(record.logicalIndex + 1, generation);
      });
    });
    surface.append(message, retry);
    element.replaceChildren(surface);
  }

  private bindScrollBridge(document: Document) {
    let lastTouchY: number | null = null;
    document.addEventListener('wheel', (event) => {
      const delta = Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
      if (!delta) return;
      event.preventDefault();
      this.root.scrollTop += delta;
    }, { capture: true, passive: false });
    document.addEventListener('touchstart', (event) => {
      lastTouchY = event.touches.length === 1 ? event.touches[0]?.clientY ?? null : null;
    }, { capture: true, passive: true });
    document.addEventListener('touchmove', (event) => {
      const touch = event.touches.length === 1 ? event.touches[0] : undefined;
      if (!touch || lastTouchY === null) return;
      const delta = lastTouchY - touch.clientY;
      lastTouchY = touch.clientY;
      if (!delta) return;
      event.preventDefault();
      this.root.scrollTop += delta;
    }, { capture: true, passive: false });
    document.addEventListener('touchend', () => {
      lastTouchY = null;
    }, { capture: true, passive: true });
  }

  private bindLinks(document: Document, index: number) {
    document.addEventListener('click', (event) => {
      if (!isRecord(event.target) || typeof event.target.closest !== 'function') return;
      const target = event.target.closest('a[href]');
      if (!isRecord(target) || typeof target.getAttribute !== 'function') return;
      const rawHref = target.getAttribute('href');
      const externalHref = typeof target.href === 'string' ? target.href : rawHref;
      if (typeof rawHref !== 'string' || !rawHref || !externalHref) return;
      event.preventDefault();
      event.stopPropagation();
      const sectionResolved = this.book.sections[index]?.resolveHref?.(rawHref);
      void Promise.resolve(sectionResolved ?? this.book.resolveHref?.(rawHref)).then((candidate) => {
        const resolved = resolvedTarget(candidate);
        if (resolved) void this.goTo(resolved);
        else this.onExternalLink(externalHref);
      });
    }, { capture: true });
  }

  private applyRecordPreferences(record: SectionRecord) {
    const document = record.iframe?.contentDocument;
    if (!document || record.appliedPreferenceRevision === this.preferenceRevision) return;
    applyEpubThemeSnapshot(document, this.preferences, fallbackEpubFont(this.preferences.epub.fontFamily), this.viewportLayout);
    applyEpubDocumentSpacing(document, this.preferences);
    record.appliedPreferenceRevision = this.preferenceRevision;
  }

  private ensureRecordPreferences(record: SectionRecord) {
    if (record.state !== 'ready' || record.appliedPreferenceRevision === this.preferenceRevision) return;
    const anchor = this.stableAnchor ?? this.captureAnchor();
    this.applyRecordPreferences(record);
    this.updateMeasurement(record);
    this.restoreAnchor(anchor);
    this.stableAnchor = this.captureAnchor();
  }

  private schedulePreferenceBatch() {
    if (this.destroyed || !this.preferenceQueue.length) return;
    const revision = this.preferenceRevision;
    this.preferenceTimer = setTimeout(() => {
      this.preferenceTimer = null;
      if (this.destroyed || revision !== this.preferenceRevision) return;
      const anchor = this.stableAnchor ?? this.captureAnchor();
      this.preferenceQueue.splice(0, PREFERENCE_BATCH_SIZE).forEach((logicalIndex) => {
        const record = this.records[logicalIndex];
        if (!record || record.state !== 'ready') return;
        this.applyRecordPreferences(record);
        this.updateMeasurement(record);
      });
      this.restoreAnchor(anchor);
      this.stableAnchor = this.captureAnchor();
      this.schedulePreferenceBatch();
    }, 16);
  }

  private logicalIndexAtReadingLine() {
    return Math.max(0, this.heightIndex.indexAtOffset(this.root.scrollTop + this.readingLineOffset()));
  }

  private currentFraction() {
    const logicalIndex = this.currentLogicalIndex;
    const readingLine = this.root.scrollTop + this.readingLineOffset();
    return clamp((readingLine - this.heightIndex.prefix(logicalIndex)) / Math.max(1, this.heightIndex.valueAt(logicalIndex)));
  }

  private emitRelocate() {
    const record = this.records[this.currentLogicalIndex];
    const section = record ? this.book.sections[record.index] : undefined;
    this.onRelocate({
      index: record?.index ?? 0,
      fraction: this.overallProgress(),
      ...(typeof section?.cfi === 'string' ? { cfi: section.cfi } : {})
    });
  }

  private overallProgress() {
    const weight = Math.max(1, this.weightIndex.valueAt(this.currentLogicalIndex));
    return clamp((this.weightIndex.prefix(this.currentLogicalIndex) + weight * this.currentFraction()) / Math.max(1, this.weightIndex.total()));
  }

  private logicalIndexForSection(sectionIndex: number) {
    const target = Math.floor(sectionIndex);
    const exact = this.sectionToLogicalIndex.get(target);
    if (exact !== undefined) return exact;
    let start = 0;
    let end = this.records.length;
    while (start < end) {
      const middle = Math.floor((start + end) / 2);
      if ((this.records[middle]?.index ?? Number.POSITIVE_INFINITY) < target) start = middle + 1;
      else end = middle;
    }
    return Math.min(start, Math.max(0, this.records.length - 1));
  }

  private captureAnchor(): ReflowableViewportAnchor | null {
    if (!this.records.length) return null;
    const viewportOffset = this.readingLineOffset();
    const absoluteOffset = this.root.scrollTop + viewportOffset;
    const logicalIndex = Math.max(0, this.heightIndex.indexAtOffset(absoluteOffset));
    const record = this.records[logicalIndex];
    const localOffset = Math.max(0, absoluteOffset - this.heightIndex.prefix(logicalIndex));
    const fraction = clamp(localOffset / Math.max(1, this.heightIndex.valueAt(logicalIndex)));
    const text = record ? this.captureTextLocator(record, localOffset) : null;
    return {
      logicalIndex,
      fraction,
      viewportOffset,
      ...(text ? { text } : {})
    };
  }

  private restoreAnchor(anchor: ReflowableViewportAnchor | null) {
    if (!anchor || this.destroyed) return;
    const record = this.records[anchor.logicalIndex];
    if (!record) return;
    const textOffset = anchor.text ? this.textOffset(record, anchor.text) : null;
    const localOffset = textOffset ?? anchor.fraction * Math.max(1, this.heightIndex.valueAt(anchor.logicalIndex));
    this.root.scrollTop = Math.max(0, this.recordTop(record) + localOffset - anchor.viewportOffset);
  }

  private captureTextLocator(record: SectionRecord, localOffset: number): TextLocator | null {
    const document = record.iframe?.contentDocument;
    const root = document?.body ?? document?.documentElement;
    if (!document || !root) return null;
    const x = Math.max(1, Math.min(document.documentElement.clientWidth - 1, document.documentElement.clientWidth * 0.5));
    const y = Math.max(1, Math.min(record.measuredHeight - 1, localOffset));
    const position = document.caretPositionFromPoint?.(x, y);
    let node = position?.offsetNode ?? null;
    let offset = position?.offset ?? 0;
    if (!node) {
      const range = (document as CaretRangeDocument).caretRangeFromPoint?.(x, y);
      node = range?.startContainer ?? null;
      offset = range?.startOffset ?? 0;
    }
    if (!node) return null;
    const path = nodePath(node, root);
    return path ? { path, offset } : null;
  }

  private textOffset(record: SectionRecord, locator: TextLocator) {
    const document = record.iframe?.contentDocument;
    const root = document?.body ?? document?.documentElement;
    if (!document || !root) return null;
    const node = nodeAtPath(root, locator.path);
    if (!node) return null;
    const maximumOffset = node.nodeType === Node.TEXT_NODE ? node.textContent?.length ?? 0 : node.childNodes.length;
    const range = document.createRange();
    try {
      range.setStart(node, Math.max(0, Math.min(maximumOffset, locator.offset)));
      range.collapse(true);
      const bounds = range.getBoundingClientRect();
      return Number.isFinite(bounds.top) ? bounds.top : null;
    } catch {
      return null;
    }
  }

  private recordTop(record: SectionRecord) {
    return record.element?.offsetTop ?? this.heightIndex.prefix(record.logicalIndex);
  }

  private readingLineOffset() {
    return Math.max(0, this.root.clientHeight) * READING_LINE_RATIO;
  }

  private titleFor(index: number) {
    const section = this.book.sections[index];
    return typeof section?.id === 'string' ? section.id : `Section ${index + 1}`;
  }

  private releaseSectionResource(record: SectionRecord) {
    if (!record.resourceHeld) return;
    record.resourceHeld = false;
    try {
      this.book.sections[record.index]?.unload?.();
    } catch (reason) {
      console.warn('reader.continuous-section-release.failed', {
        index: record.index,
        reason: reason instanceof Error ? reason.message : String(reason)
      });
    }
  }
}
