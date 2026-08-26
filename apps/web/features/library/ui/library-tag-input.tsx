'use client';

import { useEffect, useRef, useState } from 'react';
import { MultiValueCombobox } from '../../../components/ui/multi-value-combobox';
import { useI18n } from '@/i18n/provider';
import { fetchLibraryFilterOptions } from '../api/filtering';
import {
  FilterOptionSearchController,
  type FilterOptionSearchState
} from '../model/filter-option-search';
import { normalizeTagValue, parseTagValues } from '../model/tag-values';

export type LibraryTagInputProps = Readonly<{
  values: readonly string[];
  onValuesChange: (values: string[]) => void;
  placeholder: string;
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
}>;

export function LibraryTagInput({
  values,
  onValuesChange,
  placeholder,
  ariaLabel,
  className,
  disabled = false
}: LibraryTagInputProps) {
  const { t, formatNumber } = useI18n();
  const [state, setState] = useState<FilterOptionSearchState>({ kind: 'idle', options: [] });
  const searchController = useRef<FilterOptionSearchController | null>(null);

  useEffect(() => {
    const controller = new FilterOptionSearchController(
      'tags',
      fetchLibraryFilterOptions,
      setState
    );
    searchController.current = controller;
    controller.search('');
    return () => {
      controller.dispose();
      if (searchController.current === controller) searchController.current = null;
    };
  }, []);

  const options = state.options.map((option) => ({
    value: option.value,
    label: `${option.label} · ${formatNumber(option.count ?? 0)}`
  }));
  const status = state.kind === 'loading'
    ? t('正在搜索标签...')
    : state.kind === 'indexing'
      ? t('标签索引正在构建，可继续输入新标签')
      : state.kind === 'error'
        ? t('标签建议加载失败，可继续输入新标签')
        : state.kind === 'ready' && state.hasMore
          ? t('还有更多标签，请继续输入以缩小范围')
          : undefined;

  return (
    <MultiValueCombobox
      values={values}
      options={options}
      onValuesChange={onValuesChange}
      onQueryChange={(query) => searchController.current?.search(query)}
      onQueryReset={() => searchController.current?.reset()}
      onOpenChange={(open) => {
        if (!open) searchController.current?.reset();
      }}
      parseInput={parseTagValues}
      getValueKey={normalizeTagValue}
      placeholder={t(placeholder)}
      ariaLabel={t(ariaLabel)}
      className={className}
      disabled={disabled}
      loading={state.kind === 'loading'}
      status={status}
      emptyMessage={t('没有可选择的标签，可直接输入新标签')}
    />
  );
}
