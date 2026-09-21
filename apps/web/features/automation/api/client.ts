import type { CreateGrantRequest, CreatedGrantPayload, GrantView, ManagedOperationFields, Scope, WritebackTarget } from '../../../generated/automation';
import { readBoundedResponse } from '../../../shared/api/bounded-response';
import { scopes, type LibraryChoice, type ServiceSettings } from '../model/configuration';

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}
function record(value: unknown): Record<string, unknown> {
  if (!isRecord(value)) throw new Error('INVALID_AUTOMATION_RESPONSE');
  return value;
}
function text(value: unknown): string {
  if (typeof value !== 'string') throw new Error('INVALID_AUTOMATION_RESPONSE');
  return value;
}
function number(value: unknown): number {
  if (typeof value !== 'number' || !Number.isFinite(value)) throw new Error('INVALID_AUTOMATION_RESPONSE');
  return value;
}
function boolean(value: unknown): boolean {
  if (typeof value !== 'boolean') throw new Error('INVALID_AUTOMATION_RESPONSE');
  return value;
}
function strings(value: unknown): string[] {
  if (!Array.isArray(value)) throw new Error('INVALID_AUTOMATION_RESPONSE');
  return value.map(text);
}
function permissions(value: unknown): Scope[] {
  return strings(value).map((value) => {
    const scope = scopes.find((scope) => scope === value);
    if (!scope) throw new Error('INVALID_AUTOMATION_RESPONSE');
    return scope;
  });
}
function targets(value: unknown): WritebackTarget[] {
  return strings(value).map((value) => {
    if (value !== 'sidecar' && value !== 'embedded') throw new Error('INVALID_AUTOMATION_RESPONSE');
    return value;
  });
}
export function parseGrant(value: unknown): GrantView {
  const data = record(value);
  return { id: text(data.id), name: text(data.name), scopes: permissions(data.scopes), libraryIds: strings(data.libraryIds),
    writebackTargets: targets(data.writebackTargets), allowCrossLibrary: boolean(data.allowCrossLibrary),
    createdAtMs: number(data.createdAtMs), expiresAtMs: number(data.expiresAtMs),
    revokedAtMs: data.revokedAtMs === null ? null : number(data.revokedAtMs),
    lastUsedAtMs: data.lastUsedAtMs === null ? null : number(data.lastUsedAtMs) };
}
export function parseSettings(value: unknown): ServiceSettings {
  const data = record(value);
  return { enabled: boolean(data.enabled), enabledScopes: permissions(data.enabledScopes),
    publicBaseUrl: text(data.publicBaseUrl), allowInsecureHttp: boolean(data.allowInsecureHttp) };
}
export function parseOperation(value: unknown): ManagedOperationFields {
  const data = record(value);
  if (!Array.isArray(data.targets)) throw new Error('INVALID_AUTOMATION_RESPONSE');
  return { operation_id: text(data.operation_id), grant_id: text(data.grant_id), kind: text(data.kind),
    created_at_ms: number(data.created_at_ms), status: text(data.status), cancel_requested: boolean(data.cancel_requested),
    total_targets: number(data.total_targets), targets: data.targets.map((value: unknown) => {
      const target = record(value);
      return { stage: text(target.stage), relative_path: text(target.relative_path),
        destination_relative_path: target.destination_relative_path === null ? null : text(target.destination_relative_path),
        error_code: target.error_code === null ? null : text(target.error_code) };
    }) };
}
export async function loadOperations(signal: AbortSignal): Promise<ManagedOperationFields[]> {
  const result = await request('/api/automation/operations', signal);
  if (!Array.isArray(result.operations)) throw new Error('INVALID_AUTOMATION_RESPONSE');
  return result.operations.map(parseOperation);
}
export async function cancelOperation(id: string, signal: AbortSignal): Promise<ManagedOperationFields> {
  const result = await request(`/api/automation/operations/${encodeURIComponent(id)}/cancel`, signal, 'POST');
  return parseOperation(result.operation);
}
async function request(path: string, signal: AbortSignal, method = 'GET', body?: unknown): Promise<Record<string, unknown>> {
  const response = await fetch(path, { signal, method, credentials: 'same-origin', cache: 'no-store',
    headers: body === undefined ? undefined : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body) });
  const payload: unknown = JSON.parse(new TextDecoder().decode(await readBoundedResponse(response, 2 * 1024 ** 2)));
  const envelope = record(payload);
  if (!response.ok || envelope.ok !== true) throw new Error('AUTOMATION_REQUEST_FAILED');
  return record(envelope.data);
}
export async function loadAutomation(signal: AbortSignal) {
  const [settings, grants, libraries, operations] = await Promise.all([
    request('/api/automation/settings', signal), request('/api/automation/grants', signal), request('/api/libraries?purpose=upload', signal), loadOperations(signal)
  ]);
  if (!Array.isArray(grants.grants) || !Array.isArray(libraries.libraries)) throw new Error('INVALID_AUTOMATION_RESPONSE');
  const choices: LibraryChoice[] = libraries.libraries.map((value: unknown) => {
    const library = record(value); return { id: text(library.id), name: text(library.name) };
  });
  return { settings: parseSettings(settings), grants: grants.grants.map(parseGrant), libraries: choices, operations };
}
export async function createGrant(input: CreateGrantRequest, signal: AbortSignal): Promise<CreatedGrantPayload> {
  const result = await request('/api/automation/grants', signal, 'POST', input);
  return { grant: parseGrant(result.grant), token: text(result.token) };
}
export async function revokeGrant(id: string, signal: AbortSignal): Promise<void> {
  const result = await request(`/api/automation/grants/${encodeURIComponent(id)}`, signal, 'DELETE');
  if (result.revoked !== true) throw new Error('INVALID_AUTOMATION_RESPONSE');
}
export async function saveSettings(settings: ServiceSettings, signal: AbortSignal): Promise<ServiceSettings> {
  return parseSettings(await request('/api/automation/settings', signal, 'PUT', settings));
}
