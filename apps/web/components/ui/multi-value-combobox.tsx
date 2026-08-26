'use client';

import { ChevronDown, Plus, X } from 'lucide-react';
import type {
  FocusEvent as ReactFocusEvent,
  KeyboardEvent as ReactKeyboardEvent,
  ReactNode
} from 'react';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useI18n } from '@/i18n/provider';
import { cn } from './cn';

export type MultiValueComboboxOption = Readonly<{
  value: string;
  label: string;
  disabled?: boolean;
}>;

type MenuPosition = Readonly<{
  left: number;
  top: number;
  width: number;
  maxHeight: number;
}>;

type MultiValueComboboxProps = Readonly<{
  values: readonly string[];
  options: readonly MultiValueComboboxOption[];
  onValuesChange: (values: string[]) => void;
  onQueryChange?: (query: string) => void;
  onQueryReset?: () => void;
  onOpenChange?: (open: boolean) => void;
  parseInput?: (input: string) => string[];
  getValueKey?: (value: string) => string;
  placeholder?: string;
  ariaLabel: string;
  className?: string;
  disabled?: boolean;
  loading?: boolean;
  status?: ReactNode;
  emptyMessage?: ReactNode;
}>;

function defaultValueKey(value: string): string {
  return value.trim().toLocaleLowerCase();
}

function defaultParseInput(input: string): string[] {
  const value = input.trim();
  return value ? [value] : [];
}

function mergeValues(
  currentValues: readonly string[],
  candidates: readonly string[],
  getValueKey: (value: string) => string
): string[] {
  const nextValues = [...currentValues];
  const seen = new Set(currentValues.map(getValueKey).filter(Boolean));
  for (const candidate of candidates) {
    const value = candidate.trim();
    const key = getValueKey(value);
    if (!value || !key || seen.has(key)) continue;
    seen.add(key);
    nextValues.push(value);
  }
  return nextValues;
}

export function MultiValueCombobox({
  values,
  options,
  onValuesChange,
  onQueryChange,
  onQueryReset,
  onOpenChange,
  parseInput = defaultParseInput,
  getValueKey = defaultValueKey,
  placeholder = '选择或输入',
  ariaLabel,
  className,
  disabled = false,
  loading = false,
  status,
  emptyMessage
}: MultiValueComboboxProps) {
  const { t } = useI18n();
  const [query, setQuery] = useState('');
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  const selectedKeys = useMemo(
    () => new Set(values.map(getValueKey).filter(Boolean)),
    [getValueKey, values]
  );
  const queryKey = getValueKey(query);
  const availableOptions = useMemo(() => options.filter((option) => {
    if (selectedKeys.has(getValueKey(option.value))) return false;
    if (!queryKey) return true;
    return getValueKey(`${option.label} ${option.value}`).includes(queryKey);
  }), [getValueKey, options, queryKey, selectedKeys]);
  const exactOption = queryKey
    ? options.find((option) => getValueKey(option.value) === queryKey || getValueKey(option.label) === queryKey)
    : undefined;
  const canCreate = Boolean(query.trim() && queryKey && !selectedKeys.has(queryKey) && !exactOption);
  const rowCount = availableOptions.length + (canCreate ? 1 : 0);

  const setMenuOpen = useCallback((nextOpen: boolean) => {
    setOpen(nextOpen);
    onOpenChange?.(nextOpen);
    if (!nextOpen) setActiveIndex(-1);
  }, [onOpenChange]);

  const clearQuery = useCallback(() => {
    setQuery('');
    onQueryReset?.();
    setActiveIndex(-1);
  }, [onQueryReset]);

  const commitInput = useCallback((input: string) => {
    const candidates = parseInput(input).map((candidate) => {
      const candidateKey = getValueKey(candidate);
      const canonicalOption = options.find((option) => (
        getValueKey(option.value) === candidateKey || getValueKey(option.label) === candidateKey
      ));
      return canonicalOption?.value ?? candidate;
    });
    const nextValues = mergeValues(values, candidates, getValueKey);
    if (nextValues.length !== values.length) onValuesChange(nextValues);
    clearQuery();
  }, [clearQuery, getValueKey, onValuesChange, options, parseInput, values]);

  const selectOption = useCallback((option: MultiValueComboboxOption) => {
    if (option.disabled) return;
    const nextValues = mergeValues(values, [option.value], getValueKey);
    if (nextValues.length !== values.length) onValuesChange(nextValues);
    clearQuery();
    inputRef.current?.focus();
  }, [clearQuery, getValueKey, onValuesChange, values]);

  useEffect(() => {
    if (!open) return;
    function closeOnOutside(event: MouseEvent) {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (rootRef.current?.contains(target) || menuRef.current?.contains(target)) return;
      commitInput(query);
      setMenuOpen(false);
    }
    document.addEventListener('mousedown', closeOnOutside);
    return () => document.removeEventListener('mousedown', closeOnOutside);
  }, [commitInput, open, query, setMenuOpen]);

  useEffect(() => {
    if (!open) {
      setMenuPosition(null);
      return;
    }
    function positionMenu() {
      const root = rootRef.current;
      if (!root) return;
      const rect = root.getBoundingClientRect();
      const viewportPadding = 12;
      const gap = 8;
      const width = Math.min(Math.max(rect.width, 240), window.innerWidth - viewportPadding * 2);
      const desiredHeight = Math.min(288, Math.max(64, rowCount * 42 + (status ? 44 : 12)));
      const availableBelow = window.innerHeight - rect.bottom - gap - viewportPadding;
      const availableAbove = rect.top - gap - viewportPadding;
      const openUpwards = availableBelow < Math.min(desiredHeight, 176) && availableAbove > availableBelow;
      const maxHeight = Math.max(112, Math.min(desiredHeight, openUpwards ? availableAbove : availableBelow));
      const renderedHeight = Math.min(desiredHeight, maxHeight);
      const left = Math.max(viewportPadding, Math.min(rect.left, window.innerWidth - width - viewportPadding));
      const top = openUpwards ? Math.max(viewportPadding, rect.top - gap - renderedHeight) : rect.bottom + gap;
      setMenuPosition({ left, top, width, maxHeight });
    }
    positionMenu();
    window.addEventListener('resize', positionMenu);
    window.addEventListener('scroll', positionMenu, true);
    return () => {
      window.removeEventListener('resize', positionMenu);
      window.removeEventListener('scroll', positionMenu, true);
    };
  }, [open, rowCount, status]);

  function openMenu() {
    if (open) return;
    setMenuOpen(true);
    onQueryChange?.(query);
  }

  function removeValue(index: number) {
    onValuesChange(values.filter((_value, valueIndex) => valueIndex !== index));
    inputRef.current?.focus();
  }

  function onInputBlur(event: ReactFocusEvent<HTMLInputElement>) {
    const nextTarget = event.relatedTarget;
    if (nextTarget instanceof Node && (rootRef.current?.contains(nextTarget) || menuRef.current?.contains(nextTarget))) return;
    commitInput(query);
    setMenuOpen(false);
  }

  function onInputKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing) return;
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      openMenu();
      if (rowCount === 0) return;
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex((current) => {
        const start = current < 0 ? (direction === 1 ? -1 : 0) : current;
        return (start + direction + rowCount) % rowCount;
      });
      return;
    }
    if (event.key === 'Enter') {
      event.preventDefault();
      if (activeIndex >= 0) {
        if (canCreate && activeIndex === 0) commitInput(query);
        else {
          const option = availableOptions[activeIndex - (canCreate ? 1 : 0)];
          if (option) selectOption(option);
        }
      } else {
        commitInput(query);
      }
      return;
    }
    if (/^[,，;；]$/u.test(event.key)) {
      event.preventDefault();
      commitInput(query);
      return;
    }
    if (event.key === 'Backspace' && !query && values.length > 0) {
      event.preventDefault();
      removeValue(values.length - 1);
      return;
    }
    if (event.key === 'Escape') {
      event.stopPropagation();
      setMenuOpen(false);
    }
  }

  const activeOptionId = activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined;

  return (
    <div className={cn('relative min-w-0', className)}>
      <div
        ref={rootRef}
        className={cn(
          'flex min-h-11 w-full flex-wrap items-center gap-1.5 rounded-xl border border-black/[0.09] bg-white px-2 py-1.5 pr-10 text-[#34302D] outline-none transition focus-within:border-[#EFAE9B] focus-within:ring-2 focus-within:ring-[#F9D8CE]',
          disabled && 'cursor-not-allowed opacity-50'
        )}
        onMouseDown={(event) => {
          if (disabled || event.target instanceof HTMLButtonElement) return;
          event.preventDefault();
          inputRef.current?.focus();
          openMenu();
        }}
      >
        {values.map((value, index) => (
          <span
            key={`${getValueKey(value)}-${index}`}
            data-i18n-skip=""
            className="inline-flex min-w-0 max-w-full items-center gap-1 rounded-lg border border-[#F9D8CE] bg-[#FFF0EA] py-0.5 pl-2.5 pr-0.5 text-sm font-medium text-[#D94322]"
          >
            <span className="truncate">{value}</span>
            <button
              type="button"
              disabled={disabled}
              aria-label={t('移除标签“{value0}”', { value0: value })}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => removeValue(index)}
              className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-[#D94322]/70 outline-none transition hover:bg-[#FFE2D8] hover:text-[#C53C21] focus-visible:ring-2 focus-visible:ring-[#EFAE9B]"
            >
              <X size={13} aria-hidden="true" />
            </button>
          </span>
        ))}
        <input
          ref={inputRef}
          role="combobox"
          aria-label={ariaLabel}
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listboxId}
          aria-activedescendant={activeOptionId}
          aria-busy={loading}
          disabled={disabled}
          value={query}
          placeholder={values.length === 0 ? placeholder : undefined}
          onFocus={openMenu}
          onChange={(event) => {
            const nextQuery = event.target.value;
            setQuery(nextQuery);
            onQueryChange?.(nextQuery);
            setActiveIndex(-1);
            if (!open) setMenuOpen(true);
          }}
          onBlur={onInputBlur}
          onKeyDown={onInputKeyDown}
          onPaste={(event) => {
            const pastedValue = event.clipboardData.getData('text');
            const parsedValues = parseInput(pastedValue);
            if (parsedValues.length <= 1 && parsedValues[0] === pastedValue.trim()) return;
            event.preventDefault();
            commitInput(pastedValue);
          }}
          className="h-8 min-w-[8rem] flex-1 bg-transparent px-1 text-sm text-[#34302D] outline-none placeholder:text-[#AAA29B] disabled:cursor-not-allowed"
        />
        <button
          type="button"
          tabIndex={-1}
          disabled={disabled}
          aria-label={open ? t('收起选项') : t('展开选项')}
          onMouseDown={(event) => event.preventDefault()}
          onClick={() => {
            if (open) setMenuOpen(false);
            else {
              inputRef.current?.focus();
              openMenu();
            }
          }}
          className="absolute inset-y-0 right-0 flex w-10 items-center justify-center rounded-r-xl text-[#77706A] outline-none transition hover:bg-black/[0.025] disabled:opacity-50"
        >
          <ChevronDown size={16} className={cn('transition-transform duration-300', open && 'rotate-180')} aria-hidden="true" />
        </button>
      </div>

      {open && menuPosition ? createPortal(
        <div
          ref={menuRef}
          id={listboxId}
          role="listbox"
          aria-multiselectable="true"
          style={{
            left: menuPosition.left,
            top: menuPosition.top,
            width: menuPosition.width,
            maxHeight: menuPosition.maxHeight
          }}
          className="fixed z-[140] overflow-auto overscroll-contain rounded-2xl border border-[#DED8D1] bg-white p-1.5 text-[#4F4B47] shadow-xl shadow-stone-200/60"
        >
          {status ? <div role="status" className="px-3 py-2 text-xs leading-5 text-[#8A837D]">{status}</div> : null}
          {canCreate ? (
            <button
              id={`${listboxId}-0`}
              type="button"
              role="option"
              aria-selected="false"
              onMouseDown={(event) => event.preventDefault()}
              onMouseEnter={() => setActiveIndex(0)}
              onClick={() => commitInput(query)}
              className={cn(
                'flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm outline-none transition',
                activeIndex === 0 ? 'bg-[#FFF0EA] text-[#D94322]' : 'text-[#6F6A65] hover:bg-[#F5F2EE]'
              )}
            >
              <Plus size={15} className="shrink-0" aria-hidden="true" />
              <span className="truncate">{t('添加“{value0}”', { value0: query.trim() })}</span>
            </button>
          ) : null}
          {availableOptions.map((option, optionIndex) => {
            const rowIndex = optionIndex + (canCreate ? 1 : 0);
            return (
              <button
                id={`${listboxId}-${rowIndex}`}
                key={option.value}
                type="button"
                role="option"
                aria-selected="false"
                disabled={option.disabled}
                onMouseDown={(event) => event.preventDefault()}
                onMouseEnter={() => setActiveIndex(rowIndex)}
                onClick={() => selectOption(option)}
                className={cn(
                  'flex w-full items-center gap-2 rounded-xl px-3 py-2 text-left text-sm outline-none transition disabled:cursor-not-allowed disabled:opacity-40',
                  activeIndex === rowIndex ? 'bg-[#FFF0EA] text-[#D94322]' : 'text-[#6F6A65] hover:bg-[#F5F2EE]'
                )}
              >
                <Plus size={15} className="shrink-0" aria-hidden="true" />
                <span data-i18n-skip="" className="truncate">{option.label}</span>
              </button>
            );
          })}
          {rowCount === 0 && !status ? (
            <div className="px-3 py-3 text-xs leading-5 text-[#8A837D]">
              {emptyMessage ?? t('没有可选择的标签')}
            </div>
          ) : null}
        </div>,
        document.body
      ) : null}
    </div>
  );
}
