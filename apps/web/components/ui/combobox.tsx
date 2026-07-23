'use client';

import { Check, ChevronDown } from 'lucide-react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { cn } from './cn';
import type { SelectOption } from './select';
import { I18nText } from '@/i18n/provider';
import { useI18n as useExpressionI18n } from '@/i18n/provider';

type ComboboxProps = {
  value: string;
  options: SelectOption[];
  onChange: (value: string) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  inputClassName?: string;
  disabled?: boolean;
};

type MenuPosition = {
  left: number;
  top: number;
  width: number;
  maxHeight: number;
};

export function Combobox({
  value,
  options,
  onChange,
  placeholder = '选择或输入',
  ariaLabel,
  className,
  inputClassName,
  disabled = false
}: ComboboxProps) {
  const { t: i18nExpression } = useExpressionI18n();
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  const normalizedValue = value.trim().toLocaleLowerCase();
  const filteredOptions = useMemo(() => {
    if (!normalizedValue) return options;
    return options.filter((option) => `${option.label} ${option.value}`.toLocaleLowerCase().includes(normalizedValue));
  }, [normalizedValue, options]);

  useEffect(() => {
    if (!open) return;
    const exactIndex = filteredOptions.findIndex((option) => option.value === value || option.label === value);
    setActiveIndex(exactIndex);
  }, [filteredOptions, open, value]);

  useEffect(() => {
    if (!open) return;
    function closeOnOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    }
    document.addEventListener('mousedown', closeOnOutside);
    return () => document.removeEventListener('mousedown', closeOnOutside);
  }, [open]);

  useEffect(() => {
    if (!open) {
      setMenuPosition(null);
      return;
    }
    function positionMenu() {
      const input = inputRef.current;
      if (!input) return;
      const rect = input.getBoundingClientRect();
      const viewportPadding = 12;
      const gap = 8;
      const width = Math.min(rect.width, window.innerWidth - viewportPadding * 2);
      const desiredHeight = Math.min(288, Math.max(54, filteredOptions.length * 40 + 12));
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
  }, [filteredOptions.length, open]);

  function selectOption(option: SelectOption) {
    if (option.disabled) return;
    onChange(option.value);
    setOpen(false);
    inputRef.current?.focus();
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) setOpen(true);
      if (filteredOptions.length === 0) return;
      const direction = event.key === 'ArrowDown' ? 1 : -1;
      setActiveIndex((current) => {
        const start = current < 0 ? (direction === 1 ? -1 : 0) : current;
        return (start + direction + filteredOptions.length) % filteredOptions.length;
      });
      return;
    }
    if (event.key === 'Enter') {
      if (open && activeIndex >= 0 && filteredOptions[activeIndex]) {
        event.preventDefault();
        selectOption(filteredOptions[activeIndex]);
      } else {
        setOpen(false);
      }
      return;
    }
    if (event.key === 'Escape') {
      setOpen(false);
    }
  }

  return (
    <div ref={rootRef} className={cn('relative min-w-0', className)}>
      <input
        ref={inputRef}
        role="combobox"
        aria-label={ariaLabel ? i18nExpression(ariaLabel) : undefined}
        aria-autocomplete="list"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-activedescendant={activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined}
        disabled={disabled}
        value={value}
        placeholder={i18nExpression(placeholder)}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.target.value);
          setOpen(true);
        }}
        onKeyDown={onKeyDown}
        className={cn(
          'h-11 w-full min-w-0 rounded-xl border border-black/[0.09] bg-white px-3 pr-10 text-sm text-[#34302D] outline-none transition placeholder:text-[#AAA29B] focus:border-[#EFAE9B] focus:ring-2 focus:ring-[#F9D8CE] disabled:cursor-not-allowed disabled:opacity-50',
          inputClassName
        )}
      />
      <button
        type="button"
        tabIndex={-1}
        disabled={disabled}
        aria-label={open ? i18nExpression("收起选项") : i18nExpression("展开选项")}
        onMouseDown={(event) => event.preventDefault()}
        onClick={() => {
          setOpen((current) => !current);
          inputRef.current?.focus();
        }}
        className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-[#77706A] outline-none disabled:opacity-50"
      >
        <ChevronDown size={16} className={cn('transition', open && 'rotate-180')} />
      </button>
      {open && menuPosition ? createPortal(
        <div
          ref={menuRef}
          id={listboxId}
          role="listbox"
          style={{
            left: menuPosition.left,
            top: menuPosition.top,
            width: menuPosition.width,
            maxHeight: menuPosition.maxHeight
          }}
          className="fixed z-[120] overflow-auto overscroll-contain rounded-2xl border border-[#DED8D1] bg-white p-1.5 text-[#4F4B47] shadow-xl shadow-stone-200/60"
        >
          {filteredOptions.length ? filteredOptions.map((option, index) => {
            const selected = option.value === value;
            const active = index === activeIndex;
            return (
              <button
                id={`${listboxId}-${index}`}
                key={option.value}
                type="button"
                role="option"
                aria-selected={selected}
                disabled={option.disabled}
                onMouseEnter={() => setActiveIndex(index)}
                onClick={() => selectOption(option)}
                className={cn(
                  'flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-sm outline-none transition disabled:cursor-not-allowed disabled:opacity-40',
                  active ? 'bg-[#FFF0EA] text-[#D94322]' : 'text-[#6F6A65] hover:bg-[#F5F2EE]',
                  selected && 'text-[#D94322]'
                )}
              >
                <span data-i18n-skip={option.translate === false ? '' : undefined} className="truncate">
                  {option.translate === false ? option.label : i18nExpression(option.label)}
                </span>
                {selected ? <Check size={15} className="shrink-0" /> : <span className="h-[15px] w-[15px] shrink-0" />}
              </button>
            );
          }) : (
            <div className="px-3 py-3 text-xs leading-5 text-[#8A837D]"><I18nText>没有匹配选项，可继续使用当前输入值</I18nText></div>
          )}
        </div>,
        document.body
      ) : null}
    </div>
  );
}
