import type { InstallRequest, PreparationState } from '@/generated/updates';

export const installationPhases = new Set(['requested', 'checking', 'stopping', 'backup', 'copying', 'starting']);
export const preparationPhases = new Set(['downloading', 'verifying', 'extracting']);
// Preflight (300s), stop (120s), backup (60s), startup (180s), plus copying/reconnection margin.
export const observationTimeoutMs = 20 * 60_000;
export const pollIntervalMs = 3_000;
export function confirmedSuccess(state: PreparationState, current: string, expected?: InstallRequest | null) {
  return state.phase === 'success' && !!state.target && state.target.version === current
    && (!expected || (state.target.version === expected.version && state.target.sha256 === expected.sha256));
}
export function installationFailed(state: PreparationState) {
  return state.phase === 'failed' && !preparationPhases.has(state.failed_phase ?? '');
}

export function canInstall(state: PreparationState | null, protocol: number | undefined) {
  return state?.phase === 'ready' && !!state.target && state.target.format === protocol;
}
