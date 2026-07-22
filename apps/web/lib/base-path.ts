const configuredBasePath = (process.env.NEXT_PUBLIC_BASE_PATH ?? '').trim();

export const APP_BASE_PATH = configuredBasePath && configuredBasePath !== '/'
  ? `/${configuredBasePath.replace(/^\/+|\/+$/g, '')}`
  : '';

export function withBasePath(path: string) {
  if (!APP_BASE_PATH || !path.startsWith('/')) return path;
  if (path === APP_BASE_PATH || path.startsWith(`${APP_BASE_PATH}/`)) return path;
  return `${APP_BASE_PATH}${path}`;
}
