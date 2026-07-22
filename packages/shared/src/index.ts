export type ReaderItemKind = 'comic' | 'epub';

export interface HealthResponse {
  status: 'ok' | 'error';
  service: string;
}
