export type FrontendResourceStatus = {
  latestVersion: string;
  updateRequired: boolean;
};

type FetchLike = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

function record(value: unknown): Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function withTimeout<T>(task: Promise<T>, timeoutMs: number, message: string) {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(message)), timeoutMs);
    task.then(
      (value) => { clearTimeout(timer); resolve(value); },
      (reason: unknown) => { clearTimeout(timer); reject(reason); }
    );
  });
}

export function decodeFrontendResourceStatus(value: unknown): FrontendResourceStatus {
  const envelope = record(value);
  const data = record(envelope.data);
  const frontendResources = record(data.frontendResources);
  if (
    envelope.ok !== true
    || typeof frontendResources.latestVersion !== 'string'
    || !/^\d+\.\d+\.\d+$/u.test(frontendResources.latestVersion)
    || typeof frontendResources.updateRequired !== 'boolean'
  ) {
    throw new Error('前端资源版本响应无效');
  }
  return {
    latestVersion: frontendResources.latestVersion,
    updateRequired: frontendResources.updateRequired
  };
}

export function requestServiceWorkerVersion(worker: ServiceWorker, timeoutMs = 2_000) {
  return new Promise<string>((resolve, reject) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => {
      channel.port1.close();
      reject(new Error('读取前端资源版本超时'));
    }, timeoutMs);
    channel.port1.onmessage = (event: MessageEvent<unknown>) => {
      clearTimeout(timer);
      channel.port1.close();
      const version = record(event.data).version;
      if (typeof version === 'string' && /^\d+\.\d+\.\d+$/u.test(version)) resolve(version);
      else reject(new Error('前端资源版本无效'));
    };
    try {
      worker.postMessage({ type: 'GET_FRONTEND_RESOURCE_VERSION' }, [channel.port2]);
    } catch (reason) {
      clearTimeout(timer);
      channel.port1.close();
      reject(reason);
    }
  });
}

export async function checkFrontendResourceVersion(
  worker: ServiceWorker,
  endpoint: string,
  fetcher: FetchLike = fetch,
  workerTimeoutMs = 2_000
) {
  const currentVersion = await requestServiceWorkerVersion(worker, workerTimeoutMs).catch(() => 'legacy-cache');
  const response = await fetcher(endpoint, {
    cache: 'no-store',
    credentials: 'same-origin',
    headers: { 'X-Shuku-Frontend-Resource-Version': currentVersion }
  });
  if (!response.ok) throw new Error('暂时无法检查前端资源版本');
  return {
    currentVersion,
    status: decodeFrontendResourceStatus(await response.json() as unknown)
  };
}

function waitUntilInstalled(worker: ServiceWorker) {
  if (worker.state === 'installed') return Promise.resolve(worker);
  return new Promise<ServiceWorker>((resolve, reject) => {
    const handleStateChange = () => {
      if (worker.state === 'installed') {
        worker.removeEventListener('statechange', handleStateChange);
        resolve(worker);
      } else if (worker.state === 'redundant') {
        worker.removeEventListener('statechange', handleStateChange);
        reject(new Error('新版前端资源安装失败'));
      }
    };
    worker.addEventListener('statechange', handleStateChange);
  });
}

export async function waitForLatestWorker(
  registration: ServiceWorkerRegistration,
  latestVersion: string,
  timeoutMs = 20_000
) {
  if (registration.waiting) {
    const waitingVersion = await requestServiceWorkerVersion(registration.waiting).catch(() => '');
    if (waitingVersion === latestVersion) return registration.waiting;
  }

  let resolveFound: ((worker: ServiceWorker) => void) | null = null;
  const found = new Promise<ServiceWorker>((resolve) => { resolveFound = resolve; });
  const handleUpdateFound = () => {
    if (registration.installing) resolveFound?.(registration.installing);
  };
  registration.addEventListener('updatefound', handleUpdateFound);

  try {
    const updatePromise = registration.update().then(() => registration.waiting ?? registration.installing);
    const candidate = await withTimeout(Promise.race([
      updatePromise.then((worker) => worker ?? found),
      found
    ]), timeoutMs, '下载新版前端资源超时');
    const installed = await withTimeout(
      waitUntilInstalled(candidate), timeoutMs, '安装新版前端资源超时'
    );
    const installedVersion = await requestServiceWorkerVersion(installed);
    if (installedVersion !== latestVersion) throw new Error('前后端资源版本不一致');
    return installed;
  } finally {
    registration.removeEventListener('updatefound', handleUpdateFound);
  }
}

export function purgeFrontendResourcesAndActivate(worker: ServiceWorker, timeoutMs = 8_000) {
  return new Promise<void>((resolve, reject) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => {
      channel.port1.close();
      reject(new Error('激活新版前端资源超时'));
    }, timeoutMs);
    channel.port1.onmessage = (event: MessageEvent<unknown>) => {
      clearTimeout(timer);
      channel.port1.close();
      if (record(event.data).ok === true) resolve();
      else reject(new Error('清理旧前端资源失败'));
    };
    try {
      worker.postMessage({ type: 'PURGE_FRONTEND_RESOURCES_AND_ACTIVATE' }, [channel.port2]);
    } catch (reason) {
      clearTimeout(timer);
      channel.port1.close();
      reject(reason);
    }
  });
}
