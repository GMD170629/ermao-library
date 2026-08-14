import assert from 'node:assert/strict';
import test from 'node:test';
import { isReaderKeyboardControlTarget, projectReaderFramePointer, ReaderKeyboardNavigationController, readerFramePointerIntent, readerKeyIntent, readerPinchZoom, readerPointerIntent, readerPointerIntentInViewport, readerSwipeIntent } from './input-router';

function deferred() {
  let resolve!: () => void;
  const promise = new Promise<void>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

async function flush() {
  await Promise.resolve();
  await Promise.resolve();
}

test('maps keyboard navigation for both reading directions', () => {
  assert.equal(readerKeyIntent({ key: 'ArrowLeft', shiftKey: false }, 'ltr'), 'previous');
  assert.equal(readerKeyIntent({ key: 'ArrowLeft', shiftKey: false }, 'rtl'), 'next');
  assert.equal(readerKeyIntent({ key: ' ', shiftKey: true }, 'ltr'), 'previous');
  assert.equal(readerKeyIntent({ key: 'End', shiftKey: false }, 'ltr'), 'last');
  assert.equal(readerKeyIntent({ key: 'ArrowRight', shiftKey: false }, 'ltr', { keyboardPageTurn: false }), null);
  assert.equal(readerKeyIntent({ key: 'Escape', shiftKey: false }, 'ltr', { keyboardPageTurn: false }), 'escape');
  assert.equal(readerKeyIntent({ key: 'AudioVolumeUp', shiftKey: false }, 'ltr', { keyboardPageTurn: false, volumeKeyPageTurn: true }), 'previous');
});

test('keeps page keys working after toolbar focus while preserving native controls', () => {
  const toolbarButton = {
    closest: (selector: string) => selector.includes('button') ? toolbarButton : null
  } as unknown as EventTarget;
  const textInput = {
    closest: (selector: string) => selector.includes('input') ? textInput : null
  } as unknown as EventTarget;

  assert.equal(isReaderKeyboardControlTarget(toolbarButton, 'ArrowRight'), false);
  assert.equal(isReaderKeyboardControlTarget(toolbarButton, 'PageDown'), false);
  assert.equal(isReaderKeyboardControlTarget(toolbarButton, ' '), true);
  assert.equal(isReaderKeyboardControlTarget(textInput, 'ArrowRight'), true);
});

test('bounds key auto-repeat to one rendered turn and stops it on keyup', async () => {
  const controller = new ReaderKeyboardNavigationController();
  const firstTurn = deferred();
  const turns: string[] = [];

  assert.equal(controller.keyDown({ key: 'ArrowRight', repeat: false }, () => {
    turns.push('initial');
    return firstTurn.promise;
  }), true);
  assert.equal(controller.keyDown({ key: 'ArrowRight', repeat: true }, () => turns.push('queued-repeat')), false);
  controller.keyUp({ key: 'ArrowRight' });
  firstTurn.resolve();
  await flush();

  assert.equal(controller.keyDown({ key: 'ArrowRight', repeat: true }, () => turns.push('after-release')), false);
  assert.deepEqual(turns, ['initial']);
});

test('allows a held key to repeat after the previous turn settles', async () => {
  const controller = new ReaderKeyboardNavigationController();
  const turns: string[] = [];

  assert.equal(controller.keyDown({ key: 'ArrowRight', repeat: false }, () => turns.push('initial')), true);
  await flush();
  assert.equal(controller.keyDown({ key: 'ArrowRight', repeat: true }, () => turns.push('repeat')), true);
  controller.keyUp({ key: 'ArrowRight' });
  await flush();

  assert.equal(controller.keyDown({ key: 'ArrowRight', repeat: true }, () => turns.push('after-release')), false);
  assert.deepEqual(turns, ['initial', 'repeat']);
});

test('supports reversed and disabled tap zones', () => {
  assert.equal(readerPointerIntent(50, 100, 1000, 800, 'ltr', 'reversed'), 'next');
  assert.equal(readerPointerIntent(950, 100, 1000, 800, 'ltr', 'reversed'), 'previous');
  assert.equal(readerPointerIntent(50, 100, 1000, 800, 'ltr', 'disabled'), 'toggle-controls');
  assert.equal(readerPointerIntent(950, 100, 1000, 800, 'rtl', 'disabled'), 'toggle-controls');
});

test('maps pointer zones without vertical dead strips', () => {
  assert.equal(readerPointerIntent(500, 400, 1000, 800, 'ltr'), 'toggle-controls');
  assert.equal(readerPointerIntent(500, 40, 1000, 800, 'ltr'), 'toggle-controls');
  assert.equal(readerPointerIntent(500, 760, 1000, 800, 'ltr'), 'toggle-controls');
  assert.equal(readerPointerIntent(50, 100, 1000, 800, 'ltr'), 'previous');
  assert.equal(readerPointerIntent(950, 100, 1000, 800, 'ltr'), 'next');
  assert.equal(readerPointerIntent(950, 100, 1000, 800, 'rtl'), 'previous');
  assert.equal(readerPointerIntent(50, 100, 1000, 800, 'rtl'), 'next');
  assert.equal(readerPointerIntent(330, 100, 1000, 800, 'ltr'), 'toggle-controls');
  assert.equal(readerPointerIntent(670, 100, 1000, 800, 'ltr'), 'toggle-controls');
  assert.equal(readerPointerIntent(-1, 100, 1000, 800, 'ltr'), null);
  assert.equal(readerPointerIntent(500, 801, 1000, 800, 'ltr'), null);
});

test('projects an expanded EPUB iframe pointer into the visible reader viewport', () => {
  const viewport = { left: 100, top: 40, width: 900, height: 800 };
  const frame = { left: -3500, top: 40, width: 45000, height: 800 };

  assert.equal(readerFramePointerIntent(3690, 400, 45000, 800, frame, viewport, 'ltr'), 'previous');
  assert.equal(readerFramePointerIntent(4050, 400, 45000, 800, frame, viewport, 'ltr'), 'toggle-controls');
  assert.equal(readerFramePointerIntent(4410, 400, 45000, 800, frame, viewport, 'ltr'), 'next');
  assert.equal(readerFramePointerIntent(3690, 400, 45000, 800, frame, viewport, 'rtl'), 'next');
  assert.equal(readerFramePointerIntent(4410, 400, 45000, 800, frame, viewport, 'rtl'), 'previous');
});

test('projects a shifted MOBI iframe using the frame layout box coordinate space', () => {
  const viewport = { left: 0, top: 0, width: 2560, height: 1352 };
  const frame = { left: -2095, top: 48, width: 6750, height: 1256 };

  assert.equal(readerFramePointerIntent(3375, 628, 6750, 1256, frame, viewport, 'ltr'), 'toggle-controls');
  assert.equal(readerFramePointerIntent(4270, 628, 6750, 1256, frame, viewport, 'ltr'), 'next');
  assert.equal(readerFramePointerIntent(2480, 628, 6750, 1256, frame, viewport, 'ltr'), 'previous');
});

test('keeps EPUB drag coordinates stable while the continuous iframe moves', () => {
  const frameAtPointerDown = { left: 100, top: 40, width: 1000, height: 800 };
  const frameAfterScroll = { left: 60, top: 40, width: 1000, height: 800 };

  const start = projectReaderFramePointer(300, 400, 1000, 800, frameAtPointerDown);
  const moved = projectReaderFramePointer(320, 400, 1000, 800, frameAfterScroll);

  assert.deepEqual(start, { clientX: 400, clientY: 440 });
  assert.deepEqual(moved, { clientX: 380, clientY: 440 });
  assert.equal(moved!.clientX - start!.clientX, -20);
  assert.equal(projectReaderFramePointer(10, 10, 0, 800, frameAtPointerDown), null);
});

test('maps top-level pointer coordinates against an offset reader viewport', () => {
  const viewport = { left: 100, top: 40, width: 900, height: 800 };
  assert.equal(readerPointerIntentInViewport(190, 60, viewport, 'ltr'), 'previous');
  assert.equal(readerPointerIntentInViewport(550, 440, viewport, 'ltr'), 'toggle-controls');
  assert.equal(readerPointerIntentInViewport(910, 820, viewport, 'ltr'), 'next');
  assert.equal(readerPointerIntentInViewport(550, 20, viewport, 'ltr'), null);
});

test('only accepts intentional horizontal swipes', () => {
  assert.equal(readerSwipeIntent(-120, 12, 240, 'ltr'), 'next');
  assert.equal(readerSwipeIntent(120, 12, 240, 'rtl'), 'next');
  assert.equal(readerSwipeIntent(20, 4, 120, 'ltr'), null);
  assert.equal(readerSwipeIntent(-100, 95, 120, 'ltr'), null);
});

test('PDF pinch zoom is bounded and proportional', () => {
  assert.equal(readerPinchZoom(1, 100, 150), 1.5);
  assert.equal(readerPinchZoom(2, 100, 200), 2.4);
  assert.equal(readerPinchZoom(1, 100, 20), 0.6);
});
