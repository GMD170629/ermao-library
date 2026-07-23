import { createRequire } from 'node:module';
import { readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('../node_modules/typescript');
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDirectory, '..');
const sourceRoots = ['app', 'components', 'features'];
const ignoredDirectories = new Set(['.next', 'generated', 'node_modules', 'storage']);
const importLine = "import { I18nText } from '@/i18n/provider';\n";
const cjkPattern = /[\u3400-\u9fff]/u;

function listTsxFiles(root) {
  const files = [];
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (ignoredDirectories.has(entry.name)) continue;
      const path = join(directory, entry.name);
      if (entry.isDirectory()) visit(path);
      else if (extname(entry.name) === '.tsx' && !entry.name.includes('.test.') && !entry.name.includes('.spec.')) files.push(path);
    }
  }
  visit(root);
  return files;
}

function normalizedMultilineText(value) {
  return value
    .split(/\r?\n/u)
    .map((line) => line.replace(/\s+/gu, ' ').trim())
    .filter(Boolean)
    .join(' ');
}

function insertImport(source) {
  if (/import\s*\{[^}]*\bI18nText\b[^}]*\}\s*from\s*['"]@\/i18n\/provider['"]/u.test(source)) return source;
  const importMatches = [...source.matchAll(/^import .*?;\r?\n/gmu)];
  if (importMatches.length > 0) {
    const last = importMatches.at(-1);
    const index = (last?.index ?? 0) + (last?.[0].length ?? 0);
    return `${source.slice(0, index)}${importLine}${source.slice(index)}`;
  }
  const directive = source.match(/^(['"])use client\1;\r?\n/u);
  const index = directive?.[0].length ?? 0;
  return `${source.slice(0, index)}${importLine}${source.slice(index)}`;
}

let changedFiles = 0;
let changedNodes = 0;
for (const file of sourceRoots.flatMap((root) => listTsxFiles(join(webRoot, root)))) {
  const original = readFileSync(file, 'utf8');
  const sourceFile = ts.createSourceFile(file, original, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const edits = [];

  function visit(node) {
    if (ts.isJsxText(node)) {
      let ancestor = node.parent;
      let alreadyTranslated = false;
      while (ancestor) {
        if (
          ts.isJsxElement(ancestor)
          && ancestor.openingElement.tagName.getText(sourceFile) === 'I18nText'
        ) {
          alreadyTranslated = true;
          break;
        }
        ancestor = ancestor.parent;
      }
      if (alreadyTranslated) return;
      const raw = node.getText(sourceFile);
      const message = raw.includes('\n') || raw.includes('\r') ? normalizedMultilineText(raw) : raw;
      if (message.trim() && cjkPattern.test(message)) {
        edits.push({
          start: node.getStart(sourceFile),
          end: node.getEnd(),
          replacement: `<I18nText>${message}</I18nText>`
        });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  if (edits.length === 0) continue;

  let migrated = original;
  for (const edit of edits.sort((left, right) => right.start - left.start)) {
    migrated = `${migrated.slice(0, edit.start)}${edit.replacement}${migrated.slice(edit.end)}`;
  }
  migrated = insertImport(migrated);
  writeFileSync(file, migrated);
  changedFiles += 1;
  changedNodes += edits.length;
  process.stdout.write(`${relative(webRoot, file)}: ${edits.length}\n`);
}

process.stdout.write(`Migrated ${changedNodes} JSX text nodes in ${changedFiles} files\n`);
