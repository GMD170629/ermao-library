type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

export type ApplicationReachabilityProbe = () => Promise<boolean>;

const DEFAULT_PROBE_TIMEOUT_MS = 4_000;

export async function resolveApplicationOnline(
  browserReportsOnline: boolean,
  probeApplicationReachability: ApplicationReachabilityProbe
): Promise<boolean> {
  if (browserReportsOnline) return true;
  return probeApplicationReachability();
}

export async function probeApplicationReachability(
  endpoint: string,
  fetcher: FetchLike = fetch,
  timeoutMs = DEFAULT_PROBE_TIMEOUT_MS
): Promise<boolean> {
  const controller = new AbortController();
  let timeout: ReturnType<typeof setTimeout> | undefined;

  try {
    const request = fetcher(endpoint, {
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal
    }).then(
      () => true,
      () => false
    );
    const timedOut = new Promise<boolean>((resolve) => {
      timeout = setTimeout(() => {
        controller.abort();
        resolve(false);
      }, timeoutMs);
    });

    return await Promise.race([request, timedOut]);
  } finally {
    if (timeout) clearTimeout(timeout);
  }
}
