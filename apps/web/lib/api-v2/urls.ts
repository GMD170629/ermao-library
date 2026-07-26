import { withBasePath } from '../base-path';

function id(value: string) {
  return encodeURIComponent(value);
}

export const apiV2Url = {
  account: () => '/api/v2/account',
  backup: (backupId: string) => `/api/v2/operations/backups/${id(backupId)}`,
  backups: () => '/api/v2/operations/backups',
  catalogWork: (workId: string) => `/api/v2/catalog/works/${id(workId)}`,
  catalogWorks: () => '/api/v2/catalog/works',
  editionResource: (editionId: string) =>
    withBasePath(`/api/v2/reading/editions/${id(editionId)}/resource`),
  health: () => '/api/v2/operations/health',
  imports: () => '/api/v2/ingestion/imports',
  login: () => '/api/v2/auth/login',
  logout: () => '/api/v2/auth/logout',
  readerBootstrap: (editionId: string) =>
    `/api/v2/reading/editions/${id(editionId)}/bootstrap`,
  setup: () => '/api/v2/auth/setup',
  setupStatus: () => '/api/v2/auth/setup/status',
  shelves: () => '/api/v2/catalog/shelves'
} as const;
