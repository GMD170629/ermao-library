import { appendFile, readFile, realpath } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const STABLE_VERSION = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$/u;
const PLACEHOLDER = /\b(?:TODO|TBD|FIXME)\b|待补充|模板示例|template example/iu;
const LOCALES = ['zh-CN', 'en-US'];
const RELEASE_NOTES_DIRECTORY = 'release-notes';

export function parseStableVersion(value) {
  if (typeof value !== 'string') return null;
  const match = STABLE_VERSION.exec(value);
  return match ? [Number(match[1]), Number(match[2]), Number(match[3])] : null;
}

export function compareStableVersions(left, right) {
  const leftParts = parseStableVersion(left);
  const rightParts = parseStableVersion(right);
  if (!leftParts || !rightParts) throw new Error(`Cannot compare invalid stable versions: ${left}, ${right}`);
  for (let index = 0; index < leftParts.length; index += 1) {
    if (leftParts[index] !== rightParts[index]) return leftParts[index] - rightParts[index];
  }
  return 0;
}

export function extractLocalizedReleaseNote(markdown, locale) {
  const start = `<!-- shuku:locale=${locale}:start -->`;
  const end = `<!-- shuku:locale=${locale}:end -->`;
  const startIndex = markdown.indexOf(start);
  const endIndex = markdown.indexOf(end);
  if (startIndex < 0 || endIndex < 0 || endIndex <= startIndex) {
    throw new Error(`Missing or malformed ${locale} locale markers`);
  }
  if (markdown.indexOf(start, startIndex + start.length) >= 0 || markdown.indexOf(end, endIndex + end.length) >= 0) {
    throw new Error(`Duplicate ${locale} locale markers`);
  }
  return markdown.slice(startIndex + start.length, endIndex).trim();
}

function substantiveText(markdown) {
  return markdown
    .replace(/```[\s\S]*?```/gu, ' ')
    .replace(/<!--[\s\S]*?-->/gu, ' ')
    .replace(/!\[[^\]]*\]\([^)]+\)/gu, ' ')
    .replace(/\[([^\]]+)\]\([^)]+\)/gu, '$1')
    .replace(/^#{1,6}\s+.*$/gmu, ' ')
    .replace(/^[\s>*+-]+/gmu, '')
    .replace(/[`_*~]/gu, '')
    .replace(/\s+/gu, ' ')
    .trim();
}

export function validateReleaseMarkdown(markdown, version, notesPath) {
  if (!markdown.startsWith(`# v${version}\n`)) {
    throw new Error(`${notesPath}: first heading must be "# v${version}"`);
  }
  const fenceCount = (markdown.match(/^```/gmu) ?? []).length;
  if (fenceCount % 2 !== 0) throw new Error(`${notesPath}: unclosed fenced code block`);

  for (const match of markdown.matchAll(/!?\[[^\]]*\]\(([^)]+)\)/gu)) {
    const target = match[1].trim().replace(/^<|>$/gu, '');
    if (/^(?:https?:\/\/|#|mailto:)/iu.test(target)) continue;
    const normalized = path.posix.normalize(target.split(/[?#]/u, 1)[0]);
    if (normalized.startsWith('../') || normalized.startsWith('/') || /^[A-Za-z]:/u.test(normalized)) {
      throw new Error(`${notesPath}: local Markdown link escapes the release-notes directory`);
    }
  }

  const localized = Object.fromEntries(LOCALES.map((locale) => [locale, extractLocalizedReleaseNote(markdown, locale)]));
  for (const locale of LOCALES) {
    const text = substantiveText(localized[locale]);
    if (text.length < 40) throw new Error(`${notesPath}: ${locale} release note is not substantive`);
    if (PLACEHOLDER.test(text)) throw new Error(`${notesPath}: ${locale} release note contains placeholder content`);
  }
  if (!/[\p{Script=Han}]/u.test(localized['zh-CN'])) {
    throw new Error(`${notesPath}: zh-CN release note must contain Chinese content`);
  }
  if (!/[A-Za-z]{4}/u.test(localized['en-US'])) {
    throw new Error(`${notesPath}: en-US release note must contain English content`);
  }
  if (substantiveText(localized['zh-CN']) === substantiveText(localized['en-US'])) {
    throw new Error(`${notesPath}: zh-CN and en-US release notes must not be identical`);
  }
  return localized;
}

export function validateReleaseIndex(index, currentVersion) {
  if (!index || typeof index !== 'object' || Array.isArray(index)) throw new Error('release-notes/index.json must contain an object');
  if (index.schemaVersion !== 1) throw new Error('release-notes/index.json schemaVersion must be 1');
  if (index.repository !== 'GMD170629/ermao-library') throw new Error('release-notes/index.json repository is invalid');
  if (!Array.isArray(index.releases) || index.releases.length === 0) throw new Error('release-notes/index.json must contain releases');

  const seenVersions = new Set();
  for (const [position, release] of index.releases.entries()) {
    if (!release || typeof release !== 'object' || Array.isArray(release)) throw new Error(`Release at index ${position} must be an object`);
    if (!parseStableVersion(release.version)) throw new Error(`Release at index ${position} has an invalid stable version`);
    if (release.tag !== `v${release.version}`) throw new Error(`Release ${release.version} tag must be v${release.version}`);
    if (seenVersions.has(release.version)) throw new Error(`Duplicate release version ${release.version}`);
    seenVersions.add(release.version);
    if (Number.isNaN(Date.parse(release.publishedAt))) throw new Error(`Release ${release.version} has an invalid publishedAt`);
    if (release.notesPath !== `v${release.version}.md`) throw new Error(`Release ${release.version} notesPath must be v${release.version}.md`);
    const expectedUrl = `https://github.com/${index.repository}/releases/tag/${release.tag}`;
    if (release.releaseUrl !== expectedUrl) throw new Error(`Release ${release.version} releaseUrl must be ${expectedUrl}`);
    if (position > 0 && compareStableVersions(index.releases[position - 1].version, release.version) <= 0) {
      throw new Error('Releases must be ordered by descending stable version');
    }
  }
  if (index.releases[0].version !== currentVersion) {
    throw new Error(`Latest release ${index.releases[0].version} does not match application version ${currentVersion}`);
  }
  return index.releases;
}

function packageVersionFromUvLock(contents) {
  for (const section of contents.split('[[package]]')) {
    if (!/^\s*name = "ermao-books-api-python"\s*$/mu.test(section)) continue;
    const match = /^\s*version = "([^"]+)"\s*$/mu.exec(section);
    if (match) return match[1];
  }
  return null;
}

export async function readApplicationVersions(repositoryRoot) {
  const rootPackage = JSON.parse(await readFile(path.join(repositoryRoot, 'package.json'), 'utf8'));
  const webPackage = JSON.parse(await readFile(path.join(repositoryRoot, 'apps/web/package.json'), 'utf8'));
  const pyproject = await readFile(path.join(repositoryRoot, 'apps/api-python/pyproject.toml'), 'utf8');
  const runtimeConfig = await readFile(path.join(repositoryRoot, 'apps/api-python/app/core/config.py'), 'utf8');
  const serviceWorker = await readFile(path.join(repositoryRoot, 'apps/web/public/sw.js'), 'utf8');
  const uvLock = await readFile(path.join(repositoryRoot, 'apps/api-python/uv.lock'), 'utf8');
  return {
    root: rootPackage.version,
    web: webPackage.version,
    python: /^version = "([^"]+)"$/mu.exec(pyproject)?.[1] ?? null,
    runtime: /^\s*app_version: str = "([^"]+)"$/mu.exec(runtimeConfig)?.[1] ?? null,
    serviceWorker: /^const FRONTEND_RESOURCE_VERSION = '([^']+)';\r?$/mu.exec(serviceWorker)?.[1] ?? null,
    uvLock: packageVersionFromUvLock(uvLock)
  };
}

export function validateApplicationVersions(versions, expectedTag = null) {
  if (!parseStableVersion(versions.root)) throw new Error(`Root package version ${versions.root} is not stable SemVer`);
  for (const [source, version] of Object.entries(versions)) {
    if (version !== versions.root) throw new Error(`Application version mismatch: root=${versions.root}, ${source}=${version}`);
  }
  if (expectedTag && expectedTag !== `v${versions.root}`) {
    throw new Error(`Tag ${expectedTag} does not match application version v${versions.root}`);
  }
}

async function changedPaths(repositoryRoot, baseRef) {
  const output = execFileSync('git', ['diff', '--name-only', `${baseRef}...HEAD`], {
    cwd: repositoryRoot,
    encoding: 'utf8'
  });
  return new Set(output.split(/\r?\n/u).filter(Boolean));
}

export async function validateReleaseNotesRepository({
  repositoryRoot,
  expectedTag = null,
  baseRef = null
}) {
  const versions = await readApplicationVersions(repositoryRoot);
  validateApplicationVersions(versions, expectedTag);

  const notesRoot = path.join(repositoryRoot, RELEASE_NOTES_DIRECTORY);
  const index = JSON.parse(await readFile(path.join(notesRoot, 'index.json'), 'utf8'));
  const releases = validateReleaseIndex(index, versions.root);
  const resolvedNotesRoot = await realpath(notesRoot);
  for (const release of releases) {
    const candidate = path.join(notesRoot, release.notesPath);
    const resolvedCandidate = await realpath(candidate);
    if (!resolvedCandidate.startsWith(`${resolvedNotesRoot}${path.sep}`)) {
      throw new Error(`Release ${release.version} notesPath escapes release-notes`);
    }
    validateReleaseMarkdown(await readFile(resolvedCandidate, 'utf8'), release.version, release.notesPath);
  }

  if (baseRef) {
    const basePackageText = execFileSync('git', ['show', `${baseRef}:package.json`], {
      cwd: repositoryRoot,
      encoding: 'utf8'
    });
    const baseVersion = JSON.parse(basePackageText).version;
    if (baseVersion !== versions.root) {
      const changes = await changedPaths(repositoryRoot, baseRef);
      const required = [
        'release-notes/index.json',
        `release-notes/v${versions.root}.md`,
        'apps/web/package.json',
        'apps/web/public/sw.js',
        'apps/api-python/pyproject.toml',
        'apps/api-python/app/core/config.py',
        'apps/api-python/uv.lock'
      ];
      const missing = required.filter((file) => !changes.has(file));
      if (missing.length > 0) throw new Error(`Version bump must update: ${missing.join(', ')}`);
    }
  }

  return {
    version: versions.root,
    tag: `v${versions.root}`,
    notesPath: `${RELEASE_NOTES_DIRECTORY}/${releases[0].notesPath}`,
    feedDirectory: RELEASE_NOTES_DIRECTORY
  };
}

function argumentValue(name) {
  const index = process.argv.indexOf(name);
  return index >= 0 ? process.argv[index + 1] ?? null : null;
}

async function main() {
  const repositoryRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
  const result = await validateReleaseNotesRepository({
    repositoryRoot,
    expectedTag: argumentValue('--tag'),
    baseRef: argumentValue('--base-ref')
  });
  const githubOutput = process.env.GITHUB_OUTPUT;
  if (githubOutput) {
    await appendFile(
      githubOutput,
      `app_version=${result.version}\nrelease_tag=${result.tag}\nrelease_notes_path=${result.notesPath}\nfeed_directory=${result.feedDirectory}\n`,
      'utf8'
    );
  }
  console.log(`Validated ${result.tag} with strict zh-CN and en-US release notes.`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch((error) => {
    console.error(error instanceof Error ? error.message : error);
    process.exitCode = 1;
  });
}
