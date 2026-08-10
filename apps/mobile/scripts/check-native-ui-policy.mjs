import { readdir, readFile } from 'node:fs/promises';
import { extname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const mobileRoot = fileURLToPath(new URL('..', import.meta.url));
const sourceRoot = join(mobileRoot, 'src');
const allowedPressableFile = join(
  sourceRoot,
  'shared',
  'ui',
  'content-pressable.tsx',
);
const violations = [];

for (const filePath of await sourceFiles(sourceRoot)) {
  if (filePath.includes('.test.')) continue;
  const source = await readFile(filePath, 'utf8');
  const displayPath = relative(mobileRoot, filePath).replaceAll('\\', '/');

  if (/import\s*\{[^}]*\bModal\b[^}]*\}\s*from\s*['"]react-native['"]/.test(source)) {
    violations.push(`${displayPath}: use an Expo Router modal or formSheet route instead of React Native Modal.`);
  }
  if (
    filePath !== allowedPressableFile &&
    /import\s*\{[^}]*\bPressable\b[^}]*\}\s*from\s*['"]react-native['"]/.test(source)
  ) {
    violations.push(`${displayPath}: use AppButton, a system control, or ContentPressable instead of Pressable.`);
  }
  if (/accessibilityRole\s*=\s*['"](?:tab|tablist)['"]/.test(source)) {
    violations.push(`${displayPath}: do not reproduce native tabs or segmented controls with accessibility tab roles.`);
  }
  if (/\b(?:IconButton|PageHeader|ShellNavigation)\b/.test(source)) {
    violations.push(`${displayPath}: legacy custom navigation/button primitive is forbidden.`);
  }
}

if (violations.length > 0) {
  console.error('Native UI policy violations:\n');
  for (const violation of violations) console.error(`- ${violation}`);
  process.exitCode = 1;
} else {
  console.log('Native UI policy check passed.');
}

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(
    entries.map(async (entry) => {
      const entryPath = join(directory, entry.name);
      if (entry.isDirectory()) return sourceFiles(entryPath);
      return ['.ts', '.tsx'].includes(extname(entry.name)) ? [entryPath] : [];
    }),
  );
  return files.flat();
}
