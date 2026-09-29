export type FeedbackKind = 'suggestion' | 'issue';

export type FeedbackContact = { qq: string; groupName: string; email: string };
export type InstallationMethod = 'app-store' | 'manual' | 'docker';

export type FeedbackClientEnvironment = {
  client: 'web' | 'pwa';
  userAgent: string;
  platform: string;
  languages: string[];
  locale: 'zh-CN' | 'en-US';
  timeZone: string;
  viewport: string;
  screen: string;
  devicePixelRatio: number;
  colorDepth: number;
  page: string;
};

export type FeedbackDraft = {
  kind: FeedbackKind;
  markdown: string;
  contact: FeedbackContact;
  includeEnvironment: boolean;
  installationMethod: InstallationMethod | null;
  clientEnvironment: FeedbackClientEnvironment | null;
  eventId: string | null;
  files: { name: string; size: number; sha256: string }[];
};

export type FeedbackPreview = {
  diagnostics: Record<string, unknown>;
  previewHash: string;
};

export type FeedbackEnvironment = { appVersion: string };
export type FeedbackReceipt = { id: string; status: 'sent' };

export class FeedbackApiError extends Error {
  constructor(message: string, readonly code: string) { super(message); }
}

function object(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function readData(response: Response): Promise<unknown> {
  const payload: unknown = await response.json().catch(() => null);
  if (!response.ok || !object(payload) || payload.ok !== true) {
    const error = object(payload) && object(payload.error) ? payload.error : null;
    throw new FeedbackApiError(typeof error?.message === 'string' ? error.message : '反馈暂时不可用', typeof error?.code === 'string' ? error.code : 'FEEDBACK_UNAVAILABLE');
  }
  return payload.data;
}

export async function fetchFeedbackEnvironment(signal?: AbortSignal): Promise<FeedbackEnvironment> {
  const data = await readData(await fetch('/api/feedback/environment', { credentials: 'same-origin', cache: 'no-store', signal }));
  if (!object(data) || typeof data.appVersion !== 'string') throw new FeedbackApiError('系统环境信息无效', 'FEEDBACK_BAD_RESPONSE');
  return { appVersion: data.appVersion };
}

export async function previewFeedback(draft: FeedbackDraft, signal?: AbortSignal): Promise<FeedbackPreview> {
  const data = await readData(await fetch('/api/feedback/preview', {
    method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(draft), signal
  }));
  if (!object(data) || !object(data.diagnostics) || typeof data.previewHash !== 'string') throw new FeedbackApiError('反馈预览无效', 'FEEDBACK_BAD_RESPONSE');
  return { diagnostics: data.diagnostics, previewHash: data.previewHash };
}

export async function submitFeedback(draft: FeedbackDraft, previewHash: string, submissionKey: string, files: File[], signal?: AbortSignal): Promise<FeedbackReceipt> {
  const body = new FormData();
  body.set('draft', JSON.stringify({ ...draft, previewHash, submissionKey }));
  for (const file of files) body.append('files', file, file.name);
  const data = await readData(await fetch('/api/feedback', { method: 'POST', credentials: 'same-origin', body, signal }));
  if (!object(data) || typeof data.id !== 'string' || data.status !== 'sent') throw new FeedbackApiError('反馈回执无效', 'FEEDBACK_BAD_RESPONSE');
  return { id: data.id, status: 'sent' };
}
