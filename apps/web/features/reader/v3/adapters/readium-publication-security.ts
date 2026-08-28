import { readBoundedResponse } from '../../../../shared/api/bounded-response';
import type { FetchImplementation } from '@readium/shared';

class PublicationReadError extends Error {
  constructor(readonly code: 'PUBLICATION_CHANGED' | 'PUBLICATION_RESOURCE_TOO_LARGE'
    | 'PUBLICATION_RESOURCE_UNAVAILABLE' | 'READIUM_PUBLICATION_SECURITY_PROFILE_MISSING') {
    super(code);
  }
}

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
    throw new PublicationReadError('READIUM_PUBLICATION_SECURITY_PROFILE_MISSING');
  }
}

/** Fails closed before Readium turns an authenticated resource into a blob document. */
export function createSecurePublicationFetch(fetchImplementation: FetchImplementation): FetchImplementation {
  let revision: string | null = null;
  return async (input, init) => {
    const headers = new Headers(init?.headers);
    if (revision) headers.set('X-Publication-Revision', revision);
    const response = await fetchImplementation(input, { ...init, headers });
    if (!response.ok) {
      await response.body?.cancel();
      throw new PublicationReadError(response.status === 409 || response.status === 412
        ? 'PUBLICATION_CHANGED' : response.status === 413
          ? 'PUBLICATION_RESOURCE_TOO_LARGE' : 'PUBLICATION_RESOURCE_UNAVAILABLE');
    }
    const observedRevision = response.headers.get('X-Publication-Revision');
    if (revision && observedRevision !== revision) {
      await response.body?.cancel();
      throw new PublicationReadError('PUBLICATION_CHANGED');
    }
    if (observedRevision) revision ??= observedRevision;
    const method = init?.method?.toUpperCase() ?? 'GET';
    if (method === 'HEAD') { await response.body?.cancel(); return response; }
    try {
      if (isMarkup(response)) assertSecureMarkupResponse(response);
    } catch (error) { await response.body?.cancel(error); throw error; }
    const maxBytes = isMarkup(response) || response.headers.get('content-type')?.includes('json')
      ? 8 * 1024 * 1024 : 32 * 1024 * 1024;
    const bytes = await readBoundedResponse(response, maxBytes);
    const responseHeaders = new Headers(response.headers);
    responseHeaders.delete('content-encoding');
    responseHeaders.set('content-length', String(bytes.byteLength));
    return new Response(bytes, { status: response.status, headers: responseHeaders });
  };
}
