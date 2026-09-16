import type { InstallRequest } from '@/generated/updates';

// Capture the displayed package before opening the dialog, not after it closes.
export async function confirmUpdate(
  operation: 'prepare' | 'install', target: InstallRequest,
  confirm: () => Promise<boolean>,
  submit: (operation: 'prepare' | 'install', identity: InstallRequest) => Promise<void>
) {
  const identity = { version: target.version, sha256: target.sha256, ...(target.plan_sha256 ? { plan_sha256: target.plan_sha256 } : {}) };
  if (await confirm()) await submit(operation, identity);
}
