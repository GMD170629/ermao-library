import { type ReaderKind, type ReaderLocation, type ReflowableFormat } from '@shuku/reader-core';
import { progressLocationsMatch, type ExactProgressRecord, type PendingProgressMutation, type PendingVsServerDecision, type ReaderProgressSnapshot } from '../../../lib/reader';

export type LocalResumeContext = { readerKind: ReaderKind; sourceFormat?: ReflowableFormat };
export type StartupResumeDecision = { location: ReaderLocation | null; percent: number; source: 'direct-target' | 'local-exact' | 'server'; localExact: ExactProgressRecord | null };

export function decidePendingVsServer(input: {
  localExact: ExactProgressRecord | null;
  pending: PendingProgressMutation | null;
  serverSnapshot: ReaderProgressSnapshot | null;
}): PendingVsServerDecision {
  const pending = input.pending;
  if (!pending) return { kind: 'server', snapshot: input.serverSnapshot, discardPending: false };
  const validLocal = input.localExact
    && input.localExact.workId === pending.workId
    && input.localExact.volumeId === pending.volumeId
    && progressLocationsMatch(input.localExact.locator, pending.locator)
    ? input.localExact : null;
  if (!validLocal) {
    return { kind: 'server', snapshot: input.serverSnapshot, discardPending: true };
  }
  if (!input.serverSnapshot || pending.baseRevision === input.serverSnapshot.revision) {
    return { kind: 'local-pending', pending, localExact: validLocal };
  }
  if (input.serverSnapshot.revision > pending.baseRevision) {
    return { kind: 'requires-choice', pending, localExact: validLocal, server: input.serverSnapshot };
  }
  return { kind: 'local-pending', pending, localExact: validLocal };
}

export function resolveStartupResume(input: {
  localExact: ExactProgressRecord | null;
  serverSnapshot: ReaderProgressSnapshot | null;
  context: LocalResumeContext;
  serverLocation: ReaderLocation | null;
  serverPercent: number;
  hasDirectTarget: boolean;
}): StartupResumeDecision {
  if (input.hasDirectTarget) return { location: input.serverLocation, percent: input.serverPercent, source: 'direct-target', localExact: null };
  return { location: input.serverLocation, percent: input.serverPercent, source: 'server', localExact: null };
}
