import { execFileSync } from 'node:child_process';
import { createRequire } from 'node:module';
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, extname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const require = createRequire(import.meta.url);
const ts = require('../node_modules/typescript');
const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webRoot = resolve(scriptDirectory, '..');
const repositoryRoot = resolve(webRoot, '../..');
const sourceRoots = ['app', 'components', 'features', 'lib'];
const ignoredPathParts = new Set(['.next', 'generated', 'node_modules', 'storage']);
const cjkPattern = /[\u3400-\u9fff]/u;
const interpolationPattern = /\{([a-zA-Z0-9_]+)\}/gu;

function listFiles(root, acceptedExtensions) {
  const files = [];
  function visit(directory) {
    for (const entry of readdirSync(directory, { withFileTypes: true })) {
      if (ignoredPathParts.has(entry.name)) continue;
      const path = join(directory, entry.name);
      if (entry.isDirectory()) {
        visit(path);
        continue;
      }
      if (acceptedExtensions.has(extname(entry.name)) && !entry.name.includes('.test.') && !entry.name.includes('.spec.')) {
        files.push(path);
      }
    }
  }
  visit(root);
  return files;
}

function normalizeJsxText(value) {
  return value
    .split(/\r?\n/u)
    .map((line) => line.replace(/\s+/gu, ' ').trim())
    .filter(Boolean)
    .join(' ');
}

function templateSource(node) {
  let source = node.head.text;
  node.templateSpans.forEach((span, index) => {
    source += `{value${index}}${span.literal.text}`;
  });
  return source;
}

function collectTypeScriptMessages() {
  const messages = new Set();
  const files = sourceRoots.flatMap((directory) => listFiles(join(webRoot, directory), new Set(['.ts', '.tsx'])));
  for (const requestBoundary of ['proxy.ts', 'middleware.ts']) {
    const requestBoundaryPath = join(webRoot, requestBoundary);
    if (existsSync(requestBoundaryPath)) files.push(requestBoundaryPath);
  }

  for (const file of files) {
    if (file.includes(`${join(webRoot, 'i18n', 'messages')}`)) continue;
    const source = ts.createSourceFile(
      file,
      readFileSync(file, 'utf8'),
      ts.ScriptTarget.Latest,
      true,
      file.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS
    );
    function visit(node) {
      let value = null;
      if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) value = node.text;
      else if (ts.isTemplateExpression(node)) value = templateSource(node);
      else if (ts.isJsxText(node)) value = normalizeJsxText(node.getText(source));

      if (value && cjkPattern.test(value)) messages.add(value);
      ts.forEachChild(node, visit);
    }
    visit(source);
  }
  return messages;
}

/**
 * Collect only Python text that crosses a user-facing boundary.
 *
 * The backend contains many Chinese strings which are deliberately not Web
 * messages: parser regexes, provider prompts, internal invariant errors, and
 * persisted implementation details.  A language-agnostic "all constants"
 * scan turns those into catalog keys and makes the English catalog promise
 * translations for text that is never rendered by the Web application.
 *
 * This collector therefore recognizes the small set of call sites whose
 * arguments are public copy: HTTP error envelopes, system-event messages,
 * explicit localized text, and API metadata labels/descriptions.  Dynamic
 * values (for example `str(exc)`) stay out of the catalog until the backend
 * gives them a stable, explicitly catalogued contract.
 */
function collectPythonMessages(apiRoot = join(repositoryRoot, 'apps/api-python/app')) {
  const pythonSource = String.raw`
import ast
import json
from pathlib import Path
import re
import sys

root = Path(sys.argv[1])
messages = set()

def call_name(node):
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None

def static_message(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        value_index = 0
        for item in node.values:
            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                parts.append(item.value)
            elif isinstance(item, ast.FormattedValue):
                parts.append("{value%d}" % value_index)
                value_index += 1
            else:
                return None
        return "".join(parts)
    return None

def argument(call, keyword, positional_index=None):
    if keyword is not None:
        for item in call.keywords:
            if item.arg == keyword:
                return item.value
    if positional_index is not None and len(call.args) > positional_index:
        return call.args[positional_index]
    return None

def add_message(node):
    value = static_message(node)
    if value and re.search(r"[\u3400-\u9fff]", value):
        messages.add(value)

def message_arguments(call):
    name = call_name(call.func)
    if name == "fail" or name == "MessageError":
        return [argument(call, "message", 0)]
    if name == "UserAdministrationError":
        # The HTTP adapter exposes message; the first argument is an error code.
        return [argument(call, "message", 1)]
    if name and name.endswith("Body") and argument(call, "message") is not None:
        return [argument(call, "message")]
    if name in {"prepare_system_event", "_prepared_event"}:
        return [argument(call, "message")]
    if name == "_catalog_text":
        # The second argument is the canonical Chinese source; the third is
        # already the deliberate English rendering and is not a key.
        return [argument(call, None, 1)]
    if name == "LibraryFilterFieldDefinition":
        return [
            argument(call, "label", 1),
            argument(call, "group", 2),
            argument(call, "unit"),
        ]
    if name == "LibraryFilterOption":
        return [argument(call, "label", 1)]
    if name == "ProviderConfigField":
        return [argument(call, "label", 1), argument(call, "help")]
    if name == "ProviderManifest":
        return [argument(call, "name"), argument(call, "description")]
    if name == "ProviderTestResult":
        return [argument(call, "message")]
    if name == "health_check_item":
        return [argument(call, "message", 2)]
    if name == "suggestion_from_external":
        return [argument(call, "reason", 3)]
    if name == "_finish_without_match":
        return [argument(call, "message", 4)]
    return []

for path in root.rglob("*.py"):
    if "__pycache__" in path.parts or "tests" in path.parts:
        continue
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        continue
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for expression in message_arguments(node):
                if expression is not None:
                    add_message(expression)
print(json.dumps(sorted(messages), ensure_ascii=False))
`;
  const pythonExecutable = process.env.PYTHON_EXECUTABLE || 'python3';
  const output = execFileSync(pythonExecutable, ['-X', 'utf8', '-c', pythonSource, apiRoot], {
    encoding: 'utf8',
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' }
  });
  return new Set(JSON.parse(output));
}

function sortedCatalog(messages) {
  return Object.fromEntries(
    [...messages]
      .filter((message) => message.trim())
      .sort((left, right) => left.localeCompare(right, 'zh-CN'))
      .map((message) => [message, message])
  );
}

function run() {
  const messages = collectTypeScriptMessages();
  const readerCatalog = JSON.parse(readFileSync(join(repositoryRoot, 'packages/reader-contracts/reader-settings.json'), 'utf8'));
  const readerLabels = [
    ...readerCatalog.settings.map((setting) => setting.label),
    ...readerCatalog.sections.map((section) => section.label),
    ...Object.values(readerCatalog.optionGroups).flat().map((option) => option.label)
  ];
  for (const label of readerLabels) if (cjkPattern.test(label['zh-CN'])) messages.add(label['zh-CN']);
  for (const message of collectPythonMessages()) messages.add(message);
  const catalog = sortedCatalog(messages);
  const zhCatalogPath = join(webRoot, 'i18n/messages/zh-CN.json');
  const enCatalogPath = join(webRoot, 'i18n/messages/en-US.json');
  const writeMode = process.argv.includes('--write');

  if (writeMode) {
    writeFileSync(zhCatalogPath, `${JSON.stringify(catalog, null, 2)}\n`);
    process.stdout.write(`Wrote ${Object.keys(catalog).length} source messages to ${relative(repositoryRoot, zhCatalogPath)}\n`);
    return;
  }

  const zhCatalog = JSON.parse(readFileSync(zhCatalogPath, 'utf8'));
  const enCatalog = JSON.parse(readFileSync(enCatalogPath, 'utf8'));
  const expectedKeys = Object.keys(catalog);
  const missingSourceKeys = expectedKeys.filter((key) => !(key in zhCatalog));
  const missingEnglishKeys = expectedKeys.filter((key) => !(key in enCatalog));
  const staleSourceKeys = Object.keys(zhCatalog).filter((key) => !(key in catalog));
  const staleEnglishKeys = Object.keys(enCatalog).filter((key) => !(key in catalog));
  const mismatchedChineseValues = Object.entries(zhCatalog).filter(([key, value]) => key !== value);
  const untranslatedEnglishValues = Object.entries(enCatalog).filter(([, value]) => cjkPattern.test(value));
  const mismatchedPlaceholders = expectedKeys.flatMap((key) => {
    const sourcePlaceholders = Array.from(key.matchAll(interpolationPattern), (match) => match[1]).sort();
    const translated = enCatalog[key];
    if (typeof translated !== 'string') return [];
    const translatedPlaceholders = Array.from(translated.matchAll(interpolationPattern), (match) => match[1]).sort();
    return JSON.stringify(sourcePlaceholders) === JSON.stringify(translatedPlaceholders)
      ? []
      : [{ key, sourcePlaceholders, translatedPlaceholders }];
  });

  if (
    missingSourceKeys.length
    || missingEnglishKeys.length
    || staleSourceKeys.length
    || staleEnglishKeys.length
    || mismatchedChineseValues.length
    || untranslatedEnglishValues.length
    || mismatchedPlaceholders.length
  ) {
    process.stderr.write(JSON.stringify({
      missingSourceKeys,
      missingEnglishKeys,
      staleSourceKeys,
      staleEnglishKeys,
      mismatchedChineseValues,
      untranslatedEnglishValues,
      mismatchedPlaceholders
    }, null, 2));
    process.stderr.write('\n');
    process.exitCode = 1;
    return;
  }

  process.stdout.write(`Validated ${expectedKeys.length} messages across zh-CN and en-US catalogs\n`);
}

const isMainModule = process.argv[1] && resolve(process.argv[1]) === resolve(fileURLToPath(import.meta.url));
if (isMainModule) run();

export { collectPythonMessages, collectTypeScriptMessages, sortedCatalog };
