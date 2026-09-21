import type { InstallRequest, Package, ReleaseReference, GHCRReleaseReference, PreparationSummary, PreparationState, RuntimeInfo, UpdateCheck } from '@/generated/updates';
import { withBasePath } from '@/lib/base-path';

function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('更新响应无效');
  return value as Record<string, unknown>;
}
function string(value: unknown): string {
  if (typeof value !== 'string') throw new Error('更新响应无效');
  return value;
}
function number(value: unknown): number {
  if (typeof value !== 'number' || !Number.isSafeInteger(value) || value < 0) throw new Error('更新响应无效');
  return value;
}
function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('更新响应无效');
  return value;
}
const optional = (value: unknown) => value == null ? null : string(value);
export function parseRuntime(value: unknown): RuntimeInfo {
  const data = object(value);
  return { current_version: string(data.current_version), supported: boolean(data.supported), install_protocol: data.install_protocol == null ? 0 : number(data.install_protocol) };
}
function parsePackage(value: unknown): Package | ReleaseReference | GHCRReleaseReference {
  const data = object(value), environment = object(data.environment);
  if (![1, 2].includes(number(data.format)) || environment.format !== 1 || !/^[a-f0-9]{64}$/.test(string(data.sha256))) throw new Error('更新响应无效');
  const common = {
    version: string(data.version), sha256: string(data.sha256),
    filename: string(data.filename), size: number(data.size),
    environment: { format: 1 as const, platform: string(environment.platform), compatibility: string(environment.compatibility) }
  };
  if (data.format === 2 && data.oci_digest != null) {
    const oci_digest = string(data.oci_digest);
    if (!/^sha256:[a-f0-9]{64}$/.test(oci_digest)) throw new Error('更新响应无效');
    return { ...common, format: 2, oci_digest };
  }
  return data.format === 2 ? { ...common, format: 2 } : {
    ...common, format: 1, expanded_size: number(data.expanded_size), file_count: number(data.file_count)
  };
}
function parseSummary(value: unknown): PreparationSummary | null {
  if (value == null) return null;
  const data = object(value);
  return { ...(data.plan_sha256 == null ? {} : { plan_sha256: string(data.plan_sha256) }), dependency_identity: string(data.dependency_identity), baseline: string(data.baseline), code_sha256: string(data.code_sha256),
    keep: number(data.keep), install: number(data.install), remove: number(data.remove), total_bytes: number(data.total_bytes),
    dependency_bytes: number(data.dependency_bytes), verified_artifacts: number(data.verified_artifacts) };
}
export function parsePreparation(value: unknown): PreparationState {
  const data = object(value);
  const phase = string(data.phase);
  if (!['idle', 'downloading', 'verifying', 'extracting', 'ready', 'failed', 'requested', 'checking', 'stopping', 'backup', 'copying', 'starting', 'applied', 'success'].includes(phase)) throw new Error('更新响应无效');
  return { phase: phase as PreparationState['phase'], target: data.target == null ? null : parsePackage(data.target), summary: parseSummary(data.summary), downloaded: number(data.downloaded), started_at: optional(data.started_at), updated_at: optional(data.updated_at), failed_phase: optional(data.failed_phase), error: optional(data.error) };
}
export function parseCheck(value: unknown): UpdateCheck {
  const data = object(value);
  if (!Array.isArray(data.releases)) throw new Error('更新响应无效');
  return { ...parseRuntime(data), releases: data.releases.map(value => {
    const release = object(value);
    return { version: string(release.version), installable: boolean(release.installable), reason: optional(release.reason) };
  }) };
}
export class UpdateRequestError extends Error {
  constructor(readonly code: string) { super(code); }
}
async function request(path: string, signal?: AbortSignal, payload?: unknown): Promise<unknown> {
  const response = await fetch(withBasePath(`/api/updates/${path}`), {
    credentials: 'same-origin', cache: 'no-store', signal: signal ? AbortSignal.any([signal, AbortSignal.timeout(15_000)]) : AbortSignal.timeout(15_000),
    ...(payload === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  });
  const envelope = object(await response.json());
  if (!response.ok || envelope.ok !== true) {
    const error = object(envelope.error);
    throw new UpdateRequestError(typeof error.code === 'string' ? error.code : 'UPDATE_REQUEST_FAILED');
  }
  return envelope.data;
}
export const fetchRuntime = async (signal?: AbortSignal) => parseRuntime(await request('runtime', signal));
export const fetchUpdateCheck = async (signal?: AbortSignal) => parseCheck(await request('check', signal));
export const fetchUpdateState = async (signal?: AbortSignal) => parsePreparation(await request('status', signal));
export const prepareUpdate = async (version: string) => parsePreparation(await request('prepare', undefined, { version }));
export const installUpdate = async (identity: InstallRequest) => parsePreparation(await request('install', undefined, identity));
