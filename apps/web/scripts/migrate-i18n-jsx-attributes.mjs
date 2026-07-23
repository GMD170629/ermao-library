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
const hookImport = "import { useI18n as useAttributeI18n } from '@/i18n/provider';\n";
const hookStatement = '\n  const { t: i18nAttribute } = useAttributeI18n();';
const cjkPattern = /[\u3400-\u9fff]/u;

function listClientTsxFiles(root) {
  const files = [];
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (ignoredDirectories.has(entry.name)) continue;
      const path = join(directory, entry.name);
      if (entry.isDirectory()) visit(path);
      else if (extname(entry.name) === '.tsx' && !entry.name.includes('.test.') && !entry.name.includes('.spec.')) {
        const source = readFileSync(path, 'utf8');
        if (/^['"]use client['"];/u.test(source)) files.push(path);
      }
    }
  }
  visit(root);
  return files;
}

function isUppercaseName(name) {
  return Boolean(name && /^[A-Z]/u.test(name));
}

function componentFunction(node) {
  let current = node.parent;
  while (current) {
    if (ts.isFunctionDeclaration(current) && isUppercaseName(current.name?.text) && current.body) return current;
    if ((ts.isArrowFunction(current) || ts.isFunctionExpression(current)) && ts.isBlock(current.body)) {
      const declaration = current.parent;
      if (ts.isVariableDeclaration(declaration) && ts.isIdentifier(declaration.name) && isUppercaseName(declaration.name.text)) {
        return current;
      }
    }
    current = current.parent;
  }
  return null;
}

function insertImport(source) {
  if (source.includes("useI18n as useAttributeI18n")) return source;
  const importMatches = [...source.matchAll(/^import[\s\S]*?from ['"][^'"]+['"];\r?\n/gmu)];
  if (importMatches.length > 0) {
    const last = importMatches.at(-1);
    const index = (last?.index ?? 0) + (last?.[0].length ?? 0);
    return `${source.slice(0, index)}${hookImport}${source.slice(index)}`;
  }
  const directive = source.match(/^(['"])use client\1;\r?\n/u);
  const index = directive?.[0].length ?? 0;
  return `${source.slice(0, index)}${hookImport}${source.slice(index)}`;
}

function templateTranslation(node, sourceFile) {
  let source = node.head.text;
  const values = [];
  node.templateSpans.forEach((span, index) => {
    source += `{value${index}}${span.literal.text}`;
    values.push(`value${index}: ${span.expression.getText(sourceFile)}`);
  });
  return `i18nAttribute(${JSON.stringify(source)}, { ${values.join(', ')} })`;
}

let changedFiles = 0;
let changedAttributes = 0;
for (const file of sourceRoots.flatMap((root) => listClientTsxFiles(join(webRoot, root)))) {
  const original = readFileSync(file, 'utf8');
  const sourceFile = ts.createSourceFile(file, original, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const edits = [];
  const components = new Set();

  function visit(node) {
    if (ts.isJsxAttribute(node) && node.initializer) {
      const owner = componentFunction(node);
      if (!owner) {
        ts.forEachChild(node, visit);
        return;
      }
      if (ts.isStringLiteral(node.initializer) && cjkPattern.test(node.initializer.text)) {
        edits.push({
          start: node.initializer.getStart(sourceFile),
          end: node.initializer.getEnd(),
          replacement: `{i18nAttribute(${JSON.stringify(node.initializer.text)})}`
        });
        components.add(owner);
        changedAttributes += 1;
      } else if (ts.isJsxExpression(node.initializer) && node.initializer.expression) {
        const expression = node.initializer.expression;
        if (ts.isTemplateExpression(expression)) {
          const templateSource = expression.head.text + expression.templateSpans.map((span) => span.literal.text).join('');
          if (cjkPattern.test(templateSource)) {
            edits.push({
              start: node.initializer.getStart(sourceFile),
              end: node.initializer.getEnd(),
              replacement: `{${templateTranslation(expression, sourceFile)}}`
            });
            components.add(owner);
            changedAttributes += 1;
          }
        } else if ((ts.isStringLiteral(expression) || ts.isNoSubstitutionTemplateLiteral(expression)) && cjkPattern.test(expression.text)) {
          edits.push({
            start: node.initializer.getStart(sourceFile),
            end: node.initializer.getEnd(),
            replacement: `{i18nAttribute(${JSON.stringify(expression.text)})}`
          });
          components.add(owner);
          changedAttributes += 1;
        }
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  if (edits.length === 0) continue;

  for (const component of components) {
    if (!component.body.getText(sourceFile).includes('useAttributeI18n()')) {
      edits.push({
        start: component.body.getStart(sourceFile) + 1,
        end: component.body.getStart(sourceFile) + 1,
        replacement: hookStatement
      });
    }
  }

  let migrated = original;
  for (const edit of edits.sort((left, right) => right.start - left.start)) {
    migrated = `${migrated.slice(0, edit.start)}${edit.replacement}${migrated.slice(edit.end)}`;
  }
  migrated = insertImport(migrated);
  writeFileSync(file, migrated);
  changedFiles += 1;
  process.stdout.write(`${relative(webRoot, file)}: ${edits.length - components.size}\n`);
}

process.stdout.write(`Migrated ${changedAttributes} JSX attributes in ${changedFiles} files\n`);

