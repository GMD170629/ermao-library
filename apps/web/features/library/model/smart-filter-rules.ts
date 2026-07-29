import type { SmartFilterCondition, SmartFilterRules } from '../smart-filter-builder';

const VALUELESS_OPERATORS = new Set(['is_empty', 'is_not_empty', 'is_true', 'is_false']);

export function parseSmartFilterRules(value: string | null): SmartFilterRules {
  if (!value) return { combinator: 'ALL', conditions: [] };
  try {
    const parsed = JSON.parse(value) as {
      combinator?: string;
      conditions?: Array<{
        field?: string;
        operator?: string;
        value?: string | string[];
      }>;
    };
    const conditions = Array.isArray(parsed.conditions)
      ? parsed.conditions
          .filter((condition) => (
            condition
            && typeof condition.field === 'string'
            && typeof condition.operator === 'string'
          ))
          .slice(0, 30)
          .map((condition, index) => ({
            id: `route-filter-${index}`,
            field: condition.field as string,
            operator: condition.operator as string,
            value: condition.value
          }))
      : [];
    return {
      combinator: parsed.combinator === 'ANY' ? 'ANY' : 'ALL',
      conditions
    };
  } catch {
    return { combinator: 'ALL', conditions: [] };
  }
}

export function serializableSmartFilterRules(rules: SmartFilterRules) {
  return {
    combinator: rules.combinator,
    conditions: rules.conditions.map(({ field, operator, value }) => ({
      field,
      operator,
      ...(value === undefined ? {} : { value })
    }))
  };
}

export function smartFilterConditionComplete(condition: SmartFilterCondition) {
  if (VALUELESS_OPERATORS.has(condition.operator)) return true;
  if (condition.operator === 'between') {
    return Array.isArray(condition.value)
      && condition.value.length === 2
      && condition.value.every((item) => String(item).trim());
  }
  return !Array.isArray(condition.value) && Boolean(String(condition.value ?? '').trim());
}

export function applicableSmartFilterRules(rules: SmartFilterRules): SmartFilterRules {
  return {
    combinator: rules.combinator,
    conditions: rules.conditions.filter(smartFilterConditionComplete)
  };
}
