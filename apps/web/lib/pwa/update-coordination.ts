export const BEFORE_PWA_UPDATE_EVENT = 'shuku:before-pwa-update';

export type BeforePwaUpdateDetail = {
  waitUntil: (task: Promise<unknown>) => void;
};

export function createPwaUpdatePreparation() {
  const tasks: Promise<unknown>[] = [];
  const detail: BeforePwaUpdateDetail = {
    waitUntil(task) {
      tasks.push(Promise.resolve(task));
    }
  };
  return {
    detail,
    wait: () => Promise.allSettled(tasks).then(() => undefined)
  };
}

export async function prepareForPwaUpdate(target: Window = window, timeoutMs = 5_000) {
  const preparation = createPwaUpdatePreparation();
  target.dispatchEvent(new CustomEvent<BeforePwaUpdateDetail>(BEFORE_PWA_UPDATE_EVENT, {
    detail: preparation.detail
  }));
  await Promise.race([
    preparation.wait(),
    new Promise<void>((resolve) => { setTimeout(resolve, timeoutMs); })
  ]);
}
