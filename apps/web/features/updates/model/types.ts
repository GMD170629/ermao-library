import type { AppLocale } from '@/i18n/config';

export type StableVersion = `${number}.${number}.${number}`;

export type ReleaseSummary = {
  version: StableVersion;
  tag: `v${StableVersion}`;
  publishedAt: string;
  notesPath: `v${StableVersion}.md`;
  releaseUrl: string;
};

export type ReleaseFeed = {
  schemaVersion: 1;
  repository: 'GMD170629/ermao-library';
  releases: readonly ReleaseSummary[];
};

export type ReleaseFeedState =
  | { status: 'loading' }
  | { status: 'ready'; feed: ReleaseFeed }
  | { status: 'error'; message: string };

export type UpdateStatus =
  | { kind: 'update-available'; latest: ReleaseSummary }
  | { kind: 'current'; latest: ReleaseSummary }
  | { kind: 'development'; latest: ReleaseSummary };

export type LocalizedReleaseNote = {
  locale: AppLocale;
  markdown: string;
};
