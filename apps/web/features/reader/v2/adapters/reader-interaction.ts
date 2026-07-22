import type { ReaderAdapter, ReaderCommand } from '@shuku/reader-core';

export type ReaderAdapterInputIntent =
  | { type: 'command'; command: ReaderCommand }
  | { type: 'toggle-controls' }
  | { type: 'escape' };

export type ReaderAdapterInputHandler = (
  intent: ReaderAdapterInputIntent
) => boolean | void | Promise<boolean | void>;

export type ReaderInteractionPolicy = {
  horizontalPaging: 'shell-discrete' | 'adapter-interactive' | 'none';
};

export interface ReaderInteractiveAdapter extends ReaderAdapter {
  getInteractionPolicy(): ReaderInteractionPolicy;
}

export function isReaderInteractiveAdapter(adapter: ReaderAdapter | null): adapter is ReaderInteractiveAdapter {
  return Boolean(
    adapter
    && 'getInteractionPolicy' in adapter
    && typeof (adapter as ReaderInteractiveAdapter).getInteractionPolicy === 'function'
  );
}
