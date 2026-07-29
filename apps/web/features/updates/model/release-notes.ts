import type { AppLocale } from '@/i18n/config';
import type { ReleaseFeed, ReleaseSummary, StableVersion, UpdateStatus } from './types';

const stableVersionPattern = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/u;
const repository = 'GMD170629/ermao-library';

export function parseStableVersion(value: unknown): [number, number, number] | null {
  if (typeof value !== 'string') return null;
  const match = stableVersionPattern.exec(value);
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

export function compareStableVersions(left: string, right: string) {
  const leftParts = parseStableVersion(left);
  const rightParts = parseStableVersion(right);
  if (!leftParts || !rightParts) throw new Error('无法比较无效的正式版本号');
  for (let index = 0; index < leftParts.length; index += 1) {
    if (leftParts[index] !== rightParts[index]) return leftParts[index] - rightParts[index];
  }
  return 0;
}

function releaseSummary(value: unknown): ReleaseSummary | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  const candidate = value as Record<string, unknown>;
  const versionParts = parseStableVersion(candidate.version);
  if (!versionParts || typeof candidate.version !== 'string') return null;
  const version = candidate.version as StableVersion;
  const tag = `v${version}` as const;
  const notesPath = `v${version}.md` as const;
  const releaseUrl = `https://github.com/${repository}/releases/tag/${tag}`;
  if (
    candidate.tag !== tag
    || candidate.notesPath !== notesPath
    || candidate.releaseUrl !== releaseUrl
    || typeof candidate.publishedAt !== 'string'
    || Number.isNaN(Date.parse(candidate.publishedAt))
  ) return null;
  return { version, tag, notesPath, releaseUrl, publishedAt: candidate.publishedAt };
}

export function parseReleaseFeed(value: unknown): ReleaseFeed {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('更新清单格式无效');
  const candidate = value as Record<string, unknown>;
  if (candidate.schemaVersion !== 1 || candidate.repository !== repository || !Array.isArray(candidate.releases)) {
    throw new Error('更新清单格式无效');
  }
  const releases = candidate.releases.map(releaseSummary);
  if (releases.length === 0 || releases.some((release) => release === null)) throw new Error('更新清单包含无效版本');
  const typedReleases = releases as ReleaseSummary[];
  const versions = new Set<string>();
  for (const [index, release] of typedReleases.entries()) {
    if (versions.has(release.version)) throw new Error('更新清单包含重复版本');
    versions.add(release.version);
    if (index > 0 && compareStableVersions(typedReleases[index - 1].version, release.version) <= 0) {
      throw new Error('更新清单版本顺序无效');
    }
  }
  return { schemaVersion: 1, repository, releases: typedReleases };
}

export function updateStatus(currentVersion: string, feed: ReleaseFeed): UpdateStatus {
  const latest = feed.releases[0];
  const comparison = compareStableVersions(currentVersion, latest.version);
  if (comparison < 0) return { kind: 'update-available', latest };
  if (comparison > 0) return { kind: 'development', latest };
  return { kind: 'current', latest };
}

export function extractLocalizedReleaseNote(markdown: string, locale: AppLocale) {
  const start = `<!-- shuku:locale=${locale}:start -->`;
  const end = `<!-- shuku:locale=${locale}:end -->`;
  const startIndex = markdown.indexOf(start);
  const endIndex = markdown.indexOf(end);
  if (startIndex < 0 || endIndex <= startIndex) throw new Error('更新说明缺少当前语言内容');
  const localized = markdown.slice(startIndex + start.length, endIndex).trim();
  if (!localized) throw new Error('更新说明缺少当前语言内容');
  return localized;
}
