// The release request is the sole input to both dry-run and publication.
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { appendFileSync, existsSync, readFileSync } from 'node:fs';
import { basename, resolve, relative } from 'node:path';
import { pathToFileURL } from 'node:url';
import { parseStableVersion, readApplicationVersions, validateApplicationVersions } from './validate-release-notes.mjs';

export const targets = ['server-update', 'android', 'ios', 'docker', 'fnos'];
const shaPattern = /^[a-f0-9]{40}$/;
const digestPattern = /^sha256:[a-f0-9]{64}$/;
const imagePattern = /^(?:docker\.io\/)?gamersgu\/shuku-starship-web@sha256:[a-f0-9]{64}$/;
const componentFor = target => target === 'server-update' ? 'server' : target;
function requireValue(ok, message) { if (!ok) throw Error(message); }
function object(value, keys, name) {
  requireValue(value && typeof value === 'object' && !Array.isArray(value), `${name} must be an object`);
  requireValue(Object.keys(value).every(key => keys.includes(key)), `${name} contains unknown fields`);
}
function version(value, name) { requireValue(parseStableVersion(value), `${name} must be stable SemVer (channel is separate)`); }
function image(value) { requireValue(typeof value === 'string' && imagePattern.test(value), 'A trusted immutable runtime/image reference is required'); }
function sha(value) { requireValue(typeof value === 'string' && shaPattern.test(value), 'sourceCommit must be a full lowercase SHA'); }
export function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (value && typeof value === 'object') return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}
export function requestDigest(request) { return createHash('sha256').update(canonical(request)).digest('hex'); }

export function validateRequest(request, filename = `${request?.id}.json`) {
  object(request, ['schemaVersion', 'id', 'sourceCommit', 'channel', 'targets', 'versions', 'promoteLatest', 'notes', 'server', 'android', 'ios', 'docker', 'fnos'], 'request');
  requireValue(request.schemaVersion === 1, 'schemaVersion must be 1');
  requireValue(typeof request.id === 'string' && /^[a-z0-9][a-z0-9-]{0,79}$/.test(request.id), 'Invalid request id');
  requireValue(basename(filename) === `${request.id}.json`, 'Request filename must match id');
  sha(request.sourceCommit);
  requireValue(['stable', 'beta'].includes(request.channel), 'Invalid channel');
  requireValue(typeof request.promoteLatest === 'boolean', 'promoteLatest must be boolean');
  requireValue(Array.isArray(request.targets) && request.targets.length > 0 && request.targets.every(target => targets.includes(target)) && new Set(request.targets).size === request.targets.length, 'Invalid or duplicate targets');
  const selected = target => request.targets.includes(target);
  requireValue(request.channel !== 'beta' || request.targets.every(target => ['android', 'ios'].includes(target)), 'Only mobile targets currently support beta');
  object(request.versions, request.targets.map(componentFor), 'versions');
  for (const target of request.targets) version(request.versions[componentFor(target)], `versions.${componentFor(target)}`);
  object(request.notes, ['zh-CN', 'en-US'], 'notes');
  for (const locale of ['zh-CN', 'en-US']) {
    const text = request.notes[locale];
    requireValue(typeof text === 'string' && text.trim().length >= 40 && text.length <= 20000 && !/\b(?:TODO|TBD|FIXME)\b|待补充|模板示例/i.test(text), `Substantive ${locale} notes are required`);
  }
  requireValue(/\p{Script=Han}/u.test(request.notes['zh-CN']) && /[A-Za-z]{4}/.test(request.notes['en-US']) && request.notes['zh-CN'] !== request.notes['en-US'], 'Distinct bilingual notes are required');
  for (const [target, key] of [['server-update', 'server'], ['android', 'android'], ['ios', 'ios'], ['docker', 'docker'], ['fnos', 'fnos']]) {
    requireValue(selected(target) === Object.hasOwn(request, key), `${key} must exist exactly when selected`);
  }
  if (selected('server-update')) {
    const server = request.server;
    object(server, ['mode', 'baseVersion', 'runtimeImage'], 'server');
    requireValue(['code-only', 'application', 'runtime'].includes(server.mode), 'Invalid server mode');
    version(server.baseVersion, 'server.baseVersion');
    image(server.runtimeImage);
    requireValue(server.mode !== 'runtime' || selected('docker'), 'runtime requires explicit docker target');
    requireValue(request.channel === 'stable', 'Server updater currently supports stable only');
  }
  for (const target of ['android', 'ios']) {
    if (!selected(target)) continue;
    const mobile = request[target];
    object(mobile, ['destination', 'buildNumber'], target);
    requireValue(mobile.destination === (target === 'android' ? 'github-apk' : 'testflight'), `Unsupported ${target} destination`);
    requireValue(Number.isSafeInteger(mobile.buildNumber) && mobile.buildNumber > 0 && mobile.buildNumber <= 2100000000, `Invalid ${target} buildNumber`);
  }
  if (selected('docker')) {
    object(request.docker, ['fromServerUpdate', 'runtimeImage', 'application'], 'docker');
    image(request.docker.runtimeImage);
    if (request.docker.fromServerUpdate === true) {
      requireValue(selected('server-update') && request.docker.application === undefined, 'docker.fromServerUpdate requires selected server-update');
      requireValue(request.versions.docker === request.versions.server, 'Combined docker must contain selected server version');
    } else {
      requireValue(request.docker.fromServerUpdate === undefined, 'Omit fromServerUpdate for existing application');
      const app = request.docker.application;
      object(app, ['version', 'sourceCommit', 'ociDigests'], 'docker.application');
      version(app.version, 'docker.application.version'); sha(app.sourceCommit);
      requireValue(app.version === request.versions.docker && app.sourceCommit === request.sourceCommit, 'Docker must use the original application source and version');
      requireValue(Array.isArray(app.ociDigests) && app.ociDigests.length === 2 && app.ociDigests.every(digest => typeof digest === 'string' && digestPattern.test(digest)), 'Two architecture OCI digests are required');
    }
  }
  if (selected('fnos')) {
    object(request.fnos, ['fromDocker', 'image'], 'fnos');
    if (request.fnos.fromDocker === true) requireValue(selected('docker') && request.fnos.image === undefined, 'fnos.fromDocker requires explicit docker target');
    else { requireValue(request.fnos.fromDocker === undefined, 'Omit fromDocker for existing image'); image(request.fnos.image); }
  }
  return request;
}

export function releaseTag(request, target) {
  const v = request.versions[componentFor(target)];
  const suffix = request.channel === 'beta' ? `-beta.${request[target].buildNumber}` : '';
  return target === 'server-update' ? `v${v}` : `${target}-v${v}${suffix}`;
}

export function selectTasks(request, completed = {}) {
  validateRequest(request);
  return request.targets.filter(target => !completed[target]).map(target => ({
    target, version: request.versions[componentFor(target)], tag: releaseTag(request, target),
    sourceCommit: request.sourceCommit, requestDigest: requestDigest(request),
    needs: target === 'fnos' && request.fnos.fromDocker ? ['docker'] : target === 'docker' && request.docker.fromServerUpdate ? ['server-update'] : [],
  }));
}

export function gitRead(root, args) { return execFileSync('git', args, { cwd: root, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim(); }
export function validateSource(request, { root = process.cwd(), authorizedRef = 'origin/main', requestPath, accepted = false } = {}) {
  validateRequest(request, requestPath);
  requireValue(gitRead(root, ['rev-parse', `${request.sourceCommit}^{commit}`]) === request.sourceCommit, 'Source is not an exact commit');
  gitRead(root, ['merge-base', '--is-ancestor', request.sourceCommit, authorizedRef]);
  if (accepted) {
    requireValue(requestPath === `release/requests/${request.id}.json`, 'Only accepted request paths may publish');
    const previous = JSON.parse(gitRead(root, ['show', `${authorizedRef}:${requestPath}`]));
    requireValue(requestDigest(previous) === requestDigest(request), 'Request differs from authorized branch');
    const commits = gitRead(root, ['log', '--format=%H', authorizedRef, '--', requestPath]).split('\n').filter(Boolean);
    requireValue(commits.length > 0, 'Request was not admitted');
    for (const commit of commits) {
      const original = JSON.parse(gitRead(root, ['show', `${commit}:${requestPath}`]));
      requireValue(requestDigest(original) === requestDigest(request), 'Accepted request ID is immutable');
    }
    const admission = commits.at(-1);
    gitRead(root, ['merge-base', '--is-ancestor', request.sourceCommit, `${admission}^`]);
  }
}

export function validateMode(request, { root = process.cwd() } = {}) {
  if (!request.server) return;
  const { mode, baseVersion } = request.server;
  const base = `refs/tags/v${baseVersion}`;
  gitRead(root, ['merge-base', '--is-ancestor', base, request.sourceCommit]);
  if (mode === 'runtime') return;
  const changed = gitRead(root, ['diff', '--name-only', base, request.sourceCommit]).split('\n').filter(file => file !== 'ermao-library.wiki');
  const fixed = ['apps/web/Dockerfile.prod', 'scripts/container-entry.py', 'scripts/container_install.py', 'scripts/container_image.py', 'scripts/install-python-runtime.sh', 'scripts/dependency_install.py', 'scripts/dependency_environment.py', 'scripts/dependency_packages.py', 'scripts/dependency_records.py', 'scripts/build-runtime-environment.py', '.nvmrc', 'apps/api-python/.python-version'];
  requireValue(!changed.some(file => fixed.includes(file) || file.startsWith('apps/mobile/native/mobi-core/') || file.startsWith('packages/reader-core/native/') || file.startsWith('apps/api-python/shuku_dependencies/')), 'Fixed runtime changed; select runtime mode and docker');
  if (mode !== 'code-only') return;
  requireValue(!changed.some(file => file.startsWith('apps/api-python/app/db/migrations/') || file.startsWith('apps/api-python/app/contracts/') || (file.startsWith('packages/reader-contracts/') && !file.endsWith('/package.json'))), 'code-only cannot change migrations or interface contracts');
  const read = (ref, file) => gitRead(root, ['show', `${ref}:${file}`]);
  const normalize = (file, text) => {
    if (file.endsWith('package.json')) {
      const value = JSON.parse(text); delete value.version;
      return canonical(value);
    }
    if (file.endsWith('uv.lock')) return text.replace(/(\[\[package\]\]\nname = "ermao-books-api-python"\nversion = )"[^"]+"/g, '$1"APPLICATION"');
    if (file.endsWith('pyproject.toml')) return text.replace(/^version = "[^"]+"$/m, 'version = "APPLICATION"');
    if (file === 'apps/mobile/androidApp/build.gradle.kts') return text.replace(/versionCode = \d+/g, 'versionCode = BUILD').replace(/versionName = "[^"]+"/g, 'versionName = "VERSION"');
    if (file === 'apps/mobile/iosApp/ErmaoLibrary.xcodeproj/project.pbxproj') return text.replace(/CURRENT_PROJECT_VERSION = \d+;/g, 'CURRENT_PROJECT_VERSION = BUILD;').replace(/MARKETING_VERSION = [^;]+;/g, 'MARKETING_VERSION = VERSION;');
    return text;
  };
  // Only known application roots are deliverable. New build/runtime inputs fail closed.
  const application = file => /^(apps\/web\/(app|components|features|lib|generated|styles|public|i18n|hooks|contexts|types|tests|e2e)\/|apps\/api-python\/(app|tests)\/|packages\/reader-core\/(src|tests)\/)/.test(file);
  const documentation = file => /^(docs\/|release-notes\/|\.agents\/skills\/)/.test(file) || /(^|\/)(AGENTS|README)\.md$/.test(file);
  const releaseTool = file => file.startsWith('.github/workflows/') ||
    /^scripts\/(?:release-[\w-]+|validate-release-[\w-]+|validate-app-packages|assemble-release-feed|ghcr-updates|build-release-app-packages|build-code-only-app|build-application-package|accept_candidate_update|accept_container_update|container_update_(?:fixture|browser|source)|test_accept_candidate_update)(?:\.test)?\.(?:mjs|py|sh)$/.test(file);
  for (const file of changed.filter(Boolean)) {
    if (file.endsWith('/package.json') || file === 'package.json' ||
        ['pnpm-lock.yaml', 'apps/api-python/uv.lock', 'apps/api-python/pyproject.toml',
         'apps/mobile/androidApp/build.gradle.kts', 'apps/mobile/iosApp/ErmaoLibrary.xcodeproj/project.pbxproj'].includes(file)) {
      requireValue(normalize(file, read(base, file)) === normalize(file, read(request.sourceCommit, file)), `code-only dependency/configuration change: ${file}`);
    } else {
      requireValue(application(file) || documentation(file) || releaseTool(file), `code-only unsupported build/runtime/client input: ${file}`);
    }
  }
}

export async function validateRequestVersions(request, { root = process.cwd() } = {}) {
  const versions = await readApplicationVersions(root, file => gitRead(root, ['show', `${request.sourceCommit}:${relative(root, file)}`]));
  validateApplicationVersions(versions);
  for (const target of request.targets) {
    const key = componentFor(target);
    if (['docker', 'fnos'].includes(key)) continue;
    requireValue(request.versions[key] === versions[key === 'server' ? 'root' : key], `Selected ${key} version differs from source`);
  }
  for (const target of ['android', 'ios']) {
    if (!request[target]) continue;
    const file = target === 'android' ? 'apps/mobile/androidApp/build.gradle.kts' : 'apps/mobile/iosApp/ErmaoLibrary.xcodeproj/project.pbxproj';
    const expression = target === 'android' ? /versionCode = (\d+)/g : /CURRENT_PROJECT_VERSION = (\d+);/g;
    const codes = [...gitRead(root, ['show', `${request.sourceCommit}:${file}`]).matchAll(expression)].map(match => Number(match[1]));
    // Beta uses an explicit immutable request build number; stable uses the committed native number.
    if (request.channel === 'stable' || target === 'ios') requireValue(codes.length > 0 && codes.every(code => code === request[target].buildNumber), `${target} buildNumber differs from source`);
  }
}

// An invocation has one authority: an accepted request, or an explicit manual input.
export function parseAndroidInput(value) {
  if (value === undefined || value === '' || value === false || value === 'false') return false;
  if (value === true || value === 'true') return true;
  throw Error('build_android must be a boolean');
}

export function selectAndroidBuild({ request, input, eventName, mode = 'full' } = {}) {
  const manual = parseAndroidInput(input);
  if (request) {
    validateRequest(request);
    requireValue(input === undefined || input === '', 'Request and manual Android input conflict');
  }
  const selected = request ? request.targets.includes('android') : manual;
  requireValue(!selected || !['pull_request', 'pull_request_target'].includes(eventName), 'PRs cannot authorize Android');
  requireValue(!manual || eventName === 'workflow_dispatch' || eventName === 'workflow_call', 'Android input requires an explicit invocation');
  requireValue(!selected || mode !== 'code-only', 'code-only cannot select Android');
  return selected;
}

export async function workflowAndroidSelection({ root = process.cwd(), env = process.env } = {}) {
  const version = JSON.parse(readFileSync(resolve(root, 'package.json'), 'utf8')).version;
  // Version-specific, never the latest request or the previous run's selection.
  const requestPath = `release/requests/stable-${version.replaceAll('.', '-')}.json`;
  const formal = env.GITHUB_REF_TYPE === 'tag' && env.GITHUB_EVENT_NAME !== 'pull_request';
  let request;
  if (formal && existsSync(resolve(root, requestPath))) {
    request = validateRequest(JSON.parse(readFileSync(resolve(root, requestPath), 'utf8')), requestPath);
    validateSource(request, { root, requestPath, accepted: true });
    requireValue(request.channel === 'stable', 'Stable tag requires stable request');
    requireValue(!request.android || request.versions.android === version, 'Legacy stable APK version must match the server tag');
    requireValue(!request.targets.includes('ios'), 'The legacy stable workflow does not deliver iOS');
    // Admission necessarily follows the frozen source commit. Only this request may differ.
    const changed = gitRead(root, ['diff', '--name-only', request.sourceCommit, 'HEAD']).split('\n').filter(Boolean);
    requireValue(changed.every(file => file === requestPath), 'Release source differs from accepted request');
    await validateRequestVersions(request, { root });
    validateMode(request, { root });
    if (request.server) requireValue((request.server.mode === 'code-only') === (env.RELEASE_MODE === 'code-only'), 'Request and committed server mode conflict');
  }
  const input = env.GITHUB_EVENT_NAME === 'workflow_dispatch' ? env.BUILD_ANDROID_INPUT : undefined;
  const buildAndroid = selectAndroidBuild({ request, input, eventName: env.GITHUB_EVENT_NAME, mode: env.RELEASE_MODE });
  requireValue(!buildAndroid || formal, 'Stable Android requires a version tag');
  return { version, buildAndroid, reason: request ? `request:${request.id}` : buildAndroid ? 'explicit manual input' : 'not selected' };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const [file, ...args] = process.argv.slice(2);
    if (file === '--workflow') {
      const { version, buildAndroid, reason } = await workflowAndroidSelection();
      if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, `build_android=${buildAndroid}\n`);
      const summary = `- 版本 / Version: ${version}\n- 源码 / Source: ${process.env.GITHUB_SHA}\n- 服务端模式 / Server mode: ${process.env.RELEASE_MODE}\n- Docker / fnOS: ${process.env.RELEASE_MODE === 'code-only' ? '不构建 / skip' : '完整模式 / full'}\n- Android: ${buildAndroid ? '构建 / build' : '不构建 / skip'} (${reason})\n`;
      if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, summary);
      console.log(summary);
    } else {
      requireValue(file && args.every(arg => arg === '--accepted' || arg.startsWith('--ref=')), 'Usage: node scripts/release-request.mjs FILE [--accepted] [--ref=REF] (read-only dry-run)');
      const request = validateRequest(JSON.parse(readFileSync(file, 'utf8')), file);
      validateSource(request, { requestPath: file, accepted: args.includes('--accepted'), authorizedRef: args.find(arg => arg.startsWith('--ref='))?.slice(6) ?? 'origin/main' });
      validateMode(request);
      await validateRequestVersions(request);
      console.log(JSON.stringify({ dryRun: true, id: request.id, tasks: selectTasks(request) }, null, 2));
    }
  } catch (error) { console.error(error.message); process.exitCode = 1; }
}
