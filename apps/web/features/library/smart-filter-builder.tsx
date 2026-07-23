'use client';

import { Database, Plus, RotateCcw, Trash2, WandSparkles } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '../../components/ui/cn';
import { Combobox } from '../../components/ui/combobox';
import { Select } from '../../components/ui/select';
import { I18nText } from '@/i18n/provider';
import { useI18n as useAttributeI18n } from '@/i18n/provider';

export type SmartFilterOption = {
  value: string;
  label: string;
  count?: number;
  rootPath?: string;
};

export type SmartFilterField = {
  key: string;
  label: string;
  group: string;
  type: 'text' | 'select' | 'number' | 'date' | 'boolean';
  operators: string[];
  options?: SmartFilterOption[];
  allowCustom?: boolean;
  unit?: string;
};

export type SmartFilterCondition = {
  id: string;
  field: string;
  operator: string;
  value?: string | string[];
};

export type SmartFilterRules = {
  combinator: 'ALL' | 'ANY';
  conditions: SmartFilterCondition[];
};

type SmartFilterBuilderProps = {
  fields: SmartFilterField[];
  rules: SmartFilterRules;
  loading?: boolean;
  actions?: ReactNode;
  onChange: (rules: SmartFilterRules) => void;
};

const operatorLabels: Record<string, string> = {
  contains: '包含',
  not_contains: '不包含',
  equals: '等于',
  not_equals: '不等于',
  starts_with: '开头是',
  ends_with: '结尾是',
  greater_than: '大于',
  greater_or_equal: '大于等于',
  less_than: '小于',
  less_or_equal: '小于等于',
  after: '晚于',
  on_or_after: '不早于',
  before: '早于',
  on_or_before: '不晚于',
  between: '介于',
  is_empty: '为空',
  is_not_empty: '不为空',
  is_true: '是',
  is_false: '否'
};

function nextConditionId() {
  return `filter-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function createSmartFilterCondition(fields: SmartFilterField[]): SmartFilterCondition {
  const field = fields[0];
  return {
    id: nextConditionId(),
    field: field?.key ?? 'title',
    operator: field?.operators[0] ?? 'contains',
    value: ''
  };
}

function needsValue(operator: string) {
  return !['is_empty', 'is_not_empty', 'is_true', 'is_false'].includes(operator);
}

function inputClassName() {
  return 'h-11 min-w-0 rounded-xl border border-black/[0.09] bg-white px-3 text-sm text-[#34302D] outline-none transition focus:border-[#EFAE9B] focus:ring-2 focus:ring-[#F9D8CE]';
}

export function SmartFilterBuilder({ fields, rules, loading = false, actions, onChange }: SmartFilterBuilderProps) {
  const { t: i18nAttribute } = useAttributeI18n();
  const fieldOptions = fields.map((field) => ({ value: field.key, label: field.label, group: field.group }));

  function addCondition() {
    onChange({ ...rules, conditions: [...rules.conditions, createSmartFilterCondition(fields)] });
  }

  function updateCondition(id: string, patch: Partial<SmartFilterCondition>) {
    onChange({
      ...rules,
      conditions: rules.conditions.map((condition) => condition.id === id ? { ...condition, ...patch } : condition)
    });
  }

  function changeField(condition: SmartFilterCondition, fieldKey: string) {
    const field = fields.find((item) => item.key === fieldKey);
    if (!field) return;
    updateCondition(condition.id, {
      field: fieldKey,
      operator: field.operators[0],
      value: field.operators[0] === 'between' ? ['', ''] : ''
    });
  }

  function changeOperator(condition: SmartFilterCondition, operator: string) {
    updateCondition(condition.id, {
      operator,
      value: operator === 'between' ? ['', ''] : needsValue(operator) ? (Array.isArray(condition.value) ? '' : condition.value ?? '') : undefined
    });
  }

  function removeCondition(id: string) {
    onChange({ ...rules, conditions: rules.conditions.filter((condition) => condition.id !== id) });
  }

  function valueEditor(condition: SmartFilterCondition, field: SmartFilterField) {
    if (!needsValue(condition.operator)) {
      return <div className="flex h-11 items-center rounded-xl bg-black/[0.025] px-3 text-sm text-[#8A837D]"><I18nText>无需填写值</I18nText></div>;
    }
    if (condition.operator === 'between') {
      const values = Array.isArray(condition.value) ? condition.value : ['', ''];
      const type = field.type === 'date' ? 'date' : 'number';
      return (
        <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-2">
          <input aria-label={i18nAttribute("{value0}起始值", { value0: field.label })} type={type} value={values[0] ?? ''} onChange={(event) => updateCondition(condition.id, { value: [event.target.value, values[1] ?? ''] })} className={inputClassName()} />
          <span className="text-xs text-[#9B938D]"><I18nText>至</I18nText></span>
          <input aria-label={i18nAttribute("{value0}结束值", { value0: field.label })} type={type} value={values[1] ?? ''} onChange={(event) => updateCondition(condition.id, { value: [values[0] ?? '', event.target.value] })} className={inputClassName()} />
        </div>
      );
    }
    const value = Array.isArray(condition.value) ? condition.value[0] ?? '' : condition.value ?? '';
    if (field.type === 'select' && !field.allowCustom) {
      return (
        <Select
          value={value}
          options={(field.options ?? []).map((option) => ({
            value: option.value,
            label: `${option.label}${typeof option.count === 'number' ? ` · ${option.count}` : ''}`
          }))}
          onChange={(nextValue) => updateCondition(condition.id, { value: nextValue })}
          placeholder={i18nAttribute("请选择")}
          ariaLabel={i18nAttribute("{value0}筛选值", { value0: field.label })}
          className="w-full min-w-0"
          triggerClassName="!h-11 !rounded-xl !border-black/[0.09] !px-3 !font-normal !text-[#34302D]"
        />
      );
    }
    if (field.type === 'select') {
      return (
        <Combobox
          value={value}
          options={(field.options ?? []).map((option) => ({
            value: option.value,
            label: `${option.label}${typeof option.count === 'number' ? ` · ${option.count}` : ''}`
          }))}
          onChange={(nextValue) => updateCondition(condition.id, { value: nextValue })}
          placeholder={i18nAttribute("选择或输入{value0}", { value0: field.label })}
          ariaLabel={i18nAttribute("{value0}筛选值", { value0: field.label })}
        />
      );
    }
    return (
      <div className="relative">
        <input
          aria-label={i18nAttribute("{value0}筛选值", { value0: field.label })}
          type={field.type === 'number' ? 'number' : field.type === 'date' ? 'date' : 'text'}
          value={value}
          onChange={(event) => updateCondition(condition.id, { value: event.target.value })}
          className={cn(inputClassName(), 'w-full', field.unit && 'pr-14')}
          placeholder={i18nAttribute("填写{value0}", { value0: field.label })}
        />
        {field.unit ? <span className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[#938B85]">{field.unit}</span> : null}
      </div>
    );
  }

  return (
    <section className="mt-3 overflow-hidden rounded-[22px] border border-black/[0.07] bg-white/70 shadow-[0_10px_30px_rgba(59,44,36,0.035)]" aria-label={i18nAttribute("智能组合筛选")}>
      <div className="flex flex-col gap-4 border-b border-black/[0.06] px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-[#FFF0EA] text-[#DE4C2E]"><WandSparkles size={18} /></span>
          <div>
            <div className="font-semibold text-[#302C29]"><I18nText>智能组合筛选</I18nText></div>
            <div className="mt-0.5 text-xs leading-5 text-[#817A74]"><I18nText>所有作品、版本、文件、阅读和书架维度都可以自由组合，修改后实时生效。</I18nText></div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          <span className="text-xs text-[#8A837D]"><I18nText>匹配</I18nText></span>
          <Select
            value={rules.combinator}
            options={[{ value: 'ALL', label: '全部条件' }, { value: 'ANY', label: '任一条件' }]}
            onChange={(combinator) => onChange({ ...rules, combinator })}
            ariaLabel={i18nAttribute("筛选条件组合方式")}
            size="sm"
            className="min-w-[128px]"
            triggerClassName="!h-10 !rounded-xl !border-black/[0.09] !px-3 !text-sm"
          />
          <button type="button" disabled={loading || fields.length === 0 || rules.conditions.length >= 30} onClick={addCondition} className="inline-flex h-10 items-center gap-2 rounded-xl bg-[#2E2A27] px-3.5 text-sm font-medium text-white transition hover:bg-[#161412] disabled:cursor-not-allowed disabled:opacity-40"><Plus size={15} /><I18nText>添加条件</I18nText></button>
        </div>
      </div>

      <div className="space-y-2.5 p-4 sm:p-5">
        {loading ? <div className="flex min-h-28 items-center justify-center text-sm text-[#8A837D]"><I18nText>正在读取可筛选维度...</I18nText></div> : null}
        {!loading && rules.conditions.length === 0 ? (
          <button type="button" onClick={addCondition} className="flex min-h-28 w-full flex-col items-center justify-center rounded-2xl border border-dashed border-[#DCD5CE] bg-[#FAF8F6] px-6 text-center transition hover:border-[#E4A692] hover:bg-[#FFF8F5]">
            <Database size={20} className="text-[#B0A69E]" />
            <span className="mt-2 text-sm font-medium text-[#5E5752]"><I18nText>添加第一个筛选条件</I18nText></span>
            <span className="mt-1 text-xs text-[#928A83]"><I18nText>可按元数据、格式、阅读、书架、加入时间或原始文件夹筛选</I18nText></span>
          </button>
        ) : null}
        {!loading && rules.conditions.map((condition, index) => {
          const field = fields.find((item) => item.key === condition.field) ?? fields[0];
          if (!field) return null;
          return (
            <div key={condition.id} className="grid gap-2 rounded-2xl border border-black/[0.055] bg-[#FCFBF9] p-3 md:grid-cols-[34px_minmax(170px,0.85fr)_minmax(132px,0.62fr)_minmax(190px,1.35fr)_42px] md:items-center">
              <span className="hidden h-7 w-7 items-center justify-center rounded-lg bg-black/[0.04] text-xs font-semibold text-[#7B746E] md:flex">{index + 1}</span>
              <Select
                value={condition.field}
                options={fieldOptions}
                onChange={(fieldKey) => changeField(condition, fieldKey)}
                ariaLabel={i18nAttribute("第 {value0} 条筛选维度", { value0: index + 1 })}
                className="w-full min-w-0"
                triggerClassName="!h-11 !rounded-xl !border-black/[0.09] !px-3 !font-normal !text-[#34302D]"
                menuWidth={280}
              />
              <Select
                value={condition.operator}
                options={field.operators.map((operator) => ({ value: operator, label: operatorLabels[operator] ?? operator }))}
                onChange={(operator) => changeOperator(condition, operator)}
                ariaLabel={i18nAttribute("第 {value0} 条筛选条件", { value0: index + 1 })}
                className="w-full min-w-0"
                triggerClassName="!h-11 !rounded-xl !border-black/[0.09] !px-3 !font-normal !text-[#34302D]"
              />
              <div className="min-w-0">{valueEditor(condition, field)}</div>
              <button type="button" onClick={() => removeCondition(condition.id)} className="flex h-10 w-10 items-center justify-center rounded-xl text-[#9A928B] transition hover:bg-red-50 hover:text-red-600" aria-label={i18nAttribute("删除第 {value0} 条筛选条件", { value0: index + 1 })}><Trash2 size={16} /></button>
            </div>
          );
        })}
      </div>

      <div className="flex flex-col gap-3 border-t border-black/[0.055] bg-black/[0.018] px-4 py-3 text-xs text-[#7C756F] sm:flex-row sm:items-center sm:justify-between sm:px-5">
        <span>{rules.conditions.length > 0 ? i18nAttribute("已启用 {value0} 条规则 · {value1}", { value0: rules.conditions.length, value1: rules.combinator === 'ALL' ? '同时满足全部条件' : '满足任意一条即可' }) : i18nAttribute("未添加组合条件，显示基础筛选结果")}</span>
        <button type="button" disabled={rules.conditions.length === 0} onClick={() => onChange({ combinator: 'ALL', conditions: [] })} className="inline-flex h-9 items-center gap-1.5 self-start rounded-lg px-2.5 font-medium text-[#7B746E] transition hover:bg-white hover:text-[#D74A2D] disabled:cursor-not-allowed disabled:opacity-35 sm:self-auto"><RotateCcw size={13} /><I18nText>清空组合条件</I18nText></button>
      </div>
    </section>
  );
}
