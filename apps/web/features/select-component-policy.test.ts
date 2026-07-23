import assert from 'node:assert/strict';
import { readdir, readFile } from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';

const ignoredDirectories = new Set(['.next', 'node_modules', 'test-results']);
const nativeSelectPatterns = [
  /<select(?:\s|>)/,
  /createElement\(\s*['"]select['"]/
];

async function findTsxFiles(directory: string): Promise<string[]> {
  const entries = await readdir(directory, { withFileTypes: true });
  const files = await Promise.all(entries.map(async (entry) => {
    if (ignoredDirectories.has(entry.name)) return [];
    const entryPath = path.join(directory, entry.name);
    if (entry.isDirectory()) return findTsxFiles(entryPath);
    return entry.name.endsWith('.tsx') ? [entryPath] : [];
  }));
  return files.flat();
}

test('production UI uses the shared Select component instead of native select elements', async () => {
  const appRoot = path.resolve(process.cwd());
  const files = await findTsxFiles(appRoot);
  const violations: string[] = [];

  for (const file of files) {
    const source = await readFile(file, 'utf8');
    if (nativeSelectPatterns.some((pattern) => pattern.test(source))) {
      violations.push(path.relative(appRoot, file));
    }
  }

  assert.deepEqual(
    violations,
    [],
    `Native <select> elements are forbidden; use components/ui/select instead:\n${violations.join('\n')}`
  );
});
