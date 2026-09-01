import {
  READER_SCROLL_BOUNDARY_EPSILON_CSS_PIXELS,
  READER_SCROLL_VIEWPORT_FRACTION,
  readerScrollAxis,
  type ReaderPageTurnDirection,
  type ReaderReadingProgression,
  type ReaderWritingMode
} from '@shuku/reader-core';

type RtlScrollLeftModel = 'negative' | 'reverse' | 'default';

type ScrollViewportMetrics = Readonly<{
  current: number;
  maximum: number;
  viewport: number;
}>;

type ScrollViewportPlan = Readonly<{
  atBoundary: boolean;
  target: number;
}>;

function bounded(value: number, maximum: number) {
  return Math.max(0, Math.min(Math.max(0, maximum), value));
}

export function normalizedHorizontalScrollOffset(
  rawOffset: number,
  maximum: number,
  progression: ReaderReadingProgression,
  model: RtlScrollLeftModel
) {
  if (progression === 'ltr') return bounded(rawOffset, maximum);
  if (model === 'negative') return bounded(-rawOffset, maximum);
  if (model === 'reverse') return bounded(rawOffset, maximum);
  return bounded(maximum - rawOffset, maximum);
}

export function rawHorizontalScrollOffset(
  normalizedOffset: number,
  maximum: number,
  progression: ReaderReadingProgression,
  model: RtlScrollLeftModel
) {
  const offset = bounded(normalizedOffset, maximum);
  if (progression === 'ltr') return offset;
  if (model === 'negative') return -offset;
  if (model === 'reverse') return offset;
  return maximum - offset;
}

export function createScrollViewportPlan(
  metrics: ScrollViewportMetrics,
  direction: ReaderPageTurnDirection
): ScrollViewportPlan {
  const maximum = Math.max(0, metrics.maximum);
  const current = bounded(metrics.current, maximum);
  const atBoundary = direction === 'previous'
    ? current <= READER_SCROLL_BOUNDARY_EPSILON_CSS_PIXELS
    : maximum - current <= READER_SCROLL_BOUNDARY_EPSILON_CSS_PIXELS;
  if (atBoundary) return { atBoundary: true, target: current };
  const delta = Math.max(0, metrics.viewport) * READER_SCROLL_VIEWPORT_FRACTION;
  return {
    atBoundary: false,
    target: bounded(current + (direction === 'next' ? delta : -delta), maximum)
  };
}

function detectRtlScrollLeftModel(document: Document): RtlScrollLeftModel {
  const outer = document.createElement('div');
  const inner = document.createElement('div');
  outer.dir = 'rtl';
  outer.style.cssText = 'position:absolute;left:-10000px;top:-10000px;width:4px;height:1px;overflow:scroll;visibility:hidden;';
  inner.style.width = '8px';
  inner.style.height = '1px';
  outer.append(inner);
  document.body.append(outer);
  let model: RtlScrollLeftModel;
  if (outer.scrollLeft > 0) {
    model = 'default';
  } else {
    outer.scrollLeft = 1;
    model = outer.scrollLeft === 0 ? 'negative' : 'reverse';
  }
  outer.remove();
  return model;
}

async function waitForScrollSettle(window: Window, root: Element, axis: 'vertical' | 'horizontal') {
  const offset = () => axis === 'vertical' ? root.scrollTop : root.scrollLeft;
  const startedAt = window.performance.now();
  let previous = offset();
  let stableFrames = 0;
  while (window.performance.now() - startedAt < 600) {
    await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
    const current = offset();
    if (Math.abs(current - previous) <= READER_SCROLL_BOUNDARY_EPSILON_CSS_PIXELS) stableFrames += 1;
    else stableFrames = 0;
    previous = current;
    if (window.performance.now() - startedAt >= 120 && stableFrames >= 3) return;
  }
}

export async function advanceScrollViewport(input: Readonly<{
  document: Document;
  direction: ReaderPageTurnDirection;
  writingMode: ReaderWritingMode;
  readingProgression: ReaderReadingProgression;
  animated: boolean;
}>): Promise<'moved' | 'boundary' | 'unavailable'> {
  const root = input.document.scrollingElement;
  const window = input.document.defaultView;
  if (!root || !window) return 'unavailable';
  const axis = readerScrollAxis(input.writingMode);
  const horizontalMaximum = Math.max(0, root.scrollWidth - window.innerWidth);
  const verticalMaximum = Math.max(0, root.scrollHeight - window.innerHeight);
  const rtlModel = input.readingProgression === 'rtl' && axis === 'horizontal'
    ? detectRtlScrollLeftModel(input.document)
    : 'reverse';
  const current = axis === 'vertical'
    ? root.scrollTop
    : normalizedHorizontalScrollOffset(root.scrollLeft, horizontalMaximum, input.readingProgression, rtlModel);
  const plan = createScrollViewportPlan({
    current,
    maximum: axis === 'vertical' ? verticalMaximum : horizontalMaximum,
    viewport: axis === 'vertical' ? window.innerHeight : window.innerWidth
  }, input.direction);
  if (plan.atBoundary) return 'boundary';
  const behavior: ScrollBehavior = input.animated ? 'smooth' : 'auto';
  if (axis === 'vertical') {
    root.scrollTo({ top: plan.target, behavior });
  } else {
    root.scrollTo({
      left: rawHorizontalScrollOffset(plan.target, horizontalMaximum, input.readingProgression, rtlModel),
      behavior
    });
  }
  await waitForScrollSettle(window, root, axis);
  return 'moved';
}

export async function positionScrollResourceEdge(input: Readonly<{
  document: Document;
  direction: ReaderPageTurnDirection;
  writingMode: ReaderWritingMode;
  readingProgression: ReaderReadingProgression;
}>) {
  const root = input.document.scrollingElement;
  const window = input.document.defaultView;
  if (!root || !window) return false;
  const axis = readerScrollAxis(input.writingMode);
  const maximum = axis === 'vertical'
    ? Math.max(0, root.scrollHeight - window.innerHeight)
    : Math.max(0, root.scrollWidth - window.innerWidth);
  const target = input.direction === 'previous' ? maximum : 0;
  const rtlModel = input.readingProgression === 'rtl' && axis === 'horizontal'
    ? detectRtlScrollLeftModel(input.document)
    : 'reverse';
  const position = () => {
    if (axis === 'vertical') {
      root.scrollTo({ top: target, behavior: 'auto' });
      return root.scrollTop;
    }
    root.scrollTo({
      left: rawHorizontalScrollOffset(target, maximum, input.readingProgression, rtlModel),
      behavior: 'auto'
    });
    return normalizedHorizontalScrollOffset(
      root.scrollLeft,
      maximum,
      input.readingProgression,
      rtlModel
    );
  };
  const startedAt = window.performance.now();
  let stableFrames = 0;
  while (window.performance.now() - startedAt < 600) {
    const current = position();
    stableFrames = Math.abs(current - target) <= READER_SCROLL_BOUNDARY_EPSILON_CSS_PIXELS
      ? stableFrames + 1
      : 0;
    if (window.performance.now() - startedAt >= 400 && stableFrames >= 3) return true;
    await new Promise<void>((resolve) => window.requestAnimationFrame(() => resolve()));
  }
  return false;
}
