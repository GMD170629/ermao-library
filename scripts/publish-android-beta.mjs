import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export const tag = 'android-beta';

export function publicationContext(env) {
  if (env.GITHUB_REF !== 'refs/heads/develop' || !['push', 'workflow_dispatch'].includes(env.GITHUB_EVENT_NAME)) {
    throw new Error('Beta publication is restricted to develop push/manual runs');
  }
  if (!/^\d+$/.test(env.GITHUB_RUN_NUMBER ?? '') || !/^\d+$/.test(env.GITHUB_RUN_ATTEMPT ?? '') ||
      Number(env.GITHUB_RUN_NUMBER) < 1 || Number(env.GITHUB_RUN_NUMBER) > 2_099_899_999 ||
      Number(env.GITHUB_RUN_ATTEMPT) < 1 || !/^[a-f0-9]{40}$/.test(env.GITHUB_SHA ?? '') ||
      !/^[\w.-]+\/[\w.-]+$/.test(env.GITHUB_REPOSITORY ?? '') || !/^\d+$/.test(env.GITHUB_RUN_ID ?? '')) {
    throw new Error('Invalid beta build metadata');
  }
  return { repo: env.GITHUB_REPOSITORY, sha: env.GITHUB_SHA, number: Number(env.GITHUB_RUN_NUMBER),
    attempt: Number(env.GITHUB_RUN_ATTEMPT), runId: env.GITHUB_RUN_ID };
}

export function shouldPublish(release, context) {
  if (!release) return true;
  if (release.immutable) throw new Error('android-beta must be a mutable prerelease');
  if (!release.prerelease) throw new Error('Refusing to replace a non-prerelease');
  const marker = release.body?.match(/<!-- android-beta run=(\d+) attempt=(\d+) -->/);
  if (!marker) throw new Error('Existing android-beta release has no recognized build metadata');
  const [number, attempt] = marker.slice(1).map(Number);
  return context.number > number || (context.number === number && context.attempt > attempt);
}

export function verifyAssets(directory, context) {
  const apks = readdirSync(directory).filter(name => name.endsWith('.apk'));
  if (apks.length !== 1) throw new Error('Expected one signed APK');
  const name = apks[0];
  if (!/^ermao-library-[\w.+-]+\.apk$/.test(name) ||
      !name.endsWith(`-beta.${context.number}-${context.sha.slice(0, 8)}-r${context.attempt}.apk`)) {
    throw new Error('APK name does not match this build');
  }
  const checksum = `${name}.sha256`;
  const digest = createHash('sha256').update(readFileSync(resolve(directory, name))).digest('hex');
  if (readFileSync(resolve(directory, checksum), 'utf8').trim() !== `${digest}  ${name}`) {
    throw new Error('APK SHA-256 verification failed');
  }
  return { name, checksum, digest };
}

function gh(args, input) {
  return execFileSync('gh', args, { encoding: 'utf8', input, stdio: ['pipe', 'pipe', 'pipe'] });
}

export function releaseBody(context, assets) {
  const runUrl = `https://github.com/${context.repo}/actions/runs/${context.runId}`;
  return `<!-- android-beta run=${context.number} attempt=${context.attempt} -->
## Android 测试版 / Android Beta

来自 develop 的持续测试版本，可能存在未发现的问题；不代表正式发布或真机验收完成。
Continuous test build from develop. This is not a stable release or a claim of physical-device acceptance.

- 安装下方 APK，可与现有客户端共存；首次需重新登录。后续安装测试版可保留其数据。
- Install the APK below alongside the existing app. Sign in on first use; subsequent beta updates preserve beta app data.
- 包名 / Package: com.ermao.library.beta
- 构建 / Build: ${context.number} (attempt ${context.attempt}); versionCode: ${100000 + context.number}
- 提交 / Commit: ${context.sha}
- CI: ${runUrl}
- 已通过 / Passed: mobile backend contracts; shared and Android tests/lint; CI emulator smoke/safety checks; beta package and signature verification.
- SHA-256 (${assets.name}): ${assets.digest}

下载 APK 及对应 .sha256 文件以校验完整性。Download the APK and matching .sha256 file to verify integrity.
`;
}

// The caller supplies an API adapter so ordering and failure behavior are testable without publishing.
export function publish(context, directory, api) {
  const assets = verifyAssets(directory, context);
  let release = api.release();
  if (!shouldPublish(release, context)) return 'superseded';
  if (api.head() !== context.sha) return 'superseded';
  const body = releaseBody(context, assets);
  if (!release) release = api.createDraft(body);
  const keep = [assets.name, assets.checksum];
  for (const name of keep) api.upload(resolve(directory, name));
  // Upload failures leave the previous published tag/body/assets untouched.
  api.moveTag();
  api.update(release.id, body);
  for (const asset of api.assets(release.id)) {
    if (/^ermao-library-.*\.apk(?:\.sha256)?$/.test(asset.name) && !keep.includes(asset.name)) api.remove(asset.id);
  }
  return 'published';
}

function githubApi(context) {
  const base = `repos/${context.repo}`;
  const json = (path, method = 'GET', data) => JSON.parse(gh(['api', `${base}/${path}`, '--method', method,
    ...(data ? ['--input', '-'] : [])], data ? JSON.stringify(data) : undefined) || 'null');
  const release = () => {
    try { return json(`releases/tags/${tag}`); }
    catch (error) {
      if (/HTTP 404/.test(String(error.stderr))) return null;
      throw error;
    }
  };
  return {
    release,
    head: () => json('git/ref/heads/develop').object.sha,
    createDraft: body => json('releases', 'POST', { tag_name: tag, target_commitish: context.sha,
      name: 'Android 测试版 / Android Beta', body, draft: true, prerelease: true, make_latest: 'false' }),
    upload: path => gh(['release', 'upload', tag, path, '--repo', context.repo, '--clobber']),
    moveTag: () => {
      try { json(`git/ref/tags/${tag}`); }
      catch (error) {
        if (!/HTTP 404/.test(String(error.stderr))) throw error;
        json('git/refs', 'POST', { ref: `refs/tags/${tag}`, sha: context.sha });
        return;
      }
      json(`git/refs/tags/${tag}`, 'PATCH', { sha: context.sha, force: true });
    },
    update: (id, body) => json(`releases/${id}`, 'PATCH', { name: 'Android 测试版 / Android Beta',
      body, draft: false, prerelease: true, make_latest: 'false', target_commitish: context.sha }),
    assets: id => JSON.parse(gh(['api', `${base}/releases/${id}/assets`, '--paginate', '--slurp'])).flat(),
    remove: id => json(`releases/assets/${id}`, 'DELETE'),
  };
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  try {
    const context = publicationContext(process.env);
    console.log(`Android beta: ${publish(context, resolve(process.argv[2]), githubApi(context))}`);
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}
