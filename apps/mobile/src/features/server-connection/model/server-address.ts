export type ServerAddressErrorCode =
  | 'CREDENTIALS_NOT_ALLOWED'
  | 'DEVICE_LOOPBACK_NOT_ALLOWED'
  | 'EMPTY'
  | 'INSECURE_REMOTE_NOT_ALLOWED'
  | 'INVALID'
  | 'QUERY_OR_FRAGMENT_NOT_ALLOWED'
  | 'UNSUPPORTED_SCHEME';

export type ServerBaseUrl = Readonly<{
  value: string;
  hostname: string;
  protocol: 'http:' | 'https:';
  security: 'https' | 'local-http';
}>;

export type ParseServerAddressResult =
  | Readonly<{ ok: true; baseUrl: ServerBaseUrl }>
  | Readonly<{ ok: false; code: ServerAddressErrorCode }>;

const URI_SCHEME_PREFIX = /^[A-Za-z][A-Za-z0-9+.-]*:/;
const NUMERIC_PORT_PREFIX = /^[0-9]{1,5}(?:[/?#]|$)/;

function addressHasExplicitScheme(
  candidate: string,
  schemeMatch: RegExpExecArray | null,
): boolean {
  if (schemeMatch === null) {
    return false;
  }

  const normalizedScheme = schemeMatch[0].toLowerCase();
  if (normalizedScheme === 'http:' || normalizedScheme === 'https:') {
    return true;
  }

  const remainder = candidate.slice(schemeMatch[0].length);
  return !NUMERIC_PORT_PREFIX.test(remainder);
}

function normalizedHostname(url: URL): string {
  const hostname = url.hostname.toLowerCase();
  return hostname.startsWith('[') && hostname.endsWith(']')
    ? hostname.slice(1, -1)
    : hostname;
}

function ipv4Octets(hostname: string): readonly number[] | null {
  const parts = hostname.split('.');
  if (parts.length !== 4) {
    return null;
  }

  const octets: number[] = [];
  for (const part of parts) {
    if (!/^[0-9]{1,3}$/.test(part)) {
      return null;
    }
    const octet = Number(part);
    if (octet > 255) {
      return null;
    }
    octets.push(octet);
  }
  return octets;
}

function isLoopbackHost(hostname: string): boolean {
  if (
    hostname === 'localhost' ||
    hostname.endsWith('.localhost') ||
    hostname === '::1'
  ) {
    return true;
  }

  const octets = ipv4Octets(hostname);
  return octets?.[0] === 127;
}

function isLocalNetworkHost(hostname: string): boolean {
  if (hostname.endsWith('.local') || !hostname.includes('.')) {
    return true;
  }

  const octets = ipv4Octets(hostname);
  if (octets !== null) {
    const first = octets[0];
    const second = octets[1];
    if (first === undefined || second === undefined) {
      return false;
    }
    return (
      first === 10 ||
      (first === 172 && second >= 16 && second <= 31) ||
      (first === 192 && second === 168) ||
      (first === 169 && second === 254) ||
      (first === 100 && second >= 64 && second <= 127)
    );
  }

  const firstIpv6Group = hostname.split(':')[0]?.toLowerCase();
  if (firstIpv6Group === undefined) {
    return false;
  }
  const firstIpv6Value = Number.parseInt(firstIpv6Group, 16);
  return (
    Number.isFinite(firstIpv6Value) &&
    ((firstIpv6Value >= 0xfc00 && firstIpv6Value <= 0xfdff) ||
      (firstIpv6Value >= 0xfe80 && firstIpv6Value <= 0xfebf))
  );
}

export function parseServerAddress(
  candidate: string,
): ParseServerAddressResult {
  const trimmed = candidate.trim();
  if (trimmed.length === 0) {
    return { ok: false, code: 'EMPTY' };
  }

  const schemeMatch = URI_SCHEME_PREFIX.exec(trimmed);
  const hasExplicitScheme = addressHasExplicitScheme(trimmed, schemeMatch);
  if (
    hasExplicitScheme &&
    schemeMatch !== null &&
    schemeMatch[0].toLowerCase() !== 'http:' &&
    schemeMatch[0].toLowerCase() !== 'https:'
  ) {
    return { ok: false, code: 'UNSUPPORTED_SCHEME' };
  }

  let url: URL;
  try {
    url = new URL(
      hasExplicitScheme ? trimmed : `http://${trimmed}`,
    );
  } catch (cause: unknown) {
    if (cause instanceof TypeError) {
      return { ok: false, code: 'INVALID' };
    }
    throw cause;
  }

  if (url.protocol !== 'http:' && url.protocol !== 'https:') {
    return { ok: false, code: 'UNSUPPORTED_SCHEME' };
  }
  if (url.username.length > 0 || url.password.length > 0) {
    return { ok: false, code: 'CREDENTIALS_NOT_ALLOWED' };
  }
  if (url.search.length > 0 || url.hash.length > 0) {
    return {
      ok: false,
      code: 'QUERY_OR_FRAGMENT_NOT_ALLOWED',
    };
  }

  const hostname = normalizedHostname(url);
  if (hostname.length === 0) {
    return { ok: false, code: 'INVALID' };
  }
  if (isLoopbackHost(hostname)) {
    return {
      ok: false,
      code: 'DEVICE_LOOPBACK_NOT_ALLOWED',
    };
  }
  if (url.protocol === 'http:' && !isLocalNetworkHost(hostname)) {
    return {
      ok: false,
      code: 'INSECURE_REMOTE_NOT_ALLOWED',
    };
  }

  const basePath = url.pathname.replace(/\/+$/, '');
  return {
    ok: true,
    baseUrl: {
      value: `${url.origin}${basePath}`,
      hostname,
      protocol: url.protocol,
      security: url.protocol === 'https:' ? 'https' : 'local-http',
    },
  };
}

export function serverHealthUrl(baseUrl: ServerBaseUrl): string {
  return `${baseUrl.value}/api/health`;
}
