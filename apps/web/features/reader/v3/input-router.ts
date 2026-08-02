export type ReaderDirection = 'ltr' | 'rtl';
export type ReaderInputIntent = 'previous' | 'next' | 'first' | 'last' | 'escape' | 'toggle-controls';

export type ReaderViewportRect = {
  left: number;
  top: number;
  width: number;
  height: number;
};

type KeyInput = Pick<KeyboardEvent, 'key' | 'shiftKey'>;

function physicalSideIntent(side: 'left' | 'right', direction: ReaderDirection): 'previous' | 'next' {
  if (direction === 'rtl') return side === 'left' ? 'next' : 'previous';
  return side === 'left' ? 'previous' : 'next';
}

export function isReaderControlTarget(target: EventTarget | null) {
  const element = target as Element | null;
  if (!element || typeof element.closest !== 'function') return false;
  const editable = element.closest('input, textarea, select, button, [contenteditable="true"]');
  return Boolean(editable || element.closest('a, [role="button"], [data-reader-control="true"]'));
}

export function hasActiveTextSelection(selection: Selection | null | undefined) {
  return Boolean(selection && !selection.isCollapsed && selection.toString().trim());
}

export function readerKeyIntent(input: KeyInput, direction: ReaderDirection): ReaderInputIntent | null {
  if (input.key === 'Escape') return 'escape';
  if (input.key === 'ArrowLeft') return physicalSideIntent('left', direction);
  if (input.key === 'ArrowRight') return physicalSideIntent('right', direction);
  if (input.key === 'PageUp' || (input.key === ' ' && input.shiftKey)) return 'previous';
  if (input.key === 'PageDown' || input.key === ' ') return 'next';
  if (input.key === 'Home') return 'first';
  if (input.key === 'End') return 'last';
  return null;
}

export function readerPointerIntent(
  clientX: number,
  clientY: number,
  viewportWidth: number,
  viewportHeight: number,
  direction: ReaderDirection
): ReaderInputIntent | null {
  if (viewportWidth <= 0 || viewportHeight <= 0) return null;
  if (clientX < 0 || clientY < 0 || clientX > viewportWidth || clientY > viewportHeight) return null;
  if (clientX < viewportWidth * 0.33) return physicalSideIntent('left', direction);
  if (clientX > viewportWidth * 0.67) return physicalSideIntent('right', direction);
  return 'toggle-controls';
}

export function readerPointerIntentInViewport(
  clientX: number,
  clientY: number,
  viewport: ReaderViewportRect,
  direction: ReaderDirection
) {
  return readerPointerIntent(
    clientX - viewport.left,
    clientY - viewport.top,
    viewport.width,
    viewport.height,
    direction
  );
}

export function projectReaderFramePointer(
  clientX: number,
  clientY: number,
  frameViewportWidth: number,
  frameViewportHeight: number,
  frame: ReaderViewportRect
) {
  if (frameViewportWidth <= 0 || frameViewportHeight <= 0 || frame.width <= 0 || frame.height <= 0) return null;
  return {
    clientX: frame.left + (clientX * frame.width / frameViewportWidth),
    clientY: frame.top + (clientY * frame.height / frameViewportHeight)
  };
}

export function readerFramePointerIntent(
  clientX: number,
  clientY: number,
  frameViewportWidth: number,
  frameViewportHeight: number,
  frame: ReaderViewportRect,
  viewport: ReaderViewportRect,
  direction: ReaderDirection
) {
  const projected = projectReaderFramePointer(
    clientX,
    clientY,
    frameViewportWidth,
    frameViewportHeight,
    frame
  );
  if (!projected) return null;
  return readerPointerIntentInViewport(projected.clientX, projected.clientY, viewport, direction);
}

export function readerSwipeIntent(deltaX: number, deltaY: number, elapsedMs: number, direction: ReaderDirection): ReaderInputIntent | null {
  if (elapsedMs > 900 || Math.abs(deltaX) < 48 || Math.abs(deltaX) <= Math.abs(deltaY) * 1.15) return null;
  if (direction === 'rtl') return deltaX > 0 ? 'next' : 'previous';
  return deltaX < 0 ? 'next' : 'previous';
}

export function readerPinchZoom(startZoom: number, startDistance: number, currentDistance: number) {
  if (startDistance <= 0 || currentDistance <= 0) return Math.max(0.6, Math.min(2.4, startZoom));
  return Math.max(0.6, Math.min(2.4, startZoom * (currentDistance / startDistance)));
}
