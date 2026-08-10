'use client';

import { useEffect, useRef, useState } from 'react';
import { Combobox } from '../../components/ui/combobox';
import { fetchLibraryFilterOptions } from './api/filtering';
import type {
  LibraryFilterOptionSource
} from './model/filter-schema';
import {
  FilterOptionSearchController,
  type FilterOptionSearchState
} from './model/filter-option-search';
import { useI18n } from '@/i18n/provider';

type AsyncFilterValueEditorProps = {
  source: LibraryFilterOptionSource;
  value: string;
  fieldLabel: string;
  onChange: (value: string) => void;
};

export function AsyncFilterValueEditor({
  source,
  value,
  fieldLabel,
  onChange
}: AsyncFilterValueEditorProps) {
  const { t, formatNumber } = useI18n();
  const [state, setState] = useState<FilterOptionSearchState>({ kind: 'idle', options: [] });
  const searchController = useRef<FilterOptionSearchController | null>(null);

  useEffect(() => {
    const controller = new FilterOptionSearchController(
      source,
      fetchLibraryFilterOptions,
      setState
    );
    searchController.current = controller;
    return () => {
      controller.dispose();
      if (searchController.current === controller) searchController.current = null;
    };
  }, [source]);

  const options = state.options.map((option) => ({
    value: option.value,
    label: `${option.label} · ${formatNumber(option.count ?? 0)}`,
    count: option.count,
    translate: false
  }));

  const status = state.kind === 'loading'
    ? t('正在搜索筛选建议...')
    : state.kind === 'indexing'
      ? t('标签索引正在构建，可继续使用当前输入值')
      : state.kind === 'error'
        ? t('筛选建议加载失败，可继续使用当前输入值')
        : state.kind === 'ready' && state.hasMore
          ? t('还有更多结果，请继续输入以缩小范围')
          : undefined;

  return (
    <Combobox
      value={value}
      options={options}
      loading={state.kind === 'loading'}
      status={status}
      onInputChange={(nextValue) => {
        searchController.current?.inputChanged(nextValue);
      }}
      onChange={(nextValue) => {
        searchController.current?.cancel();
        onChange(nextValue);
      }}
      placeholder={t('选择或输入{value0}', { value0: fieldLabel })}
      ariaLabel={t('{value0}筛选值', { value0: fieldLabel })}
    />
  );
}
