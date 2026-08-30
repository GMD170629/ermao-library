import {
  READER_SAFETY_IMPLEMENTATION_FAILURE_CODES,
  READER_SAFETY_RULES,
  readerSafetyRule,
  type ReaderSafetyAction,
  type ReaderSafetyErrorCode,
  type ReaderSafetyImplementationFailureCode,
  type ReaderSafetyRuleId
} from './reader-safety-policy.generated';

export class ReaderSafetyPolicyError extends Error {
  constructor(
    readonly code: ReaderSafetyErrorCode,
    readonly ruleId: ReaderSafetyRuleId,
    readonly action: Extract<ReaderSafetyAction, 'BLOCK_RESOURCE' | 'REJECT_PUBLICATION'>,
    options?: ErrorOptions
  ) {
    super(code, options);
    this.name = 'ReaderSafetyPolicyError';
  }
}

export type ReaderSafetyFailure = Readonly<{
  code: ReaderSafetyErrorCode;
  ruleId: ReaderSafetyRuleId;
  action: Extract<ReaderSafetyAction, 'BLOCK_RESOURCE' | 'REJECT_PUBLICATION'>;
}>;

export class ReaderSafetyImplementationError extends Error {
  constructor(
    readonly code: ReaderSafetyImplementationFailureCode,
    readonly ruleId: ReaderSafetyRuleId,
    options?: ErrorOptions
  ) {
    super(code, options);
    this.name = 'ReaderSafetyImplementationError';
  }
}

function implementationFailureCode(
  owner: 'ENGINE' | 'PLATFORM'
): ReaderSafetyImplementationFailureCode {
  const code = READER_SAFETY_IMPLEMENTATION_FAILURE_CODES.find((candidate) => (
    candidate.startsWith(`${owner}_`)
  ));
  if (!code) throw new Error('READER_SAFETY_IMPLEMENTATION_CODE_MISSING');
  return code;
}

export function readerSafetyEngineAlgorithmUnsupported(
  ruleId: ReaderSafetyRuleId,
  options?: ErrorOptions
): never {
  throw new ReaderSafetyImplementationError(
    implementationFailureCode('ENGINE'),
    ruleId,
    options
  );
}

export function readerSafetyPlatformAlgorithmUnsupported(
  ruleId: ReaderSafetyRuleId,
  options?: ErrorOptions
): never {
  throw new ReaderSafetyImplementationError(
    implementationFailureCode('PLATFORM'),
    ruleId,
    options
  );
}

export function readerSafetyFailure(ruleId: ReaderSafetyRuleId): ReaderSafetyFailure {
  const rule = readerSafetyRule(ruleId);
  if ((rule.action !== 'REJECT_PUBLICATION' && rule.action !== 'BLOCK_RESOURCE') || !rule.errorCode) {
    throw new Error('PLATFORM_POLICY_BINDING_INVALID');
  }
  return { code: rule.errorCode, ruleId, action: rule.action };
}

export function rejectReaderSafety(ruleId: ReaderSafetyRuleId, options?: ErrorOptions): never {
  const failure = readerSafetyFailure(ruleId);
  throw new ReaderSafetyPolicyError(failure.code, failure.ruleId, failure.action, options);
}

export function isReaderSafetyRuleId(value: unknown): value is ReaderSafetyRuleId {
  return typeof value === 'string' && Object.prototype.hasOwnProperty.call(READER_SAFETY_RULES, value);
}

export function isReaderSafetyImplementationFailureCode(
  value: unknown
): value is ReaderSafetyImplementationFailureCode {
  return typeof value === 'string'
    && (READER_SAFETY_IMPLEMENTATION_FAILURE_CODES as readonly string[]).includes(value);
}

export function reviveReaderSafetyError(code: string, ruleId: unknown): Error {
  if (!isReaderSafetyRuleId(ruleId)) return new Error(code);
  if (isReaderSafetyImplementationFailureCode(code)) {
    return new ReaderSafetyImplementationError(code, ruleId);
  }
  const rule = readerSafetyRule(ruleId);
  if ((rule.action !== 'REJECT_PUBLICATION' && rule.action !== 'BLOCK_RESOURCE') || rule.errorCode !== code) {
    return new Error('PLATFORM_POLICY_BINDING_INVALID');
  }
  return new ReaderSafetyPolicyError(rule.errorCode, ruleId, rule.action);
}
