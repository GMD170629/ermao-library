import { createHash } from 'node:crypto';
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';

export function validateReleaseAssets(root, tag, remote) {
  if (!/^v\d+\.\d+\.\d+$/.test(tag)) throw Error('Invalid stable tag');
  // Explicit owner-approved exception; all other stable versions still require APKs.
  const serverOnly = ['v1.0.3', 'v1.0.4'].includes(tag);
  if (serverOnly && (existsSync(join(root, 'android')) || remote?.assets.some(asset => /\.(?:apk|ipa)(?:\.sha256)?$/.test(asset.name)))) {
    throw Error(`${tag} must not contain mobile release assets`);
  }
  const expected = [
    ...(!serverOnly ? [['android', `ermao-library-${tag}-android.apk`]] : []),
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
}

if (process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href) {
  validateReleaseAssets(process.argv[2], process.argv[3], process.argv[4] ? JSON.parse(readFileSync(process.argv[4], 'utf8')) : undefined);
  console.log('Complete release bundle verified.');
}
