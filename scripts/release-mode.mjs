// The tag's committed release entry is the only mode selector.
import { appendFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';
import { canonical, gitRead, validateMode } from './release-request.mjs';
import { serverUpdate } from './validate-release-notes.mjs';
export { serverUpdate } from './validate-release-notes.mjs';


export function releaseMode({ root = process.cwd(), version } = {}) {
  version ??= JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8')).version;
  const index = JSON.parse(readFileSync(resolve(root, 'release-notes/index.json'), 'utf8'));
  const entries = index.releases.filter(item => item.version === version);
  if (entries.length !== 1) throw Error('Expected exactly one release entry for version');
  const update = serverUpdate(entries[0]);
  return { mode: update ? 'code-only' : 'full', version, ...(update ?? {}) };
}

export function validateQuickSource(mode, { root = process.cwd(), sourceCommit = 'HEAD' } = {}) {
  if (mode.mode !== 'code-only') return null;
  const changes = validateMode({ server: mode, sourceCommit }, { root });
  let base = mode.baseVersion;
  const seen = new Set();
  while (true) {
    if (seen.has(base)) throw Error('Cyclic release baseline');
    seen.add(base);
    const ref = `refs/tags/v${base}`;
    const index = JSON.parse(gitRead(root, ['show', `${ref}:release-notes/index.json`]));
    const entry = index.releases.find(item => item.version === base);
    if (!entry) throw Error('Missing immutable baseline release metadata');
    const inherited = serverUpdate(entry);
    if (!inherited) return { seedVersion: base, ...changes };
    if (inherited.runtimeImage !== mode.runtimeImage) throw Error('Quick releases must inherit the same runtime image digest');
    gitRead(root, ['merge-base', '--is-ancestor', `refs/tags/v${inherited.baseVersion}`, ref]);
    base = inherited.baseVersion;
  }
}

export function validatePublishedBase(mode, release) {
  if (release.isDraft !== false || release.isPrerelease !== false || release.tagName !== `v${mode.baseVersion}`) {
    throw Error('code-only baseVersion must be an already published stable release');
  }
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const mode = releaseMode();
    // Once this version's tag is behind a branch tip, that tip is ordinary development.
    // Tag dispatch and the exact release commit always retain their committed mode.
    if (mode.mode === 'code-only' && process.env.GITHUB_REF_TYPE === 'branch' && process.env.GITHUB_EVENT_NAME !== 'pull_request') {
      let tagged;
      try { tagged = gitRead(process.cwd(), ['rev-parse', `refs/tags/v${mode.version}^{commit}`]); } catch { /* not tagged yet */ }
      if (tagged && tagged !== gitRead(process.cwd(), ['rev-parse', 'HEAD'])) mode.mode = 'full';
    }
    if (mode.mode === 'code-only') {
      Object.assign(mode, validateQuickSource(mode));
      if (process.argv.includes('--published-base')) {
        const release = JSON.parse(execFileSync('gh', ['release', 'view', `v${mode.baseVersion}`, '--repo', 'GMD170629/ermao-library', '--json', 'tagName,isDraft,isPrerelease'], { encoding: 'utf8' }));
        validatePublishedBase(mode, release);
      }
    }
    if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT,
      `release_mode=${mode.mode}\nruntime_image=${mode.runtimeImage ?? ''}\nseed_version=${mode.seedVersion ?? ''}\nbase_version=${mode.baseVersion ?? ''}\nhas_migrations=${Boolean(mode.migrationPaths?.length)}\nunshipped_native_count=${mode.unshippedNativePaths?.length ?? 0}\n`);
    console.log(canonical(mode));
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
