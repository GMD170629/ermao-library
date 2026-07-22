'use client';

import { Check, ChevronDown } from 'lucide-react';
import type { KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useEffect, useId, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { cn } from './cn';

export type SelectOption = {
  value: string;
  label: string;
  disabled?: boolean;
  group?: string;
};

type SelectProps<TValue extends string> = {
  value: TValue;
  options: SelectOption[];
  onChange: (value: TValue) => void;
  placeholder?: string;
  ariaLabel?: string;
  className?: string;
  triggerClassName?: string;
  menuClassName?: string;
  size?: 'sm' | 'md';
  tone?: 'light' | 'blue' | 'dark';
  align?: 'left' | 'right';
  disabled?: boolean;
  menuWidth?: number;
};

const triggerTone = {
  light: 'border-[#ded8d1] bg-white text-[#4f4b47] hover:border-[#f2b7a6] hover:bg-[#fffaf8]',
  blue: 'border-[#f4c7b9] bg-white text-[#4f4b47] hover:border-[#ed9d86] hover:bg-[#fff5f1]',
  dark: 'border-slate-700 bg-slate-900 text-slate-100 hover:border-slate-500 hover:bg-slate-800'
};

const menuTone = {
  light: 'border-[#ded8d1] bg-white text-[#4f4b47] shadow-xl shadow-stone-200/60',
  blue: 'border-[#f4c7b9] bg-white text-[#4f4b47] shadow-xl shadow-orange-100/60',
  dark: 'border-slate-700 bg-slate-900 text-slate-100 shadow-xl shadow-black/30'
};

const optionTone = {
  light: {
    active: 'bg-[#fff0ea] text-[#d94322]',
    idle: 'text-[#6f6a65] hover:bg-[#f5f2ee]',
    selected: 'text-[#d94322]'
  },
  blue: {
    active: 'bg-[#fff0ea] text-[#d94322]',
    idle: 'text-[#6f6a65] hover:bg-[#fff5f1]',
    selected: 'text-[#d94322]'
  },
  dark: {
    active: 'bg-slate-800 text-white',
    idle: 'text-slate-300 hover:bg-slate-800',
    selected: 'text-blue-300'
  }
};

const groupTone = {
  light: 'bg-white/95 text-[#9A928B]',
  blue: 'bg-white/95 text-[#A07D72]',
  dark: 'bg-slate-900/95 text-slate-500'
};

type MenuPosition = {
  left: number;
  top: number;
  width: number;
  maxHeight: number;
};

export function Select<TValue extends string>({
  value,
  options,
  onChange,
  placeholder = '请选择',
  ariaLabel,
  className,
  triggerClassName,
  menuClassName,
  size = 'md',
  tone = 'light',
  align = 'left',
  disabled = false,
  menuWidth
}: SelectProps<TValue>) {
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const [menuPosition, setMenuPosition] = useState<MenuPosition | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const buttonRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const listboxId = useId();
  const selectedIndex = useMemo(() => options.findIndex((option) => option.value === value), [options, value]);
  const selected = selectedIndex >= 0 ? options[selectedIndex] : null;
  const enabledOptions = options.filter((option) => !option.disabled);

  useEffect(() => {
    if (open) setActiveIndex(selectedIndex >= 0 ? selectedIndex : Math.max(0, options.findIndex((option) => !option.disabled)));
  }, [open, options, selectedIndex]);

  useEffect(() => {
    if (!open) return;
    function closeOnOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (!rootRef.current?.contains(target) && !menuRef.current?.contains(target)) setOpen(false);
    }
    function closeOnEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        setOpen(false);
        buttonRef.current?.focus();
      }
    }
    document.addEventListener('mousedown', closeOnOutside);
    document.addEventListener('keydown', closeOnEscape);
    return () => {
      document.removeEventListener('mousedown', closeOnOutside);
      document.removeEventListener('keydown', closeOnEscape);
    };
  }, [open]);

  useEffect(() => {
    if (!open) {
      setMenuPosition(null);
      return;
    }
    function positionMenu() {
      const trigger = buttonRef.current;
      if (!trigger) return;
      const rect = trigger.getBoundingClientRect();
      const viewportPadding = 12;
      const gap = 8;
      const width = Math.min(menuWidth ?? rect.width, window.innerWidth - viewportPadding * 2);
      const desiredHeight = Math.min(288, options.length * 40 + new Set(options.map((option) => option.group).filter(Boolean)).size * 28 + 12);
      const availableBelow = window.innerHeight - rect.bottom - gap - viewportPadding;
      const availableAbove = rect.top - gap - viewportPadding;
      const openUpwards = availableBelow < Math.min(desiredHeight, 176) && availableAbove > availableBelow;
      const maxHeight = Math.max(112, Math.min(desiredHeight, openUpwards ? availableAbove : availableBelow));
      const renderedHeight = Math.min(desiredHeight, maxHeight);
      const preferredLeft = align === 'right' ? rect.right - width : rect.left;
      const left = Math.max(viewportPadding, Math.min(preferredLeft, window.innerWidth - width - viewportPadding));
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
  }, [align, menuWidth, open, options]);

  function moveActive(direction: 1 | -1) {
    if (enabledOptions.length === 0) return;
    const currentEnabledIndex = enabledOptions.findIndex((option) => option.value === options[activeIndex]?.value);
    const nextEnabled = enabledOptions[(currentEnabledIndex + direction + enabledOptions.length) % enabledOptions.length];
    setActiveIndex(options.findIndex((option) => option.value === nextEnabled.value));
  }

  function commit(nextValue: string) {
    const option = options.find((item) => item.value === nextValue);
    if (!option || option.disabled) return;
    onChange(nextValue as TValue);
    setOpen(false);
    buttonRef.current?.focus();
  }

  function onKeyDown(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      moveActive(event.key === 'ArrowDown' ? 1 : -1);
    }
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (!open) {
        setOpen(true);
        return;
      }
      commit(options[activeIndex]?.value);
    }
  }

  return (
    <div ref={rootRef} className={cn('relative inline-flex min-w-[132px]', className)}>
      <button
        ref={buttonRef}
        type="button"
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listboxId}
        aria-label={ariaLabel}
        onClick={() => setOpen((next) => !next)}
        onKeyDown={onKeyDown}
        className={cn(
          'inline-flex w-full items-center justify-between gap-3 rounded-[12px] border font-medium outline-none transition focus:border-[#ed9d86] focus:ring-4 focus:ring-[#ffe4dc] disabled:cursor-not-allowed disabled:opacity-50',
          size === 'sm' ? 'h-9 px-3 text-xs' : 'h-11 px-4 text-sm',
          triggerTone[tone],
          triggerClassName
        )}
      >
        <span className="truncate">{selected?.label ?? placeholder}</span>
        <ChevronDown size={16} className={cn('shrink-0 transition', open && 'rotate-180')} />
      </button>
      {open && menuPosition ? createPortal(
        <div
          ref={menuRef}
          id={listboxId}
          role="listbox"
          tabIndex={-1}
          style={{
            left: menuPosition.left,
            top: menuPosition.top,
            width: menuPosition.width,
            maxHeight: menuPosition.maxHeight
          }}
          className={cn(
            'fixed z-[120] overflow-auto overscroll-contain rounded-2xl border p-1.5',
            menuTone[tone],
            menuClassName
          )}
        >
          {options.map((option, index) => {
            const isSelected = option.value === value;
            const isActive = index === activeIndex;
            return (
              <div key={option.value}>
                {option.group && option.group !== options[index - 1]?.group ? (
                  <div className={cn('sticky top-0 z-10 px-3 pb-1 pt-2 text-[11px] font-semibold tracking-[0.08em]', groupTone[tone])}>{option.group}</div>
                ) : null}
                <button
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  disabled={option.disabled}
                  onMouseEnter={() => setActiveIndex(index)}
                  onClick={() => commit(option.value)}
                  className={cn(
                    'flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2 text-left text-sm outline-none transition disabled:cursor-not-allowed disabled:opacity-40',
                    isActive ? optionTone[tone].active : optionTone[tone].idle,
                    isSelected && optionTone[tone].selected
                  )}
                >
                  <span className="truncate">{option.label}</span>
                  {isSelected ? <Check size={15} className="shrink-0" /> : <span className="h-[15px] w-[15px] shrink-0" />}
                </button>
              </div>
            );
          })}
        </div>
      , document.body) : null}
    </div>
  );
}
