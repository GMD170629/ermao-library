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
const hookImport = "import { useI18n as useExpressionI18n } from '@/i18n/provider';\n";
const hookStatement = '\n  const { t: i18nExpression } = useExpressionI18n();';
const cjkPattern = /[\u3400-\u9fff]/u;
const comparisonOperators = new Set([
  ts.SyntaxKind.EqualsEqualsToken,
  ts.SyntaxKind.EqualsEqualsEqualsToken,
  ts.SyntaxKind.ExclamationEqualsToken,
  ts.SyntaxKind.ExclamationEqualsEqualsToken
]);

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

function containingJsxExpression(node) {
  let current = node.parent;
  while (current) {
    if (ts.isJsxAttribute(current)) return null;
    if (ts.isJsxExpression(current)) return current;
    current = current.parent;
  }
  return null;
}

function isPresentationValue(node, expression) {
  let current = node.parent;
  while (current && current !== expression) {
    if (
      ts.isCallExpression(current)
      || ts.isNewExpression(current)
      || ts.isArrowFunction(current)
      || ts.isFunctionExpression(current)
      || ts.isElementAccessExpression(current)
      || ts.isPropertyAccessExpression(current)
      || ts.isPropertyAssignment(current)
      || ts.isShorthandPropertyAssignment(current)
      || ts.isCaseClause(current)
    ) {
      return false;
    }
    if (ts.isBinaryExpression(current) && comparisonOperators.has(current.operatorToken.kind)) return false;
    current = current.parent;
  }
  return current === expression;
}

function insertImport(source) {
  if (source.includes('useI18n as useExpressionI18n')) return source;
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

function templateTranslation(node, sourceFile, translator) {
  let source = node.head.text;
  const values = [];
  node.templateSpans.forEach((span, index) => {
    source += `{value${index}}${span.literal.text}`;
    values.push(`value${index}: ${span.expression.getText(sourceFile)}`);
  });
  return `${translator}(${JSON.stringify(source)}, { ${values.join(', ')} })`;
}

let changedFiles = 0;
let changedExpressions = 0;
for (const file of sourceRoots.flatMap((root) => listClientTsxFiles(join(webRoot, root)))) {
  const original = readFileSync(file, 'utf8');
  const sourceFile = ts.createSourceFile(file, original, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const edits = [];
  const componentsNeedingHook = new Set();

  function translatorFor(owner) {
    return owner.body.getText(sourceFile).includes('useAttributeI18n()') ? 'i18nAttribute' : 'i18nExpression';
  }

  function register(node, replacement) {
    const expression = containingJsxExpression(node);
    if (!expression || !isPresentationValue(node, expression)) return;
    const owner = componentFunction(node);
    if (!owner) return;
    const translator = translatorFor(owner);
    edits.push({
      start: node.getStart(sourceFile),
      end: node.getEnd(),
      replacement: replacement(translator)
    });
    if (translator === 'i18nExpression') componentsNeedingHook.add(owner);
    changedExpressions += 1;
  }

  function visit(node) {
    if (ts.isTemplateExpression(node)) {
      const source = node.head.text + node.templateSpans.map((span) => span.literal.text).join('');
      if (cjkPattern.test(source)) register(node, (translator) => templateTranslation(node, sourceFile, translator));
      return;
    }
    if ((ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) && cjkPattern.test(node.text)) {
      if (!ts.isTemplateExpression(node.parent)) {
        register(node, (translator) => `${translator}(${JSON.stringify(node.text)})`);
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(sourceFile);
  if (edits.length === 0) continue;

  for (const component of componentsNeedingHook) {
    edits.push({
      start: component.body.getStart(sourceFile) + 1,
      end: component.body.getStart(sourceFile) + 1,
      replacement: hookStatement
    });
  }

  let migrated = original;
  for (const edit of edits.sort((left, right) => right.start - left.start)) {
    migrated = `${migrated.slice(0, edit.start)}${edit.replacement}${migrated.slice(edit.end)}`;
  }
  if (componentsNeedingHook.size > 0) migrated = insertImport(migrated);
  writeFileSync(file, migrated);
  changedFiles += 1;
  process.stdout.write(`${relative(webRoot, file)}: ${edits.length - componentsNeedingHook.size}\n`);
}

process.stdout.write(`Migrated ${changedExpressions} JSX expressions in ${changedFiles} files\n`);

