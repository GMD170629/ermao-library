import { parseAndroidInput } from './release-request.mjs';
import { releaseMode } from './release-mode.mjs';
import { validateAppPackages, validateDependencyPackages } from './validate-app-packages.mjs';
import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

export function validateReleaseAssets(root, tag, remote, mode = 'full', buildAndroid = false) {
  if (!/^v\d+\.\d+\.\d+$/.test(tag)) throw Error('Invalid stable tag');
  if (typeof buildAndroid !== 'boolean') throw Error('buildAndroid must be boolean');
  if (mode === 'code-only') {
    if (buildAndroid) throw Error('code-only cannot select Android');
    if (['android', 'fnos'].some(name => existsSync(join(root, name))) || (remote && remote.assets.length)) throw Error('code-only must not contain installer assets');
    validateDependencyPackages(join(root, 'application'), tag.slice(1));
    return;
  }
  if (mode !== 'full') throw Error('Invalid release mode');
  if (!buildAndroid && (existsSync(join(root, 'android')) || remote?.assets.some(asset => /\.(?:apk|ipa)(?:\.sha256)?$/.test(asset.name)))) {
    throw Error(`${tag} must not contain mobile release assets when Android is not selected`);
  }
  const expected = [
    ...(buildAndroid ? [['android', `ermao-library-${tag}-android.apk`]] : []),
    ['fnos', `ermao-books-${tag.slice(1)}-all.fpk`],
  ];
  for (const [directory, name] of expected) {
    const files = readdirSync(join(root, directory));
    if (files.length !== 2 || !files.includes(name) || !files.includes(`${name}.sha256`)) {
      throw Error(`Incomplete or unexpected release assets: ${directory}`);
    }
    const bytes = readFileSync(join(root, directory, name));
    const digest = createHash('sha256').update(bytes).digest('hex');
    if (!bytes.length || readFileSync(join(root, directory, `${name}.sha256`), 'utf8').trim() !== `${digest}  ${name}`) {
      throw Error(`SHA-256 mismatch: ${name}`);
    }
    if (remote) {
      for (const filename of [name, `${name}.sha256`]) {
        const local = readFileSync(join(root, directory, filename));
        const asset = remote.assets.find(item => item.name === filename);
        if (!asset || asset.state !== 'uploaded' || asset.size !== local.length ||
            asset.digest !== `sha256:${createHash('sha256').update(local).digest('hex')}`) {
          throw Error(`Remote release asset incomplete or corrupt: ${filename}`);
        }
      }
    }
  }
  const ghcr = Number(tag.slice(1).split('.')[0]) > 1 || (Number(tag.slice(1).split('.')[0]) === 1 && Number(tag.slice(1).split('.')[1]) >= 1);
  if (ghcr && remote && remote.assets.length !== expected.length * 2) throw Error('Unexpected Release attachments; update dependencies belong in GHCR');
  validateAppPackages(join(root, 'application'), tag.slice(1), ghcr ? undefined : remote);
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  validateReleaseAssets(process.argv[2], process.argv[3], process.argv[4] ? JSON.parse(readFileSync(process.argv[4], 'utf8')) : undefined, releaseMode({ version: process.argv[3].slice(1) }).mode, parseAndroidInput(process.env.BUILD_ANDROID));
  console.log('Complete release bundle verified.');
}
