import { closeSync, mkdirSync, openSync, readFileSync, readdirSync, unlinkSync, writeSync } from 'node:fs';
import { join } from 'node:path';
import { randomUUID } from 'node:crypto';

/** One raw exception output for the Next.js server runtime. */
const recorded = new WeakSet<object>();

const levels = ['debug', 'info', 'warning', 'error'] as const;
type LogLevel = typeof levels[number];

function dayName(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
}

export function writeServerLog(level: LogLevel, message: string, metadata: Record<string, unknown> = {}): void {
  const root = join(process.env.STORAGE_ROOT || '/app/storage', 'logs');
  let settings: { retentionDays: number; minimumLevel: LogLevel } = { retentionDays: 3, minimumLevel: 'error' };
  try {
    settings = JSON.parse(readFileSync(join(root, 'settings.json'), 'utf8'));
  } catch (error) {
    if (!(error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT')) throw error;
  }
  if (!Number.isInteger(settings.retentionDays) || settings.retentionDays < 1 || settings.retentionDays > 365 || !levels.includes(settings.minimumLevel)) {
    throw new Error('Invalid daily log settings');
  }
  if (levels.indexOf(level) < levels.indexOf(settings.minimumLevel)) return;
  const now = new Date();
  const directory = join(root, 'web');
  mkdirSync(directory, { recursive: true });
  const cutoff = new Date(now);
  cutoff.setDate(cutoff.getDate() - settings.retentionDays + 1);
  for (const name of readdirSync(directory)) {
    if (/^\d{4}-\d{2}-\d{2}\.jsonl$/.test(name) && name.slice(0, 10) < dayName(cutoff)) {
      try { unlinkSync(join(directory, name)); } catch (error) {
        if (!(error && typeof error === 'object' && 'code' in error && error.code === 'ENOENT')) throw error;
      }
    }
  }
  const output = Buffer.from(JSON.stringify({
    id: `web_${randomUUID()}`, createdAt: now.toISOString(), level, source: 'web',
    actorType: 'system', actorId: null, action: 'runtime.message', message, metadata,
  }) + '\n', 'utf8');
  const file = openSync(join(directory, `${dayName(now)}.jsonl`), 'a');
  try {
    // One append syscall keeps complete records together across Node processes.
    if (writeSync(file, output) !== output.length) throw new Error('Incomplete daily log append');
  } finally {
    closeSync(file);
  }
}

function formatServerException(error: unknown): string {
  const seen = new Set<unknown>();
  const pending = [error];
  const lines: string[] = [];
  while (pending.length) {
    const current = pending.pop();
    if (seen.has(current)) continue;
    seen.add(current);
    try {
      if (current instanceof Error) {
        lines.push(current.stack ?? `${current.name}: ${current.message}`);
        if (current.cause !== undefined) pending.push(current.cause);
        if (current instanceof AggregateError) pending.push(...[...current.errors].reverse());
      } else {
        lines.push(String(current));
      }
    } catch (formattingError) {
      try {
        lines.push(current instanceof Error ? `${current.name}: ${current.message}` : String(current));
      } catch (messageError) {
        lines.push('[exception could not be formatted]');
        pending.push(messageError);
      }
      pending.push(formattingError);
    }
  }
  return `${lines.join('\n')}\n`;
}

export function recordServerException(error: unknown): void {
  if (typeof error === 'object' && error !== null) {
    if (recorded.has(error)) return;
    recorded.add(error);
  }
  const output = formatServerException(error);
  try {
    writeServerLog('error', error instanceof Error ? error.message : String(error), { diagnostics: { traceback: output } });
  } catch (fileError) {
    try { writeSync(2, output + formatServerException(fileError)); } catch {
      // Preserve the original failure when both physical outlets are unavailable.
    }
  }
  try {
    process.stderr.write(output);
  } catch (writeError) {
    try {
      writeSync(2, output + formatServerException(writeError));
    } catch {
      // Both physical outputs are unavailable; retain the original exit behavior.
    }
  }
}

export function installServerExceptionObserver(): void {
  Error.stackTraceLimit = Infinity;
  // A monitor observes fatal failures without taking over Node's exit behavior.
  if (!process.listeners('uncaughtExceptionMonitor').includes(recordServerException)) {
    process.on('uncaughtExceptionMonitor', recordServerException);
  }
}
