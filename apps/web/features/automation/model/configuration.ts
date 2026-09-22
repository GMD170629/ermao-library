import type { Scope, ServiceSettingsFields } from '../../../generated/automation';

export const scopeLabels: Record<Scope, string> = {
  'library:read': '查询书库', 'shelves:write': '管理个人书架', 'tags:write': '整理标签',
  'metadata:write': '更新系统元数据', 'metadata:override': '覆盖人工保护字段',
  'files:read': '读取文件元数据', 'files:move': '移动和整理文件', 'metadata:writeback': '写回文件元数据'
};
export const scopes = Object.keys(scopeLabels).filter((key): key is Scope => key in scopeLabels);
export type ServiceSettings = Required<ServiceSettingsFields>;
export type LibraryChoice = { id: string; name: string };

export function connectionUrl(settings: ServiceSettings): string {
  return settings.publicBaseUrl ? `${settings.publicBaseUrl.replace(/\/$/u, '')}/api/mcp` : '';
}

export type McpClient = "codex" | "lm-studio" | "cursor";

export function clientTemplate(url: string, token?: string, client: McpClient = "codex"): string {
  if (client === "codex") return `[mcp_servers.ermao-library]\nurl = ${JSON.stringify(url)}\nhttp_headers = { Authorization = ${JSON.stringify(`Bearer ${token ?? "<ERMAO_TOKEN>"}`)} }\n`;
  return JSON.stringify({ mcpServers: { 'ermao-library': { url, headers: { Authorization: `Bearer ${token ?? '<ERMAO_TOKEN>'}` } } } }, null, 2);
}

export function selectedScopes(previous: Scope[], scope: Scope, enabled: boolean): Scope[] {
  const next = new Set(previous);
  if (enabled) {
    next.add(scope);
    if (scope === 'files:move' || scope === 'metadata:writeback') next.add('files:read');
    if (scope === 'metadata:override' && !next.has('tags:write')) next.add('metadata:write');
  } else {
    next.delete(scope);
    if (scope === 'files:read') { next.delete('files:move'); next.delete('metadata:writeback'); }
    if (!next.has('metadata:write') && !next.has('tags:write')) next.delete('metadata:override');
  }
  next.add('library:read');
  return scopes.filter((value) => next.has(value));
}

export function operationStatusLabel(status: string): string {
  switch (status) {
    case 'QUEUED': return '等待执行';
    case 'RUNNING': case 'PREPARING': return '正在执行';
    case 'PREPARED': return '文件已准备';
    case 'FILES_PUBLISHED': return '正在同步索引';
    case 'COMPLETED': return '已完成';
    case 'CANCELLED': return '已取消';
    case 'FAILED': return '失败';
    case 'PARTIAL': return '部分完成';
    case 'RECOVERY_REQUIRED': return '需要恢复';
    default: return '状态待确认';
  }
}
export function canCancelOperation(status: string): boolean {
  return !['COMPLETED', 'CANCELLED', 'FAILED', 'PARTIAL', 'RECOVERY_REQUIRED'].includes(status);
}
