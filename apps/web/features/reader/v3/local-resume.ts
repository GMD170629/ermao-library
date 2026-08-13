import { publicationFingerprintsMatch, type ReaderKind, type ReaderLocation, type ReflowableFormat } from '@shuku/reader-core';
import { v4LocationToDomain, type ExactProgressRecord, type ReaderProgressSnapshot } from '../../../lib/reader';

export type LocalResumeContext = { readerKind: ReaderKind; sourceFormat?: ReflowableFormat };
export type StartupResumeDecision = { location: ReaderLocation | null; percent: number; source: 'direct-target' | 'local-exact' | 'server'; localExact: ExactProgressRecord | null };

export function resolveStartupResume(input: {
  localExact: ExactProgressRecord | null;
  serverSnapshot: ReaderProgressSnapshot | null;
  context: LocalResumeContext;
  serverLocation: ReaderLocation | null;
  serverPercent: number;
  hasDirectTarget: boolean;
}): StartupResumeDecision {
  if (input.hasDirectTarget) return { location: input.serverLocation, percent: input.serverPercent, source: 'direct-target', localExact: null };
  const localLocation = input.localExact?.locator
    ? v4LocationToDomain(input.localExact.locator, input.localExact.volumeId, input.context.sourceFormat ?? null)
    : null;
  const localWins = Boolean(input.localExact?.locator && localLocation
    && publicationFingerprintsMatch(input.localExact.locator.publication, input.serverSnapshot?.locator.publication ?? input.localExact.locator.publication)
    && (!input.serverSnapshot || input.localExact.revision >= input.serverSnapshot.revision));
  if (localWins && input.localExact && localLocation) return { location: localLocation, percent: input.localExact.displayPercent ?? input.serverPercent, source: 'local-exact', localExact: input.localExact };
  return { location: input.serverLocation, percent: input.serverPercent, source: 'server', localExact: null };
}
