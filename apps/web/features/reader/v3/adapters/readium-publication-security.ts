import type { FetchImplementation } from '@readium/shared';

const WEB_SECURITY_PROFILE = 'data-shuku-security-profile="web-v2"';
const REQUIRED_CSP_DIRECTIVES = [
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

async function assertSecureMarkup(response: Response) {
  const markup = await response.clone().text();
  if (!markup.includes(WEB_SECURITY_PROFILE)
    || REQUIRED_CSP_DIRECTIVES.some((directive) => !markup.includes(directive))) {
    throw new Error('READIUM_PUBLICATION_SECURITY_PROFILE_MISSING');
  }
}

/** Fails closed before Readium turns an authenticated resource into a blob document. */
export function createSecurePublicationFetch(fetchImplementation: FetchImplementation): FetchImplementation {
  return async (input, init) => {
    const response = await fetchImplementation(input, init);
    const method = init?.method?.toUpperCase() ?? 'GET';
    if (method === 'GET' && response.ok && isMarkup(response)) await assertSecureMarkup(response);
    return response;
  };
}
