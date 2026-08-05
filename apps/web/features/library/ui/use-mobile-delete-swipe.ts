'use client';

import type { PointerEvent as ReactPointerEvent } from 'react';
import { useRef, useState } from 'react';

type SwipeIntent = 'pending' | 'horizontal' | 'vertical';

type MobileSwipeGesture = {
  bookId: string;
  pointerId: number;
  startX: number;
  startY: number;
  startOffset: number;
  currentOffset: number;
  intent: SwipeIntent;
};

const DELETE_ACTION_WIDTH = 80;
const SWIPE_INTENT_THRESHOLD = 8;
const SWIPE_REVEAL_THRESHOLD = DELETE_ACTION_WIDTH / 2;

export type MobileDeleteSwipeController = Readonly<{
  actionWidth: number;
  begin: (event: ReactPointerEvent<HTMLDivElement>, bookId: string) => void;
  cancel: (event: ReactPointerEvent<HTMLDivElement>) => void;
  close: () => void;
  consumeClick: (bookId: string) => boolean;
  finish: (event: ReactPointerEvent<HTMLDivElement>) => void;
  isActionVisible: (bookId: string) => boolean;
  isDragging: (bookId: string) => boolean;
  move: (event: ReactPointerEvent<HTMLDivElement>) => void;
  offsetFor: (bookId: string) => number;
  reveal: (bookId: string) => void;
}>;

export function useMobileDeleteSwipe(enabled: boolean): MobileDeleteSwipeController {
  const swipeRef = useRef<MobileSwipeGesture | null>(null);
  const suppressedClickRef = useRef<{ bookId: string; until: number } | null>(null);
  const [openBookId, setOpenBookId] = useState<string | null>(null);
  const [activeBookId, setActiveBookId] = useState<string | null>(null);
  const [activeOffset, setActiveOffset] = useState(0);

  function offsetFor(bookId: string) {
    if (activeBookId === bookId) return activeOffset;
    return openBookId === bookId ? -DELETE_ACTION_WIDTH : 0;
  }

  function begin(event: ReactPointerEvent<HTMLDivElement>, bookId: string) {
    if (!enabled || !event.isPrimary || event.button !== 0) return;
    const startOffset = openBookId === bookId ? -DELETE_ACTION_WIDTH : 0;
    if (openBookId !== bookId) setOpenBookId(null);
    swipeRef.current = {
      bookId,
      pointerId: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      startOffset,
      currentOffset: startOffset,
      intent: 'pending'
    };
  }

  function move(event: ReactPointerEvent<HTMLDivElement>) {
    const gesture = swipeRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    const deltaX = event.clientX - gesture.startX;
    const deltaY = event.clientY - gesture.startY;

    if (gesture.intent === 'pending') {
      if (Math.max(Math.abs(deltaX), Math.abs(deltaY)) < SWIPE_INTENT_THRESHOLD) return;
      gesture.intent = Math.abs(deltaX) > Math.abs(deltaY) ? 'horizontal' : 'vertical';
      if (gesture.intent === 'vertical') {
        return;
      }
      setActiveBookId(gesture.bookId);
      setActiveOffset(gesture.startOffset);
      if (event.nativeEvent.isTrusted) event.currentTarget.setPointerCapture(event.pointerId);
    }

    if (gesture.intent !== 'horizontal') return;
    event.preventDefault();
    gesture.currentOffset = Math.max(
      -DELETE_ACTION_WIDTH,
      Math.min(0, gesture.startOffset + deltaX)
    );
    setActiveOffset(gesture.currentOffset);
  }

  function finish(event: ReactPointerEvent<HTMLDivElement>, cancelled = false) {
    const gesture = swipeRef.current;
    if (!gesture || gesture.pointerId !== event.pointerId) return;
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    if (gesture.intent === 'horizontal') {
      suppressedClickRef.current = { bookId: gesture.bookId, until: Date.now() + 500 };
      const shouldReveal = !cancelled && gesture.currentOffset <= -SWIPE_REVEAL_THRESHOLD;
      setOpenBookId(shouldReveal ? gesture.bookId : null);
    }
    swipeRef.current = null;
    setActiveBookId(null);
    setActiveOffset(0);
  }

  function consumeClick(bookId: string) {
    const suppressedClick = suppressedClickRef.current;
    if (suppressedClick?.bookId === bookId && Date.now() <= suppressedClick.until) {
      suppressedClickRef.current = null;
      return false;
    }
    suppressedClickRef.current = null;
    if (openBookId === bookId) {
      setOpenBookId(null);
      return false;
    }
    return true;
  }

  return {
    actionWidth: DELETE_ACTION_WIDTH,
    begin,
    cancel: (event: ReactPointerEvent<HTMLDivElement>) => finish(event, true),
    close: () => setOpenBookId(null),
    consumeClick,
    finish,
    isActionVisible: (bookId: string) => activeBookId === bookId || openBookId === bookId,
    isDragging: (bookId: string) => activeBookId === bookId,
    move,
    offsetFor,
    reveal: (bookId: string) => setOpenBookId(bookId)
  };
}
