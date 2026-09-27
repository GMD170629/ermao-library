import type { ManagementEvent } from './api/events';

function object(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown> : {};
}

function cell(value: unknown): string {
  const text = value === null || value === undefined ? ''
    : typeof value === 'object' ? JSON.stringify(value) : String(value);
  // A quoted CSV cell alone does not prevent spreadsheet formula execution.
  const literal = /^[=+\-@\t\r]/u.test(text) ? `'${text}` : text;
  return `"${literal.replaceAll('"', '""')}"`;
}

export function systemEventsCsv(
  events: ManagementEvent[],
  locale: string,
  translate: (message: string) => string,
): string {
  const headers = [
    '时间', '级别', '来源', '摘要', '动作', '关联类型', '事件标识', '关联标识',
    '诊断标识', '执行阶段', '异常类型', '直接原因', '根本原因', '原因状态',
    '抛出位置', '异常链', '堆栈信息', 'SQL 与参数', '完整元数据',
  ];
  const levels: Record<string, string> = { info: '信息', warning: '警告', warn: '警告', error: '错误' };
  const sources: Record<string, string> = { import: '导入', download: '下载', folder: '书库', library: '书库', system: '系统' };
  const rows = events.map((event) => {
    const metadata = event.metadata;
    const diagnostic = object(metadata.diagnostics);
    return [
      new Date(event.createdAt).toLocaleString(locale),
      translate(levels[event.level] ?? event.level),
      translate(sources[event.source] ?? event.source),
      event.message, event.action, event.targetType, event.id, event.targetId,
      diagnostic.id, metadata.stage ?? metadata.step ?? diagnostic.stage,
      diagnostic.exceptionType, diagnostic.directCause, diagnostic.rootCause,
      diagnostic.causeStatus ?? 'NOT_RECORDED', diagnostic.location,
      diagnostic.chain, diagnostic.traceback, diagnostic.databaseOperations,
      // Preserve every stored field, including SQL, parameters and correlations.
      metadata,
    ].map(cell).join(',');
  });
  return `\uFEFF${[headers.map((header) => cell(translate(header))).join(','), ...rows].join('\r\n')}`;
}
