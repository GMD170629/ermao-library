import type { FetchImplementation } from '@readium/shared';

const REQUIRED_CSP_DIRECTIVES = [
  "default-src 'none'",
  "connect-src 'none'",
  "form-action 'none'",
  "frame-src 'none'",
  "object-src 'none'",
  'script-src blob:',
] as const;

function isMarkup(response: Response) {
  const mediaType = response.headers.get('content-type')?.split(';', 1)[0]?.trim().toLowerCase();
  return mediaType === 'application/xhtml+xml' || mediaType === 'text/html';
}

function assertSecureMarkupResponse(response: Response) {
  const contentSecurityPolicy = response.headers.get('content-security-policy') ?? '';
  const contentTypeOptions = response.headers.get('x-content-type-options')?.toLowerCase();
  if (contentTypeOptions !== 'nosniff'
    || REQUIRED_CSP_DIRECTIVES.some((directive) => !contentSecurityPolicy.includes(directive))) {
    throw new Error('READIUM_PUBLICATION_SECURITY_PROFILE_MISSING');
  }
}

/** Fails closed before Readium turns an authenticated resource into a blob document. */
export function createSecurePublicationFetch(fetchImplementation: FetchImplementation): FetchImplementation {
  return async (input, init) => {
    const response = await fetchImplementation(input, init);
    const method = init?.method?.toUpperCase() ?? 'GET';
    if (method === 'GET' && response.ok && isMarkup(response)) assertSecureMarkupResponse(response);
    return response;
  };
}
