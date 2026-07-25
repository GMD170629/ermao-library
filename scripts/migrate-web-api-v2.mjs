#!/usr/bin/env node
import { readFile, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import process from 'node:process';

const repoRoot = process.cwd();
const webRoot = path.join(repoRoot, 'apps/web');
const sourceExtensions = new Set(['.ts', '.tsx', '.js', '.mjs']);
const excludedDirectories = new Set(['.next', 'node_modules', 'generated']);
const directFetchExclusions = new Set([
  'lib/api-v2/client.ts',
  'lib/auth-session.ts'
]);
const routeMappings = [
  ['/api/auth/password-reset/request', '/api/v2/auth/password-reset/request'],
  ['/api/auth/password-reset/confirm', '/api/v2/auth/password-reset/confirm'],
  ['/api/auth/setup/status', '/api/v2/auth/setup/status'],
  ['/api/auth/capabilities', '/api/v2/auth/capabilities'],
  ['/api/auth/preferences', '/api/v2/account/preferences'],
  ['/api/auth/account', '/api/v2/account'],
  ['/api/auth/avatar', '/api/v2/account/avatar'],
  ['/api/auth/login', '/api/v2/auth/login'],
  ['/api/auth/logout', '/api/v2/auth/logout'],
  ['/api/auth/setup', '/api/v2/auth/setup'],
  ['/api/auth/me', '/api/v2/account'],
  ['/api/admin/users', '/api/v2/admin/users'],
  ['/api/reader/v2/editions', '/api/v2/reading/editions'],
  ['/api/kindle-send-tasks', '/api/v2/delivery/kindle/jobs'],
  ['/api/kindle-settings', '/api/v2/delivery/kindle/settings'],
  ['/api/email-settings', '/api/v2/delivery/email/settings'],
  ['/api/monitor-folders', '/api/v2/ingestion/folders'],
  ['/api/import-tasks', '/api/v2/ingestion/imports'],
  ['/api/system/queue-operations', '/api/v2/operations/queue-operations'],
  ['/api/system/log-settings', '/api/v2/operations/log-settings'],
  ['/api/system/health', '/api/v2/operations/health'],
  ['/api/system/queues', '/api/v2/operations/queues'],
  ['/api/system-settings', '/api/v2/operations/settings'],
  ['/api/management/overview', '/api/v2/reporting/management'],
  ['/api/management/events', '/api/v2/operations/events'],
  ['/api/dashboard', '/api/v2/reporting/dashboard'],
  ['/api/metadata', '/api/v2/metadata'],
  ['/api/organize', '/api/v2/metadata'],
  ['/api/library', '/api/v2/catalog'],
  ['/api/backups', '/api/v2/operations/backups'],
  ['/api/series', '/api/v2/catalog/series'],
  ['/api/shelves', '/api/v2/catalog/shelves'],
  ['/api/works', '/api/v2/catalog/works'],
  ['/api/editions', '/api/v2/reading/editions'],
  ['/api/volumes', '/api/v2/reading/volumes'],
  ['/api/files', '/api/v2/reading/files'],
  ['/api/app-config', '/api/v2/operations/settings'],
  ['/api/health', '/api/v2/operations/health']
];

async function sourceFiles(directory) {
  const entries = await readdir(directory, { withFileTypes: true });
  const nested = await Promise.all(entries.map(async (entry) => {
    if (entry.isDirectory()) {
      if (excludedDirectories.has(entry.name)) return [];
      return sourceFiles(path.join(directory, entry.name));
    }
    return sourceExtensions.has(path.extname(entry.name)) ? [path.join(directory, entry.name)] : [];
  }));
  return nested.flat();
}

function addClientImport(source) {
  const importLine = "import { apiV2Fetch } from '@/lib/api-v2';";
  if (source.includes(importLine)) return source;
  const directive = /^(['"])use client\1;\r?\n/;
  const match = source.match(directive);
  if (match) return `${match[0]}\n${importLine}\n${source.slice(match[0].length)}`;
  return `${importLine}\n${source}`;
}

for (const file of await sourceFiles(webRoot)) {
  const relative = path.relative(webRoot, file).replaceAll(path.sep, '/');
  let source = await readFile(file, 'utf8');
  let updated = source;
  for (const [legacy, v2] of routeMappings) updated = updated.replaceAll(legacy, v2);
  const isTest = relative.includes('/e2e/') || /\.test\.[^.]+$/.test(relative);
  if (!isTest && !directFetchExclusions.has(relative) && /\bfetch\s*\(/.test(updated)) {
    updated = updated.replace(/\bfetch\s*\(/g, 'apiV2Fetch(');
    updated = addClientImport(updated);
  }
  if (updated !== source) await writeFile(file, updated, 'utf8');
}
