import type { Scope, ServiceSettingsFields } from '../../../generated/automation';

export const scopeLabels: Record<Scope, string> = {
  'system:read': '基础查询', 'system:manage': '系统管理',
  'books:write': '更新图书元数据', 'shelves:write': '更新书架',
  'files:upload': '上传图书', 'files:modify': '修改图书文件'
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
  if (enabled) next.add(scope); else next.delete(scope);
  next.add('system:read');
  return scopes.filter((value) => next.has(value));
}

export function operationStatusLabel(status: string): string {
  switch (status) {
    case 'STAGING': return '正在准备删除';
    case 'STAGED': return '等待删除';
    case 'FILES_DELETED': return '文件已删除';
    case 'INDEX_PENDING': return '等待索引更新';
    case 'INDEX_FAILED': return '索引更新失败';
    case 'RECEIVING': return '正在接收附件';
    case 'UPLOADED': return '传输完成';
    case 'PUBLISHING': return '正在保存文件';
    case 'SAVED': return '文件已保存';
    case 'IMPORTING': return '正在导入';
    case 'EXPIRED': return '已过期';
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
export function canCancelOperation(status: string, kind?: string): boolean {
  if (kind === "book_upload" || kind === "cover_upload") return ["RECEIVING", "UPLOADED"].includes(status);
  return !['COMPLETED', 'CANCELLED', 'FAILED', 'PARTIAL', 'RECOVERY_REQUIRED'].includes(status);
}
