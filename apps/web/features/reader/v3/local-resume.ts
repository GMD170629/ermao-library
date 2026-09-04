import type { ReaderPositionReport } from '@shuku/reader-core';
import type { ReaderV5PendingMutation, ReaderV5ProgressSnapshot } from '../../../lib/reader/v5-wire';

export type V5StartupResumeDecision = {
  position: ReaderPositionReport | null;
  source: 'direct-target' | 'local-pending' | 'server' | 'start';
};

/** v5 startup is an explicit priority, never a timestamp/revision merge. */
export function resolveV5StartupResume(input: {
  hasDirectTarget?: boolean;
  directPosition: ReaderPositionReport | null;
  pending: ReaderV5PendingMutation | null;
  serverSnapshot: ReaderV5ProgressSnapshot | null;
}): V5StartupResumeDecision {
  if (input.hasDirectTarget || input.directPosition) return { position: input.directPosition, source: 'direct-target' };
  if (input.pending) return { position: input.pending.position, source: 'local-pending' };
  if (input.serverSnapshot) return { position: input.serverSnapshot.position, source: 'server' };
  return { position: null, source: 'start' };
}
