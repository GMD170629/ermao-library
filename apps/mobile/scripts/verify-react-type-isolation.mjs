import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const mobileRoot = resolve(scriptDirectory, '..');
const compilerPath = resolve(
  mobileRoot,
  'node_modules',
  'typescript',
  'bin',
  'tsc',
);
const compilation = spawnSync(
  process.execPath,
  [compilerPath, '--noEmit', '--listFilesOnly'],
  {
    cwd: mobileRoot,
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  },
);

if (compilation.error !== undefined) {
  throw compilation.error;
}
if (compilation.status !== 0) {
  process.stdout.write(compilation.stdout);
  process.stderr.write(compilation.stderr);
  process.exit(compilation.status ?? 1);
}

const expectedTypeRoot = `${resolve(
  mobileRoot,
  'node_modules',
  '@types',
  'react',
)}${sep}`;
const reactTypeFiles = compilation.stdout
  .split(/\r?\n/u)
  .filter(
    (file) =>
      file.includes(`${sep}@types${sep}react${sep}`) ||
      file.includes('@types+react@'),
  );
const unexpectedTypeFiles = reactTypeFiles.filter(
  (file) => !file.startsWith(expectedTypeRoot),
);
if (reactTypeFiles.length === 0 || unexpectedTypeFiles.length > 0) {
  const details =
    unexpectedTypeFiles.length === 0
      ? 'No React type declarations were loaded'
      : `Unexpected React type declarations:\n${unexpectedTypeFiles.join('\n')}`;
  throw new Error(`Mobile React type isolation failed. ${details}`);
}

const reactTypesPackage = JSON.parse(
  readFileSync(
    resolve(expectedTypeRoot, 'package.json'),
    'utf8',
  ),
);
if (
  typeof reactTypesPackage !== 'object' ||
  reactTypesPackage === null ||
  !('version' in reactTypesPackage) ||
  typeof reactTypesPackage.version !== 'string' ||
  !reactTypesPackage.version.startsWith('19.')
) {
  throw new Error('Mobile must compile against @types/react major 19');
}

process.stdout.write(
  `React type isolation verified: ${reactTypesPackage.version}\n`,
);
